from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.models import BillingProfile

from .lifecycle import sync_subscription_lifecycle
from .models import (
    AccessMode,
    BillingCheckout,
    BillingSubscription,
    CheckoutStatus,
    StripePriceMapping,
    StripeSubscriptionStatus,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)
from .snapshots import update_entitlement_snapshot

SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}
INVOICE_EVENTS = {"invoice.paid", "invoice.payment_failed"}
EVENT_PRIORITY = {
    "checkout.session.completed": 10,
    "customer.subscription.created": 20,
    "customer.subscription.updated": 30,
    "invoice.payment_failed": 40,
    "invoice.paid": 50,
    "customer.subscription.deleted": 60,
}


class StripeEventProcessingError(RuntimeError):
    pass


def process_stripe_event(event_id: UUID | str) -> StripeWebhookEvent | None:
    with transaction.atomic():
        event = StripeWebhookEvent.objects.select_for_update().filter(pk=event_id).first()
        if event is None:
            return None
        if event.status in {
            WebhookProcessingStatus.PROCESSED,
            WebhookProcessingStatus.IGNORED,
        }:
            return event
        event.status = WebhookProcessingStatus.PROCESSING
        event.attempt_count += 1
        event.processing_error = ""
        event.save(update_fields=["status", "attempt_count", "processing_error", "updated_at"])

    try:
        with transaction.atomic():
            event = StripeWebhookEvent.objects.select_for_update().get(pk=event_id)
            _dispatch(event)
            if event.status == WebhookProcessingStatus.PROCESSING:
                event.status = WebhookProcessingStatus.PROCESSED
                event.processing_error = ""
            event.processed_at = timezone.now()
            event.save(
                update_fields=[
                    "status",
                    "organization",
                    "subscription",
                    "processed_at",
                    "processing_error",
                    "updated_at",
                ]
            )
            return event
    except Exception as error:
        with transaction.atomic():
            StripeWebhookEvent.objects.filter(pk=event_id).update(
                status=WebhookProcessingStatus.FAILED,
                processing_error=str(error)[:2000],
                processed_at=None,
                updated_at=timezone.now(),
            )
        if isinstance(error, StripeEventProcessingError):
            raise
        raise StripeEventProcessingError("Nie udało się przetworzyć eventu Stripe.") from error


def _dispatch(event: StripeWebhookEvent) -> None:
    if event.event_type == "checkout.session.completed":
        _handle_checkout(event)
        return
    if event.event_type in SUBSCRIPTION_EVENTS:
        _handle_subscription(event)
        return
    if event.event_type in INVOICE_EVENTS:
        _handle_invoice(event)
        return
    event.status = WebhookProcessingStatus.IGNORED
    event.processing_error = "Nieobsługiwany typ eventu Stripe."


def _handle_checkout(event: StripeWebhookEvent) -> None:
    data = _data_object(event)
    checkout_id = _required_string(data, "id")
    customer_id = _stripe_id(data.get("customer"), "customer")
    checkout = (
        BillingCheckout.all_objects.select_for_update()
        .select_related("price_mapping")
        .filter(stripe_checkout_session_id=checkout_id)
        .first()
    )
    if checkout is None:
        raise StripeEventProcessingError("Checkout Stripe nie ma lokalnego intentu.")
    profile = BillingProfile.objects.select_for_update().get(
        organization_id=checkout.organization_id
    )
    if profile.external_customer_id != customer_id:
        raise StripeEventProcessingError("Checkout wskazuje innego Stripe Customer.")
    metadata = data.get("metadata")
    expected_metadata = {
        "saas_core_organization_id": str(checkout.organization_id),
        "saas_core_plan_version_id": str(checkout.price_mapping.plan_version_id),
        "saas_core_price_mapping_id": str(checkout.price_mapping_id),
    }
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value for key, value in expected_metadata.items()
    ):
        raise StripeEventProcessingError("Checkout ma niespójne lokalne metadane.")
    checkout.status = CheckoutStatus.COMPLETE
    checkout.setup_intent_id = _stripe_id(data.get("setup_intent"), "setup_intent")
    checkout.completed_at = event.provider_created_at
    checkout.save(update_fields=["status", "setup_intent_id", "completed_at", "updated_at"])
    event.organization_id = profile.organization_id


