from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.shared.billing.lifecycle import process_due_lifecycle_actions
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingCheckout,
    BillingLifecycleAction,
    BillingSubscription,
    CheckoutStatus,
    EntitlementSnapshot,
    LifecycleActionStatus,
    LifecycleActionType,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)
from saas_core.modules.shared.billing.processor import (
    StripeEventProcessingError,
    process_stripe_event,
)

pytestmark = pytest.mark.django_db


def organization(*, slug: str, customer_id: str = "") -> Organization:
    tenant = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(
        organization=tenant,
        external_customer_id=customer_id,
    )
    return tenant


def price_mapping(*, price_id: str = "price_starter") -> StripePriceMapping:
    return StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id="prod_starter",
        stripe_price_id=price_id,
        livemode=False,
    )


def inbox_event(
    *,
    event_id: str,
    event_type: str,
    created: int,
    data_object: dict[str, Any],
) -> StripeWebhookEvent:
    return StripeWebhookEvent.objects.create(
        stripe_event_id=event_id,
        event_type=event_type,
        api_version="2026-07-29.dahlia",
        livemode=False,
        provider_created_at=datetime.fromtimestamp(created, tz=UTC),
        payload={
            "id": event_id,
            "object": "event",
            "api_version": "2026-07-29.dahlia",
            "created": created,
            "data": {"object": data_object},
            "livemode": False,
            "type": event_type,
        },
        signature_verified_at=datetime.fromtimestamp(created, tz=UTC),
    )


def subscription_object(
    *,
    status: str,
    price_id: str = "price_starter",
    subscription_id: str = "sub_local",
    customer_id: str = "cus_local",
    period_start: int = 1_786_000_000,
    period_end: int = 1_788_592_000,
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "object": "subscription",
        "customer": customer_id,
        "status": status,
        "items": {
            "data": [
                {
                    "id": "si_local",
                    "price": {"id": price_id, "object": "price"},
                    "current_period_start": period_start,
                    "current_period_end": period_end,
                }
            ]
        },
        "trial_start": period_start if status == StripeSubscriptionStatus.TRIALING else None,
        "trial_end": period_end if status == StripeSubscriptionStatus.TRIALING else None,
        "cancel_at_period_end": False,
        "canceled_at": None,
        "ended_at": None,
    }


def test_checkout_links_verified_customer_to_metadata_organization() -> None:
    tenant = organization(slug="checkout-link", customer_id="cus_checkout")
    mapping = price_mapping()
    checkout = BillingCheckout.all_objects.create(
        organization=tenant,
        price_mapping=mapping,
        stripe_checkout_session_id="cs_local",
        idempotency_key="checkout-link",
        checkout_url="https://checkout.stripe.test/cs_local",
    )
    event = inbox_event(
        event_id="evt_checkout_link",
        event_type="checkout.session.completed",
        created=1_786_000_000,
        data_object={
            "id": "cs_local",
            "object": "checkout.session",
            "customer": "cus_checkout",
            "setup_intent": "seti_local",
            "metadata": {
                "saas_core_organization_id": str(tenant.id),
                "saas_core_plan_version_id": str(mapping.plan_version_id),
                "saas_core_price_mapping_id": str(mapping.id),
            },
        },
    )

    processed = process_stripe_event(event.id)

    assert processed is not None
    assert processed.status == WebhookProcessingStatus.PROCESSED
    assert processed.organization_id == tenant.id
    checkout.refresh_from_db()
    assert checkout.status == CheckoutStatus.COMPLETE
    assert checkout.setup_intent_id == "seti_local"
    assert BillingProfile.objects.get(organization=tenant).external_customer_id == "cus_checkout"


