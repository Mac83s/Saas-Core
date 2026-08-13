from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing import services
from saas_core.modules.shared.billing.models import (
    BillingCheckout,
    PlanVersion,
    StripePriceMapping,
)
from saas_core.modules.shared.billing.provider import (
    ProviderCheckout,
    ProviderCustomer,
    ProviderPortal,
    StripeBillingProvider,
)
from saas_core.modules.shared.billing.services import (
    BillingCheckoutConflict,
    BillingCustomerRequired,
    BillingPlanUnavailable,
    BillingProviderUnavailable,
    create_customer_portal,
    create_setup_checkout,
)

pytestmark = pytest.mark.django_db

DEPLOYMENT_PLAN_KEYS = ("profile", "starter", "pro")


@pytest.fixture(autouse=True)
def deployment_catalog(settings: Any) -> None:
    settings.BILLING_PLAN_KEYS = DEPLOYMENT_PLAN_KEYS


class FakeProvider:
    def __init__(self) -> None:
        self.customer_calls: list[dict[str, Any]] = []
        self.checkout_calls: list[dict[str, Any]] = []
        self.portal_calls: list[dict[str, Any]] = []

    def create_customer(self, **kwargs: Any) -> ProviderCustomer:
        self.customer_calls.append(kwargs)
        return ProviderCustomer("cus_fake")

    def create_setup_checkout(self, **kwargs: Any) -> ProviderCheckout:
        self.checkout_calls.append(kwargs)
        return ProviderCheckout(
            "cs_fake",
            "https://checkout.stripe.test/cs_fake",
            datetime(2026, 8, 12, tzinfo=UTC),
        )

    def create_portal(self, **kwargs: Any) -> ProviderPortal:
        self.portal_calls.append(kwargs)
        return ProviderPortal("bps_fake", "https://billing.stripe.test/bps_fake")


def setup_owner(*, slug: str = "checkout-owner") -> tuple[Organization, TenantContext]:
    tenant = Organization.objects.create(name=slug, slug=slug)
    profile = BillingProfile.objects.create(
        organization=tenant,
        legal_name="Checkout sp. z o.o.",
        billing_email="billing@example.com",
    )
    assert profile.external_customer_id == ""
    actor = User.objects.create_user(email=f"{slug}@example.com")
    return tenant, TenantContext(
        organization_id=tenant.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset({BILLING_MANAGE}),
    )


def mapping(*, plan_key: str = "starter") -> StripePriceMapping:
    return StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key=plan_key, version=1),
        stripe_product_id=f"prod_{plan_key}",
        stripe_price_id=f"price_{plan_key}",
        livemode=False,
    )


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_CHECKOUT_SUCCESS_URL="https://app.test/settings/billing?success=1",
    BILLING_CHECKOUT_CANCEL_URL="https://app.test/settings/billing?canceled=1",
    BILLING_PORTAL_RETURN_URL="https://app.test/settings/billing",
)
def test_checkout_creates_customer_and_persists_idempotent_setup_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, context = setup_owner()
    selected = mapping()
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        first = create_setup_checkout(plan_key="starter", idempotency_key="request-one")
        repeated = create_setup_checkout(plan_key="starter", idempotency_key="request-one")

    assert first.created is True
    assert repeated.created is False
    assert repeated.checkout.id == first.checkout.id
    assert first.checkout.price_mapping == selected
    assert first.checkout.checkout_url == "https://checkout.stripe.test/cs_fake"
    assert BillingProfile.objects.get(organization=tenant).external_customer_id == "cus_fake"
    assert len(provider.customer_calls) == 1
    assert len(provider.checkout_calls) == 1
    checkout_call = provider.checkout_calls[0]
    assert checkout_call["customer_id"] == "cus_fake"
    assert checkout_call["plan_version_id"] == str(selected.plan_version_id)
    assert checkout_call["price_mapping_id"] == str(selected.id)
    assert checkout_call["success_url"] == "https://app.test/settings/billing?success=1"
    assert checkout_call["cancel_url"] == "https://app.test/settings/billing?canceled=1"
    audit = OrganizationAuditEntry.objects.get(
        organization=tenant,
        action=OrganizationAuditAction.BILLING_CHECKOUT_CREATED,
    )
    assert audit.target_id == first.checkout.id
    assert audit.metadata["stripe_customer_created"] is True


