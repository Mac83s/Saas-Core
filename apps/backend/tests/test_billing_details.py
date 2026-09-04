"""The invoice details, without which nobody can buy anything.

Stripe Tax refuses to price a plan without an address (ADR-040), so the panel
has to ask for one. Until this endpoint existed the profile was whatever the
onboarding service happened to write, the address was never collectable, and
every checkout in Stripe mode ended on `billing_profile_incomplete`.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    # Each test logs in, and the throttle counts attempts across the suite.
    cache.clear()


COMPLETE = {
    "customer_kind": "company",
    "legal_name": "Condictor sp. z o.o.",
    "tax_id": "PL1234567890",
    "country_code": "pl",
    "address_line1": "Kościuszki 3/4",
    "postal_code": "38-300",
    "city": "Gorlice",
    "billing_email": "faktury@example.com",
}


def client_for(*, role_key: str, slug: str) -> tuple[APIClient, Organization]:
    """An organization with no billing profile at all — the honest starting point."""
    user = User.objects.create_user(email=f"{slug}@example.com", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE
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
    return client, organization


def csrf_of(client: APIClient) -> str:
    return str(client.get("/api/v1/auth/csrf/").data["csrf_token"])


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"), STRIPE_LIVEMODE=False)
def test_the_overview_says_which_details_are_missing() -> None:
    client, _organization = client_for(role_key="owner", slug="details-empty")

    overview = client.get("/api/v1/billing/overview/").data

    assert overview["billing_details"]["missing"] == [
        "address_line1",
        "postal_code",
        "city",
    ]
    assert overview["billing_details"]["country_code"] == "PL"


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"), STRIPE_LIVEMODE=False)
def test_saving_the_details_unblocks_the_purchase_and_is_audited() -> None:
    client, organization = client_for(role_key="owner", slug="details-save")

    response = client.put(
        "/api/v1/billing/details/",
        COMPLETE,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_of(client),
    )

    assert response.status_code == 200
    assert response.data["missing"] == []
    # A two-letter country is stored the way the provider expects it.
    assert response.data["country_code"] == "PL"
    assert client.get("/api/v1/billing/overview/").data["billing_details"]["city"] == (
        "Gorlice"
    )
    entry = OrganizationAuditEntry.objects.filter(
        organization=organization,
        action=OrganizationAuditAction.BILLING_PROFILE_UPDATED,
    ).get()
    assert entry.metadata["fields"] == sorted(COMPLETE)


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"), STRIPE_LIVEMODE=False)
def test_an_administrator_may_not_change_the_invoice_details() -> None:
    client, _organization = client_for(role_key="admin", slug="details-admin")

    response = client.put(
        "/api/v1/billing/details/",
        COMPLETE,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_of(client),
    )

    assert response.status_code == 403


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"), STRIPE_LIVEMODE=False)
def test_the_form_is_refused_without_csrf() -> None:
    client, _organization = client_for(role_key="owner", slug="details-csrf")

    response = client.put("/api/v1/billing/details/", COMPLETE, format="json")

    assert response.status_code == 403


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"), STRIPE_LIVEMODE=False)
def test_a_nonsense_country_is_rejected() -> None:
    client, _organization = client_for(role_key="owner", slug="details-country")

    response = client.put(
        "/api/v1/billing/details/",
        {**COMPLETE, "country_code": "Polska"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_of(client),
    )

    assert response.status_code == 400
