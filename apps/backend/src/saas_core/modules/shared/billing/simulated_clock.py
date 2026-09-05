"""Time passing, for a deployment that has no payment provider behind it.

In Stripe mode the truth about a subscription lives at the provider, and
reconciliation goes and fetches it every few minutes. The simulator has no
remote to fetch from, so nothing ever moved: a trial started locally stayed
`trialing` for as long as the database lived. That is how the owner's own
organization sat in a trial that had ended ten days earlier — nothing was
broken, time simply did not pass.

This is the simulator's half of the same job. It does nothing outside simulated
mode, exactly as reconciliation does nothing outside Stripe mode, so the two
never fight over the same row.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .lifecycle import sync_subscription_lifecycle
from .models import (
    AccessMode,
    BillingSubscription,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from .snapshots import update_entitlement_snapshot
from .tenant_scope import billing_organization_ids, billing_tenant_scope

#: How long a paid period lasts in the simulator. The real one comes from the
#: provider; here the plan's own interval is the only thing to go on.
_PERIOD_DAYS = {"month": 30, "year": 365}


def _period_end(start: datetime, billing_interval: str) -> datetime:
    return start + timedelta(days=_PERIOD_DAYS.get(billing_interval, 30))


def advance_simulated_billing(*, at: datetime | None = None) -> int:
    """Move simulated subscriptions to where the clock says they should be.

    Two movements, both the ones a provider would report: a trial whose end has
    passed becomes a paid period, and a paid period that has run out rolls into
    the next one. Anything else — a failed payment, a cancellation — has no
    meaning without a provider and is left alone.
    """
    if settings.BILLING_PROVIDER != "simulated":
        return 0
    now = at or timezone.now()
    moved = 0
    for organization_id in billing_organization_ids():
        with billing_tenant_scope(organization_id):
            subscriptions = list(
                BillingSubscription.all_objects.select_for_update()
                .select_related("price_mapping__plan_version", "organization")
                .filter(
                    organization_id=organization_id,
                    state__in=(SubscriptionState.TRIALING, SubscriptionState.ACTIVE),
                )
                .order_by("created_at", "id")
            )
            for subscription in subscriptions:
                if _advance(subscription, now):
                    moved += 1
    return moved


def _advance(subscription: BillingSubscription, now: datetime) -> bool:
    interval = subscription.price_mapping.plan_version.billing_interval
    if (
        subscription.state == SubscriptionState.TRIALING
        and subscription.trial_end is not None
        and subscription.trial_end <= now
    ):
        period_start = subscription.trial_end
    elif (
        subscription.state == SubscriptionState.ACTIVE
        and subscription.current_period_end is not None
        and subscription.current_period_end <= now
    ):
        period_start = subscription.current_period_end
    else:
        return False

    period_end = _period_end(period_start, interval)
    subscription.state = SubscriptionState.ACTIVE
    subscription.provider_status = StripeSubscriptionStatus.ACTIVE
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.version += 1
    subscription.save(
        update_fields=[
            "state",
            "provider_status",
            "current_period_start",
            "current_period_end",
            "version",
            "updated_at",
        ]
    )
    update_entitlement_snapshot(
        subscription.organization,
        subscription.price_mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=period_end,
    )
    sync_subscription_lifecycle(subscription)
    return True
