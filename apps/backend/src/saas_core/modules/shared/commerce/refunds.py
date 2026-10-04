"""Money given back to a customer (ADR-073 §8, phase 4h): a refund the
company made itself — a transfer back, cash at the desk — and marks here.

The ledger gets a `refund` entry with the amount negative, so what the order
has been paid goes down by it; the row says how, why and who. A refund marked
by mistake is taken back with the opposite entry, like a payment.

What is owed is not decided here. When a source takes back what it sold, it
settles what its own terms give back (`orders.cancel_order`); the company
then marks refunds against that. Giving back more than the terms say — or
anything for an order nobody settled — is the company's own decision and
needs its reason in words.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .ledger import MANUAL_METHODS, awaited_balance, paid_minor, refund_owed, status_for
from .models import LedgerEntry, LedgerEntryKind, Order, OrderStatus, Refund, RefundStatus
from .names import COMMERCE_ENABLED, PAYMENTS_MANAGE
from .orders import order_detail
from .payments import _await, _locked

#: How long the company's reason for a refund may be.
REASON_MAX_LENGTH = 300


def record_refund(
    order_id: UUID,
    *,
    amount_minor: int,
    method: str,
    expected_version: int,
    reason: str = "",
    preview: bool = False,
) -> dict[str, Any]:
    """The company gave `amount_minor` back to the order's customer, by a
    transfer or at the desk. Writes the refund and its ledger entry and
    answers with the order as its page shows it; `preview` checks the same and
    says what the order would be, writing nothing. Locked by the order's
    version, like a payment: a repeat at the version the first call saw is 409.

    Never more than the customer has paid (`refund_exceeds_paid`). Within
    what the order's terms give back (`refund_owed_minor`) no reason is
    asked for; beyond it — or for an order nobody settled — the company says
    why (`reason_required`)."""
    context = authorize_entitled(PAYMENTS_MANAGE, COMMERCE_ENABLED)
    reason = reason.strip()
    with transaction.atomic():
        order = _locked(context, order_id, expected_version)
        paid = paid_minor(order)
        owed = refund_owed(order, paid)
        beyond = amount_minor > owed
        _refuse(order, amount_minor=amount_minor, method=method, paid=paid)
        if beyond and not reason and not preview:
            raise ValidationError({
                "reason": [
                    ErrorDetail(
                        "Zwrot ponad to, co wynika z warunków zamówienia, wymaga powodu.",
                        code="reason_required",
                    )
                ]
            })
        after = paid - amount_minor
        effect = {
            "amount_minor": amount_minor,
            "paid_minor": after,
            "refund_owed_minor": max(owed - amount_minor, 0),
            "status": status_for(order, after),
            "reason_required": beyond,
        }
        if preview:
            return effect
        now = timezone.now()
        refund = Refund.all_objects.create(
            organization_id=order.organization_id,
            order=order,
            method=method,
            status=RefundStatus.SUCCEEDED,
            amount_minor=amount_minor,
            currency=order.currency,
            reason=reason,
            refunded_at=now,
            recorded_by=context.actor_id,
        )
        _post(order, -amount_minor, now)
        # The rest of a price still awaited grows by what went back.
        if (awaited := awaited_balance(order)) is not None:
            _await(awaited, awaited.amount_minor + amount_minor)
        _move(order, after)
        _audit(context, order, "commerce.refund.recorded", refund, beyond_terms=beyond)
        return order_detail(order)


def void_refund(order_id: UUID, refund_id: UUID, *, expected_version: int) -> dict[str, Any]:
    """A refund marked by mistake is taken back: it stays in the order's
    history as canceled and the ledger gets the opposite entry, so the order
    is paid that amount again — and owes it back again where its terms said
    so."""
    context = authorize_entitled(PAYMENTS_MANAGE, COMMERCE_ENABLED)
    with transaction.atomic():
        order = _locked(context, order_id, expected_version)
        refund = Refund.all_objects.filter(
            organization_id=order.organization_id, order=order, pk=refund_id
        ).first()
        if refund is None:
            raise NotFound("Nie ma takiego zwrotu.")
        if refund.status != RefundStatus.SUCCEEDED:
            raise ValidationError({
                "refund": [ErrorDetail("Ten zwrot jest już wycofany.", code="refund_not_voidable")]
            })
        refund.status = RefundStatus.CANCELED
        refund.version += 1
        refund.save(update_fields=["status", "version", "updated_at"])
        _post(order, refund.amount_minor, timezone.now())
        if (awaited := awaited_balance(order)) is not None:
            _await(awaited, max(awaited.amount_minor - refund.amount_minor, 0))
        _move(order, paid_minor(order))
        _audit(context, order, "commerce.refund.voided", refund)
        return order_detail(order)


def _refuse(order: Order, *, amount_minor: int, method: str, paid: int) -> None:
    if order.status == OrderStatus.DRAFT:
        raise ValidationError({
            "order": [
                ErrorDetail(
                    "Zamówienie czeka na przyjęcie rezerwacji i nie ma wpłat.",
                    code="order_not_placed",
                )
            ]
        })
    if method not in MANUAL_METHODS:
        raise ValidationError({
            "method": [
                ErrorDetail(
                    "Ręcznie oznacza się zwrot na miejscu albo przelewem.",
                    code="method_not_manual",
                )
            ]
        })
    if amount_minor > paid:
        raise ValidationError({
            "amount_minor": [
                ErrorDetail(
                    "Kwota jest większa niż to, co klient wpłacił.", code="refund_exceeds_paid"
                )
            ]
        })


def _post(order: Order, amount_minor: int, at: Any) -> None:
    LedgerEntry.all_objects.create(
        organization_id=order.organization_id,
        order=order,
        kind=LedgerEntryKind.REFUND,
        amount_minor=amount_minor,
        currency=order.currency,
        occurred_at=at,
    )


def _move(order: Order, paid: int) -> None:
    order.status = status_for(order, paid)
    order.version += 1
    order.save(update_fields=["status", "version", "updated_at"])


def _audit(
    context: TenantContext, order: Order, action: str, refund: Refund, **metadata: Any
) -> None:
    record_audit(
        organization=order.organization,
        action=action,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="order",
        target_id=order.id,
        # The reason is the company's own words: on the order's page, not in
        # the history every settings manager reads.
        metadata={
            "number": order.number,
            "amount_minor": refund.amount_minor,
            "currency": refund.currency,
            "method": refund.method,
            **metadata,
        },
    )
