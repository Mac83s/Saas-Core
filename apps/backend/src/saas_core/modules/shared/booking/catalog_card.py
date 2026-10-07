"""What the catalogue says of a company's bookings (ADR-072 §11, slice 5h).

The catalogue belongs to Profiles, which cannot import Booking, so Booking
registers here what it knows:

- the badge „rezerwacja online” — the company's public form is open, its
  plan covers bookings and it takes at least one active offer online;
- what a visitor can book from the company's card: the form, and the units
  the form shows the content of, each with a page of its own under the card;
- the catalogue category an offer made from a preset points at, for a card
  that has none yet;
- and, for the company's identity in structured data, the fact that it lets
  units by the night: such a company is a lodging business whatever shelf of
  the catalogue it stands on (ADR-071 pkt 16).

Everything a visitor gets is what the company's own form would say
(`public_stays`): only what is offered online, the content of units the
company shows, „od X zł/noc” from the quote, never a unit's coordinates.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.locales import (
    clamp_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.media.api import shown_image_facts
from saas_core.modules.shared.notifications.api import public_url

from .availability import _zone
from .company_settings import online_paused, shown_conversion
from .item_translations import source_locale
from .models import (
    PublicBookingRoute,
    RangeUnit,
    Resource,
    Service,
    ServiceGroup,
    ServiceResource,
    TimeModel,
)
from .periods import period_last_day
from .presets import latest_presets
from .public import public_stays
from .security import public_booking_context
from .services import BOOKING_ENABLED
from .site_blocks import DESCRIPTION_LENGTH, _own_locales, _shown, _thing
from .unit_content import amenities_in

#: The listing's badge and filter „rezerwacja online”.
ONLINE_BOOKING = "online_booking"
#: What schema.org calls a company that lets places to stay.
LODGING_BUSINESS = "LodgingBusiness"


@contextmanager
def _open_form(organization_id: UUID) -> Iterator[PublicBookingRoute | None]:
    """The company's public form, inside its service scope — or None: the
    product has no forms, the company's is closed, or its plan does not cover
    bookings. The same gate the form's own addresses pass."""
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
        yield route


def books_online(organization_id: UUID) -> bool:
    """Whether a visitor can book the company on its public form now."""
    with _open_form(organization_id) as route:
        return (
            route is not None
            and Service.all_objects.filter(
                organization_id=organization_id, online=True, active=True
            ).exists()
        )


