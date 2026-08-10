from __future__ import annotations

from typing import Any
from uuid import UUID

from saas_core.modules.core.identity.models import User
from saas_core.observability import correlation_id

from .models import Organization, OrganizationAuditEntry


def record_audit(
    *,
    organization: Organization,
    action: str,
    actor: User | None,
    target_type: str = "",
    target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> OrganizationAuditEntry:
    return OrganizationAuditEntry.objects.create(
        organization=organization,
        actor_user=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        correlation_id=correlation_id.get(),
    )
