from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing import lifecycle
from saas_core.modules.shared.billing.lifecycle import (
    CompletedCheckoutRequired,
    TrialActivationProviderUnavailable,
    activate_trial_for_product,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingCheckout,
    BillingSubscription,
    BillingTrialActivation,
    CheckoutStatus,
    EntitlementSnapshot,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
    TrialActivationStatus,
)
from saas_core.modules.shared.billing.provider import (
    BillingProviderError,
    ProviderSubscription,
    StripeBillingProvider,
)

pytestmark = pytest.mark.django_db


class FakeProvider:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls: list[dict[str, Any]] = []

    def create_trial_subscription(self, **kwargs: Any) -> ProviderSubscription:
        self.calls.append(kwargs)
        if self.fail_once:
            self.fail_once = False
            raise BillingProviderError("temporary")
        trial_start = datetime(2026, 8, 11, 12, tzinfo=UTC)
        trial_end = trial_start + timedelta(days=3)
        return ProviderSubscription(
            id="sub_trial",
            status=StripeSubscriptionStatus.TRIALING,
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=trial_end,
        )


def trial_ready_organization(
    *, slug: str = "trial-ready"
) -> tuple[Organization, TenantContext, BillingCheckout]:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=organization,
        external_customer_id="cus_trial",
    )
    actor = User.objects.create_user(email=f"{slug}@example.com")
    context = TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="staff",
        permissions=frozenset({"site.publish"}),
    )
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id="prod_trial",
        stripe_price_id="price_trial",
        livemode=False,
    )
    checkout = BillingCheckout.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_checkout_session_id="cs_trial",
        idempotency_key="checkout-trial",
        checkout_url="https://checkout.stripe.test/cs_trial",
        status=CheckoutStatus.COMPLETE,
        setup_intent_id="seti_trial",
        completed_at=datetime(2026, 8, 11, 11, tzinfo=UTC),
    )
    return organization, context, checkout


@override_settings(STRIPE_LIVEMODE=False)
def test_first_product_activation_starts_trial_once_and_builds_local_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, checkout = trial_ready_organization()
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        first = activate_trial_for_product(source_type="site", source_id="site-one")
        repeated = activate_trial_for_product(source_type="site", source_id="site-two")

    assert first.created is True
    assert repeated.created is False
    assert repeated.activation.id == first.activation.id
    assert first.activation.checkout == checkout
    assert first.activation.source_type == "site"
    assert first.activation.source_id == "site-one"
    assert first.activation.status == TrialActivationStatus.ACTIVE
    assert len(provider.calls) == 1
    assert provider.calls[0] == {
        "customer_id": "cus_trial",
        "setup_intent_id": "seti_trial",
        "price_id": "price_trial",
        "organization_id": str(organization.id),
        "plan_version_id": str(checkout.price_mapping.plan_version_id),
        "trial_days": 3,
        "idempotency_key": f"saas-core:trial:{organization.id}",
    }
    subscription = BillingSubscription.all_objects.get(organization=organization)
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert subscription.state == SubscriptionState.TRIALING
    assert subscription.trial_end == datetime(2026, 8, 14, 12, tzinfo=UTC)
    assert snapshot.subscription_state == SubscriptionState.TRIALING
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.effective_until == subscription.trial_end
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action=OrganizationAuditAction.BILLING_TRIAL_STARTED,
    )
    assert audit.actor_user_id == context.actor_id
    assert audit.metadata["source_id"] == "site-one"


@override_settings(STRIPE_LIVEMODE=False)
def test_failed_provider_call_is_durable_and_retry_uses_same_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, _ = trial_ready_organization(slug="trial-retry")
    provider = FakeProvider(fail_once=True)
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(TrialActivationProviderUnavailable):
        activate_trial_for_product(source_type="site", source_id="site-retry")

    activation = BillingTrialActivation.all_objects.get(organization=organization)
    assert activation.status == TrialActivationStatus.FAILED
    assert activation.last_error == "temporary"
    assert activation.subscription_id is None

    with activate_tenant_context(context):
        retried = activate_trial_for_product(source_type="site", source_id="ignored-later")

    assert retried.created is True
    assert retried.activation.id == activation.id
    assert retried.activation.source_id == "site-retry"
    assert len(provider.calls) == 2


@override_settings(STRIPE_LIVEMODE=False)
def test_trial_requires_completed_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    _, context, checkout = trial_ready_organization(slug="trial-no-checkout")
    BillingCheckout.all_objects.filter(pk=checkout.pk).update(
        status=CheckoutStatus.OPEN,
        setup_intent_id="",
        completed_at=None,
    )
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(CompletedCheckoutRequired):
        activate_trial_for_product(source_type="site", source_id="site-no-checkout")

    assert provider.calls == []
    assert BillingTrialActivation.all_objects.count() == 0


@override_settings(STRIPE_SECRET_KEY="sk_test_local", STRIPE_API_VERSION="2026-07-29.dahlia")
def test_stripe_adapter_uses_setup_intent_payment_method_and_delayed_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    class SetupIntents:
        def retrieve(self, setup_intent_id: str) -> Any:
            assert setup_intent_id == "seti_adapter"
            return SimpleNamespace(
                id=setup_intent_id,
                status="succeeded",
                customer="cus_adapter",
                payment_method="pm_adapter",
            )

    class Subscriptions:
        def create(self, params: dict[str, Any], options: dict[str, Any]) -> Any:
            subscription_calls.append((params, options))
            return SimpleNamespace(
                id="sub_adapter",
                status="trialing",
                trial_start=1_786_435_200,
                trial_end=1_786_694_400,
                current_period_start=1_786_435_200,
                current_period_end=1_786_694_400,
            )

    fake_client = SimpleNamespace(
        v1=SimpleNamespace(
            setup_intents=SetupIntents(),
            subscriptions=Subscriptions(),
        )
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.provider.stripe.StripeClient",
        lambda *args, **kwargs: fake_client,
    )
    provider = StripeBillingProvider()

    result = provider.create_trial_subscription(
        customer_id="cus_adapter",
        setup_intent_id="seti_adapter",
        price_id="price_adapter",
        organization_id="org-adapter",
        plan_version_id="plan-version-adapter",
        trial_days=3,
        idempotency_key="trial-adapter",
    )

    assert result.id == "sub_adapter"
    params, options = subscription_calls[0]
    assert params["default_payment_method"] == "pm_adapter"
    assert params["items"] == [{"price": "price_adapter", "quantity": 1}]
    assert params["trial_period_days"] == 3
    assert params["trial_settings"] == {"end_behavior": {"missing_payment_method": "cancel"}}
    assert params["metadata"]["saas_core_organization_id"] == "org-adapter"
    assert options == {"idempotency_key": "trial-adapter"}
