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
        "test_farm": replace(default, key="test_farm", roles=roles),
    }
    settings.DEFAULT_ORGANIZATION_TYPE = "test_farm"


def test_the_catalogue_writes_typed_roles_and_moves_memberships(settings: Any) -> None:
    user = active_user()
    membership = membership_for(user, role_key="admin")
    Organization.objects.filter(pk=membership.organization_id).update(organization_type="test_farm")
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
    assert membership.role.organization_type == "test_farm"
    assert membership.role.key == "admin"
    assert sync_system_roles() == {"created": 0, "updated": 0, "moved": 0}

    farm_types(
        settings,
        role("owner", *CORE_OWNER),
        role("admin", "organization.read"),
        role("herd_manager", "organization.read", limited=True),
    )
    assert sync_system_roles()["updated"] == 1
    admin = Role.objects.get(organization__isnull=True, organization_type="test_farm", key="admin")
    assert admin.permissions == ["organization.read"]
    assert admin.version == 2


def test_a_typed_organization_gets_its_type_owner(settings: Any) -> None:
    farm_types(settings, role("owner", *CORE_OWNER), role("admin", "organization.read"))
    sync_system_roles()
    client = APIClient()
    login(client, active_user())

    created = client.post(
        ORGANIZATIONS_URL,
        {"name": "Farma", "slug": "farma", "organization_type": "test_farm"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert created.status_code == 201, created.data
    owner = Membership.objects.get(organization_id=created.data["id"])
    assert (owner.role.organization_type, owner.role.key) == ("test_farm", "owner")


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


def test_a_role_is_described_without_permissions_of_modules_outside_the_profile(
    settings: Any,
) -> None:
    """A module that left the profile leaves its permissions on the roles
    (MedPlano without the warehouse still had „Podgląd magazynu” under every
    role). The catalogue lists what a role opens here; the role keeps the rest."""
    client = APIClient()
    owner = active_user()
    membership = membership_for(owner)
    login(client, owner)
    own = Role.objects.create(
        organization_id=membership.organization_id,
        key="custom-old",
        name="Magazynier",
        scope="organization",
        permissions=["organization.read", "left_module.read"],
    )

    listed = {item["key"]: item["permissions"] for item in client.get(ROLES_URL).data["roles"]}

    assert listed["custom-old"] == ["organization.read"]
    own.refresh_from_db()
    assert own.permissions == ["organization.read", "left_module.read"]
    # Of the system roles nothing is hidden but what a module outside this
    # organization's reach declares.
    organization_type = Organization.objects.get(pk=membership.organization_id).organization_type
    reach = settings.ORGANIZATION_TYPES[organization_type].modules
    outside = {
        permission
        for module_id, module in settings.MODULE_CATALOG.items()
        if not module_id.startswith("core.")
        and (module_id not in settings.ACTIVE_MODULES or module_id not in reach)
        for permission in module.permissions
    }
    for system_role in Role.objects.filter(organization__isnull=True, organization_type=""):
        assert set(system_role.permissions) - set(listed[system_role.key]) <= outside
    # With a module taken out of the profile its permissions leave every description.
    module_id = next(
        module_id
        for module_id in settings.ACTIVE_MODULES
        if not module_id.startswith("core.")
        and set(settings.MODULE_CATALOG[module_id].permissions) & set(listed["owner"])
    )
    gone = set(settings.MODULE_CATALOG[module_id].permissions)
    settings.ACTIVE_MODULES = tuple(m for m in settings.ACTIVE_MODULES if m != module_id)
    after = client.get(ROLES_URL).data
    assert not gone & {p for item in after["roles"] for p in item["permissions"]}
    assert not gone & set(after["grantable_permissions"])
