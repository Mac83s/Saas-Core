from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings

from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing import lifecycle
from saas_core.modules.shared.billing.lifecycle import (
    process_due_lifecycle_actions,
    sync_subscription_lifecycle,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingLifecycleAction,
    BillingNotice,
    BillingNoticeType,
    BillingSubscription,
    EntitlementSnapshot,
    LifecycleActionStatus,
    LifecycleActionType,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.snapshots import update_entitlement_snapshot

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def subscription(
    *,
    slug: str,
    state: str,
    trial_end: datetime | None = None,
    grace_period_end: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> BillingSubscription:
    organization = Organization.objects.create(name=slug, slug=slug)
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"price_{slug}",
        livemode=False,
    )
    trial_start = NOW if trial_end is not None else None
    current_period_start = NOW if current_period_end is not None else None
    return BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{slug}",
        state=state,
        provider_status=(
            StripeSubscriptionStatus.TRIALING
            if state == SubscriptionState.TRIALING
            else StripeSubscriptionStatus.PAST_DUE
            if state == SubscriptionState.GRACE_PERIOD
            else StripeSubscriptionStatus.CANCELED
        ),
        trial_start=trial_start,
        trial_end=trial_end,
        grace_period_end=grace_period_end,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )


@override_settings(BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86400)
def test_trial_warning_is_scheduled_and_emitted_exactly_once() -> None:
    item = subscription(
        slug="trial-warning",
        state=SubscriptionState.TRIALING,
        trial_end=NOW + timedelta(days=3),
    )

    sync_subscription_lifecycle(item)
    sync_subscription_lifecycle(item)

    action = BillingLifecycleAction.all_objects.get(subscription=item)
    assert action.action_type == LifecycleActionType.TRIAL_ENDING_NOTICE
    assert action.due_at == NOW + timedelta(days=2)
    assert process_due_lifecycle_actions(at=action.due_at) == 1
    assert process_due_lifecycle_actions(at=action.due_at) == 0
    notice = BillingNotice.all_objects.get(lifecycle_action=action)
    assert notice.notice_type == BillingNoticeType.TRIAL_ENDING
    assert notice.payload["ends_at"] == (NOW + timedelta(days=3)).isoformat()
    assert BillingNotice.all_objects.count() == 1


@override_settings(BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86400)
def test_expired_grace_period_becomes_read_only_without_deleting_data() -> None:
    grace_end = NOW + timedelta(days=7)
    item = subscription(
        slug="grace-expiry",
        state=SubscriptionState.GRACE_PERIOD,
        grace_period_end=grace_end,
    )
    update_entitlement_snapshot(
        item.organization,
        item.price_mapping,
        state=SubscriptionState.GRACE_PERIOD,
        access_mode=AccessMode.FULL,
        effective_until=grace_end,
    )
    sync_subscription_lifecycle(item)

    assert BillingLifecycleAction.all_objects.filter(subscription=item).count() == 2
    assert process_due_lifecycle_actions(at=grace_end - timedelta(days=1)) == 1
    assert BillingNotice.all_objects.get(subscription=item).notice_type == (
        BillingNoticeType.GRACE_ENDING
    )
    assert process_due_lifecycle_actions(at=grace_end) == 1

    item.refresh_from_db()
    snapshot = EntitlementSnapshot.all_objects.get(organization=item.organization)
    assert item.state == SubscriptionState.READ_ONLY
    assert snapshot.subscription_state == SubscriptionState.READ_ONLY
    assert snapshot.access_mode == AccessMode.READ_ONLY
    assert snapshot.effective_until is None
    assert Organization.objects.filter(pk=item.organization_id).exists()
    assert BillingSubscription.all_objects.filter(pk=item.pk).exists()
    audit = OrganizationAuditEntry.objects.get(
        organization=item.organization,
        action=OrganizationAuditAction.BILLING_ACCESS_READ_ONLY,
    )
    assert audit.actor_user is None
    assert audit.metadata["reason"] == "grace_period_expired"


def test_canceled_subscription_stays_full_until_paid_period_ends() -> None:
    period_end = NOW + timedelta(days=10)
    item = subscription(
        slug="canceled-period",
        state=SubscriptionState.CANCELED,
        current_period_end=period_end,
    )
    update_entitlement_snapshot(
        item.organization,
        item.price_mapping,
        state=SubscriptionState.CANCELED,
        access_mode=AccessMode.FULL,
        effective_until=period_end,
    )
    sync_subscription_lifecycle(item)

    assert process_due_lifecycle_actions(at=period_end - timedelta(seconds=1)) == 0
    before = EntitlementSnapshot.all_objects.get(organization=item.organization)
    assert before.access_mode == AccessMode.FULL
    assert process_due_lifecycle_actions(at=period_end) == 1

    item.refresh_from_db()
    after = EntitlementSnapshot.all_objects.get(organization=item.organization)
    assert item.state == SubscriptionState.CANCELED
    assert after.access_mode == AccessMode.READ_ONLY
    assert after.effective_until is None
    assert OrganizationAuditEntry.objects.filter(
        organization=item.organization,
        action=OrganizationAuditAction.BILLING_ACCESS_READ_ONLY,
        metadata__reason="canceled_period_ended",
    ).exists()


@override_settings(
    BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86400,
    BILLING_LIFECYCLE_MAX_ATTEMPTS=2,
)
def test_lifecycle_action_retries_then_becomes_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = subscription(
        slug="lifecycle-retry",
        state=SubscriptionState.TRIALING,
        trial_end=NOW + timedelta(days=3),
    )
    sync_subscription_lifecycle(item)
    action = BillingLifecycleAction.all_objects.get(subscription=item)

    def fail_dispatch(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("temporary lifecycle failure")

    monkeypatch.setattr(lifecycle, "_dispatch_lifecycle_action", fail_dispatch)

    assert process_due_lifecycle_actions(at=action.due_at) == 0
    action.refresh_from_db()
    assert action.status == LifecycleActionStatus.PENDING
    assert action.attempt_count == 1
    assert process_due_lifecycle_actions(at=action.due_at) == 0
    action.refresh_from_db()
    assert action.status == LifecycleActionStatus.FAILED
    assert action.attempt_count == 2
    assert action.last_error == "temporary lifecycle failure"
