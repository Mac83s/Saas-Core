from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import transaction

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)

PUBLIC_BOOKING_PERMISSIONS = frozenset({"booking.public.read", "booking.public.manage"})


def issue_self_service_token() -> tuple[str, str]:
    token = "bk_" + secrets.token_urlsafe(32)
    return token, token_digest(token)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def public_booking_context(organization_id: UUID) -> Iterator[TenantContext]:
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key="public_booking",
        permissions=PUBLIC_BOOKING_PERMISSIONS,
        principal_kind="service",
    )
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(organization_id)
        yield context
