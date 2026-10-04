"""What a customer paid for an order (ADR-073 §4, §5): a payment the company
marks by hand — cash or a card at the desk, a transfer it saw on its account —
and the ledger the order's balance is read from.

The ledger is append-only and decides about money: what was paid is the sum of
its entries, never a field somebody edits. A mark made by mistake is taken
back with an entry of the opposite sign, not by removing the first.

A source may ask for a part of the order, or all of it, before it confirms
what it sold (`request_prepayment`): the payment then waits with a date
(`requires_payment`, `due_at`), the customer gets the transfer's details, and
the source's handler hears which came first — the money (`prepaid`) or the
date (`expired`, from the deadlines' task).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext, require_tenant_context
from saas_core.modules.core.organizations.tasks import issue_service_task_contract
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.notifications.security import encrypt_secret

from . import emails
from .balance import balance_due, overdue_balance
from .ledger import (
    MANUAL_METHODS,
    PREPAYMENT_KINDS,
    awaited_balance,
    awaited_prepayment,
    paid_minor,
    refund_owed,
    status_for,
)
from .models import (
    LedgerEntry,
    LedgerEntryKind,
    Order,
    OrderLine,
    OrderStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    PaymentRoute,
    PaymentStatus,
)
from .names import COMMERCE_ENABLED, DEADLINES_PERMISSIONS, DEADLINES_ROLE, PAYMENTS_MANAGE
from .orders import cancel_order, order_detail
from .sources import order_source
from .transfer_account import transfer_account

#: Why an order whose prepayment did not come is canceled, in its history.
PAYMENT_EXPIRED = "payment_expired"


class OrderVersionConflict(APIException):
    """Somebody changed the order since the caller read it."""

    status_code = 409
    default_code = "order_version_conflict"
    default_detail = "Zamówienie zmieniło się od chwili, gdy je otwarto. Wczytaj je ponownie."
    problem_code = "order_version_conflict"


def request_prepayment(
    order: Order,
    *,
    kind: str,
    amount_minor: int,
    transfer_days: int,
    before: datetime,
    link: str = "",
) -> datetime | None:
    """The source wants `amount_minor` of the order it has just placed before
    it confirms what it sold — a `deposit` or the `full` amount, worked out by
    the source. Answers until when the customer has to pay, and the source
    holds its record until then; or None where the amount cannot be paid
    ahead — the company gave no bank account, or nothing is left of the time
    before `before` (the start of what was sold) — and the amount is then due
    on site: the source confirms at once.

    The date is commerce's (§5): `transfer_days` from now, never past
    `before`. The customer gets the transfer's details by e-mail — with
    `link`, the source's own address where the buyer sees what they bought
    and can give it up; the source's handler hears `prepaid` when the company
    marks the payment and `expired` when the date passes first.
    """
    context = require_tenant_context()
    if not connection.in_atomic_block:
        raise RuntimeError("A prepayment is asked for inside the order's transaction.")
    if kind not in PREPAYMENT_KINDS or not 0 < amount_minor <= order.gross_minor:
        raise ValueError("A prepayment is a deposit or the whole, within the order's amount.")
    if order.status == OrderStatus.DRAFT:
        raise RuntimeError("A draft takes no payment: its source accepts it first.")
    if order_source(order.source).handler is None:
        raise RuntimeError(f"Order source {order.source!r} asks for a payment and hears nothing.")
    account = transfer_account()
    now = timezone.now()
    due_at = min(now + timedelta(days=transfer_days), before)
    if account is None or due_at <= now:
        return None
    payment = Payment.all_objects.create(
        organization_id=order.organization_id,
        order=order,
        kind=kind,
        method=PaymentMethod.TRANSFER,
        status=PaymentStatus.REQUIRES_PAYMENT,
        amount_minor=amount_minor,
        currency=order.currency,
        due_at=due_at,
    )
    PaymentRoute.objects.create(
        payment_id=payment.id,
        organization_id=order.organization_id,
        # The organization's own contract: the date comes whoever placed the
        # order has left by then (the lesson of the reminders, ADR-058 §7).
        signed_tenant_context=encrypt_secret(
            issue_service_task_contract(
                organization_id=order.organization_id,
                role_key=DEADLINES_ROLE,
                permissions=DEADLINES_PERMISSIONS,
                causation_id=f"commerce-payment:{payment.id}",
            )
        ),
        due_at=due_at,
    )
    order.version += 1
    order.save(update_fields=["version", "updated_at"])
    record_audit(
        organization=order.organization,
        action="commerce.payment.requested",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="order",
        target_id=order.id,
        metadata={
            "number": order.number,
            "amount_minor": amount_minor,
            "currency": order.currency,
            "method": payment.method,
            "due_at": due_at.isoformat(),
        },
    )
    emails.transfer_details(order, payment, account, link=link)
    return due_at


def awaited_transfer(source: str, reference: str) -> dict[str, Any] | None:
    """What the buyer of a source's record is still to transfer, and where:
    the order's number (the transfer's title), the amount, the date and the
    company's account — and which payment it is (`kind`): one the record
    waits for before it is confirmed (`deposit`, `full`), or the rest of a
    confirmed one's price (`balance`). None when nothing is awaited.
    For the source's own answer to its customer — the page after booking, the
    customer's link — so it asks for no permission of the company's people."""
    context = require_tenant_context()
    order = Order.all_objects.filter(
        organization_id=context.organization_id,
        pk__in=OrderLine.all_objects.filter(
            organization_id=context.organization_id, source=source, source_reference=reference
        ).values("order_id"),
    ).first()
    payment = _awaited(order) if order is not None else None
    account = transfer_account()
    if order is None or payment is None or account is None:
        return None
    return {
        "kind": payment.kind,
        "number": order.number,
        "amount_minor": payment.amount_minor,
        "currency": payment.currency,
        "due_at": payment.due_at,
        "account_holder": account.holder,
        "account_number": account.number,
        "bank_name": account.bank,
    }


def order_money(order: Order) -> dict[str, Any]:
    """An order's money as its source needs it to settle its record by its
    own terms (§8): what the customer has paid, what the settlement still
    owes back, and whether the rest of the price is late."""
    paid = paid_minor(order)
    return {
        "currency": order.currency,
        "paid_minor": paid,
        "refund_owed_minor": refund_owed(order, paid),
        "balance_overdue": overdue_balance(order),
    }


def money_of(source: str, reference: str) -> dict[str, Any] | None:
    """`order_money` of the order a source's record stands on, read without
    a lock — for the source's own pages. None where the record has no order."""
    context = require_tenant_context()
    order = Order.all_objects.filter(
        organization_id=context.organization_id,
        pk__in=OrderLine.all_objects.filter(
            organization_id=context.organization_id, source=source, source_reference=reference
        ).values("order_id"),
    ).first()
    return order_money(order) if order is not None else None


