"""What a company's own site shows of its stays (ADR-072, slices 5d and 5e).

Five blocks of the page editor show offers booked from–to: the list of units
(`core.stay_units`), the booking widget (`core.stay_search`), the calendar of
free days (`core.stay_calendar`), one unit's card (`core.stay_unit`) and the
map of where a unit is (`core.stay_map`). A publication is a snapshot and a
free day or a price cannot be one, so a block carries only a choice — which
offer, which unit — and the site asks here, through the registry of public
sources, each time the page is read.

A unit the form shows the content of also has a page of its own on the site,
at `/stay/<its address>/` (slice 5e): nobody publishes it — it is one unit's
card and, where the unit has a place, its map, answered while the form shows
the unit and gone when it does not.

The answer is what the company's public form would say (`public_stays`): only
what is offered online, the content of units the company shows, „od X zł/noc”
from the quote. Coordinates are in the map's answer alone: the town's centre,
or the unit's own point once the company switched „Pokaż dokładne położenie”
on for it (`unit_content.place_of`). The pictures are named by id — the site
serves them at its own host (`public_photo_ids`) — and the days a visitor
picks are read by the block from the form's own API, under the form's address.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.api import (
    PageAddress,
    SourcePage,
    SourcePageAddress,
)
from saas_core.modules.core.organizations.locales import (
    clamp_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.notifications.api import public_url

from .availability import _zone
from .company_settings import online_paused
from .item_translations import localized_texts, source_locale, translatable
from .models import PublicBookingRoute, Resource, ResourceGroup
from .periods import period_last_day
from .public import public_stays
from .security import public_booking_context
from .services import BOOKING_ENABLED
from .unit_content import amenities_in, place_of

UNITS = "core.stay_units"
SEARCH = "core.stay_search"
CALENDAR = "core.stay_calendar"
UNIT = "core.stay_unit"
MAP = "core.stay_map"
#: The blocks of a site this module fills.
SITE_BLOCK_TYPES = frozenset({UNITS, SEARCH, CALENDAR, UNIT, MAP})
#: The first segment of a unit's own page on the company's site, the same in
#: every language (as the shop's `shop`, ADR-074 pkt 7).
PAGE_SEGMENT = "stay"
#: How much of a unit's description a search result shows under its name.
DESCRIPTION_LENGTH = 160


def form_company(address: str) -> UUID | None:
    """The company a public form's address names — `<slug>/…`, what follows
    the API's prefix — or None where no form answers. The host gate lets a
    site's host read its own company's form and nobody else's."""
    if not settings.PUBLIC_BOOKING_ENABLED:
        return None
    return (
        PublicBookingRoute.objects.filter(public_slug=address.split("/", 1)[0], active=True)
        .values_list("organization_id", flat=True)
        .first()
    )


@dataclass(frozen=True, slots=True)
class _Form:
    """What the company's form says now, read once for a page."""

    organization: Organization
    #: The form's address and clock, as every stay block is told them.
    facts: dict[str, Any]
    stays: list[dict[str, Any]]


@contextmanager
def _form(organization_id: UUID, locale: str) -> Iterator[_Form | None]:
    """The company's form in the page's language, inside its service scope —
    or None: no form, no plan for it, nothing booked from–to online."""
    route = (
        PublicBookingRoute.objects.filter(organization_id=organization_id, active=True).first()
        if settings.PUBLIC_BOOKING_ENABLED
        else None
    )
    if route is None:
        yield None
        return
    with public_booking_context(organization_id):
        try:
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
        except APIException:
            yield None
            return
        organization = Organization.objects.get(pk=organization_id)
        # The company's own words in the page's language where it wrote them.
        translated = (
            locale
            if locale in organization_content_locales(organization)
            and locale != source_locale(organization)
            else None
        )
        stays = public_stays(organization, translated, route.public_slug)
        if not stays:
            yield None
            return
        zone = _zone()
        paused, _resume_on = online_paused(zone.key)
        yield _Form(
            organization=organization,
            facts={
                "slug": route.public_slug,
                # The form in the page's language when the company has it,
                # otherwise in the company's first one — a language the form
                # does not speak would be a link to nowhere.
                "form_url": public_url(
                    clamp_content_locale(locale, organization=organization),
                    f"/book/{route.public_slug}",
                ),
                "timezone": zone.key,
                "last_day": period_last_day(zone).isoformat(),
                "paused": paused,
            },
            stays=stays,
        )


def _choice(
    kind: str, item: Mapping[str, Any], *, content: bool, locale: str, page_base: str = ""
) -> dict[str, Any]:
    """One thing a guest chooses of an offer — a group or a unit — as a block
    shows it. Only the list of units and a unit's card draw its content."""
    choice: dict[str, Any] = {
        "kind": kind,
        "id": str(item["id"]),
        "name": item["name"],
        "capacity": item["capacity"],
    }
    if content:
        choice.update(
            description=item["description"],
            # By id: the site serves a picture at its own host.
            photos=[str(photo["id"]) for photo in item["photos"]],
            # The dictionary's words follow the page, whatever the company's
            # own languages are: they are ours, not the company's text.
            amenities=amenities_in([entry["key"] for entry in item["amenities"]], locale),
            town=item["town"],
            from_price=item["from_price"],
        )
        # The unit's own page, where the site has one for it.
        if page_base and item.get("public_slug"):
            choice["page_path"] = f"{page_base}{item['public_slug']}/"
    return choice


