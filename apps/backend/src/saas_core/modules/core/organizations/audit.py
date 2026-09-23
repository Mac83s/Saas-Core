from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.db import models

from saas_core.modules.core.identity.models import User
from saas_core.observability import correlation_id

from .context import current_tenant_context
from .models import Organization, OrganizationAuditEntry

#: Credentials a person does not click through: the panel is a membership, an
#: integration a key, everything else a process acting for the organization.
PANEL_PRINCIPAL = "membership"


def record_audit(
    *,
    organization: Organization,
    action: str,
    actor: User | None,
    target_type: str = "",
    target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> OrganizationAuditEntry:
    """One history row. The channel comes from the tenant context of the
    request, so none of the callers has to pass it and none can forget it."""
    context = current_tenant_context()
    return OrganizationAuditEntry.objects.create(
        organization=organization,
        actor_user=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        correlation_id=correlation_id.get(),
        channel=context.principal_kind if context is not None else "",
        credential_id=context.credential_id if context is not None else None,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_value(item) for item in value]
    return str(value)


def audit_snapshot(instance: models.Model, fields: Iterable[str]) -> dict[str, Any]:
    """The fields' values as the history stores them, taken before a change."""
    return {field: _json_value(getattr(instance, field)) for field in fields}


def field_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    private: Collection[str] = (),
) -> dict[str, dict[str, Any]]:
    """What a save really changed: `{field: {"from": …, "to": …}}`.

    A private field (a person's phone, e-mail, address, name) only says that it
    changed. The history is never rewritten, so a value written into it would
    outlive the correction the person asked for.
    """
    changes: dict[str, dict[str, Any]] = {}
    for field, value in after.items():
        if field not in before or before[field] == value:
            continue
        if field in private:
            changes[field] = {"changed": True}
        else:
            changes[field] = {"from": before[field], "to": value}
    return changes
