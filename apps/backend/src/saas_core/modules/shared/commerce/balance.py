"""The rest of an order's price, due by a transfer before what was sold begins
(ADR-073 §5, owner decision 29a, phase 4h).

A source whose customer paid a part ahead may plan the rest (`plan_balance`):
the payment then waits with a date (`balance`, `requires_payment`), the buyer
gets its details — when it is planned, once more as the date comes near and
again when it has passed — and the company's people who manage payments are
told when it is late.

A late balance cancels nothing: the booking stays confirmed, and calling it
off is the company's own decision — only it knows whether the transfer is on
its way. So the deadlines' task, which expires an unpaid prepayment, only
reports a balance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.api import (
    SettingGroup,
    SettingSpec,
    register_setting_group,
    setting,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.core.organizations.tasks import issue_service_task_contract
from saas_core.modules.shared.notifications.api import (
    notify_in_app,
    public_url,
    queue_email,
    staff_locale,
)
from saas_core.modules.shared.notifications.security import encrypt_secret

from . import emails
from .ledger import CLOSED_STATUSES, awaited_balance, paid_minor
from .models import (
    Order,
    OrderStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    PaymentRoute,
    PaymentStatus,
)
from .names import COMMERCE_ENABLED, DEADLINES_PERMISSIONS, DEADLINES_ROLE, PAYMENTS_MANAGE
from .sources import order_source
from .transfer_account import transfer_account

REMIND_DAYS = "commerce.balance.remind_days_before"
#: The notice in the panel of the people who manage payments.
OVERDUE_NOTICE = "commerce.balance_overdue"

BALANCE = SettingGroup(
    key="commerce.balance",
    module="shared.commerce",
    title={"pl": "Dopłaty przelewem", "en": "Balances by a transfer"},
    description={
        "pl": "Gdy oferta każe dopłacić resztę przelewem przed początkiem rezerwacji, klient "
        "dostaje dane do przelewu, przypomnienie przed terminem i wiadomość po terminie. "
        "Spóźniona dopłata niczego nie odwołuje — o odwołaniu decydujesz samodzielnie.",
        "en": "When an offer asks for the rest by a transfer before the booking starts, the "
        "customer gets the transfer's details, a reminder before the date and a message "
        "after it. A late balance calls nothing off — that is your own decision.",
    },
    permission=PAYMENTS_MANAGE,
    entitlement=COMMERCE_ENABLED,
    area="customer-payments",
    settings=(
        SettingSpec(
            key=REMIND_DAYS,
            type="int",
            default=3,
            minimum=0,
            maximum=30,
            unit="day",
            scopes=("organization",),
            label={"pl": "Przypomnienie o dopłacie", "en": "Balance reminder"},
            help={
                "pl": "Ile dni przed terminem dopłaty klient dostaje przypomnienie. 0: bez "
                "przypomnienia przed terminem.",
                "en": "How many days before the balance's date the customer is reminded. "
                "0: no reminder before the date.",
            },
            model_description="How many days before a balance's due date the customer gets "
            "a reminder with the transfer's details (0–30; 0 sends none before the date). "
            "After the date the customer is told once more and the company's people who "
            "manage payments get a notice; nothing is canceled automatically.",
        ),
    ),
)


def register_balance_settings() -> None:
    """From `CommerceConfig.ready`, after the area of the transfer account."""
    register_setting_group(BALANCE)


def plan_balance(
    order: Order, *, due_at: datetime, link: str = "", planned_only: bool = False
) -> datetime | None:
    """The rest of the order is due by a transfer until `due_at` — the source
    names the date, from its own terms — or, for an order that already has a
    balance planned, the date and the amount follow what the source changed
    (a booking moved, priced again; `planned_only` then leaves an order
    without a plan as it is). Answers the date, or None where nothing is
    planned: nothing is left to pay, the date has passed, or the company gave
    no bank account — the rest is then paid on site, as without a plan.

    The buyer gets the transfer's details now. Called by the source inside
    the transaction that confirmed or changed what it sold."""
    context = require_tenant_context()
    if not connection.in_atomic_block:
        raise RuntimeError("A balance is planned inside the order's transaction.")
    waiting = awaited_balance(order)
    account = transfer_account()
    left = order.gross_minor - paid_minor(order)
    now = timezone.now()
    if order.status == OrderStatus.DRAFT or order.status in CLOSED_STATUSES:
        return None
    if waiting is None and planned_only:
        return None
    if account is None or left <= 0 or due_at <= now:
        if waiting is not None:
            _close(waiting)
            order.version += 1
            order.save(update_fields=["version", "updated_at"])
        return None
    if waiting is not None and (waiting.due_at, waiting.amount_minor) == (due_at, left):
        return due_at
    if waiting is None:
        waiting = Payment.all_objects.create(
            organization_id=order.organization_id,
            order=order,
            kind=PaymentKind.BALANCE,
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.REQUIRES_PAYMENT,
            amount_minor=left,
            currency=order.currency,
            due_at=due_at,
        )
    else:
        waiting.amount_minor, waiting.due_at = left, due_at
        waiting.version += 1
        waiting.save(update_fields=["amount_minor", "due_at", "version", "updated_at"])
    _arm(order, waiting)
    order.version += 1
    order.save(update_fields=["version", "updated_at"])
    record_audit(
        organization=order.organization,
        action="commerce.balance.planned",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="order",
        target_id=order.id,
        metadata={
            "number": order.number,
            "amount_minor": left,
            "currency": order.currency,
            "method": waiting.method,
            "due_at": due_at.isoformat(),
        },
    )
    emails.balance(order, waiting, account, link=link or _link(order), step="planned")
    return due_at


def balance_due(payment: Payment, order: Order) -> datetime | None:
    """The deadlines' task came to a balance (its order locked): before its
    date the buyer is reminded, and the answer is the date — the task comes
    back then; at its date, unpaid, the buyer is told it is late and so are
    the company's people who manage payments, and the answer is None: there
    is nothing more to come back for. Nothing is canceled (29a)."""
    account = transfer_account()
    if payment.due_at is None or account is None:
        return None
    if payment.due_at > timezone.now():
        emails.balance(order, payment, account, link=_link(order), step="reminder")
        return payment.due_at
    emails.balance(order, payment, account, link=_link(order), step="overdue")
    _tell_the_company(order, payment)
    record_audit(
        organization=order.organization,
        action="commerce.balance.overdue",
        actor=None,
        target_type="order",
        target_id=order.id,
        metadata={
            "number": order.number,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "due_at": payment.due_at.isoformat(),
        },
    )
    return None


def overdue_balance(order: Order) -> bool:
    """Whether the order's balance was due and has not been paid."""
    waiting = awaited_balance(order)
    return waiting is not None and waiting.due_at is not None and waiting.due_at <= timezone.now()