def _handle_subscription(event: StripeWebhookEvent) -> None:
    data = _data_object(event)
    customer_id = _stripe_id(data.get("customer"), "customer")
    subscription_id = _required_string(data, "id")
    provider_status = _required_string(data, "status")
    if provider_status not in StripeSubscriptionStatus.values:
        raise StripeEventProcessingError(f"Nieobsługiwany status Stripe: {provider_status}.")

    profile = (
        BillingProfile.objects.select_related("organization")
        .filter(external_customer_id=customer_id)
        .first()
    )
    if profile is None:
        raise StripeEventProcessingError("Subskrypcja dotyczy nieznanego Stripe Customer.")
    price_id, item = _subscription_price(data)
    mapping = (
        StripePriceMapping.objects.select_related("plan_version__plan")
        .filter(stripe_price_id=price_id, livemode=event.livemode)
        .first()
    )
    if mapping is None:
        raise StripeEventProcessingError("Subskrypcja używa nieznanego Stripe Price.")

    subscription = (
        BillingSubscription.all_objects.select_for_update()
        .filter(stripe_subscription_id=subscription_id)
        .first()
    )
    if subscription is not None and subscription.organization_id != profile.organization_id:
        raise StripeEventProcessingError("Subskrypcja Stripe jest przypisana do innej organizacji.")
    if subscription is not None and _is_stale(event, subscription):
        _mark_stale(event, subscription)
        return

    internal_state, access_mode = subscription_access(provider_status)
    period_start, period_end = _timestamp_pair(
        data, item, "current_period_start", "current_period_end"
    )
    trial_start, trial_end = _timestamp_pair(data, {}, "trial_start", "trial_end")
    grace_period_end = None
    if provider_status == StripeSubscriptionStatus.PAST_DUE:
        grace_period_end = (
            subscription.grace_period_end
            if subscription is not None and subscription.grace_period_end is not None
            else event.provider_created_at + timedelta(days=mapping.plan_version.grace_period_days)
        )
        if subscription is not None and subscription.state == SubscriptionState.READ_ONLY:
            internal_state = SubscriptionState.READ_ONLY
            access_mode = AccessMode.READ_ONLY
            effective_until = None
        else:
            effective_until = grace_period_end
    elif provider_status == StripeSubscriptionStatus.CANCELED:
        if period_end is not None and period_end > event.provider_created_at:
            access_mode = AccessMode.FULL
            effective_until = period_end
        else:
            effective_until = None
    elif internal_state == SubscriptionState.TRIALING:
        effective_until = trial_end
    elif access_mode == AccessMode.READ_ONLY:
        effective_until = None
    else:
        effective_until = period_end
    defaults = {
        "organization_id": profile.organization_id,
        "price_mapping": mapping,
        "state": internal_state,
        "provider_status": provider_status,
        "current_period_start": period_start,
        "current_period_end": period_end,
        "trial_start": trial_start,
        "trial_end": trial_end,
        "grace_period_end": grace_period_end,
        "cancel_at_period_end": data.get("cancel_at_period_end") is True,
        "canceled_at": _optional_timestamp(data.get("canceled_at")),
        "ended_at": _optional_timestamp(data.get("ended_at")),
        "last_event_created_at": event.provider_created_at,
        "last_event_id": event.stripe_event_id,
    }
    if subscription is None:
        subscription = BillingSubscription.all_objects.create(
            stripe_subscription_id=subscription_id,
            **defaults,
        )
    else:
        for field, value in defaults.items():
            setattr(subscription, field, value)
        subscription.version += 1
        subscription.save()

    update_entitlement_snapshot(
        profile.organization,
        mapping,
        state=internal_state,
        access_mode=access_mode,
        effective_until=effective_until,
    )
    sync_subscription_lifecycle(subscription)
    event.organization_id = profile.organization_id
    event.subscription = subscription


def _handle_invoice(event: StripeWebhookEvent) -> None:
    data = _data_object(event)
    customer_id = _stripe_id(data.get("customer"), "customer")
    subscription_id = _invoice_subscription_id(data)
    profile = BillingProfile.objects.filter(external_customer_id=customer_id).first()
    if profile is None:
        raise StripeEventProcessingError("Faktura dotyczy nieznanego Stripe Customer.")
    subscription = (
        BillingSubscription.all_objects.select_for_update()
        .select_related("price_mapping__plan_version__plan")
        .filter(
            organization_id=profile.organization_id,
            stripe_subscription_id=subscription_id,
        )
        .first()
    )
    if subscription is None:
        raise StripeEventProcessingError("Faktura dotyczy nieznanej subskrypcji Stripe.")
    if _is_stale(event, subscription):
        _mark_stale(event, subscription)
        return

    if event.event_type == "invoice.paid":
        state = SubscriptionState.ACTIVE
        access_mode = AccessMode.FULL
        subscription.provider_status = StripeSubscriptionStatus.ACTIVE
        effective_until = subscription.current_period_end
        subscription.grace_period_end = None
    else:
        subscription.provider_status = StripeSubscriptionStatus.PAST_DUE
        subscription.grace_period_end = (
            subscription.grace_period_end
            if subscription.grace_period_end is not None
            else event.provider_created_at
            + timedelta(days=subscription.price_mapping.plan_version.grace_period_days)
        )
        if subscription.state == SubscriptionState.READ_ONLY:
            state = SubscriptionState.READ_ONLY
            access_mode = AccessMode.READ_ONLY
            effective_until = None
        else:
            state = SubscriptionState.GRACE_PERIOD
            access_mode = AccessMode.FULL
            effective_until = subscription.grace_period_end
    subscription.state = state
    subscription.last_event_created_at = event.provider_created_at
    subscription.last_event_id = event.stripe_event_id
    subscription.version += 1
    subscription.save(
        update_fields=[
            "state",
            "provider_status",
            "grace_period_end",
            "last_event_created_at",
            "last_event_id",
            "version",
            "updated_at",
        ]
    )
    update_entitlement_snapshot(
        profile.organization,
        subscription.price_mapping,
        state=state,
        access_mode=access_mode,
        effective_until=effective_until,
    )
    sync_subscription_lifecycle(subscription)
    event.organization_id = profile.organization_id
    event.subscription = subscription


