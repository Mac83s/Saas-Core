from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from saas_core.modules.shared.billing.management.commands import configure_stripe_prices
from saas_core.modules.shared.billing.models import Plan, StripePriceMapping
from saas_core.modules.shared.billing.provider import (
    BillingProviderError,
    ProviderPrice,
    StripeBillingProvider,
)

pytestmark = pytest.mark.django_db

DEPLOYMENT_PLAN_KEYS = ("profile", "starter", "pro")


@pytest.fixture(autouse=True)
def deployment_catalog(settings: Any) -> None:
    settings.BILLING_PLAN_KEYS = DEPLOYMENT_PLAN_KEYS


def mapping(plan_key: str) -> str:
    return f"{plan_key}=prod_{plan_key},price_{plan_key}"


class FakePriceProvider:
    def __init__(self, prices: dict[str, ProviderPrice]) -> None:
        self.prices = prices
        self.calls: list[str] = []

    def retrieve_price(self, price_id: str) -> ProviderPrice:
        self.calls.append(price_id)
        try:
            return self.prices[price_id]
        except KeyError as error:
            raise BillingProviderError("Nieznany testowy Price.") from error


def catalog_provider(*, livemode: bool) -> FakePriceProvider:
    prices: dict[str, ProviderPrice] = {}
    for plan in Plan.objects.filter(
        is_active=True,
        is_public=True,
        current_version__isnull=False,
    ).select_related("current_version"):
        version = plan.current_version
        assert version is not None
        price_id = f"price_{plan.key}"
        prices[price_id] = ProviderPrice(
            id=price_id,
            product_id=f"prod_{plan.key}",
            active=True,
            livemode=livemode,
            currency=version.currency,
            unit_amount_minor=version.unit_amount_minor,
            recurring_interval=version.billing_interval,
            recurring_interval_count=1,
        )
    return FakePriceProvider(prices)


def public_plan_keys() -> list[str]:
    return list(
        Plan.objects.filter(
            is_active=True,
            is_public=True,
            current_version__isnull=False,
        ).values_list("key", flat=True)
    )


def command_arguments() -> list[str]:
    arguments: list[str] = []
    for key in public_plan_keys():
        arguments.extend(["--mapping", mapping(key)])
    return arguments


@override_settings(STRIPE_LIVEMODE=False)
def test_command_configures_and_checks_public_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_keys = public_plan_keys()
    provider = catalog_provider(livemode=False)
    monkeypatch.setattr(
        configure_stripe_prices,
        "get_billing_provider",
        lambda: provider,
    )
    arguments = command_arguments()

    call_command("configure_stripe_prices", *arguments, "--check")
    call_command("configure_stripe_prices", *arguments, "--check")

    assert StripePriceMapping.objects.filter(livemode=False, is_active=True).count() == len(
        plan_keys
    )
    assert sorted(provider.calls) == sorted([f"price_{key}" for key in plan_keys] * 2)


@override_settings(STRIPE_LIVEMODE=False)
def test_check_fails_when_a_public_plan_has_no_mapping() -> None:
    with pytest.raises(CommandError, match="Brak aktywnego Stripe Price"):
        call_command("configure_stripe_prices", "--check")


@override_settings(
    STRIPE_LIVEMODE=False,
    BILLING_PLAN_KEYS=("profile", "starter"),
)
def test_command_ignores_and_rejects_public_plans_outside_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = catalog_provider(livemode=False)
    monkeypatch.setattr(
        configure_stripe_prices,
        "get_billing_provider",
        lambda: provider,
    )

    call_command(
        "configure_stripe_prices",
        "--mapping",
        mapping("profile"),
        "--mapping",
        mapping("starter"),
        "--check",
    )

    assert sorted(provider.calls) == ["price_profile", "price_starter"]
    with pytest.raises(CommandError, match="nie jest aktywnym planem publicznym"):
        call_command("configure_stripe_prices", "--mapping", mapping("pro"))


