"""Reading an order's money (ADR-073 §4): what was paid is the sum of the
ledger's entries, and the order's status follows from it."""

from __future__ import annotations

from typing import Any

from django.db.models import Sum

from saas_core.modules.core.identity.models import User

from .models import (
    LedgerEntry,
    LedgerEntryKind,
    Order,
    OrderStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
)

#: What the company itself marks as received; an online payment is the
#: operator's to confirm, never a person's.
MANUAL_METHODS = (PaymentMethod.CASH.value, PaymentMethod.TRANSFER.value)
#: What a source asks for before it confirms what it sold; a date not kept
#: cancels the order. A `balance` is never one (owner decision 29a).
PREPAYMENT_KINDS = (PaymentKind.DEPOSIT.value, PaymentKind.FULL.value)
#: The kinds that change what the customer has paid.
_PAID_KINDS = (LedgerEntryKind.CHARGE, LedgerEntryKind.REFUND)


def paid_minor(order: Order) -> int:
    """What the customer has paid for the order."""
    total = LedgerEntry.all_objects.filter(
        organization_id=order.organization_id, order=order, kind__in=_PAID_KINDS
    ).aggregate(total=Sum("amount_minor"))["total"]
    return int(total or 0)


def awaited_prepayment(order: Order) -> Payment | None:
    """The payment the order's source waits for before it confirms, if one
    still waits."""
    return (
        Payment.all_objects.filter(
            organization_id=order.organization_id,
            order=order,
            status=PaymentStatus.REQUIRES_PAYMENT,
            kind__in=PREPAYMENT_KINDS,
        )
        .order_by("created_at", "id")
        .first()
    )


def status_for(order: Order, paid: int) -> str:
    """The order's shortcut for lists, from what its lines come to and what
    the ledger says was paid. A canceled order stays canceled and a draft a
    draft; nothing to pay is paid."""
    if order.status in (OrderStatus.CANCELED, OrderStatus.DRAFT):
        # Canceled stays canceled; a draft is placed by its source, not by money.
        return order.status
    if paid >= order.gross_minor:
        return OrderStatus.PAID
    return OrderStatus.PARTIALLY_PAID if paid > 0 else OrderStatus.AWAITING_PAYMENT


def payments_of(order: Order) -> list[dict[str, Any]]:
    """The order's payments, oldest first, with who marked each."""
    rows = list(
        Payment.all_objects.filter(organization_id=order.organization_id, order=order).order_by(
            "created_at", "id"
        )
    )
    people = {
        user.id: " ".join(filter(None, [user.first_name, user.last_name])) or user.email
        for user in User.objects.filter(pk__in={row.recorded_by for row in rows if row.recorded_by})
    }
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "method": row.method,
            "status": row.status,
            "amount_minor": row.amount_minor,
            "due_at": row.due_at,
            "paid_at": row.paid_at,
            "recorded_by": people.get(row.recorded_by, "") if row.recorded_by else "",
        }
        for row in rows
    ]
