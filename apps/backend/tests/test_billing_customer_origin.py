"""A customer id belongs to the provider and mode that issued it.

Switching this deployment from the simulator to Stripe made the point the hard
way: the organization still carried a ``sim_customer_…``, Stripe answered
``No such customer``, and every checkout came back 502. The same wall stands
between test and live, where both ids look like ``cus_…`` and only the mode
tells them apart.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing import services
from saas_core.modules.shared.billing.models import Plan, StripePriceMapping
from saas_core.modules.shared.billing.overview import customer_billing_overview
from saas_core.modules.shared.billing.provider import ProviderCheckout, ProviderCustomer
from saas_core.modules.shared.billing.services import (
    create_setup_checkout,
    reusable_customer_id,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_catalog(settings: Any) -> None:
    settings.BILLING_PLAN_KEYS = ("profile", "starter", "pro")


class FakeProvider:
    def __init__(self) -> None:
        self.created_customers: list[dict[str, Any]] = []
        self.checkout_customers: list[str] = []

    def create_customer(self, **kwargs: Any) -> ProviderCustomer:
        self.created_customers.append(kwargs)
        return ProviderCustomer("cus_fresh")

    def create_setup_checkout(self, **kwargs: Any) -> ProviderCheckout:
        self.checkout_customers.append(kwargs["customer_id"])
        return ProviderCheckout("cs_origin", "https://checkout.stripe.test/cs", None)


def profile_for(
    *,
    slug: str,
    customer_id: str = "",
    provider: str = "",
    livemode: bool | None = None,
) -> tuple[BillingProfile, TenantContext]:
    organization = Organization.objects.create(name=slug, slug=slug)
    profile = BillingProfile.objects.create(
        organization=organization,
        legal_name="Firma testowa",
        billing_email="billing@example.com",
        country_code="PL",
        address_line1="Testowa 1",
        postal_code="00-001",
        city="Warszawa",
        external_customer_id=customer_id,
        external_customer_provider=provider,
        external_customer_livemode=livemode,
    )
    actor = User.objects.create_user(email=f"{slug}@example.com")
    return profile, TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset({BILLING_MANAGE}),
    )


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_a_simulator_customer_is_not_offered_to_stripe() -> None:
    profile, _context = profile_for(
        slug="origin-sim",
        customer_id="sim_customer_abc",
        provider="simulated",
    )

    assert reusable_customer_id(profile) == ""


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=True)
def test_a_test_mode_customer_is_not_reused_in_live_mode() -> None:
    profile, _context = profile_for(
        slug="origin-test",
        customer_id="cus_test",
        provider="stripe",
        livemode=False,
    )

    assert reusable_customer_id(profile) == ""


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_a_customer_from_the_same_space_is_reused() -> None:
    profile, _context = profile_for(
        slug="origin-same",
        customer_id="cus_same",
        provider="stripe",
        livemode=False,
    )

    assert reusable_customer_id(profile) == "cus_same"


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_an_unstamped_customer_is_assumed_to_belong_here() -> None:
    """Rows written before the stamp existed must not grow a second identity."""
    profile, _context = profile_for(slug="origin-old", customer_id="cus_old")

    assert reusable_customer_id(profile) == "cus_old"


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_the_checkout_replaces_a_foreign_customer_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, context = profile_for(
        slug="origin-checkout",
        customer_id="sim_customer_stale",
        provider="simulated",
    )
    StripePriceMapping.objects.create(
        plan_version=Plan.objects.get(key="starter").current_version,
        stripe_product_id="prod_origin",
        stripe_price_id="price_origin",
        livemode=False,
    )
    provider = FakeProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)

    with activate_tenant_context(context):
        create_setup_checkout(plan_key="starter", idempotency_key="origin-one")

    profile.refresh_from_db()
    assert len(provider.created_customers) == 1
    assert provider.checkout_customers == ["cus_fresh"]
    assert profile.external_customer_id == "cus_fresh"
    assert profile.external_customer_provider == "stripe"
    assert profile.external_customer_livemode is False


@override_settings(BILLING_PROVIDER="stripe", STRIPE_LIVEMODE=False)
def test_the_portal_is_not_offered_for_a_customer_stripe_does_not_know() -> None:
    _profile, context = profile_for(
        slug="origin-portal",
        customer_id="sim_customer_portal",
        provider="simulated",
    )

    with activate_tenant_context(context):
        overview = customer_billing_overview()

    assert overview["portal_available"] is False