@override_settings(STRIPE_LIVEMODE=False)
def test_reconfiguration_deactivates_previous_mapping() -> None:
    call_command("configure_stripe_prices", "--mapping", mapping("profile"))
    call_command(
        "configure_stripe_prices",
        "--mapping",
        "profile=prod_profile_v2,price_profile_v2",
    )

    current_version = Plan.objects.get(key="profile").current_version
    mappings = StripePriceMapping.objects.filter(plan_version=current_version, livemode=False)
    assert mappings.get(stripe_price_id="price_profile").is_active is False
    assert mappings.get(stripe_price_id="price_profile_v2").is_active is True


@override_settings(STRIPE_LIVEMODE=True)
def test_command_defaults_to_deployment_stripe_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = catalog_provider(livemode=True)
    monkeypatch.setattr(
        configure_stripe_prices,
        "get_billing_provider",
        lambda: provider,
    )

    call_command("configure_stripe_prices", *command_arguments(), "--check")

    assert StripePriceMapping.objects.filter(livemode=True, is_active=True).count() == len(
        public_plan_keys()
    )
    assert not StripePriceMapping.objects.filter(livemode=False).exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("active", False, "nieaktywny"),
        ("livemode", True, "tryb live/test"),
        ("product_id", "prod_wrong", "innego Product"),
        ("unit_amount_minor", 1, "kwota"),
        ("currency", "EUR", "waluta"),
        ("recurring_interval", "year", "interwał"),
        ("recurring_interval_count", 2, "każdy pojedynczy okres"),
    ],
)
@override_settings(STRIPE_LIVEMODE=False)
def test_check_rejects_provider_price_drift_and_rolls_back_configuration(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
    message: str,
) -> None:
    provider = catalog_provider(livemode=False)
    provider.prices["price_profile"] = replace(
        provider.prices["price_profile"],
        **{field: value},
    )
    monkeypatch.setattr(
        configure_stripe_prices,
        "get_billing_provider",
        lambda: provider,
    )

    with pytest.raises(CommandError, match=message):
        call_command("configure_stripe_prices", *command_arguments(), "--check")

    assert not StripePriceMapping.objects.exists()


@override_settings(STRIPE_SECRET_KEY="sk_test_local", STRIPE_API_VERSION="2026-07-29.dahlia")
def test_stripe_adapter_reads_recurring_price_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Prices:
        def retrieve(self, price_id: str) -> Any:
            assert price_id == "price_profile"
            return SimpleNamespace(
                id=price_id,
                product=SimpleNamespace(id="prod_profile"),
                active=True,
                livemode=False,
                currency="pln",
                unit_amount=9_900,
                recurring=SimpleNamespace(interval="month", interval_count=1),
            )

    fake_client = SimpleNamespace(v1=SimpleNamespace(prices=Prices()))
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.provider.stripe.StripeClient",
        lambda *args, **kwargs: fake_client,
    )

    result = StripeBillingProvider().retrieve_price("price_profile")

    assert result == ProviderPrice(
        id="price_profile",
        product_id="prod_profile",
        active=True,
        livemode=False,
        currency="PLN",
        unit_amount_minor=9_900,
        recurring_interval="month",
        recurring_interval_count=1,
    )


@override_settings(STRIPE_SECRET_KEY="sk_test_local", STRIPE_API_VERSION="2026-07-29.dahlia")
def test_stripe_adapter_rejects_non_recurring_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = SimpleNamespace(
        v1=SimpleNamespace(
            prices=SimpleNamespace(
                retrieve=lambda _price_id: SimpleNamespace(recurring=None),
            )
        )
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.billing.provider.stripe.StripeClient",
        lambda *args, **kwargs: fake_client,
    )

    with pytest.raises(BillingProviderError, match="cykliczną"):
        StripeBillingProvider().retrieve_price("price_one_time")
