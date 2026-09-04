from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.test import override_settings

from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing import reconciliation
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingLifecycleAction,
    BillingReconciliation,
    BillingSubscription,
    EntitlementSnapshot,
    PlanVersion,
    ReconciliationStatus,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.provider import (
    BillingProviderError,
    ProviderSubscriptionSnapshot,
    StripeBillingProvider,
)
from saas_core.modules.shared.billing.reconciliation import run_reconciliation_batch

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def local_subscription(*, slug: str, plan_key: str = "starter") -> BillingSubscription:
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=organization,
        external_customer_id=f"cus_{slug}",
    )
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key=plan_key, version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"price_{slug}",
        livemode=False,
    )
    return BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{slug}",
        state=SubscriptionState.ACTIVE,
        provider_status=StripeSubscriptionStatus.ACTIVE,
        current_period_start=NOW,
        current_period_end=NOW + timedelta(days=30),
    )


def remote_snapshot(
    item: BillingSubscription,
    *,
    status: str = StripeSubscriptionStatus.ACTIVE,
) -> ProviderSubscriptionSnapshot:
    return ProviderSubscriptionSnapshot(
        id=item.stripe_subscription_id,
        customer_id=BillingProfile.objects.get(organization=item.organization).external_customer_id,
        price_id=item.price_mapping.stripe_price_id,
        status=status,
        livemode=False,
        current_period_start=item.current_period_start,
        current_period_end=item.current_period_end,
        trial_start=None,
        trial_end=None,
        cancel_at_period_end=False,
        canceled_at=None,
        ended_at=None,
    )


class FakeProvider:
    def __init__(self, snapshot: ProviderSubscriptionSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    def retrieve_subscription(self, subscription_id: str) -> ProviderSubscriptionSnapshot:
        self.calls.append(subscription_id)
        return self.snapshot


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_RECONCILIATION_INTERVAL_SECONDS=3600,
    BILLING_RECONCILIATION_BATCH_SIZE=100,
)
def test_reconciliation_without_drift_does_not_mutate_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = local_subscription(slug="reconcile-no-change")
    provider = FakeProvider(remote_snapshot(item))
    monkeypatch.setattr(reconciliation, "get_billing_provider", lambda: provider)

    assert run_reconciliation_batch(at=NOW) == 1

    item.refresh_from_db()
    result = BillingReconciliation.all_objects.get(subscription=item)
    assert result.status == ReconciliationStatus.NO_CHANGE
    assert result.attempt_count == 1
    assert result.changes == {}
    assert item.version == 1
    assert provider.calls == [item.stripe_subscription_id]


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_RECONCILIATION_INTERVAL_SECONDS=3600,
    BILLING_RECONCILIATION_BATCH_SIZE=100,
)
def test_reconciliation_repairs_missing_past_due_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = local_subscription(slug="reconcile-repair")
    provider = FakeProvider(remote_snapshot(item, status=StripeSubscriptionStatus.PAST_DUE))
    monkeypatch.setattr(reconciliation, "get_billing_provider", lambda: provider)

    assert run_reconciliation_batch(at=NOW) == 1

    item.refresh_from_db()
    result = BillingReconciliation.all_objects.get(subscription=item)
    snapshot = EntitlementSnapshot.all_objects.get(organization=item.organization)
    assert result.status == ReconciliationStatus.SUCCEEDED
    assert result.changes["state"]["to"] == SubscriptionState.GRACE_PERIOD
    assert item.state == SubscriptionState.GRACE_PERIOD
    assert item.grace_period_end == NOW + timedelta(days=7)
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.effective_until == item.grace_period_end
    assert BillingLifecycleAction.all_objects.filter(subscription=item).count() == 2
    assert OrganizationAuditEntry.objects.filter(
        organization=item.organization,
        action=OrganizationAuditAction.BILLING_RECONCILED,
    ).exists()


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_RECONCILIATION_INTERVAL_SECONDS=3600,
    BILLING_RECONCILIATION_BATCH_SIZE=100,
)
def test_concurrent_local_change_yields_conflict_instead_of_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = local_subscription(slug="reconcile-conflict")
    snapshot = remote_snapshot(item, status=StripeSubscriptionStatus.PAST_DUE)

    class ConcurrentProvider:
        def retrieve_subscription(self, _subscription_id: str) -> ProviderSubscriptionSnapshot:
            BillingSubscription.all_objects.filter(pk=item.pk).update(version=2)
            return snapshot

    monkeypatch.setattr(
        reconciliation,
        "get_billing_provider",
        lambda: ConcurrentProvider(),
    )

    assert run_reconciliation_batch(at=NOW) == 1

    item.refresh_from_db()
    result = BillingReconciliation.all_objects.get(subscription=item)
    assert result.status == ReconciliationStatus.CONFLICT
    assert result.changes == {"baseline_version": 1, "current_version": 2}
    assert item.state == SubscriptionState.ACTIVE


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_RECONCILIATION_INTERVAL_SECONDS=3600,
    BILLING_RECONCILIATION_BATCH_SIZE=100,
    BILLING_RECONCILIATION_MAX_ATTEMPTS=2,
)
def test_provider_failure_retries_then_persists_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = local_subscription(slug="reconcile-failure")

    class FailingProvider:
        def retrieve_subscription(self, _subscription_id: str) -> ProviderSubscriptionSnapshot:
            raise BillingProviderError("temporary reconciliation failure")

    monkeypatch.setattr(
        reconciliation,
        "get_billing_provider",
        lambda: FailingProvider(),
    )

    assert run_reconciliation_batch(at=NOW) == 0
    assert run_reconciliation_batch(at=NOW + timedelta(minutes=5)) == 0

    result = BillingReconciliation.all_objects.get(subscription=item)
    assert result.status == ReconciliationStatus.FAILED
    assert result.attempt_count == 2
    assert result.last_error == "temporary reconciliation failure"
    assert result.completed_at == NOW + timedelta(minutes=5)


