"""An organization's own roles, next to its type's system roles (ADR-050).

The type fixes the system roles; an organization adds roles of its own from the
permissions its modules declare. Two are never grantable: handing over the
organization and archiving it stay with the owner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User

from .audit import record_audit
from .authorization import authorize
from .models import (
    Invitation,
    Membership,
    Organization,
    OrganizationAuditAction,
    Role,
    RoleScope,
)
from .permissions import MEMBERS_MANAGE, MEMBERS_READ, ORGANIZATION_ARCHIVE, OWNERSHIP_TRANSFER
from .role_catalog import limited_role_keys, system_roles

NEVER_GRANTABLE = frozenset({OWNERSHIP_TRANSFER, ORGANIZATION_ARCHIVE})


class RoleInUse(APIException):
    status_code = 409
    default_detail = "Rolę ktoś ma albo miał — zmień jej nazwę lub uprawnienia zamiast ją usuwać."
    default_code = "role_in_use"


class RoleVersionConflict(APIException):
    status_code = 409
    default_detail = "Rola zmieniła się w międzyczasie. Odśwież i spróbuj ponownie."
    default_code = "role_version_conflict"


@dataclass(frozen=True, slots=True)
class RoleCatalog:
    roles: list[Role]
    limited: frozenset[str]
    grantable: tuple[str, ...]


def _organization_type(organization_id: uuid.UUID) -> str:
    return (
        Organization.objects.filter(pk=organization_id)
        .values_list("organization_type", flat=True)
        .first()
        or ""
    )


def grantable_permissions(organization_type: str) -> tuple[str, ...]:
    """Permissions an own role may hold: those of core and of the type's modules."""
    known = settings.ORGANIZATION_TYPES.get(organization_type)
    allowed_modules = known.modules if known is not None else frozenset()
    permissions: dict[str, None] = {}
    for module_id in settings.ACTIVE_MODULES:
        if module_id.startswith("core.") or module_id in allowed_modules:
            for permission in settings.MODULE_CATALOG[module_id].permissions:
                if permission not in NEVER_GRANTABLE:
                    permissions[permission] = None
    return tuple(permissions)


def list_roles() -> RoleCatalog:
    context = authorize(MEMBERS_READ)
    organization_type = _organization_type(context.organization_id)
    roles = [
        *system_roles(organization_type).order_by("key"),
        *Role.objects.filter(organization_id=context.organization_id).order_by("name"),
    ]
    return RoleCatalog(
        roles=roles,
        limited=limited_role_keys(organization_type),
        grantable=grantable_permissions(organization_type),
    )


def _validated_permissions(organization_id: uuid.UUID, permissions: list[str]) -> list[str]:
    grantable = set(grantable_permissions(_organization_type(organization_id)))
    refused = sorted(set(permissions) - grantable)
    if refused:
        raise ValidationError({"permissions": [f"Niedozwolone uprawnienia: {', '.join(refused)}"]})
    return list(dict.fromkeys(permissions))


@transaction.atomic
def create_role(*, request: HttpRequest, name: str, permissions: list[str]) -> Role:
    context = authorize(MEMBERS_MANAGE)
    role = Role.objects.create(
        organization_id=context.organization_id,
        key=f"custom-{uuid.uuid4().hex[:8]}",
        name=name.strip(),
        scope=RoleScope.ORGANIZATION,
        permissions=_validated_permissions(context.organization_id, permissions),
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.ROLE_CREATED,
        actor=cast(User, request.user),
        target_type="role",
        target_id=role.id,
        metadata={"permissions": role.permissions},
    )
    return role


def _own_role(organization_id: uuid.UUID, key: str) -> Role:
    role = (
        Role.objects.select_for_update()
        .filter(organization_id=organization_id, key=key)
        .first()
    )
    if role is None:
        raise NotFound("Nie ma takiej roli w tej organizacji.")
    return role


@transaction.atomic
def update_role(
    *,
    request: HttpRequest,
    key: str,
    version: int,
    name: str | None = None,
    permissions: list[str] | None = None,
) -> Role:
    context = authorize(MEMBERS_MANAGE)
    role = _own_role(context.organization_id, key)
    if role.version != version:
        raise RoleVersionConflict
    previous = list(role.permissions)
    if name is not None:
        role.name = name.strip()
    if permissions is not None:
        role.permissions = _validated_permissions(context.organization_id, permissions)
    role.version += 1
    role.save(update_fields=["name", "permissions", "version", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.ROLE_UPDATED,
        actor=cast(User, request.user),
        target_type="role",
        target_id=role.id,
        metadata={"previous_permissions": previous, "permissions": role.permissions},
    )
    return role


@transaction.atomic
def delete_role(*, request: HttpRequest, key: str) -> None:
    context = authorize(MEMBERS_MANAGE)
    role = _own_role(context.organization_id, key)
    # Memberships and invitations keep their role for history, even revoked
    # ones; a role anybody ever held is renamed or narrowed, not deleted.
    in_use = (
        Membership.objects.filter(role=role).exists()
        or Invitation.objects.filter(role=role).exists()
    )
    if in_use:
        raise RoleInUse
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.ROLE_DELETED,
        actor=cast(User, request.user),
        target_type="role",
        target_id=role.id,
        metadata={"key": role.key, "name": role.name},
    )
    role.delete()
