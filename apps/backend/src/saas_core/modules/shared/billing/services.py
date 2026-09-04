from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

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
from saas_core.modules.core.organizations.platform_workspace import (
    assert_not_platform,
)

from .models import (
    BillingCheckout,
    BillingSubscription,
    CheckoutStatus,
    CreditPackPrice,
    CreditPurchase,
    CreditPurchaseStatus,
    StripePriceMapping,
    SubscriptionState,
)
from .provider import (
    BillingProviderCapabilityError,
    BillingProviderError,
    ProviderAddress,
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


class CreditPackUnavailable(NotFound):
    default_detail = "Pakiet kredytów nie jest dostępny."
    default_code = "credit_pack_unavailable"


class BillingProfileIncomplete(APIException):
    status_code = 409
    default_detail = "Uzupełnij dane do faktury przed pierwszą płatnością."
    default_code = "billing_profile_incomplete"


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


def _refuse_platform_workspace(organization_id: UUID) -> None:
    """The deployment does not sell itself a subscription.

    Checked in the three customer-facing entry points rather than in the panel:
    a trial, a checkout or a portal session opened against the platform's own
    workspace would put its marketing pages behind a Stripe customer that
    nobody is ever going to pay.
    """
    assert_not_platform(Organization.objects.get(pk=organization_id))


def activate_customer_trial(*, checkout_session_id: str) -> TrialActivationResult:
    """Activate the selected plan after Stripe confirms Setup Checkout."""

    context = authorize(BILLING_MANAGE, owner_only=True)
    _refuse_platform_workspace(context.organization_id)
    from .lifecycle import activate_trial_for_product

    return activate_trial_for_product(
        source_type="sites.onboarding",
        source_id=checkout_session_id,
        checkout_session_id=checkout_session_id,
    )


# The fields Stripe Tax needs before it can work out a rate, in the order a
# person reads them. The panel asks for exactly these, so the form and the
# refusal below cannot drift apart.
REQUIRED_BILLING_DETAILS: tuple[tuple[str, str], ...] = (
    ("country_code", "kraj"),
    ("address_line1", "ulica"),
    ("postal_code", "kod pocztowy"),
    ("city", "miejscowość"),
)


def missing_billing_details(profile: BillingProfile | None) -> list[str]:
    """Which required fields are still empty, named as the panel names them."""
    if profile is None:
        return [field for field, _label in REQUIRED_BILLING_DETAILS]
    return [
        field
        for field, _label in REQUIRED_BILLING_DETAILS
        if not str(getattr(profile, field, "")).strip()
    ]


def _provider_address(profile: BillingProfile) -> ProviderAddress:
    """The address Stripe Tax needs, refused early when it is incomplete.

    ADR-040 makes this required data rather than an optional detail: without a
    country and a street the provider cannot work out a VAT rate, and finding
    that out at the payment is worse than finding it out in the form.
    """
    empty = set(missing_billing_details(profile))
    missing = [label for field, label in REQUIRED_BILLING_DETAILS if field in empty]
    if missing:
        raise BillingProfileIncomplete(
            "Dane do faktury są niekompletne; brakuje: " + ", ".join(missing) + "."
        )
    return ProviderAddress(
        line1=profile.address_line1.strip(),
        postal_code=profile.postal_code.strip(),
        city=profile.city.strip(),
        country=profile.country_code.strip().upper(),
    )


@transaction.atomic
def update_billing_details(*, changes: dict[str, Any]) -> BillingProfile:
    """Save the invoice details the customer typed into the panel.

    The profile is created here when the organization never had one: an
    organization can exist before anyone has thought about paying, and the
    first person who does should not meet an error about a missing row.

    The provider is not told about the change. A customer already created at
    Stripe keeps the address it was created with until the next checkout, which
    sends the current one — going further and rewriting the remote customer
    from here would put a second writer on data the Customer Portal also edits.
    """
    context = authorize(BILLING_MANAGE, owner_only=True)
    _refuse_platform_workspace(context.organization_id)
    organization = Organization.objects.get(pk=context.organization_id)
    profile, _created = BillingProfile.objects.select_for_update().get_or_create(
        organization=organization
    )
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.full_clean(validate_unique=False, validate_constraints=False)
    profile.save()
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_PROFILE_UPDATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="billing_profile",
        target_id=profile.id,
        metadata={"fields": sorted(changes)},
    )
    return profile


def _customer_origin() -> tuple[str, bool | None]:
    """The provider and mode a customer created right now would belong to."""
    provider = str(settings.BILLING_PROVIDER)
    return provider, (bool(settings.STRIPE_LIVEMODE) if provider == "stripe" else None)


def reusable_customer_id(profile: BillingProfile) -> str:
    """The stored customer id, but only where it still means something.

    A customer id is valid nowhere except the provider and mode that issued
    it. The simulator's ``sim_customer_…`` is unknown to Stripe, and a
    test-mode ``cus_…`` is unknown in live mode — the provider answers
    ``resource_missing`` and the checkout dies with a 502. That is how
    switching this deployment from the simulator to Stripe announced itself,
    and the same wall stands between test and live.

    An id with no stamp predates this rule and is assumed to belong here.
    Assuming the opposite would create a second identity at the provider for a
    company that already has one, splitting its invoices — a quiet mistake,
    where reusing a foreign id is a loud one.
    """
    if not profile.external_customer_id or not profile.external_customer_provider:
        return profile.external_customer_id
    provider, livemode = _customer_origin()
    if profile.external_customer_provider != provider:
        return ""
    if provider == "stripe" and profile.external_customer_livemode != livemode:
        return ""
    return profile.external_customer_id


