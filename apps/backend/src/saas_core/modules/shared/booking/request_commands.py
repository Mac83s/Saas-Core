"""The assistant's commands for bookings made „on request” (ADR-076 §1;
ADR-072 §9, ADR-073 „Rozstrzygnięcia plastra 4g”).

Thin adapters over what the panel's Kalendarz › „Prośby” calls: the list of
customers' bookings that wait for the company's answer, and the answer itself
— accepted or declined, once, with the same key and the same refusal as the
panel's buttons (`services.answer_request`).

An answer is a message to somebody outside the company and a booking that
holds or lets go of its time, so each takes its own click as a step nobody
takes back. The customer is never named to a model: a request is its service,
its dates and until when the company may answer, and who asked is a handle the
panel turns into a card for the person at the screen (ADR-076 „karty osób”).
The company's own words to a customer it declines are the person's words — a
model never writes them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.api import CommandSpec, Preview, person_handle
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.customers.api import CUSTOMER

from . import orders
from .command_declarations import _effect, _id, _nullable
from .dispatch import requests as waiting_requests
from .models import Appointment, AppointmentStatus
from .pricing_commands import _money
from .serializers import AppointmentDeclineSerializer
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    AppointmentNotChangeable,
    _decline_reason,
    answer_request,
    appointment_for_tenant,
    local_time,
)

_PUBLIC = "public"


def _local_iso(value: Any, zone: str) -> str | None:
    """The company's wall clock, as a person would read a calendar."""
    if value is None:
        return None
    return str(value.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%dT%H:%M"))


# --- booking.requests.read@1 -----------------------------------------------------------


def _read_requests(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    listed = []
    for item in waiting_requests():
        quote = item.quote or {}
        prepayment = quote.get("prepayment") or {}
        listed.append({
            "request_id": str(item.id),
            "service": item.service_name,
            "unit": item.resource.name if item.resource else None,
            # The company's wall clock, and no time zone beside it: a zone
            # next to a local time was read as „convert this” (walk, 04.10).
            "starts_at": _local_iso(item.starts_at, item.timezone),
            "ends_at": _local_iso(item.ends_at, item.timezone),
            # After this the request expires by itself and the time is let go.
            "answer_by": _local_iso(item.hold_expires_at, item.timezone),
            "currency": quote.get("currency"),
            "gross_minor": quote.get("gross_minor"),
            "prepayment_minor": prepayment.get("amount_minor"),
            # Who asked, as a handle: the panel shows the person their card.
            "customer": person_handle(CUSTOMER, item.customer_id),
        })
    return {"requests": listed}


REQUESTS_READ = CommandSpec(
    name="booking.requests.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj prośby o rezerwację", "en": "Read the booking requests"},
    summary={
        "pl": "Rezerwacje klientów, które czekają na odpowiedź firmy, z terminem odpowiedzi.",
        "en": "Customers' bookings that wait for the company's answer, with the time to answer.",
    },
    model_description=(
        "Returns the customers' bookings of services taken on request that nobody has "
        "answered yet, the one whose time to answer runs out first on top: each with its "
        "request_id, the service, the unit it holds (a cottage, a room) when it is a stay, "
        "starts_at, ends_at and answer_by — already the company's local clock, not UTC: "
        "say the hours exactly as written and convert nothing; after answer_by the "
        "request expires by itself and the time is let go — and, where the booking has a "
        "price, gross_minor and the prepayment the offer asks for (prepayment_minor), in "
        "minor units of currency. `customer` is a handle such as klient:k7m2q, never a "
        "name: write it where you mean who asked and the panel shows the person the "
        "customer's card (name, e-mail, phone); name the request itself by its service and "
        "dates. Use it before accepting or declining a request, to know its request_id."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {"requests": {"type": "array"}},
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_requests,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- booking.request.accept@1 and booking.request.decline@1 ----------------------------


def _waiting(arguments: Mapping[str, Any], call: Any) -> Appointment:
    """The request as it is now: a booking that no longer waits for an answer
    — answered by somebody else, given up, expired — is refused here, before
    anybody is asked to click."""
    found = appointment_for_tenant(call.context.organization_id, _id(arguments, "request_id"))
    if found is None:
        raise NotFound("Rezerwacja nie istnieje.")
    if found.status != AppointmentStatus.PENDING_REQUEST:
        raise AppointmentNotChangeable
    return found


def _named(appointment: Appointment, at: int) -> str:
    """A request as a person knows it: what was asked for and when."""
    locale = ("pl", "en")[at]
    name = f"„{appointment.service_name}”" if at == 0 else f"“{appointment.service_name}”"
    if appointment.resource is not None:
        name += f" ({appointment.resource.name})"
    zone = ZoneInfo(appointment.timezone)
    starts = local_time(appointment.starts_at, appointment.timezone, locale)
    first, last = appointment.starts_at.astimezone(zone), appointment.ends_at.astimezone(zone)
    if first.date() == last.date():
        # A visit by the clock: its day once, then until when.
        return f"{name}, {starts}–{last:%H:%M}"
    return f"{name}, {starts} – {local_time(appointment.ends_at, appointment.timezone, locale)}"


def _reaches(appointment: Appointment) -> bool:
    customer = appointment.customer
    return bool(customer.email) and not customer.anonymized_at


def _awaits_prepayment(appointment: Appointment) -> int | None:
    """What the customer is asked to pay before the booking is confirmed, when
    accepting leads there: the offer asks for money ahead, the company has
    orders and an account to be paid to."""
    terms = (appointment.quote or {}).get("prepayment")
    if not terms or not orders.enabled():
        return None
    from saas_core.modules.shared.commerce.api import transfer_account  # noqa: PLC0415

    return int(terms["amount_minor"]) if transfer_account() is not None else None


def _observed(appointment: Appointment) -> dict[str, int | str]:
    # A request has no version: its state is what an answer must still find.
    return {f"booking.appointment:{appointment.id}": appointment.status}


def _preview_accept(arguments: Mapping[str, Any], call: Any) -> Preview:
    appointment = _waiting(arguments, call)
    awaited = _awaits_prepayment(appointment)
    currency = (appointment.quote or {}).get("currency", "")
    words = []
    for at in (0, 1):
        text = (
            f"Przyjęcie prośby o rezerwację: {_named(appointment, 0)}.",
            f"Accepting the booking request: {_named(appointment, 1)}.",
        )[at]
        if awaited is not None:
            amount = _money(awaited, currency, at)
            text += (
                f" Oferta wymaga przedpłaty {amount}: klient dostanie dane do przelewu, a "
                "rezerwacja będzie potwierdzona po wpłacie.",
                f" The offer asks for a prepayment of {amount}: the customer gets the "
                "transfer's details and the booking is confirmed once it is paid.",
            )[at]
        else:
            text += (
                " Rezerwacja zostanie potwierdzona.",
                " The booking will be confirmed.",
            )[at]
        text += _told(appointment, at)
        words.append(text)
    return Preview(
        effects=(
            _effect("updated", "booking.appointment", str(appointment.id), words[0], words[1]),
        ),
        observed_versions=_observed(appointment),
    )


def _told(appointment: Appointment, at: int) -> str:
    if _reaches(appointment):
        return (
            " Klient dostanie e-mail od razu.",
            " The customer gets an e-mail at once.",
        )[at]
    return (
        " Klient nie podał adresu e-mail — trzeba dać mu znać inaczej.",
        " The customer gave no e-mail address — they have to be told another way.",
    )[at]


def _answered(appointment: Appointment) -> dict[str, Any]:
    return {
        "request_id": str(appointment.id),
        "status": appointment.status,
        # Until when a booking that now waits for its prepayment is held.
        "hold_expires_at": _local_iso(appointment.hold_expires_at, appointment.timezone),
    }


def _answer(arguments: Mapping[str, Any], call: Any, *, accept: bool, reason: str = "") -> Any:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    return answer_request(
        appointment_id=_id(arguments, "request_id"),
        accept=accept,
        idempotency_key=call.idempotency_key,
        principal_ref=str(context.actor_id),
        reason=reason,
    )


def _accept(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return _answered(_answer(arguments, call, accept=True))


_ANSWER_OUTPUT = {
    "type": "object",
    "x-data-class": _PUBLIC,
    "properties": {
        "request_id": {"type": "string"},
        "status": {"type": "string"},
        "hold_expires_at": {"type": ["string", "null"]},
    },
}
_REQUEST_ID = {
    "type": "string",
    "description": "The request's id from booking.requests.read.",
}

REQUEST_ACCEPT = CommandSpec(
    name="booking.request.accept",
    version=1,
    module="shared.booking",
    title={"pl": "Przyjmij prośbę o rezerwację", "en": "Accept a booking request"},
    summary={
        "pl": "Firma przyjmuje rezerwację, która czekała na jej odpowiedź.",
        "en": "The company takes a booking that waited for its answer.",
    },
    model_description=(
        "Accepts a customer's booking that waits for the company's answer: the booking is "
        "confirmed (status confirmed) — or, where the offer asks for a prepayment, the "
        "customer gets the transfer's details and the booking waits for that payment "
        "(status pending_payment, held until hold_expires_at). The customer is written to "
        "at once, so it cannot be taken back: calling the booking off afterwards is a "
        "cancellation, done in the calendar. Use booking.requests.read first; when several "
        "requests wait and the person did not say which, ask — never pick one. A request "
        "that somebody answered already, that the customer gave up or that expired is "
        "refused (appointment_not_changeable)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["request_id"],
        "properties": {"request_id": _REQUEST_ID},
    },
    output_schema=_ANSWER_OUTPUT,
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="irreversible",
    run=_accept,
    undo="none:the customer has been written to; an accepted booking is called off in the calendar",
    preview=_preview_accept,
    no_version_reason="A request has no version: the consent binds its state "
    "(pending_request), and the service answers a request once.",
)


def _reason(arguments: Mapping[str, Any]) -> str:
    serializer = AppointmentDeclineSerializer(data={"reason": arguments["reason"] or ""})
    serializer.is_valid(raise_exception=True)
    return str(serializer.validated_data.get("reason", ""))


def _preview_decline(arguments: Mapping[str, Any], call: Any) -> Preview:
    appointment = _waiting(arguments, call)
    # The same refusal as the write gives: no link and no address in words
    # that go out in a platform's mail (answer 36a).
    reason = _decline_reason(_reason(arguments))
    words = []
    for at in (0, 1):
        text = (
            f"Odmowa prośby o rezerwację: {_named(appointment, 0)}. Termin zostaje zwolniony.",
            f"Declining the booking request: {_named(appointment, 1)}. Its time is let go.",
        )[at]
        text += _told(appointment, at)
        if reason and _reaches(appointment):
            text += (
                f" W e-mailu będą Twoje słowa: „{reason}”.",
                f" The e-mail carries your words: “{reason}”.",
            )[at]
        words.append(text)
    return Preview(
        effects=(
            _effect("updated", "booking.appointment", str(appointment.id), words[0], words[1]),
        ),
        observed_versions=_observed(appointment),
    )


def _decline(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return _answered(_answer(arguments, call, accept=False, reason=_reason(arguments)))


REQUEST_DECLINE = CommandSpec(
    name="booking.request.decline",
    version=1,
    module="shared.booking",
    title={"pl": "Odmów prośbie o rezerwację", "en": "Decline a booking request"},
    summary={
        "pl": "Firma nie przyjmuje rezerwacji, która czekała na jej odpowiedź.",
        "en": "The company does not take a booking that waited for its answer.",
    },
    model_description=(
        "Declines a customer's booking that waits for the company's answer: the booking "
        "lets its time go (status canceled), its draft order is canceled and the customer "
        "is written to at once, so it cannot be taken back. reason is what the company "
        "tells that customer — the person's own words, exactly as they said them, up to 300 "
        "characters of plain text without a link or an address; pass null when the person "
        "gave no reason. Never write a reason yourself and never reword one. Use "
        "booking.requests.read first; when several requests wait and the person did not "
        "say which, ask. A request that no longer waits is refused "
        "(appointment_not_changeable)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["request_id", "reason"],
        "properties": {
            "request_id": _REQUEST_ID,
            "reason": _nullable(
                "string",
                "The company's words to the customer, as the person said them; null for none.",
            ),
        },
    },
    output_schema=_ANSWER_OUTPUT,
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="irreversible",
    run=_decline,
    undo="none:the customer has been written to and the time is free again",
    preview=_preview_decline,
    no_version_reason="A request has no version: the consent binds its state "
    "(pending_request), and the service answers a request once.",
)

REQUEST_COMMANDS = (REQUESTS_READ, REQUEST_ACCEPT, REQUEST_DECLINE)
