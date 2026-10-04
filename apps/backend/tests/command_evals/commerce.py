"""Evals of the assistant's commands for orders and payments
(`shared/commerce/command_declarations.py`, ADR-073 §11)."""

from __future__ import annotations

from typing import Any
from uuid import uuid7

from django.db.models import F
from django.utils import timezone

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    Feature,
    SubscriptionState,
)
from saas_core.modules.shared.commerce.models import (
    LedgerEntry,
    Order,
    OrderLine,
    Payment,
)
from saas_core.modules.shared.commerce.names import COMMERCE_ENABLED
from saas_core.modules.shared.customers.models import Customer

from . import CommandEval

NOT_A_VERSION = "nie dotyczy: odczyt nie sprawdza wersji"


def _company(context: TenantContext) -> None:
    """Orders in the plan, and one order at 150 with 50 of it marked by hand."""
    organization_id = context.organization_id
    Feature.objects.get_or_create(
        key=COMMERCE_ENABLED, defaults={"name": "Zamówienia", "module": "shared.commerce"}
    )
    EntitlementSnapshot.all_objects.create(
        organization_id=organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={COMMERCE_ENABLED: True},
        quotas={},
        sources={COMMERCE_ENABLED: {"kind": "plan"}},
    )
    now = timezone.now()
    customer = Customer.all_objects.create(
        organization_id=organization_id, display_name="Anna Kowalska", contact_hash=uuid7().hex
    )
    order = Order.all_objects.create(
        organization_id=organization_id,
        number="R/2026/0001",
        source="booking",
        customer=customer,
        buyer_name="Anna Kowalska",
        currency="PLN",
        amounts="gross",
        net_minor=15000,
        gross_minor=15000,
        status="partially_paid",
        channel="office",
        version=3,
        placed_at=now,
    )
    OrderLine.all_objects.create(
        organization_id=organization_id,
        order=order,
        revision=1,
        position=1,
        kind="booking",
        name="Konsultacja",
        customer_name="Konsultacja",
        quantity=1,
        unit_amount_minor=15000,
        net_minor=15000,
        vat_minor=0,
        gross_minor=15000,
        tax_rate="zw",
        source="booking.appointment",
        source_reference=str(uuid7()),
    )
    payment = Payment.all_objects.create(
        organization_id=organization_id,
        order=order,
        kind="deposit",
        method="cash",
        status="succeeded",
        amount_minor=5000,
        currency="PLN",
        paid_at=now,
        recorded_by=context.actor_id,
    )
    LedgerEntry.all_objects.create(
        organization_id=organization_id,
        order=order,
        payment=payment,
        kind="charge",
        amount_minor=5000,
        currency="PLN",
        occurred_at=now,
    )


def _order(context: TenantContext) -> Order:
    return Order.all_objects.get(organization_id=context.organization_id)


def _payment(context: TenantContext) -> Payment:
    return Payment.all_objects.get(organization_id=context.organization_id)


def _state(context: TenantContext) -> dict[str, Any]:
    organization_id = context.organization_id
    return {
        "orders": sorted(
            Order.all_objects.filter(organization_id=organization_id).values_list(
                "number", "status", "version"
            )
        ),
        "payments": sorted(
            Payment.all_objects.filter(organization_id=organization_id).values_list(
                "status", "method", "amount_minor"
            )
        ),
        "ledger": sorted(
            LedgerEntry.all_objects.filter(organization_id=organization_id).values_list(
                "kind", "amount_minor"
            )
        ),
    }


def _bump(context: TenantContext) -> None:
    Order.all_objects.filter(organization_id=context.organization_id).update(
        version=F("version") + 1
    )


EVALS = {
    "commerce.orders.read@1": CommandEval(
        arguments=lambda _context: {"status": None, "q": None, "page": None},
        wrong_arguments={"status": "lost", "q": None, "page": None},
        wrong_field="status",
        stale=NOT_A_VERSION,
        state=_state,
        prepare=_company,
    ),
    "commerce.order.read@1": CommandEval(
        arguments=lambda context: {"order_id": str(_order(context).id), "number": None},
        wrong_arguments={"order_id": 7, "number": None},
        wrong_field="order_id",
        stale=NOT_A_VERSION,
        state=_state,
        prepare=_company,
    ),
    "commerce.payment.record@1": CommandEval(
        arguments=lambda context: {
            "order_id": str(_order(context).id),
            "amount_minor": 4000,
            "method": "transfer",
        },
        # Refused by the service: more than what is left to pay.
        wrong_arguments=lambda context: {
            "order_id": str(_order(context).id),
            "amount_minor": 10001,
            "method": "cash",
        },
        wrong_field="amount_minor",
        stale=_bump,
        state=_state,
        prepare=_company,
    ),
    "commerce.payment.void@1": CommandEval(
        arguments=lambda context: {
            "order_id": str(_order(context).id),
            "payment_id": str(_payment(context).id),
        },
        wrong_arguments=lambda context: {
            "order_id": str(_order(context).id),
            "payment_id": "wpłata z wczoraj",
        },
        wrong_field="payment_id",
        stale=_bump,
        state=_state,
        prepare=_company,
    ),
}