def _offer(
    stay: Mapping[str, Any], *, content: bool, locale: str, page_base: str = ""
) -> dict[str, Any]:
    return {
        "id": str(stay["id"]),
        "name": stay["name"],
        "range_unit": stay["range_unit"],
        "choices": [
            *(
                _choice(kind, item, content=content, locale=locale, page_base=page_base)
                for kind, items in (("group", stay["groups"]), ("unit", stay["units"]))
                for item in items
            ),
        ],
    }


def _shown(stays: Iterable[Mapping[str, Any]], public_slug: str) -> list[tuple[Any, str, Any]]:
    """Where the form shows the unit at that address: each offer with the
    choice that books it — the unit itself, or the group it speaks for."""
    return [
        (stay, kind, item)
        for stay in stays
        for kind, items in (("group", stay["groups"]), ("unit", stay["units"]))
        for item in items
        if public_slug and item.get("public_slug") == public_slug
    ]


def _card(form: _Form, public_slug: str, locale: str) -> dict[str, Any] | None:
    """One unit's card: its content, and each offer it is booked through with
    the one choice that books it. None — the form does not show such a unit."""
    shown = _shown(form.stays, public_slug)
    if not shown:
        return None
    _stay, kind, item = shown[0]
    return {
        **form.facts,
        "unit": _choice(kind, item, content=True, locale=locale),
        "offers": [
            {
                "id": str(stay["id"]),
                "name": stay["name"],
                "range_unit": stay["range_unit"],
                "choices": [_choice(kind, item, content=False, locale=locale)],
            }
            for stay, kind, item in shown
        ],
    }


def _places(form: _Form) -> dict[str, dict[str, Any]]:
    """Where each unit the form shows is, by the unit's id and in the form's
    order: the place the company shows of it (`place_of`) under the name a
    guest books it by — its group's, for a unit of a pool. A unit without a
    place is left out."""
    names = {
        str(item["public_slug"]): str(item["name"])
        for stay in form.stays
        for items in (stay["groups"], stay["units"])
        for item in items
        if item.get("public_slug")
    }
    units = {
        unit.public_slug: unit
        for unit in Resource.all_objects.filter(
            organization_id=form.organization.id,
            public=True,
            active=True,
            public_slug__in=list(names),
        )
    }
    places: dict[str, dict[str, Any]] = {}
    for address, name in names.items():
        place = place_of(units[address]) if address in units else None
        if place is not None:
            places[str(units[address].id)] = {"name": name, **place}
    return places


def site_blocks(
    organization_id: UUID,
    locale: str,
    blocks: Mapping[str, tuple[str, Mapping[str, Any]]],
    page_base: str = "",
) -> dict[str, Any]:
    """What each stay block of a page shows now, by the key it was asked
    under. A company without a form, without the plan for it or with nothing
    booked from–to online answers nothing, and so does a block whose offer or
    unit is gone: the page then draws no such section."""
    answers: dict[str, Any] = {}
    with _form(organization_id, locale) as form:
        if form is None:
            return answers
        # A card names its unit by id; the form knows a shown unit by its
        # address.
        wanted = {str(data.get("unit") or "") for kind, data in blocks.values() if kind == UNIT}
        addresses = (
            {
                str(key): slug
                for key, slug in Resource.all_objects.filter(
                    organization_id=organization_id,
                    public=True,
                    active=True,
                    pk__in=[key for key in wanted if key],
                ).values_list("id", "public_slug")
            }
            if wanted - {""}
            else {}
        )
        places = _places(form) if any(kind == MAP for kind, _data in blocks.values()) else {}
        for key, (block_type, data) in blocks.items():
            if block_type == UNIT:
                card = _card(form, addresses.get(str(data.get("unit") or ""), ""), locale)
                if card is not None:
                    answers[key] = card
                continue
            if block_type == MAP:
                # The unit the block names, or — naming none — the first
                # the form shows that has a place.
                named = str(data.get("unit") or "")
                place = places.get(named) if named else next(iter(places.values()), None)
                if place is not None:
                    answers[key] = {"place": place}
                continue
            asked = str(data.get("offer") or "")
            offers = [stay for stay in form.stays if not asked or str(stay["id"]) == asked]
            if offers:
                answers[key] = {
                    **form.facts,
                    "offers": [
                        _offer(
                            stay,
                            content=block_type == UNITS,
                            locale=locale,
                            page_base=page_base,
                        )
                        for stay in offers
                    ],
                }
    return answers


