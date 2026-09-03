"""Buying a credit pack: a one-off Checkout, credited only by the webhook.

The portal cannot sell a pack and never will (ADR-040 §4), so this is our own
Checkout session. What matters here is the boundary: the purchase is recorded
before the customer pays, the pool grows only when Stripe says the money
arrived, and a browser coming back from Stripe grants nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing import services
from saas_core.modules.shared.billing.credits import credit_summary
from saas_core.modules.shared.billing.models import (
    AccessMode,
    CreditPack,
    CreditPackPrice,
    CreditPurchase,
    CreditPurchaseStatus,
    EntitlementSnapshot,
    Plan,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)
from saas_core.modules.shared.billing.processor import (
    StripeEventProcessingError,
    process_stripe_event,
)
from saas_core.modules.shared.billing.provider import ProviderCheckout
from saas_core.modules.shared.billing.services import (
    BillingProfileIncomplete,
    CreditPackUnavailable,
    create_credit_checkout,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 20, 10, tzinfo=UTC)
CUSTOMER_ID = "cus_credits"


class FakeProvider:
    """Behaves like Stripe: the session is opened, nothing is paid yet."""

    def __init__(self) -> None:
        self.credit_calls: list[dict[str, Any]] = []

    def create_customer(self, **kwargs: Any) -> Any:
        raise AssertionError("customer powinien już istnieć")

    def create_credit_checkout(self, **kwargs: Any) -> ProviderCheckout:
        self.credit_calls.append(kwargs)
        return ProviderCheckout(
            "cs_credits",
            "https://checkout.stripe.test/cs_credits",
            NOW,
        )


def setup_buyer(
    *, slug: str = "credits-buyer", with_address: bool = True, priced: bool = True
) -> tuple[Organization, TenantContext, CreditPack]:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=organization,
        legal_name="Kredytowa sp. z o.o.",
        billing_email="billing@example.com",
        external_customer_id=CUSTOMER_ID,
        country_code="PL",
        address_line1="Testowa 1" if with_address else "",
        postal_code="00-001" if with_address else "",
        city="Warszawa" if with_address else "",
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        plan_version=Plan.objects.get(key="starter").current_version,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"sites.enabled": True},
        quotas={},
        sources={},
    )
    actor = User.objects.create_user(email=f"{slug}@example.com")
    pack = CreditPack.objects.get(key="credits-500")
    if priced:
        CreditPackPrice.objects.create(
            pack=pack,
            stripe_product_id="saas_core_credits_credits_500",
            stripe_price_id="price_credits_500",
            livemode=False,
        )
    return (
        organization,
        TenantContext(
            organization_id=organization.id,
            membership_id=uuid.uuid7(),
            actor_id=actor.id,
            role_key="owner",
            permissions=frozenset({BILLING_MANAGE}),
        ),
        pack,
    )


def paid_event(organization: Organization, purchase: CreditPurchase) -> StripeWebhookEvent:
    return StripeWebhookEvent.objects.create(
        stripe_event_id=f"evt_{purchase.id}",
        event_type="checkout.session.completed",
        livemode=False,
        provider_created_at=NOW,
        signature_verified_at=NOW,
        status=WebhookProcessingStatus.RECEIVED,
        payload={
            "data": {
                "object": {
                    "id": "cs_credits",
                    "customer": CUSTOMER_ID,
                    "payment_status": "paid",
                    "metadata": {
                        "saas_core_organization_id": str(organization.id),
                        "saas_core_credit_purchase_id": str(purchase.id),
                    },
                }
            }
        },
    )


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_checkout_records_the_purchase_and_credits_nothing_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, pack = setup_buyer()
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        purchase = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:1")
        summary = credit_summary(at=NOW)

    assert purchase.status == CreditPurchaseStatus.PENDING
    assert purchase.checkout_session_id == "cs_credits"
    assert purchase.checkout_url.startswith("https://checkout.stripe.test/")
    assert purchase.credits == pack.credits
    assert summary.purchased_remaining == 0
    call = provider.credit_calls[0]
    assert call["price_id"] == "price_credits_500"
    assert call["customer_id"] == CUSTOMER_ID
    assert call["purchase_id"] == str(purchase.id)


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_repeating_the_same_key_reuses_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _organization, context, _pack = setup_buyer(slug="credits-replay")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        first = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:same")
        second = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:same")

    assert first.id == second.id
    assert len(provider.credit_calls) == 1
    assert CreditPurchase.all_objects.count() == 1


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_a_pack_without_a_price_in_this_mode_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live deployment must not fall back to a test-mode price."""
    _organization, context, _pack = setup_buyer(slug="credits-unpriced", priced=False)
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(CreditPackUnavailable):
        create_credit_checkout(pack_key="credits-500", idempotency_key="buy:none")
    assert provider.credit_calls == []


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_an_incomplete_billing_address_stops_the_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, _pack = setup_buyer(slug="credits-noaddr", with_address=False)
    BillingProfile.objects.filter(organization=organization).update(external_customer_id="")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(BillingProfileIncomplete):
        create_credit_checkout(pack_key="credits-500", idempotency_key="buy:noaddr")


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_the_webhook_credits_the_pool_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, pack = setup_buyer(slug="credits-webhook")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)
    with activate_tenant_context(context):
        purchase = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:hook")

    event = paid_event(organization, purchase)
    process_stripe_event(event.id)
    process_stripe_event(event.id)

    purchase.refresh_from_db()
    event.refresh_from_db()
    assert purchase.status == CreditPurchaseStatus.SUCCEEDED
    assert event.status == WebhookProcessingStatus.PROCESSED
    assert event.organization_id == organization.id
    with activate_tenant_context(context):
        summary = credit_summary(at=NOW)
    assert summary.purchased_remaining == pack.credits


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_an_unpaid_session_never_credits_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The return URL is not proof; neither is a session that was only opened."""
    organization, context, _pack = setup_buyer(slug="credits-unpaid")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)
    with activate_tenant_context(context):
        purchase = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:unpaid")

    event = paid_event(organization, purchase)
    event.payload["data"]["object"]["payment_status"] = "unpaid"
    event.save(update_fields=["payload"])

    with pytest.raises(StripeEventProcessingError):
        process_stripe_event(event.id)

    purchase.refresh_from_db()
    assert purchase.status == CreditPurchaseStatus.PENDING
    with activate_tenant_context(context):
        assert credit_summary(at=NOW).purchased_remaining == 0


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_a_session_naming_another_organization_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, _pack = setup_buyer(slug="credits-mine")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)
    with activate_tenant_context(context):
        purchase = create_credit_checkout(pack_key="credits-500", idempotency_key="buy:mixed")

    event = paid_event(organization, purchase)
    event.payload["data"]["object"]["metadata"]["saas_core_organization_id"] = str(uuid.uuid7())
    event.save(update_fields=["payload"])

    with pytest.raises(StripeEventProcessingError):
        process_stripe_event(event.id)

    purchase.refresh_from_db()
    assert purchase.status == CreditPurchaseStatus.PENDING
