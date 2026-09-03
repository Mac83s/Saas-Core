from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings

from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.models import BillingProfile
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE

from .models import (
    BillingSubscription,
    EntitlementSnapshot,
    Plan,
    StripePriceMapping,
    SubscriptionState,
)


def _plan_payload(
    plan: Plan,
    *,
    current_plan_version_id: UUID | None,
    checkout_versions: set[UUID],
) -> dict[str, Any]:
    version = plan.current_version
    if version is None:  # Defensive guard for catalog drift between query and serialization.
        raise RuntimeError("Publiczny plan nie ma bieżącej wersji.")
    return {
        "key": plan.key,
        "name": plan.name,
        "description": plan.description,
        "version": version.version,
        "currency": version.currency,
        "billing_interval": version.billing_interval,
        "unit_amount_minor": version.unit_amount_minor,
        "trial_days": version.trial_days,
        "features": version.feature_keys,
        "quotas": version.quotas,
        "is_current": version.id == current_plan_version_id,
        "checkout_available": version.id in checkout_versions,
    }


def customer_billing_overview() -> dict[str, Any]:
    """Return customer-facing billing state from local, tenant-scoped data."""

    context = authorize(BILLING_MANAGE)
    public_plans = {
        plan.key: plan
        for plan in Plan.objects.filter(
            key__in=settings.BILLING_PLAN_KEYS,
            is_active=True,
            is_public=True,
            current_version__isnull=False,
        ).select_related("current_version")
    }
    plans = [
        public_plans[plan_key]
        for plan_key in settings.BILLING_PLAN_KEYS
        if plan_key in public_plans
    ]
    current_version_ids = [plan.current_version_id for plan in plans]
    checkout_versions: set[UUID] = set(
        StripePriceMapping.objects.filter(
            plan_version_id__in=current_version_ids,
            is_active=True,
            livemode=settings.STRIPE_LIVEMODE,
        ).values_list("plan_version_id", flat=True)
    )
    snapshot = (
        EntitlementSnapshot.all_objects.select_related("plan_version__plan")
        .filter(organization_id=context.organization_id)
        .first()
    )
    subscription = (
        BillingSubscription.all_objects.select_related("price_mapping__plan_version__plan")
        .filter(organization_id=context.organization_id)
        .exclude(state=SubscriptionState.CANCELED)
        .first()
    )
    profile = BillingProfile.objects.filter(organization_id=context.organization_id).first()
    current_plan_version_id = (
        subscription.price_mapping.plan_version_id
        if subscription is not None
        else snapshot.plan_version_id
        if snapshot is not None
        else None
    )

    return {
        "can_manage": context.role_key == "owner",
        "payment_mode": settings.BILLING_PROVIDER,
        # Whether a subscription is live, which is not the same question as
        # whether there is anything to show. The payload below falls back to the
        # entitlement snapshot so a canceled plan still has a name and a state —
        # and the panel used to read its mere presence as "already subscribed",
        # which left an organization whose trial had ended with every plan
        # button disabled and no way to buy anything. This flag answers the
        # question create_setup_checkout actually asks.
        "has_active_subscription": subscription is not None,
        "portal_available": (
            settings.BILLING_PROVIDER == "stripe"
            and bool(profile and profile.external_customer_id)
        ),
        "subscription": _subscription_payload(subscription, snapshot),
        "plans": [
            _plan_payload(
                plan,
                current_plan_version_id=current_plan_version_id,
                checkout_versions=checkout_versions,
            )
            for plan in plans
        ],
    }


def _subscription_payload(
    subscription: BillingSubscription | None,
    snapshot: EntitlementSnapshot | None,
) -> dict[str, Any] | None:
    if subscription is None and snapshot is None:
        return None
    state = (
        subscription.state
        if subscription is not None
        else snapshot.subscription_state
        if snapshot is not None
        else SubscriptionState.UNCONFIGURED
    )
    plan_version = (
        subscription.price_mapping.plan_version
        if subscription is not None
        else snapshot.plan_version
        if snapshot is not None
        else None
    )
    return {
        "state": state,
        "access_mode": snapshot.access_mode if snapshot is not None else None,
        "plan_key": plan_version.plan.key if plan_version is not None else None,
        "plan_version": plan_version.version if plan_version is not None else None,
        "current_period_end": (
            subscription.current_period_end if subscription is not None else None
        ),
        "trial_end": subscription.trial_end if subscription is not None else None,
        "grace_period_end": (subscription.grace_period_end if subscription is not None else None),
        "cancel_at_period_end": (
            subscription.cancel_at_period_end if subscription is not None else False
        ),
    }
