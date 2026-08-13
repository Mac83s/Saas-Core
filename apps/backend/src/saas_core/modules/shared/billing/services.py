from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Organization,
    OrganizationAuditAction,
)
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE

from .models import (
    BillingCheckout,
    BillingSubscription,
    CheckoutStatus,
    StripePriceMapping,
    SubscriptionState,
)
from .provider import (
    BillingProviderCapabilityError,
    BillingProviderError,
    get_billing_provider,
)

if TYPE_CHECKING:
    from .lifecycle import TrialActivationResult


class BillingPlanUnavailable(NotFound):
    default_detail = "Wybrany plan nie jest dostępny."
    default_code = "billing_plan_unavailable"


class BillingCheckoutConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inny Checkout."
    default_code = "billing_checkout_conflict"


class ActiveSubscriptionExists(APIException):
    status_code = 409
    default_detail = "Organizacja ma już bieżącą subskrypcję."
    default_code = "active_subscription_exists"


class BillingCustomerRequired(APIException):
    status_code = 409
    default_detail = "Organizacja nie ma jeszcze Stripe Customer."
    default_code = "billing_customer_required"


class BillingProviderUnavailable(APIException):
    status_code = 502
    default_detail = "Dostawca płatności jest chwilowo niedostępny."
    default_code = "billing_provider_unavailable"


class BillingPortalUnavailable(APIException):
    status_code = 409
    default_detail = "Portal płatniczy nie jest dostępny w bieżącym trybie płatności."
    default_code = "billing_portal_unavailable"


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    checkout: BillingCheckout
    created: bool


@dataclass(frozen=True, slots=True)
class PortalResult:
    session_id: str
    url: str


def activate_customer_trial(*, checkout_session_id: str) -> TrialActivationResult:
    """Activate the selected plan after Stripe confirms Setup Checkout."""

    authorize(BILLING_MANAGE, owner_only=True)
    from .lifecycle import activate_trial_for_product

    return activate_trial_for_product(
        source_type="sites.onboarding",
        source_id=checkout_session_id,
        checkout_session_id=checkout_session_id,
    )


def create_setup_checkout(*, plan_key: str, idempotency_key: str) -> CheckoutResult:
    context = authorize(BILLING_MANAGE, owner_only=True)
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 120:
        raise BillingCheckoutConflict
    if (
        BillingSubscription.all_objects.filter(organization_id=context.organization_id)
        .exclude(state=SubscriptionState.CANCELED)
        .exists()
    ):
        raise ActiveSubscriptionExists

    mapping = (
        StripePriceMapping.objects.select_related("plan_version__plan")
        .filter(
            plan_version__plan__key=plan_key,
            plan_version__plan__key__in=settings.BILLING_PLAN_KEYS,
            plan_version__plan__is_active=True,
            plan_version__plan__is_public=True,
            plan_version__plan__current_version_id=F("plan_version_id"),
            is_active=True,
            livemode=settings.STRIPE_LIVEMODE,
        )
        .first()
    )
    if mapping is None:
        raise BillingPlanUnavailable
    existing = BillingCheckout.all_objects.filter(
        organization_id=context.organization_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.price_mapping_id != mapping.id:
            raise BillingCheckoutConflict
        return CheckoutResult(existing, False)

    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    profile = BillingProfile.objects.get(organization=organization)
    try:
        provider = get_billing_provider()
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error
    customer_created = False
    if not profile.external_customer_id:
        try:
            customer = provider.create_customer(
                email=profile.billing_email or actor.email,
                name=profile.legal_name or organization.name,
                organization_id=str(organization.id),
                idempotency_key=f"saas-core:customer:{organization.id}",
            )
        except (BillingProviderError, ImproperlyConfigured) as error:
            raise BillingProviderUnavailable from error
        profile.external_customer_id = customer.id
        try:
            with transaction.atomic():
                profile.save(update_fields=["external_customer_id", "updated_at"])
        except IntegrityError as error:
            raise BillingCheckoutConflict from error
        customer_created = True

    try:
        provider_checkout = provider.create_setup_checkout(
            customer_id=profile.external_customer_id,
            organization_id=str(organization.id),
            plan_version_id=str(mapping.plan_version_id),
            price_mapping_id=str(mapping.id),
            success_url=settings.BILLING_CHECKOUT_SUCCESS_URL,
            cancel_url=settings.BILLING_CHECKOUT_CANCEL_URL,
            idempotency_key=f"saas-core:checkout:{organization.id}:{normalized_key}",
        )
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error

    if provider_checkout.completed and not provider_checkout.setup_intent_id:
        raise BillingProviderUnavailable("Dostawca nie zwrócił potwierdzenia symulacji.")
    completed_at = timezone.now() if provider_checkout.completed else None

    try:
        with transaction.atomic():
            checkout = BillingCheckout.all_objects.create(
                organization=organization,
                price_mapping=mapping,
                stripe_checkout_session_id=provider_checkout.id,
                idempotency_key=normalized_key,
                checkout_url=provider_checkout.url,
                status=(
                    CheckoutStatus.COMPLETE
                    if provider_checkout.completed
                    else CheckoutStatus.OPEN
                ),
                setup_intent_id=provider_checkout.setup_intent_id,
                completed_at=completed_at,
                expires_at=provider_checkout.expires_at,
            )
    except IntegrityError:
        checkout = BillingCheckout.all_objects.get(
            organization=organization,
            idempotency_key=normalized_key,
        )
        if checkout.price_mapping_id != mapping.id:
            raise BillingCheckoutConflict from None
        return CheckoutResult(checkout, False)

    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_CHECKOUT_CREATED,
        actor=actor,
        target_type="billing_checkout",
        target_id=checkout.id,
        metadata={
            "plan": mapping.plan_version.plan.key,
            "plan_version": mapping.plan_version.version,
            "stripe_checkout_session_id": checkout.stripe_checkout_session_id,
            "stripe_customer_created": customer_created,
            "payment_mode": settings.BILLING_PROVIDER,
        },
    )
    return CheckoutResult(checkout, True)


def create_customer_portal() -> PortalResult:
    context = authorize(BILLING_MANAGE, owner_only=True)
    if settings.BILLING_PROVIDER == "simulated":
        raise BillingPortalUnavailable
    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    profile = BillingProfile.objects.get(organization=organization)
    if not profile.external_customer_id:
        raise BillingCustomerRequired
    try:
        portal = get_billing_provider().create_portal(
            customer_id=profile.external_customer_id,
            return_url=settings.BILLING_PORTAL_RETURN_URL,
        )
    except BillingProviderCapabilityError as error:
        raise BillingPortalUnavailable from error
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_PORTAL_CREATED,
        actor=actor,
        target_type="billing_portal",
        metadata={"stripe_portal_session_id": portal.id},
    )
    return PortalResult(portal.id, portal.url)
