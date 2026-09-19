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
from .plan_offer import plan_keys_for_organization, plan_keys_for_type
from .services import missing_billing_details, reusable_customer_id


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


def _public_plans(plan_keys: tuple[str, ...]) -> list[Plan]:
    """The given plans a customer may buy, in the profile's order."""
    by_key = {
        plan.key: plan
        for plan in Plan.objects.filter(
            key__in=plan_keys,
            is_active=True,
            is_public=True,
            current_version__isnull=False,
        ).select_related("current_version")
    }
    return [by_key[key] for key in plan_keys if key in by_key]


def public_plan_catalog(organization_type: str | None = None) -> list[dict[str, Any]]:
    """What a visitor sees on the pricing page before signing in.

    The catalogue only — price, interval, trial and what the plan includes.
    Nothing here belongs to an organization, so there is no tenant to set and
    no permission to ask for; the plan tables carry no organization at all.
    The product site reads its prices from here rather than from its own copy,
    so a price published in billing cannot disagree with the one advertised.
    """
    catalog: list[dict[str, Any]] = []
    # Without a type the visitor sees the default one: the product's main
    # customer, the one its pricing page is about.
    for plan in _public_plans(
        plan_keys_for_type(organization_type or settings.DEFAULT_ORGANIZATION_TYPE)
    ):
        version = plan.current_version
        if version is None:  # Same guard as the overview: catalogue drift.
            continue
        catalog.append({
            "key": plan.key,
            "name": plan.name,
            "description": plan.description,
            "currency": version.currency,
            "billing_interval": version.billing_interval,
            "unit_amount_minor": version.unit_amount_minor,
            "trial_days": version.trial_days,
            "features": version.feature_keys,
            "quotas": version.quotas,
        })
    return catalog


def customer_billing_overview() -> dict[str, Any]:
    """Return customer-facing billing state from local, tenant-scoped data."""

    context = authorize(BILLING_MANAGE)
    plans = _public_plans(plan_keys_for_organization(context.organization_id))
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
        # The invoice details travel with the overview because the panel needs
        # them on the same screen as the plans: without an address Stripe Tax
        # cannot price anything, so the form is part of buying, not a setting
        # tucked away somewhere else.
        "billing_details": _billing_details_payload(profile),
        # A customer id from the simulator, or from test mode in a live
        # deployment, would send the customer to a portal Stripe cannot open.
        "portal_available": (
            settings.BILLING_PROVIDER == "stripe"
            and bool(profile and reusable_customer_id(profile))
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


def _billing_details_payload(profile: BillingProfile | None) -> dict[str, Any]:
    # An organization with no profile yet is shown the model's own defaults, and
    # what is missing is read off the same object — so the form cannot say
    # "country: PL" while the list underneath calls the country missing.
    shown = profile if profile is not None else BillingProfile()
    return {
        "customer_kind": shown.customer_kind,
        "legal_name": shown.legal_name,
        "tax_id": shown.tax_id,
        "country_code": shown.country_code,
        "address_line1": shown.address_line1,
        "postal_code": shown.postal_code,
        "city": shown.city,
        "billing_email": shown.billing_email,
        "missing": missing_billing_details(shown),
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