def _ensure_provider_customer(
    *,
    provider: Any,
    organization: Organization,
    actor: User,
    profile: BillingProfile,
) -> tuple[str, bool]:
    """Returns the provider customer for this organization, creating it once.

    Shared by the plan checkout and the credit-pack checkout: both need a
    customer carrying the billing address, and creating a second one would give
    the same company two identities at the provider.
    """
    existing = reusable_customer_id(profile)
    if existing:
        return existing, False
    try:
        customer = provider.create_customer(
            email=profile.billing_email or actor.email,
            name=profile.legal_name or organization.name,
            address=_provider_address(profile),
            organization_id=str(organization.id),
            idempotency_key=f"saas-core:customer:{organization.id}",
        )
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error
    profile.external_customer_id = customer.id
    (
        profile.external_customer_provider,
        profile.external_customer_livemode,
    ) = _customer_origin()
    try:
        with transaction.atomic():
            profile.save(
                update_fields=[
                    "external_customer_id",
                    "external_customer_provider",
                    "external_customer_livemode",
                    "updated_at",
                ]
            )
    except IntegrityError as error:
        raise BillingCheckoutConflict from error
    return profile.external_customer_id, True


def create_credit_checkout(*, pack_key: str, idempotency_key: str) -> CreditPurchase:
    """Opens a one-off payment for a credit pack.

    The portal cannot sell this (ADR-040 §4), so it is our own Checkout. The
    purchase is recorded first and credited only by the webhook — a browser
    returning from Stripe proves nothing.
    """
    context = authorize(BILLING_MANAGE, owner_only=True)
    _refuse_platform_workspace(context.organization_id)
    from .credits import start_credit_purchase

    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    profile = BillingProfile.objects.get(organization=organization)
    purchase = start_credit_purchase(pack_key, idempotency_key=idempotency_key)
    if purchase.status != CreditPurchaseStatus.PENDING or purchase.checkout_session_id:
        return purchase

    price = (
        CreditPackPrice.objects.filter(
            pack=purchase.pack, livemode=settings.STRIPE_LIVEMODE, is_active=True
        )
        .values_list("stripe_price_id", flat=True)
        .first()
    )
    if price is None:
        raise CreditPackUnavailable
    try:
        provider = get_billing_provider()
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error
    customer_id, _created = _ensure_provider_customer(
        provider=provider, organization=organization, actor=actor, profile=profile
    )
    try:
        provider_checkout = provider.create_credit_checkout(
            customer_id=customer_id,
            organization_id=str(organization.id),
            purchase_id=str(purchase.id),
            price_id=price,
            success_url=settings.BILLING_CREDITS_CHECKOUT_SUCCESS_URL,
            cancel_url=settings.BILLING_CREDITS_CHECKOUT_CANCEL_URL,
            idempotency_key=f"saas-core:credits:{organization.id}:{purchase.id}",
        )
    except (BillingProviderError, ImproperlyConfigured) as error:
        raise BillingProviderUnavailable from error

    purchase.checkout_session_id = provider_checkout.id
    purchase.checkout_url = provider_checkout.url
    purchase.expires_at = provider_checkout.expires_at
    purchase.save(
        update_fields=[
            "checkout_session_id",
            "checkout_url",
            "expires_at",
            "updated_at",
        ]
    )
    if provider_checkout.completed:
        # The simulator settles immediately; real Stripe never does, and the
        # webhook is what credits the pool there.
        from .credits import complete_credit_purchase

        return complete_credit_purchase(
            organization_id=organization.id,
            purchase_id=purchase.id,
            provider_reference=provider_checkout.id,
        )
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BILLING_CHECKOUT_CREATED,
        actor=actor,
        target_type="credit_purchase",
        target_id=purchase.id,
        metadata={
            "credit_pack": purchase.pack.key,
            "credits": purchase.credits,
            "stripe_checkout_session_id": purchase.checkout_session_id,
            "payment_mode": settings.BILLING_PROVIDER,
        },
    )
    return purchase


def create_setup_checkout(*, plan_key: str, idempotency_key: str) -> CheckoutResult:
    context = authorize(BILLING_MANAGE, owner_only=True)
    _refuse_platform_workspace(context.organization_id)
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
            # Both catalogs can hold an active price for the same plan version;
            # only the one belonging to the provider now in use may be sold.
            provider=settings.BILLING_PROVIDER,
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
    customer_id, customer_created = _ensure_provider_customer(
        provider=provider, organization=organization, actor=actor, profile=profile
    )

    try:
        provider_checkout = provider.create_setup_checkout(
            customer_id=customer_id,
            organization_id=str(organization.id),
            plan_version_id=str(mapping.plan_version_id),
            price_mapping_id=str(mapping.id),
            currency=mapping.plan_version.currency,
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
                    CheckoutStatus.COMPLETE if provider_checkout.completed else CheckoutStatus.OPEN
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
    _refuse_platform_workspace(context.organization_id)
    if settings.BILLING_PROVIDER == "simulated":
        raise BillingPortalUnavailable
    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    profile = BillingProfile.objects.get(organization=organization)
    customer_id = reusable_customer_id(profile)
    if not customer_id:
        raise BillingCustomerRequired
    try:
        portal = get_billing_provider().create_portal(
            customer_id=customer_id,
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
