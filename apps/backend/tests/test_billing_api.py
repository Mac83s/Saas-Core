from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing import lifecycle, services
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingCheckout,
    BillingSubscription,
    CheckoutStatus,
    EntitlementSnapshot,
    Plan,
    PlanVersion,
    StripePriceMapping,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)
from saas_core.modules.shared.billing.processor import process_stripe_event
from saas_core.modules.shared.billing.provider import (
    ProviderCheckout,
    ProviderCustomer,
    ProviderPortal,
    ProviderSubscription,
)
from saas_core.modules.shared.billing.snapshots import update_entitlement_snapshot

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"


class FakeProvider:
    def create_customer(self, **_kwargs: Any) -> ProviderCustomer:
        return ProviderCustomer("cus_api")

    def create_setup_checkout(self, **_kwargs: Any) -> ProviderCheckout:
        return ProviderCheckout(
            "cs_api",
            "https://checkout.stripe.test/cs_api",
            datetime(2026, 8, 12, tzinfo=UTC),
        )

    def create_portal(self, **_kwargs: Any) -> ProviderPortal:
        return ProviderPortal("bps_api", "https://billing.stripe.test/bps_api")

    def create_trial_subscription(self, **_kwargs: Any) -> ProviderSubscription:
        trial_start = timezone.now()
        trial_end = trial_start + timedelta(days=3)
        return ProviderSubscription(
            id="sub_api",
            status="trialing",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=trial_end,
        )


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def billing_client(*, role_key: str, slug: str) -> tuple[APIClient, Organization]:
    user = User.objects.create_user(
        email=f"{slug}@example.com",
        password=PASSWORD,
    )
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug,
        slug=slug,
        status=OrganizationStatus.ACTIVE,
    )
    BillingProfile.objects.create(
        organization=organization,
        # ADR-040: Stripe Tax needs an address, so the profile is
        # required data before the first payment.
        country_code="PL",
        address_line1="Testowa 1",
        postal_code="00-001",
        city="Warszawa",
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    response = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return client, organization


def seed_price() -> None:
    StripePriceMapping.objects.create(
        plan_version=Plan.objects.get(key="starter").current_version,
        stripe_product_id="prod_api",
        stripe_price_id="price_api",
        livemode=False,
    )


@override_settings(
    BILLING_PLAN_KEYS=("profile", "starter", "pro"),
    STRIPE_LIVEMODE=False,
)
def test_owner_checkout_requires_csrf_and_idempotency_and_is_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_price()
    client, _ = billing_client(role_key="owner", slug="billing-api-owner")
    monkeypatch.setattr(services, "get_billing_provider", FakeProvider)

    missing_csrf = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="checkout-api",
    )
    csrf = client.cookies["csrftoken"].value
    missing_idempotency = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    created = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="checkout-api",
    )
    repeated = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="checkout-api",
    )

    assert missing_csrf.status_code == 403
    assert missing_idempotency.status_code == 409
    assert missing_idempotency.data["code"] == "billing_checkout_conflict"
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.data["id"] == repeated.data["id"] == "cs_api"


