from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing import services
from saas_core.modules.shared.billing.models import (
    AccessMode,
    PlanVersion,
    StripePriceMapping,
    SubscriptionState,
)
from saas_core.modules.shared.billing.provider import (
    ProviderCheckout,
    ProviderCustomer,
    ProviderPortal,
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
    BillingProfile.objects.create(organization=organization)
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
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id="prod_api",
        stripe_price_id="price_api",
        livemode=False,
    )


@override_settings(STRIPE_LIVEMODE=False)
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

    assert checkout.status_code == 403
    assert portal.status_code == 403
    assert checkout.data["code"] == "organization_permission_denied"
    assert portal.data["code"] == "organization_permission_denied"


def test_owner_can_explain_entitlements_from_local_snapshot() -> None:
    client, organization = billing_client(role_key="owner", slug="billing-support-owner")
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
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
    assert response.data["snapshot"]["plan_version"] == 1
    items = {item["key"]: item for item in response.data["items"]}
    assert items["booking.enabled"]["available"] is True
    assert items["booking.enabled"]["reason"] == "allowed"
    assert items["booking.enabled"]["evidence"]["kind"] == "plan"
    assert items["appointments.monthly"]["value"] == 1_000
    assert items["appointments.monthly"]["used"] == 0
    assert items["appointments.monthly"]["reason"] == "quota_available"


def test_support_report_requires_billing_permission_even_with_active_tenant() -> None:
    client, _ = billing_client(role_key="viewer", slug="billing-support-viewer")

    response = client.get("/api/v1/billing/support/entitlements/")

    assert response.status_code == 403
    assert response.data["code"] == "organization_permission_denied"
