from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    OrganizationAuditAction,
)

from .models import (
    AccessMode,
    BillingCheckout,
    BillingLifecycleAction,
    BillingNotice,
    BillingNoticeType,
    BillingSubscription,
    BillingTrialActivation,
    CheckoutStatus,
    LifecycleActionStatus,
    LifecycleActionType,
    StripeSubscriptionStatus,
    SubscriptionState,
    TrialActivationStatus,
)
from .provider import BillingProviderError, ProviderSubscription, get_billing_provider
from .snapshots import update_entitlement_snapshot

SOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
logger = logging.getLogger(__name__)


class TrialActivationError(APIException):
    status_code = 409
    default_detail = "Nie można aktywować subskrypcji."
    default_code = "trial_activation_error"


class CompletedCheckoutRequired(TrialActivationError):
    default_detail = "Pierwsza aktywacja produktu wymaga zakończonego Checkout."
    default_code = "completed_checkout_required"


class TrialActivationConflict(TrialActivationError):
    default_detail = "Nie można jednoznacznie aktywować wybranego planu."
    default_code = "trial_activation_conflict"


class TrialActivationProviderUnavailable(TrialActivationError):
    status_code = 502
    default_detail = "Dostawca płatności nie aktywował subskrypcji."
    default_code = "trial_activation_provider_unavailable"


@dataclass(frozen=True, slots=True)
class TrialActivationResult:
    activation: BillingTrialActivation
    created: bool


def activate_trial_for_product(
    *,
    source_type: str,
    source_id: str,
    checkout_session_id: str | None = None,
) -> TrialActivationResult:
    context = require_tenant_context()
    normalized_type, normalized_id = _normalize_source(source_type, source_id)
    normalized_checkout_session_id = _normalize_checkout_session_id(checkout_session_id)

    with transaction.atomic():
        # BillingProfile is the stable per-organization mutex shared with the
        # webhook processor and subscription persistence. It serializes two
        # activation attempts even when they target different Checkout rows.
        BillingProfile.objects.select_for_update().get(organization_id=context.organization_id)
        activation = (
            BillingTrialActivation.all_objects.select_for_update()
            .select_related("checkout__price_mapping__plan_version__plan")
            .filter(organization_id=context.organization_id)
            .first()
        )
        if (
            activation is not None
            and normalized_checkout_session_id is not None
            and activation.checkout.stripe_checkout_session_id != normalized_checkout_session_id
        ):
            raise TrialActivationConflict("Aktywacja jest już powiązana z inną sesją Checkout.")
        if activation is not None and activation.status == TrialActivationStatus.ACTIVE:
            return TrialActivationResult(activation, False)
        if activation is None:
            checkouts = (
                BillingCheckout.all_objects.select_for_update()
                .select_related("price_mapping__plan_version__plan")
                .filter(
                    organization_id=context.organization_id,
                    status=CheckoutStatus.COMPLETE,
                    price_mapping__livemode=settings.STRIPE_LIVEMODE,
                )
                .exclude(setup_intent_id="")
            )
            if normalized_checkout_session_id is not None:
                checkouts = checkouts.filter(
                    stripe_checkout_session_id=normalized_checkout_session_id
                )
            checkout = checkouts.order_by("-completed_at").first()
            if checkout is None:
                raise CompletedCheckoutRequired(
                    "Pierwsza aktywacja produktu wymaga zakończonego Checkout."
                )
            activation, _ = BillingTrialActivation.all_objects.get_or_create(
                organization_id=context.organization_id,
                defaults={
                    "checkout": checkout,
                    "source_type": normalized_type,
                    "source_id": normalized_id,
                },
            )
            if normalized_checkout_session_id is not None and activation.checkout_id != checkout.id:
                raise TrialActivationConflict("Aktywacja jest już powiązana z inną sesją Checkout.")

    activation = BillingTrialActivation.all_objects.select_related(
        "checkout__price_mapping__plan_version__plan",
        "organization",
    ).get(pk=activation.pk)
    checkout = activation.checkout
    profile = BillingProfile.objects.get(organization_id=activation.organization_id)
    if not profile.external_customer_id:
        raise TrialActivationConflict("Organizacja nie ma Stripe Customer.")

    mapping = checkout.price_mapping
    plan_version = mapping.plan_version
    if (
        BillingSubscription.all_objects.filter(organization_id=activation.organization_id)
        .exclude(state=SubscriptionState.CANCELED)
        .exists()
    ):
        raise TrialActivationConflict("Organizacja ma już bieżącą subskrypcję.")
    try:
        provider = get_billing_provider()
        provider_subscription = provider.create_trial_subscription(
            customer_id=profile.external_customer_id,
            setup_intent_id=checkout.setup_intent_id,
            price_id=mapping.stripe_price_id,
            organization_id=str(activation.organization_id),
            plan_version_id=str(plan_version.id),
            trial_days=plan_version.trial_days,
            idempotency_key=f"saas-core:trial:{activation.organization_id}",
        )
        if provider_subscription.status != StripeSubscriptionStatus.TRIALING:
            raise BillingProviderError("Stripe nie utworzył subskrypcji w stanie trialing.")
    except (BillingProviderError, ImproperlyConfigured) as error:
        BillingTrialActivation.all_objects.filter(
            pk=activation.pk,
        ).exclude(status=TrialActivationStatus.ACTIVE).update(
            status=TrialActivationStatus.FAILED,
            last_error=str(error)[:2000],
        )
        raise TrialActivationProviderUnavailable(
            "Dostawca płatności nie aktywował triala."
        ) from error

    try:
        return _persist_trial_activation(activation.id, provider_subscription)
    except TrialActivationConflict as error:
        BillingTrialActivation.all_objects.filter(
            pk=activation.pk,
        ).exclude(status=TrialActivationStatus.ACTIVE).update(
            status=TrialActivationStatus.FAILED,
            last_error=str(error)[:2000],
        )
        raise


