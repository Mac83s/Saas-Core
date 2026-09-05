"""The credits screen: who may look, and who may spend.

The domain has been complete for days and invisible: a ledger, two buckets, a
checkout, and no way for a customer to learn how many credits they have. This
covers the panel's side of it, and the split the owner asked for — anybody who
does the work can see the balance, only the owner can buy.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    CreditPack,
    CreditPackPrice,
    CreditPurchase,
    CreditPurchaseStatus,
    EntitlementSnapshot,
    Plan,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def with_a_live_plan(organization: Organization) -> None:
    """Credits are an add-on to a subscription, so the tenant needs one."""
    with transaction.atomic():
        set_local_organization_id(organization.id)
        EntitlementSnapshot.all_objects.create(
            organization=organization,
            plan_version=Plan.objects.get(key="starter").current_version,
            subscription_state=SubscriptionState.ACTIVE,
            access_mode=AccessMode.FULL,
            features={},
            quotas={},
            sources={},
        )


def client_for(*, role_key: str, slug: str) -> tuple[APIClient, Organization, User]:
    user = User.objects.create_user(email=f"{slug}@example.com", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE
    )
    BillingProfile.objects.create(
        organization=organization,
        legal_name="Firma kredytowa",
        billing_email="faktury@example.com",
        country_code="PL",
        address_line1="Testowa 1",
        postal_code="00-001",
        city="Warszawa",
        external_customer_id=f"cus_{slug}",
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        ).status_code
        == 200
    )
    return client, organization, user


def price_the_packs() -> None:
    for pack in CreditPack.objects.all():
        CreditPackPrice.objects.create(
            pack=pack,
            stripe_product_id=f"prod_{pack.key}",
            stripe_price_id=f"price_{pack.key}",
            livemode=False,
        )


@override_settings(STRIPE_LIVEMODE=False)
def test_a_member_sees_the_balance_and_the_catalog() -> None:
    price_the_packs()
    client, _organization, _user = client_for(role_key="staff", slug="credits-member")

    response = client.get("/api/v1/billing/credits/")

    assert response.status_code == 200
    body = response.data
    # A staff member does the work that spends credits, so they see the number.
    assert body["can_buy"] is False
    assert body["balance"]["available"] == 0
    assert [pack["key"] for pack in body["packs"]] == [
        "credits-100",
        "credits-500",
        "credits-2000",
    ]
    assert all(pack["purchasable"] for pack in body["packs"])
    assert body["purchases"] == []


@override_settings(STRIPE_LIVEMODE=False)
def test_a_pack_without_a_price_in_this_mode_is_shown_but_not_offered() -> None:
    """A live deployment must not advertise a button that answers 404."""
    client, _organization, _user = client_for(role_key="owner", slug="credits-unpriced")

    body = client.get("/api/v1/billing/credits/").data

    # No plan, so no buying either — and the panel is told which of the two
    # reasons applies.
    assert body["can_buy"] is False
    assert body["plan_required"] is True
    assert not any(pack["purchasable"] for pack in body["packs"])


@override_settings(BILLING_PROVIDER="simulated", STRIPE_LIVEMODE=False)
def test_the_owner_buys_and_the_purchase_shows_up_in_the_history() -> None:
    price_the_packs()
    client, organization, _user = client_for(role_key="owner", slug="credits-buyer")
    with_a_live_plan(organization)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]

    response = client.post(
        "/api/v1/billing/credits/checkout/",
        {"pack": "credits-500"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="credits-buy-one",
    )

    assert response.status_code in {200, 201}, response.data
    purchase = CreditPurchase.all_objects.get(organization=organization)
    assert purchase.credits == 500
    history = client.get("/api/v1/billing/credits/").data["purchases"]
    assert len(history) == 1
    assert history[0]["pack_key"] == "credits-500"
    # The simulator settles at once, so the pool grows immediately here.
    assert history[0]["status"] == CreditPurchaseStatus.SUCCEEDED


@override_settings(BILLING_PROVIDER="simulated", STRIPE_LIVEMODE=False)
def test_a_member_who_is_not_the_owner_cannot_buy() -> None:
    price_the_packs()
    client, _organization, _user = client_for(role_key="admin", slug="credits-admin")
    with_a_live_plan(_organization)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]

    response = client.post(
        "/api/v1/billing/credits/checkout/",
        {"pack": "credits-500"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="credits-buy-admin",
    )

    assert response.status_code == 403
    assert not CreditPurchase.all_objects.exists()


@override_settings(BILLING_PROVIDER="simulated", STRIPE_LIVEMODE=False)
def test_buying_without_csrf_is_refused() -> None:
    price_the_packs()
    client, _organization, _user = client_for(role_key="owner", slug="credits-csrf")
    with_a_live_plan(_organization)

    response = client.post(
        "/api/v1/billing/credits/checkout/",
        {"pack": "credits-500"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="credits-buy-csrf",
    )

    assert response.status_code == 403
