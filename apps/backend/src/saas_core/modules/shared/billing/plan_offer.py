"""Which plans an organization is offered — those of its type (ADR-050)."""

from __future__ import annotations

from uuid import UUID

from django.conf import settings

from saas_core.modules.core.organizations.models import Organization


def plan_keys_for_type(organization_type: str) -> tuple[str, ...]:
    """The plans offered to one kind of organization (ADR-050), profile order."""
    known = settings.ORGANIZATION_TYPES.get(organization_type)
    offered = set(known.plan_keys) if known is not None else set()
    return tuple(key for key in settings.BILLING_PLAN_KEYS if key in offered)


def plan_keys_for_organization(organization_id: UUID) -> tuple[str, ...]:
    """The plans the acting organization may buy — those of its type."""
    organization_type = (
        Organization.objects.filter(pk=organization_id)
        .values_list("organization_type", flat=True)
        .first()
    )
    return plan_keys_for_type(organization_type or "")
