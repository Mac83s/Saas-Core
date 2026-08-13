from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import close_old_connections, connections
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
    TrialActivationConflict,
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
    StripeWebhookEvent,
    SubscriptionState,
    TrialActivationStatus,
)
from saas_core.modules.shared.billing.processor import process_stripe_event
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
    *, slug: str = "trial-ready", plan_key: str = "starter"
) -> tuple[Organization, TenantContext, BillingCheckout]:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=organization,
        external_customer_id=("cus_trial" if slug == "trial-ready" else f"cus_{slug}"),
    )
    actor = User.objects.create_user(email=f"{slug}@example.com")
    context = TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="staff",
        permissions=frozenset({"site.publish"}),
    )
    plan_version = PlanVersion.objects.get(plan__key=plan_key, version=1)
    mapping = StripePriceMapping.objects.filter(
        plan_version=plan_version,
        livemode=False,
        is_active=True,
    ).first() or StripePriceMapping.objects.create(
        plan_version=plan_version,
        stripe_product_id=f"prod_trial_{plan_key}",
        stripe_price_id=("price_trial" if plan_key == "starter" else f"price_trial_{plan_key}"),
        livemode=False,
    )
    checkout_suffix = "" if slug == "trial-ready" else f"_{slug}"
    stripe_checkout_session_id = f"cs_trial{checkout_suffix}"
    checkout = BillingCheckout.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_checkout_session_id=stripe_checkout_session_id,
        idempotency_key=f"checkout-trial{checkout_suffix}",
        checkout_url=f"https://checkout.stripe.test/{stripe_checkout_session_id}",
        status=CheckoutStatus.COMPLETE,
        setup_intent_id=f"seti_trial{checkout_suffix}",
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
def test_profile_plan_uses_its_fourteen_day_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context, _ = trial_ready_organization(slug="trial-profile", plan_key="profile")
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        activate_trial_for_product(source_type="site", source_id="profile-site")

    assert provider.calls[0]["trial_days"] == 14


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


@override_settings(STRIPE_LIVEMODE=False)
def test_checkout_return_activates_only_the_exact_tenant_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, expected_checkout = trial_ready_organization(slug="trial-exact-checkout")
    other_mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="pro", version=1),
        stripe_product_id="prod_other_checkout",
        stripe_price_id="price_other_checkout",
        livemode=False,
    )
    BillingCheckout.all_objects.create(
        organization=organization,
        price_mapping=other_mapping,
        stripe_checkout_session_id="cs_newer_but_not_selected",
        idempotency_key="checkout-newer",
        checkout_url="https://checkout.stripe.test/cs_newer_but_not_selected",
        status=CheckoutStatus.COMPLETE,
        setup_intent_id="seti_newer",
        completed_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
    )
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        result = activate_trial_for_product(
            source_type="sites.onboarding",
            source_id=expected_checkout.stripe_checkout_session_id,
            checkout_session_id=expected_checkout.stripe_checkout_session_id,
        )

    assert result.activation.checkout_id == expected_checkout.id
    assert provider.calls[0]["price_id"] == expected_checkout.price_mapping.stripe_price_id


@override_settings(STRIPE_LIVEMODE=False)
def test_checkout_return_cannot_activate_another_tenant_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context, _ = trial_ready_organization(slug="trial-current-tenant")
    _, _, foreign_checkout = trial_ready_organization(slug="trial-foreign-tenant")
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(CompletedCheckoutRequired):
        activate_trial_for_product(
            source_type="sites.onboarding",
            source_id=foreign_checkout.stripe_checkout_session_id,
            checkout_session_id=foreign_checkout.stripe_checkout_session_id,
        )

    assert provider.calls == []


def _assert_concurrent_checkout_returns_cannot_switch_the_selected_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, first_checkout = trial_ready_organization(slug="trial-concurrent")
    second_mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="pro", version=1),
        stripe_product_id="prod_trial_concurrent_pro",
        stripe_price_id="price_trial_concurrent_pro",
        livemode=False,
    )
    second_checkout = BillingCheckout.all_objects.create(
        organization=organization,
        price_mapping=second_mapping,
        stripe_checkout_session_id="cs_trial_concurrent_pro",
        idempotency_key="checkout-trial-concurrent-pro",
        checkout_url="https://checkout.stripe.test/cs_trial_concurrent_pro",
        status=CheckoutStatus.COMPLETE,
        setup_intent_id="seti_trial_concurrent_pro",
        completed_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
    )
    provider = FakeProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    def attempt(checkout: BillingCheckout) -> str:
        close_old_connections()
        try:
            with activate_tenant_context(context):
                activate_trial_for_product(
                    source_type="sites.onboarding",
                    source_id=checkout.stripe_checkout_session_id,
                    checkout_session_id=checkout.stripe_checkout_session_id,
                )
            return "activated"
        except TrialActivationConflict:
            return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, (first_checkout, second_checkout)))

    assert sorted(outcomes) == ["activated", "conflict"]
    activation = BillingTrialActivation.all_objects.get(organization=organization)
    assert activation.checkout_id in {first_checkout.id, second_checkout.id}
    assert len(provider.calls) == 1


