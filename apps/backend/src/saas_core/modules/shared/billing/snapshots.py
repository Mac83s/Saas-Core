from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from saas_core.modules.core.organizations.models import Organization

from .models import EntitlementSnapshot, StripePriceMapping


def update_entitlement_snapshot(
    organization: Organization,
    mapping: StripePriceMapping,
    *,
    state: str,
    access_mode: str,
    effective_until: datetime | None,
) -> EntitlementSnapshot:
    plan_version = mapping.plan_version
    source = {
        "kind": "plan",
        "ref": f"{plan_version.plan.key}:v{plan_version.version}",
        "stripe_price_id": mapping.stripe_price_id,
    }
    sources = {key: source for key in [*plan_version.feature_keys, *plan_version.quotas]}
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
            features={key: True for key in plan_version.feature_keys},
            quotas=plan_version.quotas,
            sources=sources,
            effective_until=effective_until,
        )
    snapshot.plan_version = plan_version
    snapshot.subscription_state = state
    snapshot.access_mode = access_mode
    snapshot.features = {key: True for key in plan_version.feature_keys}
    snapshot.quotas = plan_version.quotas
    snapshot.sources = sources
    snapshot.effective_until = effective_until
    snapshot.version += 1
    snapshot.computed_at = timezone.now()
    snapshot.save()
    return snapshot