@override_settings(STRIPE_LIVEMODE=False)
def test_checkout_idempotency_key_cannot_select_another_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context = setup_owner(slug="checkout-conflict")
    mapping(plan_key="starter")
    mapping(plan_key="pro")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        create_setup_checkout(plan_key="starter", idempotency_key="same-key")
        with pytest.raises(BillingCheckoutConflict):
            create_setup_checkout(plan_key="pro", idempotency_key="same-key")


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_PLAN_KEYS=("profile", "starter"),
)
def test_checkout_rejects_public_plan_outside_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context = setup_owner(slug="checkout-hidden-plan")
    mapping(plan_key="pro")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context), pytest.raises(BillingPlanUnavailable):
        create_setup_checkout(plan_key="pro", idempotency_key="hidden-plan")

    assert provider.customer_calls == []
    assert provider.checkout_calls == []


@override_settings(STRIPE_LIVEMODE=False)
def test_checkout_uses_only_the_current_public_plan_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context = setup_owner(slug="checkout-current-version")
    old_mapping = mapping()
    plan = old_mapping.plan_version.plan
    current = PlanVersion.objects.create(
        plan=plan,
        version=2,
        currency="PLN",
        billing_interval="month",
        unit_amount_minor=15_900,
        feature_keys=old_mapping.plan_version.feature_keys,
        quotas=old_mapping.plan_version.quotas,
        trial_days=3,
        grace_period_days=7,
    )
    plan.current_version = current
    plan.save(update_fields=["current_version", "updated_at"])
    current_mapping = StripePriceMapping.objects.create(
        plan_version=current,
        stripe_product_id="prod_starter_v2",
        stripe_price_id="price_starter_v2",
        livemode=False,
    )
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        result = create_setup_checkout(plan_key="starter", idempotency_key="current-version")

    assert result.checkout.price_mapping == current_mapping


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_PORTAL_RETURN_URL="https://app.test/settings/billing",
)
def test_portal_uses_server_return_url_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, context = setup_owner(slug="portal-owner")
    BillingProfile.objects.filter(organization=tenant).update(external_customer_id="cus_portal")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        result = create_customer_portal()

    assert result.url == "https://billing.stripe.test/bps_fake"
    assert provider.portal_calls == [
        {
            "customer_id": "cus_portal",
            "return_url": "https://app.test/settings/billing",
        }
    ]
    assert OrganizationAuditEntry.objects.filter(
        organization=tenant,
        action=OrganizationAuditAction.BILLING_PORTAL_CREATED,
    ).exists()


def test_portal_requires_customer_and_checkout_is_owner_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context = setup_owner(slug="portal-missing")
    mapping()
    monkeypatch.setattr(services, "get_billing_provider", FakeProvider)

    with activate_tenant_context(context), pytest.raises(BillingCustomerRequired):
        create_customer_portal()

    unauthorized = TenantContext(
        organization_id=context.organization_id,
        membership_id=context.membership_id,
        actor_id=context.actor_id,
        role_key="admin",
        permissions=frozenset({BILLING_MANAGE}),
    )
    with activate_tenant_context(unauthorized), pytest.raises(OrganizationPermissionDenied):
        create_setup_checkout(plan_key="starter", idempotency_key="owner-only")


@override_settings(STRIPE_LIVEMODE=False, STRIPE_SECRET_KEY="")
def test_checkout_reports_missing_provider_configuration_as_unavailable() -> None:
    _, context = setup_owner(slug="checkout-provider-missing")
    mapping()

    with activate_tenant_context(context), pytest.raises(BillingProviderUnavailable):
        create_setup_checkout(plan_key="starter", idempotency_key="provider-missing")

    assert BillingCheckout.all_objects.count() == 0


@override_settings(STRIPE_SECRET_KEY="sk_test_local", STRIPE_API_VERSION="2026-07-29.dahlia")
def test_stripe_adapter_uses_setup_mode_without_starting_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    class CheckoutSessions:
        def create(self, params, options):
            calls.append((params, options))
            return SimpleNamespace(
                id="cs_adapter",
                url="https://checkout.stripe.test/cs_adapter",
                expires_at=1_786_086_400,
            )

    fake_client = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=CheckoutSessions()))
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.provider.stripe.StripeClient",
        lambda *args, **kwargs: fake_client,
    )
    provider = StripeBillingProvider()

    provider.create_setup_checkout(
        customer_id="cus_adapter",
        organization_id="org-id",
        plan_version_id="plan-version-id",
        price_mapping_id="mapping-id",
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
        idempotency_key="adapter-key",
    )

    params, options = calls[0]
    assert params["mode"] == "setup"
    assert params["payment_method_types"] == ["card"]
    assert "subscription_data" not in params
    assert "line_items" not in params
    assert params["metadata"]["saas_core_price_mapping_id"] == "mapping-id"
    assert options == {"idempotency_key": "adapter-key"}
    assert BillingCheckout.all_objects.count() == 0