def expire_prepayment(payment_id: UUID) -> bool:
    """The date of a payment a source waited for has passed: the payment
    expires, its order is canceled and the source lets go of what it held —
    in the caller's transaction and tenant (the deadlines' task). Says whether
    anything expired: a payment marked or called off meanwhile is left as it
    is, and so is a balance — late, it cancels nothing by itself (owner
    decision 29a)."""
    context = require_tenant_context()
    found = Payment.all_objects.filter(
        organization_id=context.organization_id, pk=payment_id
    ).first()
    if found is None:
        return False
    # The order first, as every write on its payments locks it.
    order = Order.all_objects.select_for_update().get(
        organization_id=context.organization_id, pk=found.order_id
    )
    payment = awaited_prepayment(order)
    if (
        payment is None
        or payment.id != payment_id
        or payment.due_at is None
        or payment.due_at > timezone.now()
    ):
        return False
    cancel_order(order, awaited=PaymentStatus.EXPIRED, reason=PAYMENT_EXPIRED)
    handler = order_source(order.source).handler
    if handler is not None:
        handler.expired(order)
    return True


def payment_due(payment_id: UUID) -> tuple[bool, datetime | None]:
    """The deadlines' task came to a payment, in the payment's own tenant:
    says whether an order expired, and when to come back for the payment — a
    balance is looked at twice, to remind before its date and to report it
    late at it; None when there is nothing more to come for."""
    context = require_tenant_context()
    found = Payment.all_objects.filter(
        organization_id=context.organization_id, pk=payment_id
    ).first()
    if found is None:
        return False, None
    if found.kind != PaymentKind.BALANCE:
        return expire_prepayment(payment_id), None
    # The order first, as every write on its payments locks it.
    order = Order.all_objects.select_for_update().get(
        organization_id=context.organization_id, pk=found.order_id
    )
    payment = awaited_balance(order)
    if payment is None or payment.id != payment_id:
        return False, None
    return False, balance_due(payment, order)


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
    call saw is 409 and changes nothing, so a retry never marks twice.

    Where the order waits for a payment, an amount that covers it is that
    payment — however it came, the row that waited is the one marked; a
    smaller amount is a payment of its own and leaves the rest awaited until
    the same date. Covering a prepayment makes the source confirm what it
    held (`prepayment_met`); a balance changes nothing but the money."""
    context = authorize_entitled(PAYMENTS_MANAGE, COMMERCE_ENABLED)
    with transaction.atomic():
        order = _locked(context, order_id, expected_version)
        paid = paid_minor(order)
        _refuse(order, amount_minor=amount_minor, method=method, due=order.gross_minor - paid)
        after = paid + amount_minor
        awaited = _awaited(order)
        covered = awaited is not None and amount_minor >= awaited.amount_minor
        met = covered and awaited is not None and awaited.kind in PREPAYMENT_KINDS
        effect = {
            "amount_minor": amount_minor,
            "paid_minor": after,
            "due_minor": order.gross_minor - after,
            "status": status_for(order, after),
            "prepayment_met": met,
        }
        if preview:
            return effect
        now = timezone.now()
        marked = {
            # The whole at once, the rest of it, or a part ahead of the rest.
            "kind": (
                PaymentKind.DEPOSIT
                if after < order.gross_minor
                else PaymentKind.FULL
                if paid == 0
                else PaymentKind.BALANCE
            ),
            "method": method,
            "status": PaymentStatus.SUCCEEDED,
            "amount_minor": amount_minor,
            "paid_at": now,
            "recorded_by": context.actor_id,
        }
        if awaited is not None and covered:
            payment = awaited
            for name, value in marked.items():
                setattr(payment, name, value)
            payment.version += 1
            payment.save(update_fields=[*marked, "version", "updated_at"])
            PaymentRoute.objects.filter(payment_id=payment.id).delete()
        else:
            payment = Payment.all_objects.create(
                organization_id=order.organization_id,
                order=order,
                currency=order.currency,
                **marked,
            )
            if awaited is not None:
                _await(awaited, awaited.amount_minor - amount_minor)
        _post(order, payment, amount_minor, now)
        _move(order, after)
        _audit(context, order, "commerce.payment.recorded", payment)
        if met:
            handler = order_source(order.source).handler
            if handler is not None:
                handler.prepaid(order)
        return order_detail(order)


def void_payment(order_id: UUID, payment_id: UUID, *, expected_version: int) -> dict[str, Any]:
    """A payment marked by mistake is taken back: it stays in the order's
    history as canceled, and the ledger gets the opposite entry. Not a refund —
    no money went back to anybody. What the source confirmed when the payment
    was marked stays confirmed: taking a booking back is the company's own
    decision, never a side effect of a correction."""
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
        # A part of a payment still awaited is awaited again.
        if (awaited := _awaited(order)) is not None:
            _await(awaited, awaited.amount_minor + payment.amount_minor)
        _post(order, payment, -payment.amount_minor, timezone.now())
        _move(order, paid_minor(order))
        _audit(context, order, "commerce.payment.voided", payment)
        return order_detail(order)


def _awaited(order: Order) -> Payment | None:
    """The payment the order waits for: what its source asked for before it
    confirms, else the rest due by a transfer."""
    return awaited_prepayment(order) or awaited_balance(order)


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
    if order.status == OrderStatus.DRAFT:
        raise ValidationError({
            "order": [
                ErrorDetail(
                    "Zamówienie czeka na przyjęcie rezerwacji. Najpierw odpowiedz na prośbę "
                    "klienta.",
                    code="order_not_placed",
                )
            ]
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


def _await(payment: Payment, amount_minor: int) -> None:
    """What is still awaited of a prepayment, after a part came or went."""
    payment.amount_minor = amount_minor
    payment.version += 1
    payment.save(update_fields=["amount_minor", "version", "updated_at"])


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
