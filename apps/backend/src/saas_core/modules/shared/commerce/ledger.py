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
    Refund,
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


def refunded_minor(order: Order) -> int:
    """What the company has given back to the customer — the ledger's
    `refund` entries, as a positive amount."""
    total = LedgerEntry.all_objects.filter(
        organization_id=order.organization_id, order=order, kind=LedgerEntryKind.REFUND
    ).aggregate(total=Sum("amount_minor"))["total"]
    return -int(total or 0)


def refund_owed(order: Order, paid: int | None = None) -> int:
    """What the order's terms say is still to be given back (§8): what its
    source settled when it took back what it sold, less what went back
    already — and never more than the customer has paid."""
    if order.refund_due_minor is None:
        return 0
    paid = paid_minor(order) if paid is None else paid
    return max(min(order.refund_due_minor - refunded_minor(order), paid), 0)


def awaited_balance(order: Order) -> Payment | None:
    """The rest of the order's price the customer is to transfer by a date,
    if one is planned and still awaited. Late, it cancels nothing (29a)."""
    return (
        Payment.all_objects.filter(
            organization_id=order.organization_id,
            order=order,
            status=PaymentStatus.REQUIRES_PAYMENT,
            kind=PaymentKind.BALANCE,
        )
        .order_by("created_at", "id")
        .first()
    )


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
    people = _names({row.recorded_by for row in rows if row.recorded_by})
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


def refunds_of(order: Order) -> list[dict[str, Any]]:
    """What was given back for the order, oldest first, with who marked each."""
    rows = list(
        Refund.all_objects.filter(organization_id=order.organization_id, order=order).order_by(
            "created_at", "id"
        )
    )
    people = _names({row.recorded_by for row in rows if row.recorded_by})
    return [
        {
            "id": row.id,
            "method": row.method,
            "status": row.status,
            "amount_minor": row.amount_minor,
            "reason": row.reason,
            "refunded_at": row.refunded_at,
            "recorded_by": people.get(row.recorded_by, "") if row.recorded_by else "",
        }
        for row in rows
    ]


def _names(ids: set[Any]) -> dict[Any, str]:
    return {
        user.id: " ".join(filter(None, [user.first_name, user.last_name])) or user.email
        for user in User.objects.filter(pk__in=ids)
    }
