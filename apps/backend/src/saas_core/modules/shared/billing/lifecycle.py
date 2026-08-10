from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction

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
    BillingSubscription,
    BillingTrialActivation,
    CheckoutStatus,
    StripeSubscriptionStatus,
    SubscriptionState,
    TrialActivationStatus,
)
from .provider import BillingProviderError, ProviderSubscription, get_billing_provider
from .snapshots import update_entitlement_snapshot

SOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


class TrialActivationError(RuntimeError):
    pass


class CompletedCheckoutRequired(TrialActivationError):
    pass


class TrialActivationConflict(TrialActivationError):
    pass


class TrialActivationProviderUnavailable(TrialActivationError):
    pass


@dataclass(frozen=True, slots=True)
class TrialActivationResult:
    activation: BillingTrialActivation
    created: bool


def activate_trial_for_product(*, source_type: str, source_id: str) -> TrialActivationResult:
    context = require_tenant_context()
    normalized_type, normalized_id = _normalize_source(source_type, source_id)

    with transaction.atomic():
        activation = (
            BillingTrialActivation.all_objects.select_for_update()
            .select_related("checkout__price_mapping__plan_version__plan")
            .filter(organization_id=context.organization_id)
            .first()
        )
        if activation is not None and activation.status == TrialActivationStatus.ACTIVE:
            return TrialActivationResult(activation, False)
        if activation is None:
            checkout = (
                BillingCheckout.all_objects.select_for_update()
                .select_related("price_mapping__plan_version__plan")
                .filter(
                    organization_id=context.organization_id,
                    status=CheckoutStatus.COMPLETE,
                    price_mapping__livemode=settings.STRIPE_LIVEMODE,
                )
                .exclude(setup_intent_id="")
                .order_by("-completed_at")
                .first()
            )
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
    try:
        provider_subscription = get_billing_provider().create_trial_subscription(
            customer_id=profile.external_customer_id,
            setup_intent_id=checkout.setup_intent_id,
            price_id=mapping.stripe_price_id,
            organization_id=str(activation.organization_id),
            plan_version_id=str(plan_version.id),
            trial_days=plan_version.trial_days,
            idempotency_key=f"saas-core:trial:{activation.organization_id}",
        )
        if provider_subscription.status != StripeSubscriptionStatus.TRIALING:
            raise BillingProviderError(
                "Stripe nie utworzył subskrypcji w stanie trialing."
            )
    except BillingProviderError as error:
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
    with transaction.atomic():
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
