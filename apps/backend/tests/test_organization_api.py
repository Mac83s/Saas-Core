from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserSession, UserStatus
from saas_core.modules.core.identity.tokens import digest_secret
from saas_core.modules.core.organizations.middleware import (
    ACTIVE_ORGANIZATION_SESSION_KEY,
)
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
    Role,
)

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
ORGANIZATIONS_URL = "/api/v1/organizations/"
CURRENT_URL = "/api/v1/organizations/current/"
ACTIVE_URL = "/api/v1/session/active-organization/"
PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def active_user(*, email: str = "owner@example.com") -> User:
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def membership_for(
    user: User,
    *,
    role_key: str = "owner",
    slug: str = "acme",
    organization_status: str = OrganizationStatus.ACTIVE,
    membership_status: str = MembershipStatus.ACTIVE,
) -> Membership:
    organization = Organization.objects.create(
        name=slug.upper(),
        slug=slug,
        status=organization_status,
    )
    return Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
        status=membership_status,
    )


def login(client: APIClient, user: User):
    csrf = client.get(CSRF_URL).data["csrf_token"]
    return client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )


def csrf_value(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def test_login_selects_only_organization_but_requires_choice_for_many() -> None:
    single_user = active_user(email="single@example.com")
    single_membership = membership_for(single_user, slug="single")
    single_client = APIClient(enforce_csrf_checks=True)

    assert login(single_client, single_user).status_code == 200
    assert single_client.session[ACTIVE_ORGANIZATION_SESSION_KEY] == str(
        single_membership.organization_id
    )
    assert single_client.get(CURRENT_URL).status_code == 200

    multi_user = active_user(email="multi@example.com")
    membership_for(multi_user, slug="multi-one")
    membership_for(multi_user, slug="multi-two")
    multi_client = APIClient(enforce_csrf_checks=True)

    assert login(multi_client, multi_user).status_code == 200
    assert ACTIVE_ORGANIZATION_SESSION_KEY not in multi_client.session
    missing = multi_client.get(CURRENT_URL)
    assert missing.status_code == 409
    assert missing.data["code"] == "active_organization_required"


def test_create_organization_is_atomic_creates_owner_and_rotates_session() -> None:
    user = active_user()
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    old_session_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.post(
        ORGANIZATIONS_URL,
        {
            "name": "Nowa firma",
            "slug": "nowa-firma",
            "workspace_kind": "business",
            "default_locale": "pl",
            "timezone": "Europe/Warsaw",
            "currency": "PLN",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == 201
    organization = Organization.objects.get(slug="nowa-firma")
    membership = Membership.objects.get(organization=organization, user=user)
    assert membership.role.key == "owner"
    assert BillingProfile.objects.filter(organization=organization).exists()
    assert response.data["active"] is True
    assert client.session[ACTIVE_ORGANIZATION_SESSION_KEY] == str(organization.id)
    new_session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert new_session_key != old_session_key
    assert not Session.objects.filter(session_key=old_session_key).exists()
    tracking = UserSession.objects.get(user=user)
    assert tracking.session_key_hash == digest_secret(new_session_key)


def test_create_requires_csrf_and_duplicate_slug_returns_conflict() -> None:
    user = active_user()
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    payload = {"name": "ACME", "slug": "acme"}

    missing_csrf = client.post(ORGANIZATIONS_URL, payload, format="json")
    created = client.post(
        ORGANIZATIONS_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    duplicate = client.post(
        ORGANIZATIONS_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert missing_csrf.status_code == 403
    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.data["code"] == "organization_slug_conflict"


def test_list_contains_only_callers_organizations_and_marks_active() -> None:
    user = active_user()
    active_membership = membership_for(user, slug="mine")
    membership_for(user, slug="second")
    foreign_user = active_user(email="foreign@example.com")
    membership_for(foreign_user, slug="foreign")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    session = client.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(active_membership.organization_id)
    session.save()

    response = client.get(ORGANIZATIONS_URL)

    assert response.status_code == 200
    assert {item["slug"] for item in response.data} == {"mine", "second"}
    assert [item["slug"] for item in response.data if item["active"]] == ["mine"]


def test_active_organization_switch_rejects_foreign_tenant_and_rotates_on_success() -> None:
    user = active_user()
    first = membership_for(user, slug="first")
    second = membership_for(user, slug="second")
    foreign = membership_for(active_user(email="other@example.com"), slug="foreign")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    old_session_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    rejected = client.put(
        ACTIVE_URL,
        {"organization_id": str(foreign.organization_id)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    selected = client.put(
        ACTIVE_URL,
        {"organization_id": str(second.organization_id)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert rejected.status_code == 404
    assert selected.status_code == 200
    assert selected.data["organization"]["id"] == str(second.organization_id)
    assert selected.data["organization"]["id"] != str(first.organization_id)
    assert client.cookies[settings.SESSION_COOKIE_NAME].value != old_session_key
    assert client.get(CURRENT_URL).data["slug"] == "second"


@pytest.mark.parametrize("role_key", ["viewer", "staff", "manager", "admin", "owner"])
def test_every_system_role_can_read_current_organization(role_key: str) -> None:
    user = active_user(email=f"{role_key}@example.com")
    membership_for(user, role_key=role_key, slug=f"org-{role_key}")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200

    response = client.get(CURRENT_URL)

    assert response.status_code == 200
    assert response.data["role"] == role_key


@pytest.mark.parametrize(
    ("role_key", "expected_status"),
    [
        ("viewer", 403),
        ("staff", 403),
        ("manager", 403),
        ("admin", 200),
        ("owner", 200),
    ],
)
def test_settings_update_uses_central_permission_decision(
    role_key: str,
    expected_status: int,
) -> None:
    user = active_user(email=f"settings-{role_key}@example.com")
    membership = membership_for(user, role_key=role_key, slug=f"settings-{role_key}")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200

    response = client.patch(
        CURRENT_URL,
        {
            "version": membership.organization.version,
            "name": "Zmieniona nazwa",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == expected_status
    membership.organization.refresh_from_db()
    assert (membership.organization.name == "Zmieniona nazwa") is (expected_status == 200)


def test_update_is_optimistic_and_cannot_target_organization_from_body() -> None:
    user = active_user()
    current = membership_for(user, slug="current")
    other = membership_for(user, slug="other")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    session = client.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(current.organization_id)
    session.save()

    conflict = client.patch(
        CURRENT_URL,
        {
            "version": current.organization.version + 1,
            "name": "Nie zapisuj",
            "organization_id": str(other.organization_id),
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert conflict.status_code == 409
    assert conflict.data["code"] == "organization_version_conflict"
    current.organization.refresh_from_db()
    other.organization.refresh_from_db()
    assert current.organization.name == "CURRENT"
    assert other.organization.name == "OTHER"


@pytest.mark.parametrize(("role_key", "expected_status"), [("admin", 403), ("owner", 200)])
def test_archive_is_owner_only(role_key: str, expected_status: int) -> None:
    user = active_user(email=f"archive-{role_key}@example.com")
    membership = membership_for(user, role_key=role_key, slug=f"archive-{role_key}")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200

    response = client.delete(CURRENT_URL, HTTP_X_CSRFTOKEN=csrf_value(client))

    assert response.status_code == expected_status
    membership.organization.refresh_from_db()
    if expected_status == 200:
        assert membership.organization.status == OrganizationStatus.ARCHIVED
        assert ACTIVE_ORGANIZATION_SESSION_KEY not in client.session
    else:
        assert membership.organization.status == OrganizationStatus.ACTIVE


@pytest.mark.parametrize(
    ("organization_status", "membership_status"),
    [
        (OrganizationStatus.SUSPENDED, MembershipStatus.ACTIVE),
        (OrganizationStatus.ACTIVE, MembershipStatus.SUSPENDED),
    ],
)
def test_switch_rejects_suspended_organization_or_membership(
    organization_status: str,
    membership_status: str,
) -> None:
    user = active_user()
    membership = membership_for(
        user,
        organization_status=organization_status,
        membership_status=membership_status,
    )
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200

    response = client.put(
        ACTIVE_URL,
        {"organization_id": str(membership.organization_id)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == 404


def test_organization_endpoints_require_authentication() -> None:
    client = APIClient()

    assert client.get(ORGANIZATIONS_URL).status_code == 403
    assert client.get(CURRENT_URL).status_code == 403
