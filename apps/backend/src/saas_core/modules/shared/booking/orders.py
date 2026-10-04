"""A booking's order (ADR-073 §1, §3): where the product has commerce and the
company's plan has orders, a priced booking is placed as an order `R/…` in the
booking's own transaction, from the lines of its frozen quote. A move that
changes the price writes the order's next revision; a cancellation cancels it.

An offer that asks for money before it confirms (`transfer`, `deposit`,
`full`) asks commerce for that payment right after placing the order (§5):
the booking then waits (`pending_payment`) until the date commerce names, and
commerce tells booking which came first — the money (`_prepaid` confirms the
booking) or the date (`_expired` lets its time go).

Commerce is no dependency of booking: without the module everything here is
silent, and its API is imported late (the pattern of `materials.py`). A booking
made before orders, or without a price, has none and gets none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.history import HistoryTarget
from saas_core.modules.shared.customers.api import Customer

from .models import Appointment, PaymentPolicy, Service
from .security import PUBLIC_BOOKING_ROLE

#: The order source bookings register as, and the prefix of their numbers.
SOURCE = "booking"
PREFIX = "R"
#: What a line of such an order stands for.
LINE_SOURCE = "booking.appointment"
#: A quote line's kind as an order line's; every other kind is the booking itself.
_LINE_KINDS = {"extra": "extra", "discount": "discount"}


def enabled() -> bool:
    return "shared.commerce" in settings.ACTIVE_MODULES


def register() -> None:
    """From `BookingConfig.ready`."""
    if enabled():
        from saas_core.modules.shared.commerce.api import (  # noqa: PLC0415
            OrderHandler,
            register_order_source,
            register_transfer_account_use,
        )

        register_order_source(
            SOURCE,
            PREFIX,
            targets=_targets,
            handler=OrderHandler(prepaid=_prepaid, expired=_expired),
        )
        # The company's account stays while an offer asks for a transfer.
        register_transfer_account_use(_asks_for_transfer)


def orders_available() -> bool:
    """Whether the company's bookings become orders at all: the product has
    commerce and the company's plan has orders. Without them an offer takes
    no payment ahead (ADR-072 §8)."""
    if not enabled():
        return False
    from saas_core.modules.shared.billing.decisions import decide_feature  # noqa: PLC0415
    from saas_core.modules.shared.commerce.api import COMMERCE_ENABLED  # noqa: PLC0415

    return bool(decide_feature(COMMERCE_ENABLED).allowed)


def transfer_account_set() -> bool:
    """Whether the company gave the account its customers transfer to."""
    if not enabled():
        return False
    from saas_core.modules.shared.commerce.api import transfer_account  # noqa: PLC0415

    return transfer_account() is not None


def prepayment_available() -> bool:
    """Whether a customer of the company can pay before the booking is
    confirmed: today by a transfer to the company's account; online comes
    with the operator (ADR-073 §5)."""
    return orders_available() and transfer_account_set()


def place(
    appointment: Appointment,
    customer: Customer,
    *,
    hold: bool = True,
    draft: bool = False,
    link: str = "",
) -> datetime | None:
    """A new booking with a price becomes an order. Where its quote asks for
    a prepayment, commerce is asked for it and the answer is until when the
    booking waits — None: nothing is awaited, the booking is confirmed.
    `hold` false is for a booking that never waits (a visit under way).
    `draft`: the booking waits for the company's answer first — its order has
    no number and asks for nothing until `accepted`. `link`: the customer's
    own link to the booking, for the mail with the transfer's details."""
    quote = appointment.quote
    if not enabled() or not quote or not quote["lines"]:
        return None
    from saas_core.modules.shared.commerce.api import (  # noqa: PLC0415
        OrderChannel,
        place_order,
    )

    public = require_tenant_context().role_key == PUBLIC_BOOKING_ROLE
    order = place_order(
        source=SOURCE,
        customer=customer,
        currency=quote["currency"],
        amounts=quote["amounts"],
        lines=_lines(appointment, quote),
        channel=OrderChannel.COMPANY_SITE if public else OrderChannel.OFFICE,
        draft=draft,
    )
    if order is None or draft or not hold:
        return None
    return _prepayment(appointment, order, link)


def accepted(appointment: Appointment, *, link: str = "") -> datetime | None:
    """The company accepted the request: its order gets its number, and where
    the quote asks for a prepayment the booking now waits for that — the
    answer is until when, None when nothing is awaited."""
    if not enabled():
        return None
    from saas_core.modules.shared.commerce.api import accept_order, order_for  # noqa: PLC0415

    order = order_for(LINE_SOURCE, str(appointment.id))
    if order is None:
        return None
    return _prepayment(appointment, accept_order(order), link)


