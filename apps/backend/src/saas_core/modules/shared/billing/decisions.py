from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, cast

from django.utils import timezone

from saas_core.modules.core.organizations.context import require_tenant_context

from .models import AccessMode, EntitlementSnapshot, Feature, QuotaDefinition


class FeatureOperation(StrEnum):
    READ = "read"
    WRITE = "write"


class DecisionReason(StrEnum):
    ALLOWED = "allowed"
    SNAPSHOT_MISSING = "snapshot_missing"
    SNAPSHOT_EXPIRED = "snapshot_expired"
    ACCESS_BLOCKED = "access_blocked"
    READ_ONLY = "read_only"
    UNKNOWN_FEATURE = "unknown_feature"
    FEATURE_DISABLED = "feature_disabled"
    UNKNOWN_QUOTA = "unknown_quota"
    QUOTA_MISSING = "quota_missing"
    QUOTA_AVAILABLE = "quota_available"


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    snapshot_id: str | None
    snapshot_version: int | None
    subscription_state: str | None
    access_mode: str | None
    source: Any | None


@dataclass(frozen=True, slots=True)
class FeatureDecision:
    feature_key: str
    operation: FeatureOperation
    allowed: bool
    reason: DecisionReason
    evidence: DecisionEvidence


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    quota_key: str
    value: int
    available: bool
    reason: DecisionReason
    evidence: DecisionEvidence


def can(
    feature_key: str,
    *,
    operation: FeatureOperation = FeatureOperation.WRITE,
    at: datetime | None = None,
) -> bool:
    return decide_feature(feature_key, operation=operation, at=at).allowed


def limit(quota_key: str, *, at: datetime | None = None) -> int:
    return decide_quota(quota_key, at=at).value


def decide_feature(
    feature_key: str,
    *,
    operation: FeatureOperation = FeatureOperation.WRITE,
    at: datetime | None = None,
) -> FeatureDecision:
    require_tenant_context()
    snapshot = cast(EntitlementSnapshot | None, EntitlementSnapshot.objects.first())
    evidence = _evidence(snapshot, feature_key)
    if snapshot is None:
        return FeatureDecision(
            feature_key,
            operation,
            False,
            DecisionReason.SNAPSHOT_MISSING,
            evidence,
        )
    if not Feature.objects.filter(key=feature_key, is_active=True).exists():
        return FeatureDecision(
            feature_key,
            operation,
            False,
            DecisionReason.UNKNOWN_FEATURE,
            evidence,
        )
    access_reason = _access_denial(snapshot, operation=operation, at=at)
    if access_reason is not None:
        return FeatureDecision(feature_key, operation, False, access_reason, evidence)
    if snapshot.features.get(feature_key) is not True:
        return FeatureDecision(
            feature_key,
            operation,
            False,
            DecisionReason.FEATURE_DISABLED,
            evidence,
        )
    return FeatureDecision(
        feature_key,
        operation,
        True,
        DecisionReason.ALLOWED,
        evidence,
    )


def decide_quota(quota_key: str, *, at: datetime | None = None) -> QuotaDecision:
    require_tenant_context()
    snapshot = cast(EntitlementSnapshot | None, EntitlementSnapshot.objects.first())
    evidence = _evidence(snapshot, quota_key)
    if snapshot is None:
        return QuotaDecision(
            quota_key,
            0,
            False,
            DecisionReason.SNAPSHOT_MISSING,
            evidence,
        )
    if not QuotaDefinition.objects.filter(key=quota_key, is_active=True).exists():
        return QuotaDecision(
            quota_key,
            0,
            False,
            DecisionReason.UNKNOWN_QUOTA,
            evidence,
        )
    access_reason = _access_denial(snapshot, operation=FeatureOperation.READ, at=at)
    if access_reason is not None:
        return QuotaDecision(quota_key, 0, False, access_reason, evidence)
    value = snapshot.quotas.get(quota_key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return QuotaDecision(
            quota_key,
            0,
            False,
            DecisionReason.QUOTA_MISSING,
            evidence,
        )
    return QuotaDecision(
        quota_key,
        value,
        True,
        DecisionReason.QUOTA_AVAILABLE,
        evidence,
    )


def _access_denial(
    snapshot: EntitlementSnapshot,
    *,
    operation: FeatureOperation,
    at: datetime | None,
) -> DecisionReason | None:
    checked_at = at or timezone.now()
    if snapshot.effective_until is not None and snapshot.effective_until <= checked_at:
        return DecisionReason.SNAPSHOT_EXPIRED
    if snapshot.access_mode == AccessMode.BLOCKED:
        return DecisionReason.ACCESS_BLOCKED
    if snapshot.access_mode == AccessMode.READ_ONLY and operation == FeatureOperation.WRITE:
        return DecisionReason.READ_ONLY
    return None


def _evidence(
    snapshot: EntitlementSnapshot | None,
    key: str,
) -> DecisionEvidence:
    if snapshot is None:
        return DecisionEvidence(None, None, None, None, None)
    source = snapshot.sources.get(key)
    if source is None:
        source = snapshot.sources.get("plan")
    return DecisionEvidence(
        snapshot_id=str(snapshot.id),
        snapshot_version=snapshot.version,
        subscription_state=snapshot.subscription_state,
        access_mode=snapshot.access_mode,
        source=source,
    )
