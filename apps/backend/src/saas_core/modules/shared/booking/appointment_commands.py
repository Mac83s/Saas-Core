"""The assistant's read of the calendar (ADR-076, uzupełnienie 2026-10-04
„karty osób”): the visits and stays of some days, as the panel's Kalendarz
lists them for the same person — theirs only where the product shows them no
others (`services.list_appointments`).

A booking is its service, its time, its place and its state. Who it is for is
a handle: the model never gets the customer's name, e-mail or phone, and the
person at the screen reads them on the card the panel shows for the handle.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, person_handle
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.customers.api import CUSTOMER

from . import orders
from .models import AppointmentStatus
from .request_commands import _local_iso
from .services import BOOKING_ENABLED, BOOKING_READ, list_appointments

#: The longest stretch of days one read answers for, and how many bookings.
MAX_DAYS = 31
AT_ONCE = 60
_STATUSES = list(AppointmentStatus.values)
_DAY = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def _day(arguments: Mapping[str, Any], field: str) -> date:
    try:
        return date.fromisoformat(arguments[field])
    except ValueError:
        raise ValidationError({field: ["Podaj dzień jako RRRR-MM-DD."]}) from None


def _read_appointments(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    first, last = _day(arguments, "from"), _day(arguments, "to")
    if last < first:
        raise ValidationError({"to": ["Ostatni dzień nie może być przed pierwszym."]})
    if (last - first).days >= MAX_DAYS:
        raise ValidationError({"to": [f"Najwyżej {MAX_DAYS} dni naraz."]}, code="range_too_long")
    zone = ZoneInfo(Organization.objects.get(pk=call.context.organization_id).timezone)
    listed = list_appointments(
        starts_from=datetime.combine(first, time.min, tzinfo=zone),
        starts_until=datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone),
        limit=AT_ONCE + 1,
    )
    shown = listed[:AT_ONCE]
    numbers = orders.links([item.id for item in shown if item.quote and item.quote["lines"]])
    return {
        "appointments": [
            {
                "appointment_id": str(item.id),
                "service": item.service_name,
                "status": item.status,
                "starts_at": _local_iso(item.starts_at, item.timezone),
                "ends_at": _local_iso(item.ends_at, item.timezone),
                "timezone": item.timezone,
                "place": item.location.name,
                "unit": item.resource.name if item.resource else None,
                "customer": person_handle(CUSTOMER, item.customer_id),
                "order": numbers[item.id]["number"] if item.id in numbers else None,
            }
            for item in shown
        ],
        "more": len(listed) > AT_ONCE,
    }


APPOINTMENTS_READ = CommandSpec(
    name="booking.appointments.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj wizyty i pobyty z kalendarza", "en": "Read the calendar's bookings"},
    summary={
        "pl": "Wizyty i pobyty z wybranych dni: usługa, termin, miejsce, stan i klient "
        "jako karta, którą widzi tylko osoba przy ekranie.",
        "en": "The visits and stays of the chosen days: service, time, place, state and the "
        "customer as a card only the person at the screen sees.",
    },
    model_description=(
        "Returns the bookings that start on the days `from`–`to` (both included, the "
        f"company's local days, at most {MAX_DAYS} at once), earliest first, up to {AT_ONCE} "
        "(`more` says there are others — ask for fewer days): each with its service, "
        "starts_at and ends_at as the company's local time, its place, the unit it takes "
        "when it is a stay or a rental, its status — pending_request (waits for the "
        "company's answer), pending_payment (waits for a prepayment), confirmed, completed, "
        "canceled, no_show — the number of its order when it has one, and `customer`: a "
        "handle such as klient:k7m2q. You never get the customer's name, e-mail or phone; "
        "write the handle where you mean the person and the panel shows the person their "
        "card — so „who comes tomorrow” and „give me the phone of tomorrow's customer” are "
        "both answered with the handle. The person may see only their own visits; then "
        "only those are here. Work the day out from the time stamp of the person's message "
        "(„jutro” is the day after it, in the company's time zone)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["from", "to"],
        "properties": {
            "from": {
                "type": "string",
                "pattern": _DAY,
                "description": "The first day, YYYY-MM-DD, as the company's local day.",
            },
            "to": {
                "type": "string",
                "pattern": _DAY,
                "description": "The last day, YYYY-MM-DD; the same as `from` for one day.",
            },
        },
    },
    # The customer is a handle: nothing here is anybody's personal data.
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "appointments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string"},
                        "service": {"type": "string"},
                        "status": {"type": "string", "enum": _STATUSES},
                        "starts_at": {"type": "string"},
                        "ends_at": {"type": "string"},
                        "timezone": {"type": "string"},
                        "place": {"type": "string"},
                        "unit": {"type": ["string", "null"]},
                        "customer": {"type": "string"},
                        "order": {"type": ["string", "null"]},
                    },
                },
            },
            "more": {"type": "boolean"},
        },
    },
    permission=BOOKING_READ,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_appointments,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)
