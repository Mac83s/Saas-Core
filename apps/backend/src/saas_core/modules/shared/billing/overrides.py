from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditAction,
    WorkspaceKind,
)

from .models import EntitlementGrant, Feature, GrantSource, QuotaDefinition
from .snapshots import refresh_entitlement_snapshot, refresh_internal_snapshot
from .tenant_scope import billing_organization_ids, billing_tenant_scope


class BillingOperatorRequired(PermissionDenied):
    default_detail = "Operacja wymaga aktywnego operatora platformy."
    default_code = "billing_operator_required"


class OverrideIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji został użyty dla innego override'u."
    default_code = "billing_override_idempotency_conflict"


class OverrideTargetConflict(APIException):
    status_code = 409
    default_detail = "Dla tego pola istnieje już aktywny override."
    default_code = "billing_override_target_conflict"


@transaction.atomic
def create_entitlement_override(
    *,
    actor: User,
    reason: str,
    idempotency_key: str,
    feature_key: str | None = None,
    enabled: bool | None = None,
    quota_key: str | None = None,
    limit_value: int | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> EntitlementGrant:
    context = require_tenant_context()
    _authorize_operator(actor)
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    checked_at = timezone.now()
    starts_at = valid_from or checked_at
    normalized_reason = reason.strip()
    normalized_key = idempotency_key.strip()
    if not normalized_reason:
        raise ValueError("Uzasadnienie override'u jest wymagane.")
    if not normalized_key or len(normalized_key) > 120:
        raise ValueError("Klucz idempotencji musi mieć od 1 do 120 znaków.")
    if expires_at is not None and expires_at <= starts_at:
        raise ValueError("Wygaśnięcie override'u musi przypadać po jego początku.")
    if starts_at > checked_at:
        raise ValueError("Override może rozpocząć się najpóźniej w chwili jego utworzenia.")
    feature, quota = _resolve_target(
        feature_key=feature_key,
        enabled=enabled,
        quota_key=quota_key,
        limit_value=limit_value,
    )
    existing = EntitlementGrant.all_objects.filter(
        organization=organization,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if _same_override(
            existing,
            actor=actor,
            reason=normalized_reason,
            feature=feature,
            enabled=enabled,
            quota=quota,
            limit_value=limit_value,
            valid_from=valid_from,
            expires_at=expires_at,
        ):
            return existing
        raise OverrideIdempotencyConflict

    active_target = EntitlementGrant.all_objects.filter(
        organization=organization,
        source=GrantSource.OVERRIDE,
        revoked_at__isnull=True,
        feature=feature,
        quota_definition=quota,
        valid_from__lte=checked_at,
    ).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=checked_at))
    if active_target.exists():
        raise OverrideTargetConflict

    grant = EntitlementGrant.all_objects.create(
        organization=organization,
        source=GrantSource.OVERRIDE,
        feature=feature,
        quota_definition=quota,
        enabled=enabled,
        limit_value=limit_value,
        reason=normalized_reason,
        idempotency_key=normalized_key,
        granted_by=actor,
        valid_from=starts_at,
        expires_at=expires_at,
    )
    if starts_at <= checked_at:
        # The platform workspace has no plan to recompute against, so its
        # snapshot is built from these overrides alone. Same audited path,
        # same entitlement check afterwards.
        if organization.workspace_kind == WorkspaceKind.PLATFORM:
            refresh_internal_snapshot(organization, at=checked_at)
        else:
            refresh_entitlement_snapshot(organization, at=checked_at)
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_CREATED,
        actor=actor,
        target_type="entitlement_grant",
        target_id=grant.id,
        metadata={
            "target": feature.key if feature else cast(QuotaDefinition, quota).key,
            "value": enabled if feature else limit_value,
            "reason": normalized_reason,
            "valid_from": starts_at.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    return grant


@transaction.atomic
def revoke_entitlement_override(*, actor: User, grant_id: UUID, reason: str) -> EntitlementGrant:
    context = require_tenant_context()
    _authorize_operator(actor)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("Uzasadnienie cofnięcia override'u jest wymagane.")
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    grant = EntitlementGrant.all_objects.select_for_update().get(
        pk=grant_id,
        organization=organization,
        source=GrantSource.OVERRIDE,
    )
    if grant.revoked_at is not None:
        return grant
    grant.revoked_at = timezone.now()
    grant.save(update_fields=["revoked_at", "updated_at"])
    refresh_entitlement_snapshot(organization)
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_REVOKED,
        actor=actor,
        target_type="entitlement_grant",
        target_id=grant.id,
        metadata={"reason": normalized_reason},
    )
    return grant