def _arm(order: Order, payment: Payment) -> None:
    """When the deadlines' task next looks at the balance: the company's days
    before its date for the reminder, else the date itself."""
    assert payment.due_at is not None
    days = int(setting(REMIND_DAYS) or 0)
    reminder = payment.due_at - timedelta(days=days)
    look_at = reminder if days > 0 and reminder > timezone.now() else payment.due_at
    PaymentRoute.objects.update_or_create(
        payment_id=payment.id,
        defaults={
            "organization_id": order.organization_id,
            # The organization's own contract, as for a prepayment's date.
            "signed_tenant_context": encrypt_secret(
                issue_service_task_contract(
                    organization_id=order.organization_id,
                    role_key=DEADLINES_ROLE,
                    permissions=DEADLINES_PERMISSIONS,
                    causation_id=f"commerce-payment:{payment.id}",
                )
            ),
            "due_at": look_at,
            "dispatched_at": None,
        },
    )


def _close(payment: Payment) -> None:
    payment.status = PaymentStatus.CANCELED
    payment.version += 1
    payment.save(update_fields=["status", "version", "updated_at"])
    PaymentRoute.objects.filter(payment_id=payment.id).delete()


def _link(order: Order) -> str:
    """The buyer's own address of what they bought, as its source gives it."""
    handler = order_source(order.source).handler
    return handler.link(order) if handler is not None and handler.link is not None else ""


def _tell_the_company(order: Order, payment: Payment) -> None:
    """The people who mark payments hear that a balance is late: in the panel
    and by e-mail, once per balance and date. The notice names the order and
    the amount, never the buyer."""
    assert payment.due_at is not None
    payload: dict[str, Any] = {
        "order_id": str(order.id),
        "number": order.number,
        "amount_minor": payment.amount_minor,
        "currency": payment.currency,
        "due_at": payment.due_at.isoformat(),
    }
    for membership in _payment_managers(order.organization_id):
        user = membership.user
        identity = f"{OVERDUE_NOTICE}:{payment.id}:{payment.due_at.isoformat()}:{user.id}"
        notify_in_app(
            organization_id=order.organization_id,
            user_id=user.id,
            kind=OVERDUE_NOTICE,
            payload=payload,
            idempotency_key=identity,
            severity="warning",
        )
        locale = staff_locale(organization_id=order.organization_id, user=user)
        queue_email(
            recipient_email=user.email,
            template_key=emails.OFFICE_BALANCE_OVERDUE,
            template_version=1,
            locale=locale,
            template_context={
                "number": order.number,
                "organization_name": order.organization.name,
                "amount": emails.money(payment.amount_minor, payment.currency, locale),
                "due_at": emails.local_time(payment.due_at, order.organization.timezone, locale),
                "panel_url": public_url(locale, f"/panel/orders/{order.id}"),
            },
            idempotency_key=identity,
            causation_id=f"commerce-order:{order.id}",
            recipient_user=user,
        )


def _payment_managers(organization_id: UUID) -> list[Membership]:
    return [
        membership
        for membership in Membership.objects.select_related("role", "user").filter(
            organization_id=organization_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
        )
        if PAYMENTS_MANAGE in (membership.role.permissions or ())
    ]