@override_settings(STRIPE_SECRET_KEY="sk_test_local", STRIPE_API_VERSION="2026-07-29.dahlia")
def test_stripe_adapter_normalizes_retrieved_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieved: list[str] = []

    class Subscriptions:
        def retrieve(self, subscription_id: str) -> object:
            retrieved.append(subscription_id)
            return SimpleNamespace(
                id=subscription_id,
                customer="cus_adapter",
                status="active",
                livemode=False,
                items=SimpleNamespace(
                    data=[
                        SimpleNamespace(
                            price=SimpleNamespace(id="price_adapter"),
                            current_period_start=1_786_435_200,
                            current_period_end=1_789_027_200,
                        )
                    ]
                ),
                trial_start=None,
                trial_end=None,
                cancel_at_period_end=False,
                canceled_at=None,
                ended_at=None,
            )

    fake_client = SimpleNamespace(v1=SimpleNamespace(subscriptions=Subscriptions()))
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.provider.stripe.StripeClient",
        lambda *args, **kwargs: fake_client,
    )

    snapshot = StripeBillingProvider().retrieve_subscription("sub_adapter")

    assert retrieved == ["sub_adapter"]
    assert snapshot.customer_id == "cus_adapter"
    assert snapshot.price_id == "price_adapter"
    assert snapshot.status == StripeSubscriptionStatus.ACTIVE
    assert snapshot.current_period_end is not None


@override_settings(
    BILLING_PROVIDER="stripe",
    STRIPE_LIVEMODE=False,
    BILLING_RECONCILIATION_INTERVAL_SECONDS=3600,
    BILLING_RECONCILIATION_BATCH_SIZE=100,
)
def test_a_subscription_from_another_provider_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching a deployment to Stripe must not make it interrogate Stripe
    about subscriptions the simulator started. It cannot know them, so every
    pass filed another failure and the queue never emptied.
    """
    # Different plans, because only one price per plan version may be active.
    simulated = local_subscription(slug="reconcile-simulated", plan_key="pro")
    simulated.price_mapping.provider = "simulated"
    simulated.price_mapping.save(update_fields=["provider", "updated_at"])
    stripe_one = local_subscription(slug="reconcile-stripe")
    provider = FakeProvider(remote_snapshot(stripe_one))
    monkeypatch.setattr(reconciliation, "get_billing_provider", lambda: provider)

    handled = run_reconciliation_batch(at=NOW)

    assert handled == 1
    assert provider.calls == [stripe_one.stripe_subscription_id]
    assert not BillingReconciliation.all_objects.filter(
        subscription_id=simulated.id
    ).exists()
