from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import stripe
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class BillingProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderCustomer:
    id: str


@dataclass(frozen=True, slots=True)
class ProviderCheckout:
    id: str
    url: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderPortal:
    id: str
    url: str


class BillingProvider(Protocol):
    def create_customer(
        self,
        *,
        email: str,
        name: str,
        organization_id: str,
        idempotency_key: str,
    ) -> ProviderCustomer: ...

    def create_setup_checkout(
        self,
        *,
        customer_id: str,
        organization_id: str,
        plan_version_id: str,
        price_mapping_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> ProviderCheckout: ...

    def create_portal(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> ProviderPortal: ...


class StripeBillingProvider:
    def __init__(self) -> None:
        if not settings.STRIPE_SECRET_KEY:
            raise ImproperlyConfigured("STRIPE_SECRET_KEY jest wymagany")
        self.client = stripe.StripeClient(
            settings.STRIPE_SECRET_KEY,
            stripe_version=settings.STRIPE_API_VERSION,
            max_network_retries=2,
        )

    def create_customer(
        self,
        *,
        email: str,
        name: str,
        organization_id: str,
        idempotency_key: str,
    ) -> ProviderCustomer:
        try:
            customer = self.client.v1.customers.create(
                {
                    "email": email,
                    "name": name,
                    "metadata": {"saas_core_organization_id": organization_id},
                },
                {"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił utworzenie Customer.") from error
        return ProviderCustomer(_required_attribute(customer, "id"))

    def create_setup_checkout(
        self,
        *,
        customer_id: str,
        organization_id: str,
        plan_version_id: str,
        price_mapping_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> ProviderCheckout:
        metadata = {
            "saas_core_organization_id": organization_id,
            "saas_core_plan_version_id": plan_version_id,
            "saas_core_price_mapping_id": price_mapping_id,
        }
        try:
            checkout = self.client.v1.checkout.sessions.create(
                {
                    "mode": "setup",
                    "customer": customer_id,
                    "payment_method_types": ["card"],
                    "client_reference_id": organization_id,
                    "metadata": metadata,
                    "setup_intent_data": {"metadata": metadata},
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
                {"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił utworzenie Checkout.") from error
        raw_expiry = getattr(checkout, "expires_at", None)
        expires_at = (
            datetime.fromtimestamp(raw_expiry, tz=UTC)
            if isinstance(raw_expiry, int) and not isinstance(raw_expiry, bool)
            else None
        )
        return ProviderCheckout(
            _required_attribute(checkout, "id"),
            _required_attribute(checkout, "url"),
            expires_at,
        )

    def create_portal(self, *, customer_id: str, return_url: str) -> ProviderPortal:
        try:
            portal = self.client.v1.billing_portal.sessions.create({
                "customer": customer_id,
                "return_url": return_url,
            })
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił utworzenie Customer Portal.") from error
        return ProviderPortal(
            _required_attribute(portal, "id"),
            _required_attribute(portal, "url"),
        )


def get_billing_provider() -> BillingProvider:
    return StripeBillingProvider()


def _required_attribute(value: Any, field: str) -> str:
    attribute = getattr(value, field, None)
    if not isinstance(attribute, str) or not attribute:
        raise BillingProviderError(f"Stripe nie zwrócił pola {field}.")
    return attribute