def expire_entitlement_overrides(*, at: datetime | None = None, batch_size: int = 100) -> int:
    checked_at = at or timezone.now()
    expired = 0
    remaining = batch_size
    # Grants force row-level security, so the sweep walks organizations
    # instead of asking for every expired grant at once (ADR-039).
    for organization_id in billing_organization_ids():
        if remaining <= 0:
            break
        with billing_tenant_scope(organization_id):
            ids = list(
                EntitlementGrant.all_objects.filter(
                    organization_id=organization_id,
                    source=GrantSource.OVERRIDE,
                    revoked_at__isnull=True,
                    expires_at__lte=checked_at,
                )
                .order_by("expires_at", "id")
                .values_list("id", flat=True)[:remaining]
            )
        remaining -= len(ids)
        for grant_id in ids:
            _expire_override(organization_id=organization_id, grant_id=grant_id, at=checked_at)
        expired += len(ids)
    return expired


def _expire_override(*, organization_id: UUID, grant_id: UUID, at: datetime) -> None:
    with billing_tenant_scope(organization_id):
        _expire_override_in_scope(grant_id=grant_id, at=at)


def _expire_override_in_scope(*, grant_id: UUID, at: datetime) -> None:
    grant = (
        EntitlementGrant.all_objects.select_for_update()
        .select_related("organization")
        .filter(pk=grant_id, revoked_at__isnull=True, expires_at__lte=at)
        .first()
    )
    if grant is None:
        return
    expired_at = grant.expires_at
    if expired_at is None:
        return
    Organization.objects.select_for_update().get(pk=grant.organization_id)
    grant.revoked_at = expired_at
    grant.save(update_fields=["revoked_at", "updated_at"])
    refresh_entitlement_snapshot(grant.organization, at=at)
    record_audit(
        organization=grant.organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_EXPIRED,
        actor=None,
        target_type="entitlement_grant",
        target_id=grant.id,
        metadata={"expired_at": expired_at.isoformat()},
    )


def _authorize_operator(actor: User) -> None:
    context = require_tenant_context()
    if context.actor_id != actor.id or not actor.is_active or not actor.is_staff:
        raise BillingOperatorRequired


def _resolve_target(
    *,
    feature_key: str | None,
    enabled: bool | None,
    quota_key: str | None,
    limit_value: int | None,
) -> tuple[Feature | None, QuotaDefinition | None]:
    feature_override = feature_key is not None and isinstance(enabled, bool)
    quota_override = (
        quota_key is not None
        and isinstance(limit_value, int)
        and not isinstance(limit_value, bool)
        and limit_value >= 0
    )
    if feature_override == quota_override:
        raise ValueError("Override wymaga dokładnie jednej poprawnej funkcji albo quota.")
    if feature_override:
        return Feature.objects.get(key=cast(str, feature_key), is_active=True), None
    return None, QuotaDefinition.objects.get(key=cast(str, quota_key), is_active=True)


def _same_override(
    grant: EntitlementGrant,
    *,
    actor: User,
    reason: str,
    feature: Feature | None,
    enabled: bool | None,
    quota: QuotaDefinition | None,
    limit_value: int | None,
    valid_from: datetime | None,
    expires_at: datetime | None,
) -> bool:
    return (
        grant.source == GrantSource.OVERRIDE
        and grant.granted_by_id == actor.id
        and grant.reason == reason
        and grant.feature_id == (feature.id if feature else None)
        and grant.enabled == enabled
        and grant.quota_definition_id == (quota.id if quota else None)
        and grant.limit_value == limit_value
        and (valid_from is None or grant.valid_from == valid_from)
        and grant.expires_at == expires_at
    )
