"""Organization types the product declares (ADR-050).

The gate is proven here through the API; that it holds under RLS on a running
stack is recorded in the handoff, because this database connects as the owner.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.config.composition import CompositionError, organization_types_from
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.overview import public_plan_catalog
from saas_core.modules.shared.billing.plan_offer import plan_keys_for_type
from test_organization_api import (
    ORGANIZATIONS_URL,
    active_user,
    csrf_value,
    login,
    membership_for,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def with_types(settings: Any, **types: Any) -> None:
    settings.ORGANIZATION_TYPES = types
    settings.DEFAULT_ORGANIZATION_TYPE = next(iter(types))


def business() -> Any:
    """The profile's default type, renamed `business` — tests below set types
    themselves, so they hold in Saas-Core and in every product repository."""
    return replace(
        settings.ORGANIZATION_TYPES[settings.DEFAULT_ORGANIZATION_TYPE], key="business", roles=()
    )


def test_the_profile_types_stay_inside_the_profile() -> None:
    composed = {module for module in settings.ACTIVE_MODULES if not module.startswith("core.")}
    assert next(iter(settings.ORGANIZATION_TYPES)) == settings.DEFAULT_ORGANIZATION_TYPE
    for organization_type in settings.ORGANIZATION_TYPES.values():
        assert organization_type.modules <= composed
        assert set(organization_type.plan_keys) <= set(settings.BILLING_PLAN_KEYS)
    assert Organization().organization_type == settings.DEFAULT_ORGANIZATION_TYPE


def test_a_type_may_not_use_a_module_the_profile_does_not_compose() -> None:
    artifact = {
        "organizationTypes": [
            {
                "key": "farm",
                "label": {"pl": "Gospodarstwo", "en": "Farm"},
                "modules": ["vertical.nothing"],
                "planKeys": [],
                "selfSignup": True,
            }
        ]
    }
    with pytest.raises(CompositionError, match="vertical.nothing"):
        organization_types_from(artifact, ("core.identity",))
    with pytest.raises(CompositionError, match="deployment:artifact"):
        organization_types_from({}, ("core.identity",))


def test_a_new_organization_takes_the_only_offered_type_or_a_chosen_one(
    settings: Any,
) -> None:
    with_types(settings, business=business())
    client = APIClient()
    user = active_user()
    login(client, user)
    body = {"name": "Nowa", "slug": "nowa"}

    created = client.post(
        ORGANIZATIONS_URL, body, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )
    assert created.status_code == 201, created.data
    assert created.data["organization_type"] == "business"

    with_types(
        settings,
        business=business(),
        farm=replace(business(), key="farm", modules=frozenset({"shared.booking"})),
        hidden=replace(business(), key="hidden", self_signup=False),
    )
    ambiguous = client.post(
        ORGANIZATIONS_URL,
        {"name": "Druga", "slug": "druga"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert ambiguous.status_code == 400
    assert "organization_type" in str(ambiguous.data)

    refused = client.post(
        ORGANIZATIONS_URL,
        {"name": "Ukryta", "slug": "ukryta", "organization_type": "hidden"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert refused.status_code == 400

    farm = client.post(
        ORGANIZATIONS_URL,
        {"name": "Gospodarstwo", "slug": "gospodarstwo", "organization_type": "farm"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert farm.status_code == 201, farm.data
    assert farm.data["organization_type"] == "farm"


def test_an_organization_cannot_call_a_module_its_type_does_not_have(settings: Any) -> None:
    with_types(settings, business=business())
    client = APIClient()
    user = active_user()
    membership = membership_for(user)
    Organization.objects.filter(pk=membership.organization_id).update(
        organization_type="business"
    )
    login(client, user)

    # Billing's overview asks for a permission, not a plan, so it answers any owner.
    assert client.get("/api/v1/billing/overview/").status_code == 200

    with_types(settings, business=replace(business(), modules=frozenset({"shared.booking"})))
    gated = client.get("/api/v1/billing/overview/")
    assert gated.status_code == 404
    assert gated.json()["code"] == "module_not_available"
    # Core stays reachable whatever the type: it belongs to every organization.
    assert client.get("/api/v1/organizations/current/").status_code == 200


def test_plans_are_offered_per_type(settings: Any) -> None:
    first, *rest = settings.BILLING_PLAN_KEYS
    with_types(
        settings,
        business=replace(business(), plan_keys=tuple(rest)),
        farm=replace(business(), key="farm", plan_keys=(first,)),
    )

    assert plan_keys_for_type("farm") == (first,)
    assert plan_keys_for_type("unknown") == ()
    assert [plan["key"] for plan in public_plan_catalog("farm")] == [first]
    assert [plan["key"] for plan in public_plan_catalog()] == list(rest)


def test_a_new_organization_gets_the_free_plan_of_its_type(settings: Any) -> None:
    """Rolnik nie kupuje własnego rejestru: darmowy plan typu nadaje się sam."""
    from saas_core.modules.shared.billing.models import (  # noqa: PLC0415
        EntitlementSnapshot,
        Plan,
        PlanVersion,
    )
    from saas_core.modules.shared.billing.plan_offer import (  # noqa: PLC0415
        plan_keys_for_type,
    )

    paid_key, *_ = settings.BILLING_PLAN_KEYS
    paid = Plan.objects.get(key=paid_key)
    assert paid.current_version is not None
    free_plan = Plan.objects.create(key="free_test", name="Darmowy", is_public=True)
    free_version = PlanVersion.objects.create(
        plan=free_plan,
        version=1,
        currency=paid.current_version.currency,
        billing_interval=paid.current_version.billing_interval,
        unit_amount_minor=0,
        feature_keys=list(paid.current_version.feature_keys),
        quotas=dict(paid.current_version.quotas),
        trial_days=0,
        grace_period_days=0,
    )
    free_plan.current_version = free_version
    free_plan.save(update_fields=["current_version"])
    settings.BILLING_PLAN_KEYS = (*settings.BILLING_PLAN_KEYS, "free_test")
    with_types(
        settings,
        business=replace(business(), plan_keys=(paid_key,)),
        farm=replace(business(), key="farm", plan_keys=("free_test",)),
    )
    assert plan_keys_for_type("farm") == ("free_test",)

    client = APIClient()
    user = active_user(email="rolnik-darmowy@example.test")
    login(client, user)
    response = client.post(
        ORGANIZATIONS_URL,
        {
            "name": "Gospodarstwo Darmowe",
            "slug": "gospodarstwo-darmowe",
            "organization_type": "farm",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 201

    organization = Organization.objects.get(slug="gospodarstwo-darmowe")
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert snapshot.features == {key: True for key in free_version.feature_keys}
    assert all(entry["ref"] == "free_test:v1" for entry in snapshot.sources.values())

    # Firma nie ma darmowego planu swojego typu, więc nic nie dostaje.
    company_user = active_user(email="firma-platna@example.test")
    login(client, company_user)
    response = client.post(
        ORGANIZATIONS_URL,
        {
            "name": "Firma Płatna",
            "slug": "firma-platna",
            "organization_type": "business",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 201
    company = Organization.objects.get(slug="firma-platna")
    assert not EntitlementSnapshot.all_objects.filter(organization=company).exists()