def _prepayment(appointment: Appointment, order: Any, link: str) -> datetime | None:
    """Asks commerce for what the booking's quote wants paid ahead."""
    from saas_core.modules.shared.commerce.api import request_prepayment  # noqa: PLC0415

    terms = (appointment.quote or {}).get("prepayment")
    if not terms:
        return None
    return request_prepayment(
        order,
        kind=terms["kind"],
        amount_minor=terms["amount_minor"],
        transfer_days=terms["transfer_due_days"],
        # A transfer is no use once the booking has begun.
        before=appointment.starts_at,
        link=link,
    )


def repriced(appointment: Appointment) -> None:
    """The booking was priced again for its new time."""
    quote = appointment.quote
    if not enabled() or not quote or not quote["lines"]:
        return
    from saas_core.modules.shared.commerce.api import order_for, reprice_order  # noqa: PLC0415

    order = order_for(LINE_SOURCE, str(appointment.id))
    if order is not None:
        reprice_order(order, amounts=quote["amounts"], lines=_lines(appointment, quote))


def canceled(appointment: Appointment) -> None:
    if not enabled():
        return
    from saas_core.modules.shared.commerce.api import cancel_order, order_for  # noqa: PLC0415

    order = order_for(LINE_SOURCE, str(appointment.id))
    if order is not None:
        cancel_order(order)


def lock(appointment_id: UUID) -> None:
    """Takes the booking's order before the booking itself. Commerce changes
    an order and then tells booking — a payment marked, a date passed — so a
    change that starts from the booking and ends in its order (calling it
    off) locks the two in the same order, or a customer giving up a booking
    while the company marks its payment would wait on each other."""
    if enabled():
        from saas_core.modules.shared.commerce.api import order_for  # noqa: PLC0415

        order_for(LINE_SOURCE, str(appointment_id))


def links(appointment_ids: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    """The orders of a list of visits, for a link from each: `{"id",
    "number"}` by visit. One read; empty for a caller who may not read
    orders."""
    if not enabled() or not appointment_ids:
        return {}
    from saas_core.modules.shared.commerce.api import orders_of  # noqa: PLC0415

    found = orders_of(LINE_SOURCE, [str(visit_id) for visit_id in appointment_ids])
    return {UUID(reference): order for reference, order in found.items()}


def awaited(appointment: Appointment) -> dict[str, Any] | None:
    """What the booking's customer still has to pay before it is confirmed,
    and where (the transfer's details) — for the customer's own pages."""
    if not enabled():
        return None
    from saas_core.modules.shared.commerce.api import awaited_transfer  # noqa: PLC0415

    return awaited_transfer(LINE_SOURCE, str(appointment.id))


def _booked(order: Any) -> Appointment | None:
    """The booking an order of this source stands for, locked."""
    from saas_core.modules.shared.commerce.api import order_references  # noqa: PLC0415

    references = order_references(order, LINE_SOURCE)
    return (
        Appointment.all_objects.select_for_update(of=("self",))
        .filter(organization_id=order.organization_id, pk__in=references)
        .first()
    )


def _prepaid(order: Any) -> None:
    """Commerce: the payment the booking waited for has come."""
    from .services import confirm_pending  # noqa: PLC0415

    appointment = _booked(order)
    if appointment is not None:
        confirm_pending(appointment)


def _expired(order: Any) -> None:
    """Commerce: it has not come by its date, and the order is canceled."""
    from .services import expire_pending  # noqa: PLC0415

    appointment = _booked(order)
    if appointment is not None:
        expire_pending(appointment)


def _asks_for_transfer(organization_id: UUID) -> bool:
    return Service.all_objects.filter(
        organization_id=organization_id, payment_policy=PaymentPolicy.TRANSFER
    ).exists()


def _targets(
    organization_id: UUID, source: str, references: Sequence[str]
) -> Mapping[str, HistoryTarget]:
    """A line of a booking's order is the visit: its offer, its start and its
    day in the calendar — as the company's history names a visit."""
    if source != LINE_SOURCE:
        return {}
    from .history_targets import appointment_targets  # noqa: PLC0415

    named = appointment_targets(organization_id, [UUID(reference) for reference in references])
    return {str(visit_id): target for visit_id, target in named.items()}


def _lines(appointment: Appointment, quote: dict[str, Any]) -> list[Any]:
    from saas_core.modules.shared.commerce.api import OrderLineInput  # noqa: PLC0415

    return [
        OrderLineInput(
            kind=_LINE_KINDS.get(line["kind"], "booking"),
            name=line["name"][:240],
            customer_name=line["customer_name"][:240],
            quantity=line["quantity"],
            unit_amount_minor=line["unit_amount_minor"],
            net_minor=line["net_minor"],
            vat_minor=line["vat_minor"],
            gross_minor=line["gross_minor"],
            tax_rate=line["vat_code"],
            source=LINE_SOURCE,
            source_reference=str(appointment.id),
        )
        for line in quote["lines"]
    ]
