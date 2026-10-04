"""What a company's own site shows of its stays (ADR-072, slice 5d).

Three blocks of the page editor show offers booked from–to: the list of units
(`core.stay_units`), the booking widget (`core.stay_search`) and the calendar
of free days (`core.stay_calendar`). A publication is a snapshot and a free
day or a price cannot be one, so a block carries only a choice — which offer —
and the site asks here, through the registry of public sources, each time the
page is read.

The answer is what the company's public form would say (`public_stays`): only
what is offered online, the content of units the company shows, „od X zł/noc”
from the quote, never coordinates. The pictures are named by id — the site
serves them at its own host (`served_photo_ids`) — and the days a visitor
picks are read by the block from the form's own API, under the form's address.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from saas_core.modules.shared.notifications.api import public_url

from .availability import _zone
from .company_settings import online_paused
from .item_translations import source_locale
from .models import PublicBookingRoute
from .periods import period_last_day
from .public import public_stays
from .security import public_booking_context
from .services import BOOKING_ENABLED
from .unit_content import amenities_in

UNITS = "core.stay_units"
SEARCH = "core.stay_search"
CALENDAR = "core.stay_calendar"
#: The blocks of a site this module fills.
SITE_BLOCK_TYPES = frozenset({UNITS, SEARCH, CALENDAR})


def _choice(kind: str, item: Mapping[str, Any], *, content: bool, locale: str) -> dict[str, Any]:
    """One thing a guest chooses of an offer — a group or a unit — as a block
    shows it. Only the list of units draws its content."""
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
    return choice


def _offer(stay: Mapping[str, Any], *, content: bool, locale: str) -> dict[str, Any]:
    return {
        "id": str(stay["id"]),
        "name": stay["name"],
        "range_unit": stay["range_unit"],
        "choices": [
            *(_choice("group", item, content=content, locale=locale) for item in stay["groups"]),
            *(_choice("unit", item, content=content, locale=locale) for item in stay["units"]),
        ],
    }


def site_blocks(
    organization_id: UUID, locale: str, blocks: Mapping[str, tuple[str, Mapping[str, Any]]]
) -> dict[str, Any]:
    """What each stay block of a page shows now, by the key it was asked
    under. A company without a form, without the plan for it or with nothing
    booked from–to online answers nothing, and so does a block whose offer is
    gone: the page then draws no such section."""
    if not settings.PUBLIC_BOOKING_ENABLED:
        return {}
    route = PublicBookingRoute.objects.filter(organization_id=organization_id, active=True).first()
    if route is None:
        return {}
    with public_booking_context(organization_id):
        try:
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
        except APIException:
            return {}
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
            return {}
        zone = _zone()
        paused, _resume_on = online_paused(zone.key)
        form = {
            "slug": route.public_slug,
            # The form in the page's language when the company has it,
            # otherwise in the company's first one — a language the form does
            # not speak would be a link to nowhere.
            "form_url": public_url(
                clamp_content_locale(locale, organization=organization),
                f"/book/{route.public_slug}",
            ),
            "timezone": zone.key,
            "last_day": period_last_day(zone).isoformat(),
            "paused": paused,
        }
    answers: dict[str, Any] = {}
    for key, (block_type, data) in blocks.items():
        wanted = str(data.get("offer") or "")
        offers = [stay for stay in stays if not wanted or str(stay["id"]) == wanted]
        if offers:
            answers[key] = {
                **form,
                "offers": [
                    _offer(stay, content=block_type == UNITS, locale=locale) for stay in offers
                ],
            }
    return answers