@override_settings(STRIPE_LIVEMODE=False)
def test_non_owner_cannot_create_checkout_or_portal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_price()
    client, organization = billing_client(role_key="admin", slug="billing-api-admin")
    BillingProfile.objects.filter(organization=organization).update(
        external_customer_id="cus_admin"
    )
    monkeypatch.setattr(services, "get_billing_provider", FakeProvider)
    csrf = client.cookies["csrftoken"].value

    checkout = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="admin-checkout",
    )
    portal = client.post(
        "/api/v1/billing/portal/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    activation = client.post(
        "/api/v1/billing/trial-activation/",
        {"checkout_session_id": "checkout-return"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert checkout.status_code == 403
    assert portal.status_code == 403
    assert activation.status_code == 403
    assert checkout.data["code"] == "organization_permission_denied"
    assert portal.data["code"] == "organization_permission_denied"
    assert activation.data["code"] == "organization_permission_denied"


def test_owner_can_activate_trial_after_checkout_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = billing_client(role_key="owner", slug="billing-api-activation")
    activation_id = uuid.uuid7()

    def fake_activate_trial_for_product(**kwargs: str) -> SimpleNamespace:
        assert kwargs == {
            "source_type": "sites.onboarding",
            "source_id": "checkout-session",
            "checkout_session_id": "checkout-session",
        }
        return SimpleNamespace(
            activation=SimpleNamespace(id=activation_id, status="active"),
            created=True,
        )

    monkeypatch.setattr(
        lifecycle,
        "activate_trial_for_product",
        fake_activate_trial_for_product,
    )
    missing_csrf = client.post(
        "/api/v1/billing/trial-activation/",
        {"checkout_session_id": "checkout-session"},
        format="json",
    )
    csrf = client.cookies["csrftoken"].value

    response = client.post(
        "/api/v1/billing/trial-activation/",
        {"checkout_session_id": "checkout-session"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert missing_csrf.status_code == 403
    assert response.status_code == 201
    assert response.data == {
        "id": activation_id,
        "status": "active",
        "created": True,
    }


@override_settings(
    BILLING_PLAN_KEYS=("profile", "starter", "pro"),
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_SECRET="whsec_bridge_test",
    STRIPE_API_VERSION="2026-07-29.dahlia",
)
def test_checkout_webhook_trial_activation_unlocks_site_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_price()
    client, organization = billing_client(role_key="owner", slug="billing-api-bridge")
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.webhooks.stripe.Webhook.construct_event",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    csrf = client.cookies["csrftoken"].value
    site_payload = {
        "name": "Bridge Site",
        "slug": "bridge-site",
        "default_locale": "pl",
    }
    assert not EntitlementSnapshot.all_objects.filter(organization=organization).exists()
    assert not BillingSubscription.all_objects.filter(organization=organization).exists()

    blocked_site = client.post(
        "/api/v1/sites/",
        site_payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="bridge-site-before-trial",
    )
    checkout_response = client.post(
        "/api/v1/billing/checkout/",
        {"plan": "starter"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="bridge-checkout",
    )

    assert blocked_site.status_code == 403
    assert blocked_site.data["code"] == "entitlement_required"
    assert checkout_response.status_code == 201
    checkout = BillingCheckout.all_objects.select_related("price_mapping").get(
        stripe_checkout_session_id=checkout_response.data["id"]
    )
    assert checkout.status == CheckoutStatus.OPEN
    event_created = int(timezone.now().timestamp())
    event_payload = {
        "id": "evt_api_bridge_checkout",
        "object": "event",
        "api_version": "2026-07-29.dahlia",
        "created": event_created,
        "data": {
            "object": {
                "id": checkout.stripe_checkout_session_id,
                "object": "checkout.session",
                "customer": "cus_api",
                "setup_intent": "seti_api",
                "metadata": {
                    "saas_core_organization_id": str(organization.id),
                    "saas_core_plan_version_id": str(checkout.price_mapping.plan_version_id),
                    "saas_core_price_mapping_id": str(checkout.price_mapping_id),
                },
            }
        },
        "livemode": False,
        "type": "checkout.session.completed",
    }
    webhook_response = client.post(
        "/api/v1/billing/webhooks/stripe/",
        data=json.dumps(event_payload, separators=(",", ":")).encode(),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="verified-in-test",
    )

    assert webhook_response.status_code == 202
    webhook = StripeWebhookEvent.objects.get(stripe_event_id="evt_api_bridge_checkout")
    processed = process_stripe_event(webhook.id)
    checkout.refresh_from_db()
    assert processed is not None
    assert processed.status == WebhookProcessingStatus.PROCESSED
    assert checkout.status == CheckoutStatus.COMPLETE
    assert checkout.setup_intent_id == "seti_api"

    activation_response = client.post(
        "/api/v1/billing/trial-activation/",
        {"checkout_session_id": checkout.stripe_checkout_session_id},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert activation_response.status_code == 201
    assert activation_response.data["status"] == "active"
    subscription = BillingSubscription.all_objects.get(organization=organization)
    assert subscription.state == SubscriptionState.TRIALING
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert snapshot.subscription_state == SubscriptionState.TRIALING
    assert snapshot.features["sites.enabled"] is True

    created_site = client.post(
        "/api/v1/sites/",
        site_payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="bridge-site-after-trial",
    )

    assert created_site.status_code == 201


def test_owner_can_explain_entitlements_from_local_snapshot() -> None:
    client, organization = billing_client(role_key="owner", slug="billing-support-owner")
    mapping = StripePriceMapping.objects.create(
        plan_version=Plan.objects.get(key="starter").current_version,
        stripe_product_id="prod_support",
        stripe_price_id="price_support",
    )
    update_entitlement_snapshot(
        organization,
        mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=None,
    )

    response = client.get("/api/v1/billing/support/entitlements/")

    assert response.status_code == 200
    assert response.data["snapshot"]["plan_key"] == "starter"
    assert (
        response.data["snapshot"]["plan_version"]
        == Plan.objects.get(key="starter").current_version.version
    )
    items = {item["key"]: item for item in response.data["items"]}
    assert items["booking.enabled"]["available"] is True
    assert items["booking.enabled"]["reason"] == "allowed"
    assert items["booking.enabled"]["evidence"]["kind"] == "plan"
    assert items["appointments.monthly"]["value"] == 1_000
    assert items["appointments.monthly"]["used"] == 0
    assert items["appointments.monthly"]["reason"] == "quota_available"


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"))
def test_owner_sees_customer_billing_overview_and_deployment_plan_catalog() -> None:
    client, organization = billing_client(role_key="owner", slug="billing-overview-owner")
    hidden_plan = Plan.objects.create(
        key="hidden-public-plan",
        name="Ukryty plan",
        is_active=True,
        is_public=True,
    )
    hidden_version = PlanVersion.objects.create(
        plan=hidden_plan,
        version=1,
        unit_amount_minor=39_900,
        feature_keys=[],
        quotas={},
        trial_days=0,
    )
    hidden_plan.current_version = hidden_version
    hidden_plan.save(update_fields=["current_version", "updated_at"])
    mapping = StripePriceMapping.objects.create(
        plan_version=Plan.objects.get(key="starter").current_version,
        stripe_product_id="prod_overview",
        stripe_price_id="price_overview",
    )
    update_entitlement_snapshot(
        organization,
        mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=None,
    )

    response = client.get("/api/v1/billing/overview/")

    assert response.status_code == 200
    assert response.data["can_manage"] is True
    assert response.data["portal_available"] is False
    assert response.data["subscription"]["plan_key"] == "starter"
    plans = {plan["key"]: plan for plan in response.data["plans"]}
    assert set(plans) == {"profile", "starter", "pro"}
    assert plans["profile"]["trial_days"] == 14
    assert plans["starter"]["is_current"] is True
    assert plans["starter"]["checkout_available"] is True


def test_customer_billing_overview_requires_billing_permission() -> None:
    client, _ = billing_client(role_key="viewer", slug="billing-overview-viewer")

    response = client.get("/api/v1/billing/overview/")

    assert response.status_code == 403
    assert response.data["code"] == "organization_permission_denied"


def test_support_report_requires_billing_permission_even_with_active_tenant() -> None:
    client, _ = billing_client(role_key="viewer", slug="billing-support-viewer")

    response = client.get("/api/v1/billing/support/entitlements/")

    assert response.status_code == 403
    assert response.data["code"] == "organization_permission_denied"
