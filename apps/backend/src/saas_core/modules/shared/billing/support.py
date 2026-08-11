from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE

from .decisions import FeatureOperation, decide_feature, decide_quota
from .models import EntitlementSnapshot, Feature, QuotaDefinition, QuotaUsage


def entitlement_support_report() -> dict[str, Any]:
    context = authorize(BILLING_MANAGE)
    snapshot = (
        EntitlementSnapshot.all_objects.select_related("plan_version__plan")
        .filter(organization_id=context.organization_id)
        .first()
    )
    items: list[dict[str, Any]] = []
    for feature in Feature.objects.filter(is_active=True).order_by("key"):
        read = decide_feature(feature.key, operation=FeatureOperation.READ)
        write = decide_feature(feature.key, operation=FeatureOperation.WRITE)
        items.append({
            "kind": "feature",
            "key": feature.key,
            "available": write.allowed,
            "reason": str(write.reason),
            "read_allowed": read.allowed,
            "read_reason": str(read.reason),
            "value": None,
            "used": None,
            "reserved": None,
            "period_start": None,
            "period_end": None,
            "evidence": write.evidence.source,
        })

    today = timezone.now().date()
    for quota in QuotaDefinition.objects.filter(is_active=True).order_by("key"):
        decision = decide_quota(quota.key)
        usage = (
            QuotaUsage.all_objects.filter(
                organization_id=context.organization_id,
                quota_definition=quota,
                period_start__lte=today,
            )
            .filter(Q(period_end__isnull=True) | Q(period_end__gt=today))
            .order_by("-period_start")
            .first()
        )
        items.append({
            "kind": "quota",
            "key": quota.key,
            "available": decision.available,
            "reason": str(decision.reason),
            "read_allowed": None,
            "read_reason": None,
            "value": decision.value,
            "used": usage.used if usage else 0,
            "reserved": usage.reserved if usage else 0,
            "period_start": usage.period_start if usage else None,
            "period_end": usage.period_end if usage else None,
            "evidence": decision.evidence.source,
        })

    return {
        "snapshot": (
            {
                "id": snapshot.id,
                "version": snapshot.version,
                "subscription_state": snapshot.subscription_state,
                "access_mode": snapshot.access_mode,
                "plan_key": snapshot.plan_version.plan.key if snapshot.plan_version else None,
                "plan_version": snapshot.plan_version.version if snapshot.plan_version else None,
                "computed_at": snapshot.computed_at,
                "effective_until": snapshot.effective_until,
            }
            if snapshot
            else None
        ),
        "items": items,
    }
