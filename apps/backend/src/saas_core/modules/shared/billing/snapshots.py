from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from saas_core.modules.core.organizations.models import Organization

from .models import (
    EntitlementGrant,
    EntitlementSnapshot,
    Feature,
    GrantSource,
    PlanVersion,
    QuotaDefinition,
    StripePriceMapping,
)


@transaction.atomic
def update_entitlement_snapshot(
    organization: Organization,
    mapping: StripePriceMapping,
    *,
    state: str,
    access_mode: str,
    effective_until: datetime | None,
) -> EntitlementSnapshot:
    plan_version = mapping.plan_version
    return _write_entitlement_snapshot(
        organization,
        plan_version=plan_version,
        stripe_price_id=mapping.stripe_price_id,
        state=state,
        access_mode=access_mode,
        effective_until=effective_until,
    )


@transaction.atomic
def refresh_entitlement_snapshot(
    organization: Organization,
    *,
    at: datetime | None = None,
) -> EntitlementSnapshot:
    snapshot = (
        EntitlementSnapshot.all_objects.select_for_update(of=("self",))
        .select_related("plan_version__plan")
        .get(organization=organization)
    )
    if snapshot.plan_version is None:
        raise ValueError("Snapshot bez wersji planu nie może być przeliczony.")
    plan_source = next(
        (
            source
            for source in snapshot.sources.values()
            if isinstance(source, dict) and source.get("kind") == "plan"
        ),
        {},
    )
    return _write_entitlement_snapshot(
        organization,
        plan_version=snapshot.plan_version,
        stripe_price_id=plan_source.get("stripe_price_id"),
        state=snapshot.subscription_state,
        access_mode=snapshot.access_mode,
        effective_until=snapshot.effective_until,
        at=at,
        snapshot=snapshot,
    )


def _write_entitlement_snapshot(
    organization: Organization,
    *,
    plan_version: PlanVersion,
    stripe_price_id: str | None,
    state: str,
    access_mode: str,
    effective_until: datetime | None,
    at: datetime | None = None,
    snapshot: EntitlementSnapshot | None = None,
) -> EntitlementSnapshot:
    checked_at = at or timezone.now()
    source: dict[str, Any] = {
        "kind": "plan",
        "ref": f"{plan_version.plan.key}:v{plan_version.version}",
    }
    if stripe_price_id:
        source["stripe_price_id"] = stripe_price_id
    features = {key: True for key in plan_version.feature_keys}
    quotas = dict(plan_version.quotas)
    sources: dict[str, dict[str, Any]] = {
        key: source for key in [*plan_version.feature_keys, *plan_version.quotas]
    }
    overrides = (
        EntitlementGrant.all_objects.select_related("feature", "quota_definition", "granted_by")
        .filter(
            organization=organization,
            source=GrantSource.OVERRIDE,
            revoked_at__isnull=True,
            valid_from__lte=checked_at,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=checked_at))
        .order_by("valid_from", "created_at", "id")
    )
    for grant in overrides:
        if grant.feature_id:
            target_key = cast(Feature, grant.feature).key
            fallback_value = features.get(target_key)
            features[target_key] = cast(bool, grant.enabled)
        else:
            target_key = cast(QuotaDefinition, grant.quota_definition).key
            fallback_value = quotas.get(target_key)
            quotas[target_key] = cast(int, grant.limit_value)
        fallback_source = sources.get(target_key)
        sources[target_key] = {
            "kind": "override",
            "ref": str(grant.id),
            "reason": grant.reason,
            "granted_by": str(grant.granted_by_id),
            "valid_from": grant.valid_from.isoformat(),
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "fallback_value": fallback_value,
            "fallback_source": fallback_source,
        }
    if snapshot is None:
        snapshot = (
            EntitlementSnapshot.all_objects.select_for_update()
            .filter(organization=organization)
            .first()
        )
    if snapshot is None:
        return EntitlementSnapshot.all_objects.create(
            organization=organization,
            plan_version=plan_version,
            subscription_state=state,
            access_mode=access_mode,
            features=features,
            quotas=quotas,
            sources=sources,
            effective_until=effective_until,
        )
    snapshot.plan_version = plan_version
    snapshot.subscription_state = state
    snapshot.access_mode = access_mode
    snapshot.features = features
    snapshot.quotas = quotas
    snapshot.sources = sources
    snapshot.effective_until = effective_until
    snapshot.version += 1
    snapshot.computed_at = timezone.now()
    snapshot.save()
    return snapshot