def test_subscription_event_builds_local_subscription_and_snapshot() -> None:
    tenant = organization(slug="subscription-trial", customer_id="cus_local")
    mapping = price_mapping()
    event = inbox_event(
        event_id="evt_subscription_trial",
        event_type="customer.subscription.created",
        created=1_786_000_100,
        data_object=subscription_object(status=StripeSubscriptionStatus.TRIALING),
    )

    processed = process_stripe_event(event.id)

    subscription = BillingSubscription.all_objects.get(organization=tenant)
    snapshot = EntitlementSnapshot.all_objects.get(organization=tenant)
    assert processed is not None
    assert processed.status == WebhookProcessingStatus.PROCESSED
    assert processed.subscription_id == subscription.id
    assert subscription.price_mapping == mapping
    assert subscription.state == SubscriptionState.TRIALING
    assert subscription.provider_status == StripeSubscriptionStatus.TRIALING
    assert snapshot.plan_version == mapping.plan_version
    assert snapshot.subscription_state == SubscriptionState.TRIALING
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.features["booking.enabled"] is True
    assert snapshot.quotas["appointments.monthly"] == 1_000


def test_older_subscription_event_does_not_regress_local_state() -> None:
    tenant = organization(slug="subscription-order", customer_id="cus_local")
    price_mapping()
    newer = inbox_event(
        event_id="evt_subscription_newer",
        event_type="customer.subscription.updated",
        created=1_786_000_200,
        data_object=subscription_object(status=StripeSubscriptionStatus.ACTIVE),
    )
    older = inbox_event(
        event_id="evt_subscription_older",
        event_type="customer.subscription.created",
        created=1_786_000_100,
        data_object=subscription_object(status=StripeSubscriptionStatus.TRIALING),
    )

    process_stripe_event(newer.id)
    stale = process_stripe_event(older.id)

    subscription = BillingSubscription.all_objects.get(organization=tenant)
    assert stale is not None
    assert stale.status == WebhookProcessingStatus.IGNORED
    assert "Starszy event" in stale.processing_error
    assert subscription.state == SubscriptionState.ACTIVE
    assert subscription.last_event_id == "evt_subscription_newer"


def test_payment_failure_starts_grace_and_later_paid_event_restores_access() -> None:
    tenant = organization(slug="invoice-lifecycle", customer_id="cus_local")
    price_mapping()
    created = inbox_event(
        event_id="evt_subscription_active",
        event_type="customer.subscription.created",
        created=1_786_000_100,
        data_object=subscription_object(status=StripeSubscriptionStatus.ACTIVE),
    )
    process_stripe_event(created.id)
    failed = inbox_event(
        event_id="evt_invoice_failed",
        event_type="invoice.payment_failed",
        created=1_786_000_200,
        data_object={
            "id": "in_failed",
            "object": "invoice",
            "customer": "cus_local",
            "subscription": "sub_local",
        },
    )

    process_stripe_event(failed.id)

    subscription = BillingSubscription.all_objects.get(organization=tenant)
    snapshot = EntitlementSnapshot.all_objects.get(organization=tenant)
    assert subscription.state == SubscriptionState.GRACE_PERIOD
    assert subscription.grace_period_end == failed.provider_created_at + timedelta(days=7)
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.effective_until == failed.provider_created_at + timedelta(days=7)
    assert BillingLifecycleAction.all_objects.filter(
        subscription=subscription,
        action_type=LifecycleActionType.GRACE_EXPIRED,
        status=LifecycleActionStatus.PENDING,
    ).exists()

    paid = inbox_event(
        event_id="evt_invoice_paid",
        event_type="invoice.paid",
        created=1_786_000_300,
        data_object={
            "id": "in_paid",
            "object": "invoice",
            "customer": "cus_local",
            "parent": {"subscription_details": {"subscription": "sub_local"}},
        },
    )
    process_stripe_event(paid.id)

    subscription.refresh_from_db()
    snapshot.refresh_from_db()
    assert subscription.state == SubscriptionState.ACTIVE
    assert subscription.grace_period_end is None
    assert snapshot.subscription_state == SubscriptionState.ACTIVE
    assert snapshot.access_mode == AccessMode.FULL
    assert not BillingLifecycleAction.all_objects.filter(
        subscription=subscription,
        status=LifecycleActionStatus.PENDING,
    ).exists()