def _assert_subscription_webhook_can_win_race_with_trial_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, context, checkout = trial_ready_organization(slug="trial-webhook-race")
    provider_started = Event()
    allow_provider_return = Event()

    class CoordinatedProvider(FakeProvider):
        def create_trial_subscription(self, **kwargs: Any) -> ProviderSubscription:
            self.calls.append(kwargs)
            provider_started.set()
            assert allow_provider_return.wait(timeout=10)
            trial_start = datetime(2026, 8, 11, 12, tzinfo=UTC)
            trial_end = trial_start + timedelta(days=3)
            return ProviderSubscription(
                id="sub_trial_webhook_race",
                status=StripeSubscriptionStatus.TRIALING,
                trial_start=trial_start,
                trial_end=trial_end,
                current_period_start=trial_start,
                current_period_end=trial_end,
            )

    provider = CoordinatedProvider()
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)
    event_created = 1_786_435_200
    event = StripeWebhookEvent.objects.create(
        stripe_event_id="evt_trial_webhook_race",
        event_type="customer.subscription.created",
        api_version="2026-07-29.dahlia",
        livemode=False,
        provider_created_at=datetime.fromtimestamp(event_created, tz=UTC),
        payload={
            "id": "evt_trial_webhook_race",
            "object": "event",
            "api_version": "2026-07-29.dahlia",
            "created": event_created,
            "data": {
                "object": {
                    "id": "sub_trial_webhook_race",
                    "object": "subscription",
                    "customer": "cus_trial-webhook-race",
                    "status": StripeSubscriptionStatus.TRIALING,
                    "items": {
                        "data": [
                            {
                                "id": "si_trial_webhook_race",
                                "price": {
                                    "id": checkout.price_mapping.stripe_price_id,
                                    "object": "price",
                                },
                                "current_period_start": event_created,
                                "current_period_end": event_created + 3 * 86_400,
                            }
                        ]
                    },
                    "trial_start": event_created,
                    "trial_end": event_created + 3 * 86_400,
                    "cancel_at_period_end": False,
                    "canceled_at": None,
                    "ended_at": None,
                }
            },
            "livemode": False,
            "type": "customer.subscription.created",
        },
        signature_verified_at=datetime.fromtimestamp(event_created, tz=UTC),
    )

    def activate() -> bool:
        close_old_connections()
        try:
            with activate_tenant_context(context):
                return activate_trial_for_product(
                    source_type="sites.onboarding",
                    source_id=checkout.stripe_checkout_session_id,
                    checkout_session_id=checkout.stripe_checkout_session_id,
                ).created
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        activation_future = executor.submit(activate)
        assert provider_started.wait(timeout=10)
        processed = process_stripe_event(event.id)
        allow_provider_return.set()
        assert activation_future.result(timeout=10) is True

    assert processed is not None
    assert BillingSubscription.all_objects.filter(organization=organization).count() == 1
    activation = BillingTrialActivation.all_objects.get(organization=organization)
    assert activation.subscription.stripe_subscription_id == "sub_trial_webhook_race"


@override_settings(STRIPE_LIVEMODE=False, STRIPE_SECRET_KEY="")
def test_missing_provider_configuration_marks_activation_failed() -> None:
    organization, context, _ = trial_ready_organization(slug="trial-provider-missing")

    with activate_tenant_context(context), pytest.raises(TrialActivationProviderUnavailable):
        activate_trial_for_product(source_type="site", source_id="site-provider-missing")

    activation = BillingTrialActivation.all_objects.get(organization=organization)
    assert activation.status == TrialActivationStatus.FAILED
    assert "STRIPE_SECRET_KEY" in activation.last_error


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


@pytest.mark.django_db(transaction=True)
@override_settings(STRIPE_LIVEMODE=False)
def test_concurrent_trial_paths_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep both real-transaction scenarios in the final test in this module.
    # Django's flush does not re-run catalog data migrations between
    # TransactionTestCase-style tests.
    _assert_concurrent_checkout_returns_cannot_switch_the_selected_plan(monkeypatch)
    _assert_subscription_webhook_can_win_race_with_trial_response(monkeypatch)
