from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import stripe
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class BillingProviderError(RuntimeError):
    pass


class BillingProviderCapabilityError(BillingProviderError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderAddress:
    """Where the buyer is, which is what decides the VAT rate (ADR-040).

    Stripe Tax refuses to compute without it, so this is required data rather
    than a nicety — the organization fills it in before it can pay.
    """

    line1: str
    postal_code: str
    city: str
    country: str


@dataclass(frozen=True, slots=True)
class ProviderCustomer:
    id: str


@dataclass(frozen=True, slots=True)
class ProviderCheckout:
    id: str
    url: str
    expires_at: datetime | None
    completed: bool = False
    setup_intent_id: str = ""


@dataclass(frozen=True, slots=True)
class ProviderPortal:
    id: str
    url: str


@dataclass(frozen=True, slots=True)
class ProviderPrice:
    id: str
    product_id: str
    active: bool
    livemode: bool
    currency: str
    unit_amount_minor: int
    recurring_interval: str
    recurring_interval_count: int


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    id: str
    status: str
    trial_start: datetime
    trial_end: datetime
    current_period_start: datetime | None
    current_period_end: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderSubscriptionSnapshot:
    id: str
    customer_id: str
    price_id: str
    status: str
    livemode: bool
    current_period_start: datetime | None
    current_period_end: datetime | None
    trial_start: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    canceled_at: datetime | None
    ended_at: datetime | None


class BillingProvider(Protocol):
    def create_customer(
        self,
        *,
        email: str,
        name: str,
        address: ProviderAddress,
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
        currency: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> ProviderCheckout: ...

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
    ) -> ProviderCheckout: ...

    def create_portal(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> ProviderPortal: ...

    def retrieve_price(self, price_id: str) -> ProviderPrice: ...

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

    def retrieve_subscription(
        self,
        subscription_id: str,
    ) -> ProviderSubscriptionSnapshot: ...


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
        address: ProviderAddress,
        organization_id: str,
        idempotency_key: str,
    ) -> ProviderCustomer:
        try:
            customer = self.client.v1.customers.create(
                {
                    "email": email,
                    "name": name,
                    # Stripe Tax reads the rate off this address; without it a
                    # subscription with automatic_tax is refused outright.
                    "address": {
                        "line1": address.line1,
                        "postal_code": address.postal_code,
                        "city": address.city,
                        "country": address.country,
                    },
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
        currency: str,
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
                    # Setup mode charges nothing, but the current API still
                    # requires a currency and refuses the session without it.
                    "currency": currency.lower(),
                    "payment_method_types": ["card"],
                    "client_reference_id": organization_id,
                    # ADR-040: the address decides the rate and the VAT number
                    # decides whether it is reverse charged, so both are
                    # collected here and written back onto the Customer. Stripe
                    # validates the number in VIES; we do not.
                    "billing_address_collection": "required",
                    "tax_id_collection": {"enabled": True},
                    "customer_update": {"address": "auto", "name": "auto"},
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
        """One-off payment for a credit pack — never a subscription.

        The portal cannot sell this and never will, so it is its own Checkout
        opened from our panel (ADR-040 §4). Confirmation comes from the
        webhook; the browser coming back proves nothing.
        """
        metadata = {
            "saas_core_organization_id": organization_id,
            "saas_core_credit_purchase_id": purchase_id,
        }
        try:
            checkout = self.client.v1.checkout.sessions.create(
                {
                    "mode": "payment",
                    "customer": customer_id,
                    "line_items": [{"price": price_id, "quantity": 1}],
                    "client_reference_id": organization_id,
                    "automatic_tax": {"enabled": True},
                    "billing_address_collection": "required",
                    "tax_id_collection": {"enabled": True},
                    "customer_update": {"address": "auto", "name": "auto"},
                    "invoice_creation": {"enabled": True},
                    "metadata": metadata,
                    "payment_intent_data": {"metadata": metadata},
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
                {"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił Checkout pakietu kredytów.") from error
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
        # The configuration is named rather than left to the account default:
        # the default can be changed in the dashboard and no review would see
        # it (ADR-040).
        configuration = settings.STRIPE_PORTAL_CONFIGURATION_ID
        try:
            portal = self.client.v1.billing_portal.sessions.create(
                {
                    "customer": customer_id,
                    "return_url": return_url,
                    **({"configuration": configuration} if configuration else {}),
                }
            )
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił utworzenie Customer Portal.") from error
        return ProviderPortal(
            _required_attribute(portal, "id"),
            _required_attribute(portal, "url"),
        )

    def retrieve_price(self, price_id: str) -> ProviderPrice:
        try:
            price = self.client.v1.prices.retrieve(price_id)
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe nie zwrócił konfiguracji Price.") from error

        recurring = getattr(price, "recurring", None)
        if recurring is None:
            raise BillingProviderError("Stripe Price nie jest ceną cykliczną.")
        return ProviderPrice(
            id=_required_attribute(price, "id"),
            product_id=_reference_id(getattr(price, "product", None), "product"),
            active=_required_boolean(price, "active"),
            livemode=_required_boolean(price, "livemode"),
            currency=_required_attribute(price, "currency").upper(),
            unit_amount_minor=_required_nonnegative_integer(price, "unit_amount"),
            recurring_interval=_required_attribute(recurring, "interval"),
            recurring_interval_count=_required_positive_integer(recurring, "interval_count"),
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
                    "automatic_tax": {"enabled": True},
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

    def retrieve_subscription(
        self,
        subscription_id: str,
    ) -> ProviderSubscriptionSnapshot:
        try:
            subscription = self.client.v1.subscriptions.retrieve(subscription_id)
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe odrzucił pobranie subskrypcji.") from error
        items = getattr(subscription, "items", None)
        rows = getattr(items, "data", None)
        if not isinstance(rows, list) or len(rows) != 1:
            raise BillingProviderError("Subskrypcja Stripe musi mieć dokładnie jeden Price.")
        price_id = _reference_id(getattr(rows[0], "price", None), "price")
        period_start, period_end = _subscription_period(subscription)
        trial_start, trial_end = _optional_timestamp_pair(
            subscription,
            "trial_start",
            "trial_end",
        )
        livemode = getattr(subscription, "livemode", None)
        if not isinstance(livemode, bool):
            raise BillingProviderError("Stripe nie zwrócił trybu subskrypcji.")
        return ProviderSubscriptionSnapshot(
            id=_required_attribute(subscription, "id"),
            customer_id=_reference_id(getattr(subscription, "customer", None), "customer"),
            price_id=price_id,
            status=_required_attribute(subscription, "status"),
            livemode=livemode,
            current_period_start=period_start,
            current_period_end=period_end,
            trial_start=trial_start,
            trial_end=trial_end,
            cancel_at_period_end=getattr(subscription, "cancel_at_period_end", False) is True,
            canceled_at=_optional_timestamp_value(getattr(subscription, "canceled_at", None)),
            ended_at=_optional_timestamp_value(getattr(subscription, "ended_at", None)),
        )


def get_billing_provider() -> BillingProvider:
    if settings.BILLING_PROVIDER == "stripe":
        return StripeBillingProvider()
    if settings.BILLING_PROVIDER == "simulated":
        from .simulated_provider import SimulatedBillingProvider

        return SimulatedBillingProvider()
    raise ImproperlyConfigured("Nieobsługiwany BILLING_PROVIDER")


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


def _required_boolean(value: Any, field: str) -> bool:
    raw = getattr(value, field, None)
    if not isinstance(raw, bool):
        raise BillingProviderError(f"Stripe nie zwrócił pola logicznego {field}.")
    return raw


def _required_nonnegative_integer(value: Any, field: str) -> int:
    raw = getattr(value, field, None)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise BillingProviderError(f"Stripe nie zwrócił poprawnej liczby {field}.")
    return raw


def _required_positive_integer(value: Any, field: str) -> int:
    raw = _required_nonnegative_integer(value, field)
    if raw == 0:
        raise BillingProviderError(f"Stripe nie zwrócił dodatniej liczby {field}.")
    return raw


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


def _optional_timestamp_pair(
    value: Any,
    start_field: str,
    end_field: str,
) -> tuple[datetime | None, datetime | None]:
    start = _optional_timestamp_value(getattr(value, start_field, None))
    end = _optional_timestamp_value(getattr(value, end_field, None))
    if (start is None) != (end is None) or (start is not None and end is not None and end <= start):
        raise BillingProviderError("Stripe zwrócił nieprawidłowe okno czasowe.")
    return start, end


def _optional_timestamp_value(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise BillingProviderError("Stripe zwrócił nieprawidłowy timestamp.")
    return datetime.fromtimestamp(raw, tz=UTC)