def test_canceled_webhook_keeps_full_access_until_provider_period_end() -> None:
    tenant = organization(slug="subscription-canceled", customer_id="cus_local")
    price_mapping()
    event = inbox_event(
        event_id="evt_subscription_canceled",
        event_type="customer.subscription.deleted",
        created=1_786_000_100,
        data_object=subscription_object(status=StripeSubscriptionStatus.CANCELED),
    )

    process_stripe_event(event.id)

    subscription = BillingSubscription.all_objects.get(organization=tenant)
    snapshot = EntitlementSnapshot.all_objects.get(organization=tenant)
    assert subscription.state == SubscriptionState.CANCELED
    assert snapshot.access_mode == AccessMode.FULL
    assert snapshot.effective_until == subscription.current_period_end
    action = BillingLifecycleAction.all_objects.get(
        subscription=subscription,
        action_type=LifecycleActionType.CANCELED_PERIOD_ENDED,
    )

    assert process_due_lifecycle_actions(at=action.due_at) == 1
    snapshot.refresh_from_db()
    assert snapshot.access_mode == AccessMode.READ_ONLY
    assert snapshot.effective_until is None


def test_late_payment_failure_does_not_reopen_expired_grace_period() -> None:
    tenant = organization(slug="grace-no-reopen", customer_id="cus_local")
    price_mapping()
    created = inbox_event(
        event_id="evt_grace_active",
        event_type="customer.subscription.created",
        created=1_786_000_100,
        data_object=subscription_object(status=StripeSubscriptionStatus.ACTIVE),
    )
    process_stripe_event(created.id)
    failed = inbox_event(
        event_id="evt_grace_failed",
        event_type="invoice.payment_failed",
        created=1_786_000_200,
        data_object={
            "id": "in_grace_failed",
            "object": "invoice",
            "customer": "cus_local",
            "subscription": "sub_local",
        },
    )
    process_stripe_event(failed.id)
    subscription = BillingSubscription.all_objects.get(organization=tenant)
    grace_end = subscription.grace_period_end
    assert grace_end is not None
    assert process_due_lifecycle_actions(at=grace_end) == 2

    repeated = inbox_event(
        event_id="evt_grace_failed_late",
        event_type="invoice.payment_failed",
        created=int((grace_end + timedelta(hours=1)).timestamp()),
        data_object={
            "id": "in_grace_failed_late",
            "object": "invoice",
            "customer": "cus_local",
            "subscription": "sub_local",
        },
    )
    process_stripe_event(repeated.id)

    subscription.refresh_from_db()
    snapshot = EntitlementSnapshot.all_objects.get(organization=tenant)
    assert subscription.state == SubscriptionState.READ_ONLY
    assert subscription.grace_period_end == grace_end
    assert snapshot.access_mode == AccessMode.READ_ONLY
    assert snapshot.effective_until is None


def test_unknown_price_is_a_persistent_retryable_failure() -> None:
    organization(slug="unknown-price", customer_id="cus_local")
    event = inbox_event(
        event_id="evt_unknown_price",
        event_type="customer.subscription.created",
        created=1_786_000_100,
        data_object=subscription_object(
            status=StripeSubscriptionStatus.ACTIVE,
            price_id="price_unknown",
        ),
    )

    with pytest.raises(StripeEventProcessingError, match="nieznanego Stripe Price"):
        process_stripe_event(event.id)

    event.refresh_from_db()
    assert event.status == WebhookProcessingStatus.FAILED
    assert event.attempt_count == 1
    assert "nieznanego Stripe Price" in event.processing_error
    assert BillingSubscription.all_objects.count() == 0


def test_unknown_event_is_ignored_once() -> None:
    event = inbox_event(
        event_id="evt_unhandled",
        event_type="product.updated",
        created=1_786_000_100,
        data_object={"id": "prod_local", "object": "product"},
    )

    first = process_stripe_event(event.id)
    second = process_stripe_event(event.id)

    assert first is not None
    assert second is not None
    assert first.status == WebhookProcessingStatus.IGNORED
    assert second.attempt_count == 1
