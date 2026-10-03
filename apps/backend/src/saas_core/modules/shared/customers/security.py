"""The tenant a public read of a document runs in (ADR-073 §9): a `service`
context with one permission, set from the PII-free route — the pattern of
booking's `public_booking_context`, never a membership."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import transaction

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)

PUBLIC_DOCUMENTS_ROLE = "public_documents"
PUBLIC_DOCUMENTS_PERMISSIONS = frozenset({"customers.public.read"})


@contextmanager
def public_documents_context(organization_id: UUID) -> Iterator[TenantContext]:
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=PUBLIC_DOCUMENTS_ROLE,
        permissions=PUBLIC_DOCUMENTS_PERMISSIONS,
        principal_kind="service",
    )
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(organization_id)
        yield context