def _persist_trial_activation(
    activation_id: UUID,
    provider_subscription: ProviderSubscription,
) -> TrialActivationResult:
    if provider_subscription.status != StripeSubscriptionStatus.TRIALING:
        raise TrialActivationConflict("Stripe nie utworzył subskrypcji w stanie trialing.")
    organization_id = BillingTrialActivation.all_objects.values_list(
        "organization_id", flat=True
    ).get(pk=activation_id)
    with transaction.atomic():
        BillingProfile.objects.select_for_update().get(organization_id=organization_id)
        activation = (
            BillingTrialActivation.all_objects.select_for_update()
            .select_related(
                "checkout__price_mapping__plan_version__plan",
                "organization",
            )
            .get(pk=activation_id)
        )
        if activation.status == TrialActivationStatus.ACTIVE:
            return TrialActivationResult(activation, False)

        mapping = activation.checkout.price_mapping
        subscription = (
            BillingSubscription.all_objects.select_for_update()
            .filter(stripe_subscription_id=provider_subscription.id)
            .first()
        )
        if subscription is not None and (
            subscription.organization_id != activation.organization_id
            or subscription.price_mapping_id != mapping.id
        ):
            raise TrialActivationConflict(
                "Subskrypcja Stripe jest powiązana z inną organizacją albo ceną."
            )
        current = (
            BillingSubscription.all_objects.select_for_update()
            .filter(organization_id=activation.organization_id)
            .exclude(state=SubscriptionState.CANCELED)
            .first()
        )
        if current is not None and (subscription is None or current.id != subscription.id):
            raise TrialActivationConflict("Organizacja ma już bieżącą subskrypcję.")

        if subscription is None:
            subscription = BillingSubscription.all_objects.create(
                organization=activation.organization,
                price_mapping=mapping,
                stripe_subscription_id=provider_subscription.id,
                state=SubscriptionState.TRIALING,
                provider_status=StripeSubscriptionStatus.TRIALING,
                current_period_start=provider_subscription.current_period_start,
                current_period_end=provider_subscription.current_period_end,
                trial_start=provider_subscription.trial_start,
                trial_end=provider_subscription.trial_end,
            )
        elif subscription.state in {
            SubscriptionState.UNCONFIGURED,
            SubscriptionState.TRIALING,
        }:
            subscription.state = SubscriptionState.TRIALING
            subscription.provider_status = StripeSubscriptionStatus.TRIALING
            subscription.current_period_start = provider_subscription.current_period_start
            subscription.current_period_end = provider_subscription.current_period_end
            subscription.trial_start = provider_subscription.trial_start
            subscription.trial_end = provider_subscription.trial_end
            subscription.save()

        if subscription.state == SubscriptionState.TRIALING:
            update_entitlement_snapshot(
                activation.organization,
                mapping,
                state=SubscriptionState.TRIALING,
                access_mode=AccessMode.FULL,
                effective_until=provider_subscription.trial_end,
            )
        sync_subscription_lifecycle(subscription)

        activation.subscription = subscription
        activation.status = TrialActivationStatus.ACTIVE
        activation.activated_at = provider_subscription.trial_start
        activation.last_error = ""
        activation.save(
            update_fields=[
                "subscription",
                "status",
                "activated_at",
                "last_error",
                "updated_at",
            ]
        )
        actor = User.objects.filter(pk=require_tenant_context().actor_id).first()
        record_audit(
            organization=activation.organization,
            action=OrganizationAuditAction.BILLING_TRIAL_STARTED,
            actor=actor,
            target_type="billing_trial_activation",
            target_id=activation.id,
            metadata={
                "source_type": activation.source_type,
                "source_id": activation.source_id,
                "plan": mapping.plan_version.plan.key,
                "plan_version": mapping.plan_version.version,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "trial_end": provider_subscription.trial_end.isoformat(),
            },
        )
        return TrialActivationResult(activation, True)