def _own_locales(organization: Organization, kind: str, item_id: Any) -> frozenset[str]:
    """The company's languages the unit — or the group it speaks for — has a
    name of its own in, beside the one the company writes in."""
    model = ResourceGroup if kind == "group" else Resource
    found = model.all_objects.filter(organization_id=organization.id, pk=item_id).first()
    if found is None:
        return frozenset()
    entry = translatable("group" if kind == "group" else "resource")
    return frozenset(
        code
        for code in organization_content_locales(organization)
        if code != source_locale(organization)
        and "name" in localized_texts(entry, [found], code).get(found.id, {})
    )


def _thing(
    stay: Mapping[str, Any], item: Mapping[str, Any], unit: Resource, locale: str
) -> dict[str, Any] | None:
    """What a unit let by the night is, for a search engine: a place to stay
    with its name, how many it takes, what it has and its town — and its
    point only where the company shows it. A thing rented by the day (a
    kayak) is no accommodation: it is a product let out, with what a day of
    it costs from — and without a price on the list it gets no node, because
    a product without an offer is an error to a search engine."""
    if stay["range_unit"] != "night":
        price = item.get("from_price")
        if not price:
            return None
        rented: dict[str, Any] = {"@type": "Product", "name": str(item["name"])}
        if item["description"]:
            rented["description"] = " ".join(str(item["description"]).split())
        rented["offers"] = {
            "@type": "Offer",
            # Let out, not sold: the price is of one day, and the least of it.
            "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
            "priceSpecification": {
                "@type": "UnitPriceSpecification",
                "minPrice": f"{price['gross_minor'] / 100:.2f}",
                "priceCurrency": price["currency"],
                # A price charged once for the whole rental names no unit.
                **({"unitCode": "DAY"} if price["per"] == "day" else {}),
            },
        }
        return rented
    thing: dict[str, Any] = {"@type": "Accommodation", "name": str(item["name"])}
    if item["description"]:
        thing["description"] = " ".join(str(item["description"]).split())
    if item["capacity"]:
        thing["occupancy"] = {"@type": "QuantitativeValue", "maxValue": item["capacity"]}
    amenities = amenities_in([entry["key"] for entry in item["amenities"]], locale)
    if amenities:
        thing["amenityFeature"] = [
            {"@type": "LocationFeatureSpecification", "name": entry["label"], "value": True}
            for entry in amenities
        ]
    place = place_of(unit)
    if place is not None and place["town"]:
        thing["address"] = {"@type": "PostalAddress", "addressLocality": place["town"]["name"]}
    if place is not None and place["exact"]:
        thing["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": place["latitude"],
            "longitude": place["longitude"],
        }
    return thing


def site_page(
    organization_id: UUID, locale: str, public_slug: str, address: PageAddress | None = None
) -> SourcePage | None:
    """The page of the unit at that address: its card as the page's one
    block. None — the form shows no such unit now. A unit's page links to no
    other language of itself, so where the site answers for it (`address`)
    goes unread."""
    with _form(organization_id, locale) as form:
        if form is None:
            return None
        shown = _shown(form.stays, public_slug)
        if not shown:
            return None
        stay, kind, item = shown[0]
        unit = Resource.all_objects.filter(
            organization_id=organization_id, public=True, active=True, public_slug=public_slug
        ).first()
        if unit is None:
            return None
        town = item["town"]["name"] if item["town"] else ""
        blocks: list[dict[str, Any]] = [
            {
                "block_type": UNIT,
                "schema_version": 1,
                # The page's own heading: the unit's name is its title.
                "data": {"unit": str(unit.id), "main": True},
            }
        ]
        # Where it is, under the card — as much as the company shows.
        if place_of(unit) is not None:
            blocks.append({"block_type": MAP, "schema_version": 1, "data": {"unit": str(unit.id)}})
        return SourcePage(
            key=str(unit.id),
            title=f"{item['name']} — {town}" if town else str(item["name"]),
            description=" ".join(str(item["description"]).split())[:DESCRIPTION_LENGTH],
            blocks=blocks,
            locales=_own_locales(form.organization, kind, item["id"]),
            # The cover: the first picture the unit shows.
            image=unit.photos[0] if unit.photos else None,
            thing=_thing(stay, item, unit, locale),
        )


def site_pages(organization_id: UUID) -> list[SourcePageAddress]:
    """Every unit that has a page now: the ones the form shows the content
    of, each with the languages it has a name in."""
    with _form(organization_id, "") as form:
        if form is None:
            return []
        seen: dict[str, tuple[str, Any]] = {}
        for stay in form.stays:
            for kind, items in (("group", stay["groups"]), ("unit", stay["units"])):
                for item in items:
                    if item.get("public_slug"):
                        seen.setdefault(str(item["public_slug"]), (kind, item["id"]))
        changed = dict(
            Resource.all_objects.filter(
                organization_id=organization_id, public_slug__in=list(seen)
            ).values_list("public_slug", "updated_at")
        )
        return [
            SourcePageAddress(
                slug=slug,
                locales=_own_locales(form.organization, kind, item_id),
                changed_at=changed.get(slug),
            )
            for slug, (kind, item_id) in sorted(seen.items())
        ]
