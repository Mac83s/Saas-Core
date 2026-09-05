"""Time passes in the simulator, or the local product is frozen forever.

The owner's own organization sat in a trial that had ended ten days earlier.
Nothing was broken: the simulator has no remote state, so nothing ever told the
product that the trial was over — and the panel then refused a new purchase
because a subscription still looked live. This is the clock that was missing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings

from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingSubscription,
    EntitlementSnapshot,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.simulated_clock import advance_simulated_billing

pytestmark = pytest.mark.django_db

STARTED = datetime(2026, 8, 11, 12, tzinfo=UTC)


def simulated_subscription(
    *,
    slug: str,
    state: str,
    trial_end: datetime | None = None,
    period_end: datetime | None = None,
) -> BillingSubscription:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(organization=organization, external_customer_id=f"sim_{slug}")
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"sim_price_{slug}",
        provider="simulated",
        livemode=False,
    )
    return BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sim_subscription_{slug}",
        state=state,
        provider_status=(
            StripeSubscriptionStatus.TRIALING
            if state == SubscriptionState.TRIALING
            else StripeSubscriptionStatus.ACTIVE
        ),
        trial_start=STARTED if trial_end else None,
        trial_end=trial_end,
        current_period_start=STARTED,
        current_period_end=period_end or trial_end,
    )


@override_settings(BILLING_PROVIDER="simulated")
def test_a_trial_whose_day_has_come_becomes_a_paid_period() -> None:
    trial_end = STARTED + timedelta(days=3)
    subscription = simulated_subscription(
        slug="clock-trial", state=SubscriptionState.TRIALING, trial_end=trial_end
    )

    moved = advance_simulated_billing(at=trial_end + timedelta(minutes=1))

    assert moved == 1
    subscription.refresh_from_db()
    assert subscription.state == SubscriptionState.ACTIVE
    assert subscription.current_period_start == trial_end
    assert subscription.current_period_end == trial_end + timedelta(days=30)
    snapshot = EntitlementSnapshot.all_objects.get(organization=subscription.organization)
    assert snapshot.subscription_state == SubscriptionState.ACTIVE
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.effective_until == subscription.current_period_end


@override_settings(BILLING_PROVIDER="simulated")
def test_a_trial_still_running_is_left_where_it_is() -> None:
    trial_end = STARTED + timedelta(days=3)
    subscription = simulated_subscription(
        slug="clock-early", state=SubscriptionState.TRIALING, trial_end=trial_end
    )

    assert advance_simulated_billing(at=trial_end - timedelta(hours=1)) == 0
    subscription.refresh_from_db()
    assert subscription.state == SubscriptionState.TRIALING


@override_settings(BILLING_PROVIDER="simulated")
def test_a_finished_period_rolls_into_the_next_one() -> None:
    period_end = STARTED + timedelta(days=30)
    subscription = simulated_subscription(
        slug="clock-period", state=SubscriptionState.ACTIVE, period_end=period_end
    )

    assert advance_simulated_billing(at=period_end + timedelta(minutes=1)) == 1
    subscription.refresh_from_db()
    assert subscription.current_period_start == period_end
    assert subscription.current_period_end == period_end + timedelta(days=30)


@override_settings(BILLING_PROVIDER="stripe")
def test_the_clock_does_not_touch_a_deployment_that_has_a_real_provider() -> None:
    """Stripe owns its own truth; reconciliation is what asks for it."""
    trial_end = STARTED + timedelta(days=3)
    subscription = simulated_subscription(
        slug="clock-stripe", state=SubscriptionState.TRIALING, trial_end=trial_end
    )

    assert advance_simulated_billing(at=trial_end + timedelta(days=5)) == 0
    subscription.refresh_from_db()
    assert subscription.state == SubscriptionState.TRIALING
