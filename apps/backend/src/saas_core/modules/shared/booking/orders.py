"""A booking's order (ADR-073 §1, §3): where the product has commerce and the
company's plan has orders, a priced booking is placed as an order `R/…` in the
booking's own transaction, from the lines of its frozen quote. A move that
changes the price writes the order's next revision; a cancellation cancels it.

Commerce is no dependency of booking: without the module everything here is
silent, and its API is imported late (the pattern of `materials.py`). A booking
made before orders, or without a price, has none and gets none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.conf import settings

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.history import HistoryTarget
from saas_core.modules.shared.customers.api import Customer

from .models import Appointment
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
            register_order_source,
        )

        register_order_source(SOURCE, PREFIX, targets=_targets)


def place(appointment: Appointment, customer: Customer) -> None:
    """A new booking with a price becomes an order."""
    quote = appointment.quote
    if not enabled() or not quote or not quote["lines"]:
        return
    from saas_core.modules.shared.commerce.api import OrderChannel, place_order  # noqa: PLC0415

    public = require_tenant_context().role_key == PUBLIC_BOOKING_ROLE
    place_order(
        source=SOURCE,
        customer=customer,
        currency=quote["currency"],
        amounts=quote["amounts"],
        lines=_lines(appointment, quote),
        channel=OrderChannel.COMPANY_SITE if public else OrderChannel.OFFICE,
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
