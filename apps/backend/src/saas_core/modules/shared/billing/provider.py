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


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    id: str
    status: str
    trial_start: datetime
    trial_end: datetime
    current_period_start: datetime | None
    current_period_end: datetime | None


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

    def create_trial_subscription(
        self,
        *,
        customer_id: str,
        setup_intent_id: str,
        price_id: str,
        organization_id: str,
        plan_version_id: str,
        trial_days: int,
        idempotency_key: str,
    ) -> ProviderSubscription: ...


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

    def create_trial_subscription(
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
        try:
            setup_intent = self.client.v1.setup_intents.retrieve(setup_intent_id)
            if _required_attribute(setup_intent, "status") != "succeeded":
                raise BillingProviderError("SetupIntent nie został zakończony.")
            if _reference_id(getattr(setup_intent, "customer", None), "customer") != customer_id:
                raise BillingProviderError("SetupIntent wskazuje innego Customer.")
            payment_method_id = _reference_id(
                getattr(setup_intent, "payment_method", None),
                "payment_method",
            )
            subscription = self.client.v1.subscriptions.create(
                {
                    "customer": customer_id,
                    "items": [{"price": price_id, "quantity": 1}],
                    "default_payment_method": payment_method_id,
                    "trial_period_days": trial_days,
                    "trial_settings": {"end_behavior": {"missing_payment_method": "cancel"}},
                    "metadata": {
                        "saas_core_organization_id": organization_id,
                        "saas_core_plan_version_id": plan_version_id,
                    },
                },
                {"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił aktywację triala.") from error

        status = _required_attribute(subscription, "status")
        if status != "trialing":
            raise BillingProviderError("Stripe nie utworzył subskrypcji w stanie trialing.")
        trial_start = _required_timestamp(subscription, "trial_start")
        trial_end = _required_timestamp(subscription, "trial_end")
        if trial_end <= trial_start:
            raise BillingProviderError("Stripe zwrócił nieprawidłowe okno triala.")
        period_start, period_end = _subscription_period(subscription)
        return ProviderSubscription(
            id=_required_attribute(subscription, "id"),
            status=status,
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=period_start,
            current_period_end=period_end,
        )


def get_billing_provider() -> BillingProvider:
    return StripeBillingProvider()


def _required_attribute(value: Any, field: str) -> str:
    attribute = getattr(value, field, None)
    if not isinstance(attribute, str) or not attribute:
        raise BillingProviderError(f"Stripe nie zwrócił pola {field}.")
    return attribute


def _reference_id(value: Any, field: str) -> str:
    if isinstance(value, str) and value:
        return value
    return _required_attribute(value, "id") if value is not None else _missing_reference(field)


def _missing_reference(field: str) -> str:
    raise BillingProviderError(f"Stripe nie zwrócił referencji {field}.")


def _required_timestamp(value: Any, field: str) -> datetime:
    raw = getattr(value, field, None)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise BillingProviderError(f"Stripe nie zwrócił timestampu {field}.")
    return datetime.fromtimestamp(raw, tz=UTC)


def _subscription_period(subscription: Any) -> tuple[datetime | None, datetime | None]:
    raw_start = getattr(subscription, "current_period_start", None)
    raw_end = getattr(subscription, "current_period_end", None)
    if raw_start is None and raw_end is None:
        items = getattr(subscription, "items", None)
        rows = getattr(items, "data", None)
        if isinstance(rows, list) and len(rows) == 1:
            raw_start = getattr(rows[0], "current_period_start", None)
            raw_end = getattr(rows[0], "current_period_end", None)
    if raw_start is None and raw_end is None:
        return None, None
    if (
        not isinstance(raw_start, int)
        or isinstance(raw_start, bool)
        or not isinstance(raw_end, int)
        or isinstance(raw_end, bool)
        or raw_end <= raw_start
    ):
        raise BillingProviderError("Stripe zwrócił nieprawidłowy okres subskrypcji.")
    return datetime.fromtimestamp(raw_start, tz=UTC), datetime.fromtimestamp(raw_end, tz=UTC)
