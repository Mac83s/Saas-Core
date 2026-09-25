from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import stripe
from django.core.management import call_command
from django.test import override_settings

from saas_core.modules.shared.billing.models import Plan, PlanVersion, StripePriceMapping

pytestmark = pytest.mark.django_db

DEPLOYMENT_PLAN_KEYS = ("profile", "starter", "pro")


@pytest.fixture(autouse=True)
def deployment_catalog(settings: Any) -> None:
    settings.BILLING_PLAN_KEYS = DEPLOYMENT_PLAN_KEYS


class FakeStripe:
    """An in-memory Stripe account with just the calls the command makes."""

    def __init__(self) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.prices: dict[str, SimpleNamespace] = {}
        self.v1 = SimpleNamespace(
            products=SimpleNamespace(update=self._update_product, create=self._create_product),
            prices=SimpleNamespace(
                list=self._list_prices,
                update=self._update_price,
                create=self._create_price,
            ),
            billing_portal=SimpleNamespace(
                configurations=SimpleNamespace(update=lambda *args, **kwargs: None)
            ),
        )

    def _update_product(self, product_id: str, payload: dict[str, Any]) -> SimpleNamespace:
        if product_id not in self.products:
            raise stripe.InvalidRequestError("No such product", "id")  # type: ignore[no-untyped-call]
        self.products[product_id].update(payload)
        return SimpleNamespace(id=product_id)

    def _create_product(self, payload: dict[str, Any]) -> SimpleNamespace:
        self.products[payload["id"]] = dict(payload)
        return SimpleNamespace(id=payload["id"])

    def _list_prices(self, params: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(
            data=[
                price
                for price in self.prices.values()
                if price.product == params["product"] and price.active == params["active"]
            ]
        )

    def _update_price(self, price_id: str, payload: dict[str, Any]) -> SimpleNamespace:
        self.prices[price_id].active = payload["active"]
        return self.prices[price_id]

    def _create_price(self, payload: dict[str, Any]) -> SimpleNamespace:
        price_id = f"price_fake_{len(self.prices) + 1}"
        recurring = payload.get("recurring")
        self.prices[price_id] = SimpleNamespace(
            id=price_id,
            product=payload["product"],
            unit_amount=payload["unit_amount"],
            currency=payload["currency"],
            tax_behavior=payload["tax_behavior"],
            recurring=SimpleNamespace(interval=recurring["interval"]) if recurring else None,
            active=True,
        )
        return self.prices[price_id]


def active_mapping(version: PlanVersion) -> StripePriceMapping:
    return StripePriceMapping.objects.get(plan_version=version, livemode=False, is_active=True)


@override_settings(
    BILLING_PROVIDER="stripe",
    STRIPE_SECRET_KEY="sk_test_catalog",
    STRIPE_LIVEMODE=False,
    STRIPE_PORTAL_CONFIGURATION_ID="",
)
def test_new_plan_version_with_unchanged_price_gets_its_own_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = FakeStripe()
    monkeypatch.setattr(stripe, "StripeClient", lambda *args, **kwargs: account)
    plan = (
        Plan.objects.select_related("current_version")
        .filter(key__in=DEPLOYMENT_PLAN_KEYS, current_version__unit_amount_minor__gt=0)
        .order_by("key")
        .first()
    )
    assert plan is not None and plan.current_version is not None
    call_command("provision_stripe_catalog")
    previous = plan.current_version
    previous_price_id = active_mapping(previous).stripe_price_id

    # A data migration adding a feature publishes a new version at the same
    # amount; the Stripe price still matches it, but it already names the
    # previous version for every subscription sold on it.
    current = PlanVersion.objects.create(
        plan=plan,
        version=previous.version + 1,
        currency=previous.currency,
        billing_interval=previous.billing_interval,
        unit_amount_minor=previous.unit_amount_minor,
        feature_keys=previous.feature_keys,
        quotas=previous.quotas,
        trial_days=previous.trial_days,
        grace_period_days=previous.grace_period_days,
    )
    plan.current_version = current
    plan.save(update_fields=["current_version", "updated_at"])

    call_command("provision_stripe_catalog")

    current_price_id = active_mapping(current).stripe_price_id
    assert current_price_id != previous_price_id
    assert account.prices[current_price_id].unit_amount == previous.unit_amount_minor
    assert account.prices[current_price_id].active is True
    # The old price stops being offered, but still resolves to the version
    # its subscribers bought.
    assert account.prices[previous_price_id].active is False
    assert (
        StripePriceMapping.objects.get(stripe_price_id=previous_price_id).plan_version_id
        == previous.id
    )

    prices_before_rerun = set(account.prices)
    call_command("provision_stripe_catalog")

    assert set(account.prices) == prices_before_rerun
    assert active_mapping(current).stripe_price_id == current_price_id
