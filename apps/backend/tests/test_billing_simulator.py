from __future__ import annotations

import uuid
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing.models import (
    BillingCheckout,
    BillingReconciliation,
    BillingSubscription,
    CheckoutStatus,
    EntitlementSnapshot,
    PlanVersion,
    StripePriceMapping,
    StripeWebhookEvent,
    SubscriptionState,
)
from saas_core.modules.shared.billing.overview import customer_billing_overview
from saas_core.modules.shared.billing.provider import get_billing_provider
from saas_core.modules.shared.billing.reconciliation import run_reconciliation_batch
from saas_core.modules.shared.billing.services import (
    BillingPortalUnavailable,
    activate_customer_trial,
    create_customer_portal,
    create_setup_checkout,
)
from saas_core.modules.shared.billing.simulated_provider import SimulatedBillingProvider

pytestmark = pytest.mark.django_db

DEPLOYMENT_PLAN_KEYS = ("profile", "starter", "pro")


@pytest.fixture(autouse=True)
def deployment_catalog(settings: Any) -> None:
    settings.BILLING_PLAN_KEYS = DEPLOYMENT_PLAN_KEYS


def owner_context(*, slug: str) -> tuple[Organization, TenantContext]:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=organization,
        legal_name="Symulowana firma",
        billing_email="billing@example.com",
    )
    actor = User.objects.create_user(email=f"{slug}@example.com")
    return organization, TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset({BILLING_MANAGE}),
    )


@override_settings(BILLING_PROVIDER="simulated", STRIPE_LIVEMODE=False)
def test_simulated_price_configuration_is_deterministic_and_idempotent() -> None:
    old_mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="profile", version=1),
        stripe_product_id="prod_old_test",
        stripe_price_id="price_old_test",
        livemode=False,
    )
    first_output = StringIO()
    second_output = StringIO()

    call_command("configure_simulated_prices", stdout=first_output)
    call_command("configure_simulated_prices", stdout=second_output)

    old_mapping.refresh_from_db()
    assert old_mapping.is_active is False
    active = StripePriceMapping.objects.filter(livemode=False, is_active=True)
    assert set(active.values_list("stripe_price_id", flat=True)) == {
        "sim_price_profile_v1",
        "sim_price_starter_v1",
        "sim_price_pro_v1",
    }
    assert "configured=3, unchanged=0" in first_output.getvalue()
    assert "configured=0, unchanged=3" in second_output.getvalue()


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_simulated_price_configuration_refuses_stripe_mode() -> None:
    with pytest.raises(CommandError, match="BILLING_PROVIDER=simulated"):
        call_command("configure_simulated_prices")


@override_settings(
    BILLING_PROVIDER="simulated",
    STRIPE_LIVEMODE=False,
    BILLING_CHECKOUT_SUCCESS_URL=(
        "https://app.test/settings/billing?checkout=success&session_id={CHECKOUT_SESSION_ID}"
    ),
)
def test_simulated_checkout_and_exact_activation_create_trial_without_webhook() -> None:
    call_command("configure_simulated_prices")
    organization, context = owner_context(slug="simulator-flow")

    with activate_tenant_context(context):
        checkout_result = create_setup_checkout(
            plan_key="profile",
            idempotency_key="simulated-payment-one",
        )
        repeated = create_setup_checkout(
            plan_key="profile",
            idempotency_key="simulated-payment-one",
        )
        before_activation = customer_billing_overview()
        activation = activate_customer_trial(
            checkout_session_id=checkout_result.checkout.stripe_checkout_session_id
        )
        overview = customer_billing_overview()
        with pytest.raises(BillingPortalUnavailable):
            create_customer_portal()

    checkout = BillingCheckout.all_objects.get(pk=checkout_result.checkout.id)
    profile = BillingProfile.objects.get(organization=organization)
    subscription = BillingSubscription.all_objects.get(organization=organization)
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert checkout_result.created is True
    assert repeated.created is False
    assert repeated.checkout.id == checkout.id
    assert checkout.status == CheckoutStatus.COMPLETE
    assert checkout.completed_at is not None
    assert checkout.setup_intent_id.startswith("sim_setup_")
    assert checkout.checkout_url.endswith(checkout.stripe_checkout_session_id)
    assert profile.external_customer_id.startswith("sim_customer_")
    assert activation.created is True
    assert subscription.state == SubscriptionState.TRIALING
    assert subscription.stripe_subscription_id.startswith("sim_subscription_")
    assert snapshot.plan_version_id == checkout.price_mapping.plan_version_id
    assert before_activation["payment_mode"] == "simulated"
    assert before_activation["portal_available"] is False
    assert overview["payment_mode"] == "simulated"
    assert overview["portal_available"] is False
    assert overview["subscription"]["plan_key"] == "profile"
    assert run_reconciliation_batch() == 0
    assert not BillingReconciliation.all_objects.exists()
    assert not StripeWebhookEvent.objects.exists()


@override_settings(
    BILLING_PROVIDER="simulated",
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_SECRET="whsec_must_not_be_used",
)
def test_simulator_hard_disables_public_stripe_webhook_without_persistence() -> None:
    response = Client().post(
        "/api/v1/billing/webhooks/stripe/",
        data=b'{}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="ignored",
    )

    assert response.status_code == 503
    assert response.json() == {"received": False}
    assert not StripeWebhookEvent.objects.exists()


@override_settings(BILLING_PROVIDER="simulated", STRIPE_LIVEMODE=False)
def test_provider_factory_selects_explicit_simulator() -> None:
    assert isinstance(get_billing_provider(), SimulatedBillingProvider)
