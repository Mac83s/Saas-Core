"""The organization's history of changes: who, when, what, before → after, and
through which channel — readable by the owner and the admin only."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.audit import field_changes
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
HISTORY_URL = "/api/v1/organizations/current/history/"
CURRENT_URL = "/api/v1/organizations/current/"


def member_client(*, slug: str, role_key: str = "owner") -> tuple[APIClient, Organization]:
    user = User.objects.create_user(
        email=f"{slug}@example.test", password=PASSWORD, first_name="Ola", last_name="Nowak"
    )
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug.replace("-", " ").title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"profiles.enabled": True},
        quotas={},
        sources={"profiles.enabled": {"kind": "plan"}},
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


def _csrf(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def test_a_change_says_who_what_before_and_after_and_through_which_channel() -> None:
    client, organization = member_client(slug="historia-zmian")
    other, _ = member_client(slug="historia-obca")
    renamed = other.patch(
        CURRENT_URL,
        {"version": 1, "name": "Cudza nazwa"},
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(other),
    )
    assert renamed.status_code == 200

    version = client.get(CURRENT_URL).data["version"]
    response = client.patch(
        CURRENT_URL,
        {"version": version, "name": "Salon Uroda"},
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )
    assert response.status_code == 200

    history = client.get(HISTORY_URL).data
    latest = history["items"][0]
    assert latest["action"] == OrganizationAuditAction.ORGANIZATION_UPDATED
    assert latest["actor"] == {"name": "Ola Nowak", "email": "historia-zmian@example.test"}
    assert latest["channel"] == "panel"
    assert latest["changes"] == {"name": {"from": "Historia Zmian", "to": "Salon Uroda"}}
    # Another company's history never leaks in, rename included.
    renamed_to = [item["changes"].get("name", {}).get("to") for item in history["items"]]
    assert "Cudza nazwa" not in renamed_to
    assert OrganizationAuditAction.ORGANIZATION_UPDATED in history["actions"]
    assert history["total"] == OrganizationAuditEntry.objects.filter(
        organization=organization
    ).count()


def test_history_pages_newest_first_and_filters_by_action() -> None:
    client, organization = member_client(slug="historia-strony")
    for name in ("Pierwsza", "Druga", "Trzecia"):
        version = client.get(CURRENT_URL).data["version"]
        client.patch(
            CURRENT_URL,
            {"version": version, "name": name},
            format="json",
            HTTP_X_CSRFTOKEN=_csrf(client),
        )

    first = client.get(HISTORY_URL, {"page_size": 1, "action": "organization.updated"}).data
    second = client.get(
        HISTORY_URL, {"page_size": 1, "page": 2, "action": "organization.updated"}
    ).data

    assert first["total"] == 3
    assert first["items"][0]["changes"]["name"]["to"] == "Trzecia"
    assert second["items"][0]["changes"]["name"]["to"] == "Druga"
    assert client.get(HISTORY_URL, {"page_size": 101}).status_code == 400


def test_a_company_card_hides_contact_values_in_its_history() -> None:
    client, _organization = member_client(slug="historia-wizytowka")
    profile = client.get("/api/v1/profiles/organization/").data["profile"]

    saved = client.put(
        f"/api/v1/profiles/{profile['id']}/",
        {
            "display_name": profile["display_name"],
            "headline": "Salon w centrum",
            "contact_phone": "+48 600 100 200",
            "expected_version": profile["version"],
        },
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )
    assert saved.status_code == 200

    entry = next(
        item
        for item in client.get(HISTORY_URL).data["items"]
        if item["action"] == OrganizationAuditAction.PROFILE_UPDATED
    )
    assert entry["changes"]["headline"] == {"from": "", "to": "Salon w centrum"}
    # The history is never rewritten, so a phone number written into it would
    # outlive its correction.
    assert entry["changes"]["contact_phone"] == {"changed": True}


def test_only_those_who_manage_the_organization_read_its_history() -> None:
    client, _organization = member_client(slug="historia-podglad", role_key="viewer")

    response = client.get(HISTORY_URL)

    assert response.status_code == 403


def test_field_changes_keeps_only_real_changes_and_masks_private_fields() -> None:
    before: dict[str, Any] = {"name": "A", "phone": "1", "city": "X"}
    after: dict[str, Any] = {"name": "B", "phone": "2", "city": "X"}

    assert field_changes(before, after, private=("phone",)) == {
        "name": {"from": "A", "to": "B"},
        "phone": {"changed": True},
    }