def _normalize_source(source_type: str, source_id: str) -> tuple[str, str]:
    normalized_type = source_type.strip().lower()
    normalized_id = source_id.strip()
    if len(normalized_type) > 64 or SOURCE_TYPE_RE.fullmatch(normalized_type) is None:
        raise TrialActivationConflict("Nieprawidłowy typ źródła aktywacji.")
    if not normalized_id or len(normalized_id) > 160:
        raise TrialActivationConflict("Nieprawidłowy identyfikator źródła aktywacji.")
    return normalized_type, normalized_id


def _normalize_checkout_session_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        raise TrialActivationConflict("Nieprawidłowy identyfikator sesji Checkout.")
    return normalized


def sync_subscription_lifecycle(subscription: BillingSubscription) -> None:
    warning_lead = timedelta(seconds=settings.BILLING_LIFECYCLE_WARNING_LEAD_SECONDS)
    desired: dict[str, datetime] = {}
    if subscription.state == SubscriptionState.TRIALING and subscription.trial_end:
        desired[LifecycleActionType.TRIAL_ENDING_NOTICE] = subscription.trial_end - warning_lead
    if subscription.state == SubscriptionState.GRACE_PERIOD and subscription.grace_period_end:
        desired[LifecycleActionType.GRACE_ENDING_NOTICE] = (
            subscription.grace_period_end - warning_lead
        )
        desired[LifecycleActionType.GRACE_EXPIRED] = subscription.grace_period_end
    if (
        subscription.state == SubscriptionState.CANCELED or subscription.cancel_at_period_end
    ) and subscription.current_period_end:
        desired[LifecycleActionType.CANCELED_PERIOD_ENDED] = subscription.current_period_end

    now = timezone.now()
    pending = BillingLifecycleAction.all_objects.filter(
        subscription=subscription,
        status=LifecycleActionStatus.PENDING,
    )
    for action in pending:
        if desired.get(action.action_type) != action.due_at:
            action.status = LifecycleActionStatus.CANCELED
            action.processed_at = now
            action.save(update_fields=["status", "processed_at", "updated_at"])

    for action_type, due_at in desired.items():
        action, created = BillingLifecycleAction.all_objects.get_or_create(
            organization_id=subscription.organization_id,
            subscription=subscription,
            action_type=action_type,
            due_at=due_at,
        )
        if not created and action.status in {
            LifecycleActionStatus.CANCELED,
            LifecycleActionStatus.FAILED,
        }:
            action.status = LifecycleActionStatus.PENDING
            action.attempt_count = 0
            action.last_error = ""
            action.processed_at = None
            action.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "last_error",
                    "processed_at",
                    "updated_at",
                ]
            )


