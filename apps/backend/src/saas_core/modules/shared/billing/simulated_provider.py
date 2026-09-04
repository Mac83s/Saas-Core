from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone

from .models import StripePriceMapping, StripeSubscriptionStatus
from .provider import (
    BillingProviderCapabilityError,
    BillingProviderError,
    ProviderAddress,
    ProviderCheckout,
    ProviderCustomer,
    ProviderPortal,
    ProviderPrice,
    ProviderSubscription,
    ProviderSubscriptionSnapshot,
)


def _simulated_id(prefix: str, value: str) -> str:
    return f"sim_{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"


class SimulatedBillingProvider:
    """Deterministic non-production billing adapter without an external payment system."""

    def create_customer(
        self,
        *,
        email: str,
        name: str,
        address: ProviderAddress,
        organization_id: str,
        idempotency_key: str,
    ) -> ProviderCustomer:
        del email, name, address, idempotency_key
        return ProviderCustomer(_simulated_id("customer", organization_id))

    def create_setup_checkout(
        self,
        *,
        customer_id: str,
        organization_id: str,
        plan_version_id: str,
        price_mapping_id: str,
        currency: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> ProviderCheckout:
        del customer_id, organization_id, plan_version_id, price_mapping_id
        del currency, cancel_url
        session_id = _simulated_id("checkout", idempotency_key)
        setup_intent_id = _simulated_id("setup", idempotency_key)
        return ProviderCheckout(
            id=session_id,
            url=success_url.replace("{CHECKOUT_SESSION_ID}", session_id),
            expires_at=None,
            completed=True,
            setup_intent_id=setup_intent_id,
        )

    def create_credit_checkout(
        self,
        *,
        customer_id: str,
        organization_id: str,
        purchase_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> ProviderCheckout:
        del customer_id, organization_id, price_id, cancel_url, idempotency_key
        session_id = _simulated_id("credit-checkout", purchase_id)
        return ProviderCheckout(
            id=session_id,
            url=success_url.replace("{CHECKOUT_SESSION_ID}", session_id),
            expires_at=None,
            completed=True,
        )

    def create_portal(self, *, customer_id: str, return_url: str) -> ProviderPortal:
        del customer_id, return_url
        raise BillingProviderCapabilityError(
            "Portal klienta nie jest dostępny w symulatorze płatności."
        )

    def retrieve_price(self, price_id: str) -> ProviderPrice:
        mapping = (
            StripePriceMapping.objects.select_related("plan_version")
            .filter(stripe_price_id=price_id, livemode=False, is_active=True)
            .first()
        )
        if mapping is None or not price_id.startswith("sim_price_"):
            raise BillingProviderError("Symulator nie zna wskazanej ceny.")
        version = mapping.plan_version
        return ProviderPrice(
            id=mapping.stripe_price_id,
            product_id=mapping.stripe_product_id,
            active=mapping.is_active,
            livemode=False,
            currency=version.currency,
            unit_amount_minor=version.unit_amount_minor,
            recurring_interval=version.billing_interval,
            recurring_interval_count=1,
        )

    def create_subscription(
        self,
        *,
        customer_id: str,
        setup_intent_id: str,
        price_id: str,
        organization_id: str,
        plan_version_id: str,
        trial_days: int,
        idempotency_key: str,
    ) -> ProviderSubscription:
        del customer_id, setup_intent_id, price_id, organization_id, plan_version_id
        if trial_days < 0:
            raise BillingProviderError("Liczba dni triala nie może być ujemna.")
        started = timezone.now()
        if trial_days == 0:
            # A returning customer: no free period, so the plan starts paid.
            return ProviderSubscription(
                id=_simulated_id("subscription", idempotency_key),
                status=StripeSubscriptionStatus.ACTIVE,
                trial_start=None,
                trial_end=None,
                current_period_start=started,
                current_period_end=started + timedelta(days=30),
            )
        trial_end = started + timedelta(days=trial_days)
        return ProviderSubscription(
            id=_simulated_id("subscription", idempotency_key),
            status=StripeSubscriptionStatus.TRIALING,
            trial_start=started,
            trial_end=trial_end,
            current_period_start=started,
            current_period_end=trial_end,
        )

    def retrieve_subscription(
        self,
        subscription_id: str,
    ) -> ProviderSubscriptionSnapshot:
        del subscription_id
        raise BillingProviderCapabilityError(
            "Zdalna rekonsyliacja nie jest dostępna w symulatorze płatności."
        )
