"""Commerce's part of the demo (core/organizations/demo.py): the account a
company's customers pay to, and what happens to an order's money in a story.

The account comes first (the part runs before the calendar): an offer may ask
for a transfer only once the company has one. It is set the way a person sets
it — the settings group `commerce.transfer`, after the second factor — and
only where the company has none. The number is made up: an IBAN whose check
digits are right, so no validation fails, and whose bank code is all zeros, so
no bank has it; the holder's name says it is a test account.

A story's money steps are the company's own acts, each at its moment
(`DemoRun.play`): `commerce.pay` marks what was received (`method`: `cash` or
`transfer`; `amount`: `awaited` — the prepayment or balance the order waits
for — or everything still due), `commerce.refund` marks what was given back
(what the order's terms owe, unless `amount` says otherwise) and
`commerce.lapse` is the date of a prepayment passing unpaid, as the deadlines'
task meets it. The order is found by what the source's step left in the
story's memo (`order`: the source and the reference of a line). A step counts
what the order already has, so a second run marks nothing twice.

Scenario data, under `commerce`: `{"transfer": {"holder", "bank"}}`.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.demo import DemoStep, DemoStory, register_demo_step
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.core.organizations.tasks import tenant_task_context
from saas_core.modules.shared.notifications.security import decrypt_secret

from .ledger import (
    CLOSED_STATUSES,
    awaited_balance,
    awaited_prepayment,
    paid_minor,
    refund_owed,
)
from .models import (
    Order,
    OrderStatus,
    Payment,
    PaymentRoute,
    PaymentStatus,
    Refund,
    RefundStatus,
)
from .orders import order_for
from .payments import payment_due, record_payment
from .refunds import record_refund
from .transfer_account import TRANSFER, transfer_account, valid

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import (
        DemoOrganization,
        DemoRun,
        DemoScenario,
    )

#: The core scenario's own companies (the default scenario leaves it to us).
DEFAULTS: dict[str, dict[str, Any]] = {
    "studio": {"transfer": {"holder": "Studio Testowe — konto testowe", "bank": "Bank Testowy"}},
    "domki": {"transfer": {"holder": "Domki nad Jeziorem — konto testowe", "bank": "Bank Testowy"}},
    "kajaki": {"transfer": {"holder": "Kajaki Krutynia — konto testowe", "bank": "Bank Testowy"}},
}


def demo_iban(seed: str) -> str:
    """A Polish account number nobody has: the bank's code is all zeros, the
    rest comes from `seed`, and the check digits are right (ISO 13616)."""
    tail = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 10**8
    bban = f"{0:016d}{tail:08d}"
    # „PL00” moved to the end, letters as numbers: P = 25, L = 21.
    check = 98 - int(f"{bban}252100") % 97
    number = f"PL{check:02d}{bban}"
    assert valid(number)
    return number


def _data(scenario: DemoScenario, spec: DemoOrganization) -> dict[str, Any] | None:
    data = spec.data.get("commerce")
    if data is None and scenario.default:
        data = DEFAULTS.get(spec.key)
    return data


def describe(scenario: DemoScenario, spec: DemoOrganization) -> list[str]:
    data = _data(scenario, spec)
    if not data or "transfer" not in data:
        return []
    return [f"rachunek do przelewów (zmyślony, {data['transfer']['holder']})"]


def seed_transfer_accounts(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = _data(run.scenario, spec)
        if not data or "transfer" not in data:
            continue
        try:
            with run.setting_up(spec.key), run.acting(spec.key, step_up=True):
                if transfer_account() is not None:
                    run.log(f"= rachunek do przelewów ({spec.name})")
                    continue
                change_settings(
                    TRANSFER.key,
                    changes={
                        "account_holder": data["transfer"]["holder"],
                        "account_number": demo_iban(spec.slug),
                        "bank_name": data["transfer"]["bank"],
                    },
                    expected_version=read_group(TRANSFER.key).version,
                    idempotency_key=str(run.stable_id("transfer-account", spec.slug)),
                )
        except (APIException, DjangoValidationError) as error:
            # A plan without orders: the company takes no transfers.
            run.log(f"! rachunek do przelewów {spec.name}: {getattr(error, 'detail', error)}")
            continue
        run.log(f"+ rachunek do przelewów {spec.name} (zmyślony numer, konto testowe)")


# --- a story's money ---------------------------------------------------------------


def _order(story: DemoStory) -> Order | None:
    """The story's order, locked — or None: the source's record has none (no
    price, a plan without orders) or the story never got that far."""
    reference = story.memo.get("order")
    return order_for(*reference) if reference else None


def _turn(story: DemoStory, step: DemoStep) -> int:
    """Which of the story's steps of this kind this one is, from 1."""
    index = next(n for n, item in enumerate(story.steps) if item is step)
    return sum(1 for item in story.steps[: index + 1] if item.do == step.do)


def _pay(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    with run.acting(key, step.data.get("by")):
        order = _order(story)
        if order is None or order.status in (*CLOSED_STATUSES, OrderStatus.DRAFT.value):
            return
        marked = Payment.all_objects.filter(
            organization_id=order.organization_id, order=order, status=PaymentStatus.SUCCEEDED
        ).count()
        if marked >= _turn(story, step):
            return
        amount = order.gross_minor - paid_minor(order)
        if step.data.get("amount") == "awaited":
            awaited = awaited_prepayment(order) or awaited_balance(order)
            if awaited is None:
                return
            amount = awaited.amount_minor
        if amount <= 0:
            return
        record_payment(
            order.id,
            amount_minor=amount,
            method=step.data.get("method", "cash"),
            expected_version=order.version,
        )


def _refund(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    with run.acting(key, step.data.get("by")):
        order = _order(story)
        if order is None:
            return
        marked = Refund.all_objects.filter(
            organization_id=order.organization_id, order=order, status=RefundStatus.SUCCEEDED
        ).count()
        if marked >= _turn(story, step):
            return
        amount = step.data.get("amount") or refund_owed(order)
        if amount <= 0:
            return
        record_refund(
            order.id,
            amount_minor=amount,
            method=step.data.get("method", "transfer"),
            expected_version=order.version,
            reason=step.data.get("reason", ""),
        )


def _lapse(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    """The prepayment's date passes unpaid: what the deadlines' task does when
    it comes to the payment, for this one payment and under its own contract."""
    with run.acting(key):
        order = _order(story)
        payment = awaited_prepayment(order) if order is not None else None
        if payment is None or payment.due_at is None or payment.due_at > timezone.now():
            return
        route = PaymentRoute.objects.filter(
            payment_id=payment.id, dispatched_at__isnull=True
        ).first()
    if route is None:
        return
    with tenant_task_context(
        decrypt_secret(route.signed_tenant_context),
        expected_causation_id=f"commerce-payment:{payment.id}",
        expires=False,
    ):
        payment_due(payment.id)
    PaymentRoute.objects.filter(pk=route.pk, dispatched_at__isnull=True).update(
        dispatched_at=timezone.now()
    )


def register_steps() -> None:
    """From `CommerceConfig.ready`."""
    register_demo_step("commerce.pay", _pay)
    register_demo_step("commerce.refund", _refund)
    register_demo_step("commerce.lapse", _lapse)
