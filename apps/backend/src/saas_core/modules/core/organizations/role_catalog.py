"""System roles per organization type (ADR-050).

A product declares, per organization type, which system roles exist and what
they may do. They are written after every `migrate`, from the catalogue the
deployment composed — not by migrations, because a product must not edit core's
migrations and a role's permissions are configuration of the product, not
history of the schema. Types that declare no roles keep core's global ones.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import connections, transaction
from django.db.models import QuerySet

from .models import Membership, Role, RoleScope

logger = logging.getLogger(__name__)

#: Core's global roles a limited manager may hand out.
GLOBAL_LIMITED_ROLE_KEYS = frozenset({"viewer", "staff"})

_GUARD = "organizations_system_role_immutable"
_DISABLE_GUARD = f"ALTER TABLE organizations_role DISABLE TRIGGER {_GUARD}"
_ENABLE_GUARD = f"ALTER TABLE organizations_role ENABLE TRIGGER {_GUARD}"


def system_role_scope(organization_type: str) -> str:
    """The `Role.organization_type` of the system roles this type uses."""
    known = settings.ORGANIZATION_TYPES.get(organization_type)
    return organization_type if known is not None and known.roles else ""


def system_roles(organization_type: str) -> QuerySet[Role]:
    return Role.objects.filter(
        organization__isnull=True,
        organization_type=system_role_scope(organization_type),
    )


def system_role(organization_type: str, key: str) -> Role:
    return system_roles(organization_type).get(key=key)


def limited_role_keys(organization_type: str) -> frozenset[str]:
    known = settings.ORGANIZATION_TYPES.get(organization_type)
    if known is None or not known.roles:
        return GLOBAL_LIMITED_ROLE_KEYS
    return frozenset(role.key for role in known.roles if role.limited)


def sync_system_roles(using: str = "default") -> dict[str, int]:
    """Makes the system roles match the catalogue; returns what it changed.

    Idempotent. Creates missing roles, updates changed permissions or names
    (bumping the version, so cached permission sets notice), and moves the
    memberships of each typed organization from core's global role to its
    type's role of the same key. A role the catalogue dropped stays, because a
    membership may still point at it; that is logged, not deleted.
    """
    created = updated = moved = 0
    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            # ALTER TABLE refuses while deferred foreign-key checks are pending
            # in this transaction; checking them now clears the queue.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(_DISABLE_GUARD)
        for organization_type in settings.ORGANIZATION_TYPES.values():
            if not organization_type.roles:
                continue
            declared = {role.key for role in organization_type.roles}
            for template in organization_type.roles:
                permissions = list(template.permissions)
                name = template.label.get("pl") or template.key
                role = (
                    Role.objects.using(using)
                    .filter(
                        organization__isnull=True,
                        organization_type=organization_type.key,
                        key=template.key,
                    )
                    .first()
                )
                if role is None:
                    role = Role.objects.using(using).create(
                        key=template.key,
                        name=name,
                        scope=RoleScope.SYSTEM,
                        organization_type=organization_type.key,
                        permissions=permissions,
                        is_immutable=True,
                    )
                    created += 1
                elif role.permissions != permissions or role.name != name:
                    role.permissions = permissions
                    role.name = name
                    role.version += 1
                    role.save(
                        using=using,
                        update_fields=["permissions", "name", "version", "updated_at"],
                    )
                    updated += 1
                moved += (
                    Membership.objects.using(using)
                    .filter(
                        organization__organization_type=organization_type.key,
                        role__organization__isnull=True,
                        role__organization_type="",
                        role__key=template.key,
                    )
                    .update(role=role)
                )
            stale = (
                Role.objects.using(using)
                .filter(organization__isnull=True, organization_type=organization_type.key)
                .exclude(key__in=declared)
                .values_list("key", flat=True)
            )
            for key in stale:
                logger.warning(
                    "organization_type_role_undeclared",
                    extra={"organization_type": organization_type.key, "role_key": key},
                )
        with connections[using].cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(_ENABLE_GUARD)
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    return {"created": created, "updated": updated, "moved": moved}


def sync_after_migrate(sender: Any, using: str = "default", **_: Any) -> None:
    changes = sync_system_roles(using)
    if any(changes.values()):
        logger.info("organization_type_roles_synced", extra=changes)