def process_due_lifecycle_actions(
    *,
    at: datetime | None = None,
    limit: int = 100,
) -> int:
    if limit <= 0:
        raise ValueError("Limit akcji lifecycle musi być dodatni.")
    checked_at = at or timezone.now()
    action_ids = list(
        BillingLifecycleAction.all_objects.filter(
            status=LifecycleActionStatus.PENDING,
            due_at__lte=checked_at,
        )
        .order_by("due_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    handled = 0
    for action_id in action_ids:
        try:
            if _process_lifecycle_action(action_id, checked_at):
                handled += 1
        except Exception as error:
            _record_lifecycle_failure(action_id, error)
            logger.exception(
                "billing_lifecycle_action_failed",
                extra={"lifecycle_action_id": str(action_id)},
            )
    return handled


def _process_lifecycle_action(action_id: UUID, checked_at: datetime) -> bool:
    with transaction.atomic():
        action = (
            BillingLifecycleAction.all_objects.select_for_update()
            .select_related(
                "organization",
                "subscription__price_mapping__plan_version__plan",
            )
            .filter(pk=action_id)
            .first()
        )
        if (
            action is None
            or action.status != LifecycleActionStatus.PENDING
            or action.due_at > checked_at
        ):
            return False
        action.attempt_count += 1
        action.status = _dispatch_lifecycle_action(action, checked_at)
        action.processed_at = checked_at
        action.last_error = ""
        action.save(
            update_fields=[
                "status",
                "attempt_count",
                "processed_at",
                "last_error",
                "updated_at",
            ]
        )
        return True


def _dispatch_lifecycle_action(
    action: BillingLifecycleAction,
    checked_at: datetime,
) -> str:
    subscription = action.subscription
    if action.action_type == LifecycleActionType.TRIAL_ENDING_NOTICE:
        if subscription.state != SubscriptionState.TRIALING:
            return LifecycleActionStatus.CANCELED
        _create_notice(action, BillingNoticeType.TRIAL_ENDING, subscription.trial_end)
        return LifecycleActionStatus.PROCESSED
    if action.action_type == LifecycleActionType.GRACE_ENDING_NOTICE:
        if subscription.state != SubscriptionState.GRACE_PERIOD:
            return LifecycleActionStatus.CANCELED
        _create_notice(
            action,
            BillingNoticeType.GRACE_ENDING,
            subscription.grace_period_end,
        )
        return LifecycleActionStatus.PROCESSED
    if action.action_type == LifecycleActionType.GRACE_EXPIRED:
        if (
            subscription.state != SubscriptionState.GRACE_PERIOD
            or subscription.grace_period_end is None
            or subscription.grace_period_end > checked_at
        ):
            return LifecycleActionStatus.CANCELED
        _transition_to_read_only(
            action,
            state=SubscriptionState.READ_ONLY,
            reason="grace_period_expired",
            boundary=subscription.grace_period_end,
        )
        return LifecycleActionStatus.PROCESSED
    if action.action_type == LifecycleActionType.CANCELED_PERIOD_ENDED:
        if (
            subscription.current_period_end is None
            or subscription.current_period_end > checked_at
            or (
                subscription.state != SubscriptionState.CANCELED
                and not subscription.cancel_at_period_end
            )
        ):
            return LifecycleActionStatus.CANCELED
        _transition_to_read_only(
            action,
            state=SubscriptionState.CANCELED,
            reason="canceled_period_ended",
            boundary=subscription.current_period_end,
        )
        return LifecycleActionStatus.PROCESSED
    return LifecycleActionStatus.CANCELED


def _create_notice(
    action: BillingLifecycleAction,
    notice_type: str,
    ends_at: datetime | None,
) -> None:
    if ends_at is None:
        raise ValueError("Ostrzeżenie lifecycle nie ma daty granicznej.")
    BillingNotice.all_objects.get_or_create(
        organization=action.organization,
        lifecycle_action=action,
        defaults={
            "subscription": action.subscription,
            "notice_type": notice_type,
            "payload": {
                "subscription_id": str(action.subscription_id),
                "notice_type": notice_type,
                "ends_at": ends_at.isoformat(),
            },
        },
    )


def _transition_to_read_only(
    action: BillingLifecycleAction,
    *,
    state: str,
    reason: str,
    boundary: datetime,
) -> None:
    subscription = action.subscription
    previous_state = subscription.state
    subscription.state = state
    subscription.cancel_at_period_end = False
    subscription.version += 1
    subscription.save(
        update_fields=[
            "state",
            "cancel_at_period_end",
            "version",
            "updated_at",
        ]
    )
    update_entitlement_snapshot(
        action.organization,
        subscription.price_mapping,
        state=state,
        access_mode=AccessMode.READ_ONLY,
        effective_until=None,
    )
    BillingLifecycleAction.all_objects.filter(
        subscription=subscription,
        status=LifecycleActionStatus.PENDING,
    ).exclude(pk=action.pk).update(
        status=LifecycleActionStatus.CANCELED,
        processed_at=timezone.now(),
    )
    record_audit(
        organization=action.organization,
        action=OrganizationAuditAction.BILLING_ACCESS_READ_ONLY,
        actor=None,
        target_type="billing_subscription",
        target_id=subscription.id,
        metadata={
            "previous_state": previous_state,
            "state": state,
            "reason": reason,
            "boundary": boundary.isoformat(),
            "lifecycle_action_id": str(action.id),
        },
    )


def _record_lifecycle_failure(action_id: UUID, error: Exception) -> None:
    with transaction.atomic():
        action = (
            BillingLifecycleAction.all_objects.select_for_update()
            .filter(pk=action_id, status=LifecycleActionStatus.PENDING)
            .first()
        )
        if action is None:
            return
        action.attempt_count += 1
        if action.attempt_count >= settings.BILLING_LIFECYCLE_MAX_ATTEMPTS:
            action.status = LifecycleActionStatus.FAILED
        action.last_error = str(error)[:2000]
        action.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_error",
                "updated_at",
            ]
        )