def subscription_access(provider_status: str) -> tuple[str, str]:
    mapping = {
        StripeSubscriptionStatus.INCOMPLETE: (
            SubscriptionState.UNCONFIGURED,
            AccessMode.BLOCKED,
        ),
        StripeSubscriptionStatus.INCOMPLETE_EXPIRED: (
            SubscriptionState.CANCELED,
            AccessMode.BLOCKED,
        ),
        StripeSubscriptionStatus.TRIALING: (SubscriptionState.TRIALING, AccessMode.FULL),
        StripeSubscriptionStatus.ACTIVE: (SubscriptionState.ACTIVE, AccessMode.FULL),
        StripeSubscriptionStatus.PAST_DUE: (
            SubscriptionState.GRACE_PERIOD,
            AccessMode.FULL,
        ),
        StripeSubscriptionStatus.CANCELED: (
            SubscriptionState.CANCELED,
            AccessMode.READ_ONLY,
        ),
        StripeSubscriptionStatus.UNPAID: (
            SubscriptionState.READ_ONLY,
            AccessMode.READ_ONLY,
        ),
        StripeSubscriptionStatus.PAUSED: (
            SubscriptionState.READ_ONLY,
            AccessMode.READ_ONLY,
        ),
    }
    return mapping[StripeSubscriptionStatus(provider_status)]


def _data_object(event: StripeWebhookEvent) -> dict[str, Any]:
    data = event.payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("object"), dict):
        raise StripeEventProcessingError("Event Stripe nie zawiera data.object.")
    return cast(dict[str, Any], data["object"])


def _subscription_price(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    items = data.get("items")
    rows = items.get("data") if isinstance(items, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise StripeEventProcessingError("Subskrypcja musi zawierać dokładnie jeden Price.")
    item = rows[0]
    price = item.get("price")
    return _stripe_id(price, "price"), item


def _invoice_subscription_id(data: dict[str, Any]) -> str:
    direct = data.get("subscription")
    if direct is not None:
        return _stripe_id(direct, "subscription")
    parent = data.get("parent")
    details = parent.get("subscription_details") if isinstance(parent, dict) else None
    if isinstance(details, dict):
        return _stripe_id(details.get("subscription"), "subscription")
    raise StripeEventProcessingError("Faktura nie wskazuje subskrypcji Stripe.")


def _stripe_id(value: Any, field: str) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    if not isinstance(value, str) or not value:
        raise StripeEventProcessingError(f"Brak identyfikatora Stripe {field}.")
    return value


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise StripeEventProcessingError(f"Brak pola {field} w obiekcie Stripe.")
    return value


def _optional_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StripeEventProcessingError("Nieprawidłowy timestamp Stripe.")
    return datetime.fromtimestamp(value, tz=UTC)


def _timestamp_pair(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    start_key: str,
    end_key: str,
) -> tuple[datetime | None, datetime | None]:
    raw_start = primary.get(start_key, fallback.get(start_key))
    raw_end = primary.get(end_key, fallback.get(end_key))
    start = _optional_timestamp(raw_start)
    end = _optional_timestamp(raw_end)
    if (start is None) != (end is None):
        raise StripeEventProcessingError("Nieprawidłowe okno czasowe Stripe.")
    if start is not None and end is not None and end <= start:
        raise StripeEventProcessingError("Nieprawidłowe okno czasowe Stripe.")
    return start, end


def _is_stale(event: StripeWebhookEvent, subscription: BillingSubscription) -> bool:
    previous_at = subscription.last_event_created_at
    if previous_at is None:
        return False
    if event.provider_created_at != previous_at:
        return event.provider_created_at < previous_at
    previous_type = (
        StripeWebhookEvent.objects.filter(stripe_event_id=subscription.last_event_id)
        .values_list("event_type", flat=True)
        .first()
    )
    return EVENT_PRIORITY.get(event.event_type, 0) <= EVENT_PRIORITY.get(previous_type or "", 0)


def _mark_stale(event: StripeWebhookEvent, subscription: BillingSubscription) -> None:
    event.organization_id = subscription.organization_id
    event.subscription = subscription
    event.status = WebhookProcessingStatus.IGNORED
    event.processing_error = "Starszy event Stripe nie zmienił lokalnego stanu."