def _photos(organization_id: UUID, photos: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pictures at the form's address, each with what a page states of a
    picture: its stored size and whether a model made it (ADR-059). One read,
    however many pictures."""
    facts = shown_image_facts(
        organization_id=organization_id, asset_ids=[str(photo["id"]) for photo in photos]
    )
    listed = []
    for photo in photos:
        fact = facts.get(str(photo["id"]))
        listed.append({
            **photo,
            "width": fact.width if fact else 0,
            "height": fact.height if fact else 0,
            "ai_generated": bool(fact and fact.ai),
        })
    return listed


def _words(organization: Organization, locale: str) -> str | None:
    """The language the company's own words are asked in: the page's, where
    the company has it beside the one it writes in."""
    return (
        locale
        if locale in organization_content_locales(organization)
        and locale != source_locale(organization)
        else None
    )


def _form_url(organization: Organization, locale: str, public_slug: str) -> str:
    """The form in the page's language when the company has it, otherwise in
    the company's first one — as a block of its own site links it."""
    return public_url(
        clamp_content_locale(locale, organization=organization), f"/book/{public_slug}"
    )


def card(organization_id: UUID, locale: str) -> dict[str, Any] | None:
    """What a visitor can book at the company from its catalogue card: the
    form's address and the units the form shows the content of, in the form's
    order, each once. None — nothing is booked online there now."""
    with _open_form(organization_id) as route:
        if route is None:
            return None
        organization = Organization.objects.get(pk=organization_id)
        stays = public_stays(organization, _words(organization, locale), route.public_slug)
        if (
            not stays
            and not Service.all_objects.filter(
                organization_id=organization_id,
                time_model=TimeModel.SLOT,
                online=True,
                active=True,
            ).exists()
        ):
            return None
        units: dict[str, dict[str, Any]] = {}
        for stay in stays:
            for item in (*stay["groups"], *stay["units"]):
                slug = str(item.get("public_slug") or "")
                if not slug or slug in units:
                    continue
                units[slug] = {
                    "slug": slug,
                    "name": item["name"],
                    "description": " ".join(str(item["description"]).split())[:DESCRIPTION_LENGTH],
                    "capacity": item["capacity"],
                    # The cover: the first picture the unit shows.
                    "photo": item["photos"][0] if item["photos"] else None,
                    "town": item["town"],
                    "from_price": item["from_price"],
                    "range_unit": stay["range_unit"],
                }
        covers = {
            str(photo["id"]): photo
            for photo in _photos(
                organization_id, [found["photo"] for found in units.values() if found["photo"]]
            )
        }
        for found in units.values():
            if found["photo"]:
                found["photo"] = covers[str(found["photo"]["id"])]
        return {
            "form_url": _form_url(organization, locale, route.public_slug),
            "units": list(units.values()),
            # Roughly what the prices are in the reader's own money (5i).
            "conversion": shown_conversion(organization.currency, locale),
        }


def unit(organization_id: UUID, locale: str, public_slug: str) -> dict[str, Any] | None:
    """The unit at that address as its own page under the company's card
    shows it: its content, the form it is booked on and each offer it is
    booked through with the one choice that books it. None — the form shows
    no such unit now."""
    with _open_form(organization_id) as route:
        if route is None:
            return None
        organization = Organization.objects.get(pk=organization_id)
        asked = _words(organization, locale)
        shown = _shown(public_stays(organization, asked, route.public_slug), public_slug)
        resource = Resource.all_objects.filter(
            organization_id=organization_id, public=True, active=True, public_slug=public_slug
        ).first()
        if not shown or resource is None:
            return None
        stay, kind, item = shown[0]
        own = _own_locales(organization, kind, item["id"])
        zone = _zone()
        paused, _resume_on = online_paused(zone.key)
        return {
            "form_url": _form_url(organization, locale, route.public_slug),
            "form_slug": route.public_slug,
            "timezone": zone.key,
            "last_day": period_last_day(zone).isoformat(),
            "paused": paused,
            "conversion": shown_conversion(organization.currency, locale),
            "unit": {
                "slug": public_slug,
                "name": item["name"],
                "description": item["description"],
                "capacity": item["capacity"],
                "photos": _photos(organization_id, item["photos"]),
                # The dictionary's words follow the page; they are ours.
                "amenities": amenities_in([entry["key"] for entry in item["amenities"]], locale),
                "town": item["town"],
                "from_price": item["from_price"],
                # The language of the name and description in this answer,
                # the one the company writes in, and the others the unit —
                # or the group it speaks for — has a name of its own in.
                "locale": asked if asked in own else source_locale(organization),
                "source_locale": source_locale(organization),
                "translated_locales": sorted(own),
            },
            "offers": [
                {
                    "id": str(offer["id"]),
                    "name": offer["name"],
                    "range_unit": offer["range_unit"],
                    "choice": {"kind": choice_kind, "id": str(choice["id"])},
                }
                for offer, choice_kind, choice in shown
            ],
            "thing": _thing(stay, item, resource, locale),
        }


def category_hint(organization_id: UUID) -> str:
    """The catalogue category the company's offers point at: that of the
    preset its newest offer made from one came from; "" when no offer came
    from a preset that names a category. The caller holds the tenant."""
    categories = {preset.id: preset.catalog_category or "" for preset in latest_presets()}
    for preset_id in (
        Service.all_objects.filter(organization_id=organization_id)
        .exclude(preset_id="")
        .order_by("-created_at", "-id")
        .values_list("preset_id", flat=True)
    ):
        if categories.get(preset_id):
            return categories[preset_id]
    return ""


def business_type(organization_id: UUID) -> str:
    """`LodgingBusiness` for a company that lets units by the night: it has a
    switched-on offer booked by the night with a switched-on unit to book —
    one of its own or one of a group's. A fact about what the company does,
    whether or not it takes those bookings online. The caller holds the
    tenant."""
    offers = Service.all_objects.filter(
        organization_id=organization_id,
        time_model=TimeModel.RANGE,
        range_unit=RangeUnit.NIGHT,
        active=True,
    )
    lets = (
        ServiceResource.all_objects.filter(service__in=offers, resource__active=True).exists()
        or ServiceGroup.all_objects.filter(
            service__in=offers, group__active=True, group__units__active=True
        ).exists()
    )
    return LODGING_BUSINESS if lets else ""


def register() -> None:
    """From `BookingConfig.ready`: what the catalogue asks Booking."""
    from saas_core.modules.shared.profiles.api import (  # noqa: PLC0415
        CatalogBooking,
        register_catalog_badge,
        register_catalog_booking,
        register_category_hint,
    )

    register_catalog_badge(ONLINE_BOOKING, books_online)
    register_catalog_booking(CatalogBooking("booking.form", card, unit))
    register_category_hint("shared.booking.presets", category_hint)
