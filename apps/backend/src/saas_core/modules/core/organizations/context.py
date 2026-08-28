from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from django.db import connection

from .models import Membership


class MissingTenantContext(RuntimeError):
    pass


class TenantContextTransactionRequired(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: UUID
    membership_id: UUID
    actor_id: UUID
    role_key: str
    permissions: frozenset[str]
    principal_kind: str = "membership"
    # Which credential is acting, when one is. `core` deliberately does not know
    # what kind of credential that is — it only carries the id so a module that
    # does can narrow what this request may touch.
    credential_id: UUID | None = None

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


_active_tenant: ContextVar[TenantContext | None] = ContextVar(
    "active_tenant",
    default=None,
)


def context_from_membership(membership: Membership) -> TenantContext:
    permissions = frozenset(
        permission
        for permission in membership.role.permissions
        if isinstance(permission, str) and permission
    )
    return TenantContext(
        organization_id=membership.organization_id,
        membership_id=membership.id,
        actor_id=membership.user_id,
        role_key=membership.role.key,
        permissions=permissions,
    )


def current_tenant_context() -> TenantContext | None:
    return _active_tenant.get()


def require_tenant_context() -> TenantContext:
    context = current_tenant_context()
    if context is None:
        raise MissingTenantContext("Operacja wymaga aktywnego tenant context.")
    return context


@contextmanager
def activate_tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    token = _active_tenant.set(context)
    try:
        yield context
    finally:
        _active_tenant.reset(token)


def set_local_organization_id(organization_id: UUID) -> None:
    if not connection.in_atomic_block:
        raise TenantContextTransactionRequired(
            "SET LOCAL tenant context wymaga aktywnej transakcji."
        )
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization_id)])
