"""System roles per organization type and an organization's own roles (ADR-050)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.config.composition import RoleTemplate
from saas_core.modules.core.organizations.models import Membership, Organization, Role
from saas_core.modules.core.organizations.role_catalog import sync_system_roles
from test_organization_api import (
    ORGANIZATIONS_URL,
    active_user,
    csrf_value,
    login,
    membership_for,
)

pytestmark = pytest.mark.django_db

ROLES_URL = "/api/v1/organizations/current/roles/"
CORE_OWNER = (
    "organization.read",
    "organization.members.read",
    "organization.members.manage",
    "organization.members.manage_limited",
    "organization.settings.manage",
    "organization.billing.manage",
    "organization.ownership.transfer",
    "organization.archive",
)


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def role(key: str, *permissions: str, limited: bool = False) -> RoleTemplate:
    return RoleTemplate(
        key=key, label={"pl": key.title(), "en": key}, permissions=permissions, limited=limited
    )


def farm_types(settings: Any, *roles: RoleTemplate) -> None:
    default = settings.ORGANIZATION_TYPES[settings.DEFAULT_ORGANIZATION_TYPE]
    settings.ORGANIZATION_TYPES = {
        "farm": replace(default, key="farm", roles=roles),
    }
    settings.DEFAULT_ORGANIZATION_TYPE = "farm"


def test_the_catalogue_writes_typed_roles_and_moves_memberships(settings: Any) -> None:
    user = active_user()
    membership = membership_for(user, role_key="admin")
    Organization.objects.filter(pk=membership.organization_id).update(organization_type="farm")
    farm_types(
        settings,
        role("owner", *CORE_OWNER),
        role("admin", "organization.read", "organization.members.read"),
        role("herd_manager", "organization.read", limited=True),
    )

    first = sync_system_roles()
    assert first["created"] == 3
    assert first["moved"] == 1
    membership.refresh_from_db()
    assert membership.role.organization_type == "farm"
    assert membership.role.key == "admin"
    assert sync_system_roles() == {"created": 0, "updated": 0, "moved": 0}

    farm_types(
        settings,
        role("owner", *CORE_OWNER),
        role("admin", "organization.read"),
        role("herd_manager", "organization.read", limited=True),
    )
    assert sync_system_roles()["updated"] == 1
    admin = Role.objects.get(organization__isnull=True, organization_type="farm", key="admin")
    assert admin.permissions == ["organization.read"]
    assert admin.version == 2


def test_a_typed_organization_gets_its_type_owner(settings: Any) -> None:
    farm_types(settings, role("owner", *CORE_OWNER), role("admin", "organization.read"))
    sync_system_roles()
    client = APIClient()
    login(client, active_user())

    created = client.post(
        ORGANIZATIONS_URL,
        {"name": "Farma", "slug": "farma", "organization_type": "farm"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert created.status_code == 201, created.data
    owner = Membership.objects.get(organization_id=created.data["id"])
    assert (owner.role.organization_type, owner.role.key) == ("farm", "owner")


def test_an_organization_defines_its_own_role_within_its_modules() -> None:
    client = APIClient()
    owner = active_user()
    membership = membership_for(owner)
    login(client, owner)
    headers = {"HTTP_X_CSRFTOKEN": csrf_value(client)}

    listed = client.get(ROLES_URL)
    assert listed.status_code == 200
    assert {"owner", "admin"} <= {item["key"] for item in listed.data["roles"]}
    grantable = listed.data["grantable_permissions"]
    assert "organization.read" in grantable
    assert "organization.ownership.transfer" not in grantable

    refused = client.post(
        ROLES_URL,
        {"name": "Przejęcie", "permissions": ["organization.ownership.transfer"]},
        format="json",
        **headers,
    )
    assert refused.status_code == 400

    created = client.post(
        ROLES_URL,
        {"name": "Biuro", "permissions": ["organization.read", "organization.members.read"]},
        format="json",
        **headers,
    )
    assert created.status_code == 201, created.data
    key = created.data["key"]
    assert created.data["scope"] == "organization"

    stale = client.patch(
        f"{ROLES_URL}{key}/",
        {"version": 7, "permissions": ["organization.read"]},
        format="json",
        **headers,
    )
    assert stale.status_code == 409
    changed = client.patch(
        f"{ROLES_URL}{key}/",
        {"version": 1, "permissions": ["organization.read"]},
        format="json",
        **headers,
    )
    assert changed.status_code == 200
    assert changed.data["permissions"] == ["organization.read"]

    worker = active_user(email="biuro@example.com")
    Membership.objects.create(
        organization_id=membership.organization_id,
        user=worker,
        role=Role.objects.get(key="viewer", organization=None, organization_type=""),
    )
    worker_membership = Membership.objects.get(user=worker)
    assigned = client.patch(
        f"/api/v1/organizations/current/members/{worker_membership.id}/",
        {"role": key},
        format="json",
        **headers,
    )
    assert assigned.status_code == 200, assigned.data
    assert client.delete(f"{ROLES_URL}{key}/", **headers).status_code == 409

    unused = client.post(
        ROLES_URL, {"name": "Tymczasowa", "permissions": []}, format="json", **headers
    )
    assert client.delete(f"{ROLES_URL}{unused.data['key']}/", **headers).status_code == 204
