"""What a customer paid for an order (ADR-073 §4, §5): a payment the company
marks by hand — cash or a card at the desk, a transfer it saw on its account —
and the ledger the order's balance is read from.

The ledger is append-only and decides about money: what was paid is the sum of
its entries, never a field somebody edits. A mark made by mistake is taken
back with an entry of the opposite sign, not by removing the first.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .ledger import MANUAL_METHODS, paid_minor, status_for
from .models import (
    LedgerEntry,
    LedgerEntryKind,
    Order,
    OrderStatus,
    Payment,
    PaymentKind,
    PaymentStatus,
)
from .orders import COMMERCE_ENABLED, order_detail

PAYMENTS_MANAGE = "commerce.payments.manage"


class OrderVersionConflict(APIException):
    """Somebody changed the order since the caller read it."""

    status_code = 409
    default_code = "order_version_conflict"
    default_detail = "Zamówienie zmieniło się od chwili, gdy je otwarto. Wczytaj je ponownie."
    problem_code = "order_version_conflict"


def record_payment(
    order_id: UUID,
    *,
    amount_minor: int,
    method: str,
    expected_version: int,
    preview: bool = False,
) -> dict[str, Any]:
    """The company received `amount_minor` for the order, at the desk or by a
    transfer. Writes the payment and its ledger entry and moves the order's
    status, and answers with the order as its page shows it; `preview` checks
    the same and says what the order would be, writing nothing. Locked by the
    order's version: a repeat at the version the first
    call saw is 409 and changes nothing, so a retry never marks twice."""
    context = authorize_entitled(PAYMENTS_MANAGE, COMMERCE_ENABLED)
    with transaction.atomic():
        order = _locked(context, order_id, expected_version)
        paid = paid_minor(order)
        _refuse(order, amount_minor=amount_minor, method=method, due=order.gross_minor - paid)
        after = paid + amount_minor
        effect = {
            "amount_minor": amount_minor,
            "paid_minor": after,
            "due_minor": order.gross_minor - after,
            "status": status_for(order, after),
        }
        if preview:
            return effect
        now = timezone.now()
        payment = Payment.all_objects.create(
            organization_id=order.organization_id,
            order=order,
            # The whole at once, the rest of it, or a part ahead of the rest.
            kind=(
                PaymentKind.DEPOSIT
                if after < order.gross_minor
                else PaymentKind.FULL
                if paid == 0
                else PaymentKind.BALANCE
            ),
            method=method,
            status=PaymentStatus.SUCCEEDED,
            amount_minor=amount_minor,
            currency=order.currency,
            paid_at=now,
            recorded_by=context.actor_id,
        )
        _post(order, payment, amount_minor, now)
        _move(order, after)
        _audit(context, order, "commerce.payment.recorded", payment)
        return order_detail(order)


def void_payment(order_id: UUID, payment_id: UUID, *, expected_version: int) -> dict[str, Any]:
    """A payment marked by mistake is taken back: it stays in the order's
    history as canceled, and the ledger gets the opposite entry. Not a refund —
    no money went back to anybody."""
    context = authorize_entitled(PAYMENTS_MANAGE, COMMERCE_ENABLED)
    with transaction.atomic():
        order = _locked(context, order_id, expected_version)
        payment = Payment.all_objects.filter(
            organization_id=order.organization_id, order=order, pk=payment_id
        ).first()
        if payment is None:
            raise NotFound("Nie ma takiej wpłaty.")
        if payment.status != PaymentStatus.SUCCEEDED or payment.method not in MANUAL_METHODS:
            raise ValidationError({
                "payment": [
                    ErrorDetail(
                        "Wycofać można tylko wpłatę oznaczoną ręcznie, która nie jest już "
                        "wycofana.",
                        code="payment_not_voidable",
                    )
                ]
            })
        payment.status = PaymentStatus.CANCELED
        payment.version += 1
        payment.save(update_fields=["status", "version", "updated_at"])
        _post(order, payment, -payment.amount_minor, timezone.now())
        _move(order, paid_minor(order))
        _audit(context, order, "commerce.payment.voided", payment)
        return order_detail(order)


def _locked(context: TenantContext, order_id: UUID, expected_version: int) -> Order:
    order = (
        Order.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, pk=order_id)
        .first()
    )
    if order is None:
        raise NotFound("Nie ma takiego zamówienia.")
    if order.version != expected_version:
        raise OrderVersionConflict
    return order


def _refuse(order: Order, *, amount_minor: int, method: str, due: int) -> None:
    if order.status == OrderStatus.CANCELED:
        raise ValidationError({
            "order": [ErrorDetail("Zamówienie jest anulowane.", code="order_canceled")]
        })
    if method not in MANUAL_METHODS:
        raise ValidationError({
            "method": [
                ErrorDetail(
                    "Ręcznie oznacza się wpłatę na miejscu albo przelew.", code="method_not_manual"
                )
            ]
        })
    if amount_minor > due:
        raise ValidationError({
            "amount_minor": [
                ErrorDetail(
                    "Kwota jest większa niż to, co zostało do zapłaty.", code="amount_exceeds_due"
                )
            ]
        })


def _post(order: Order, payment: Payment, amount_minor: int, at: Any) -> None:
    LedgerEntry.all_objects.create(
        organization_id=order.organization_id,
        order=order,
        payment=payment,
        kind=LedgerEntryKind.CHARGE,
        amount_minor=amount_minor,
        currency=order.currency,
        occurred_at=at,
    )


def _move(order: Order, paid: int) -> None:
    order.status = status_for(order, paid)
    order.version += 1
    order.save(update_fields=["status", "version", "updated_at"])


def _audit(context: TenantContext, order: Order, action: str, payment: Payment) -> None:
    record_audit(
        organization=order.organization,
        action=action,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="order",
        target_id=order.id,
        metadata={
            "number": order.number,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "method": payment.method,
        },
    )
