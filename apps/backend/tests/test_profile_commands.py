"""What is particular to the business card commands (A1b-10): reading never
creates the card; a company without one gets it from its first change; a card
already in the public directory is public the moment it changes, so changing it
takes a click of its own."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

from command_evals.profiles import _fields
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.profiles.catalog import _place_entry
from saas_core.modules.shared.profiles.catalog_contract import (
    categories as catalog_categories,
)
from saas_core.modules.shared.profiles.models import PublicProfile
from test_command_evals import assistant, clicked, invocation, owner, writes

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def _no_card(slug: str, key: str) -> TenantContext:
    person = owner(slug, key)
    PublicProfile.all_objects.filter(organization_id=person.organization_id).delete()
    EntitlementSnapshot.all_objects.get_or_create(
        organization_id=person.organization_id,
        defaults={
            "subscription_state": SubscriptionState.ACTIVE,
            "access_mode": AccessMode.FULL,
            "features": {"profiles.enabled": True},
            "quotas": {},
            "sources": {},
        },
    )
    return person


def test_reading_never_creates_the_card() -> None:
    person = _no_card("card-read", "profiles.organization.read@1")
    with activate_tenant_context(assistant(person)), CaptureQueriesContext(connection) as queries:
        (result,) = execute_plan([invocation("profiles.organization.read@1", {})])

    assert result.status == "done", result
    assert result.output["exists"] is False
    assert writes(queries) == []
    assert not PublicProfile.all_objects.filter(organization_id=person.organization_id).exists()


def test_the_catalogue_options_carry_what_a_match_needs() -> None:
    """The card read lists keys only; matching „fryzjer w Olsztynie” to a
    category and a town needs the keywords and the names (A2)."""
    person = _no_card("card-options", "profiles.catalog_options.read@1")
    with activate_tenant_context(assistant(person)), CaptureQueriesContext(connection) as queries:
        (result,) = execute_plan([invocation("profiles.catalog_options.read@1", {})])

    assert result.status == "done", result
    categories = {entry["key"]: entry for entry in result.output["categories"]}
    # The profile's own dictionary: a product names its own categories.
    key, known = next(iter(catalog_categories(settings.DEFAULT_ORGANIZATION_TYPE).items()))
    assert categories[key]["keywords"]["pl"] == list(known.keywords["pl"])
    assert categories[key]["label"]["pl"]
    towns = {entry["slug"]: entry for entry in result.output["cities"]}
    assert towns["olsztyn"]["name"] == "Olsztyn"
    # The same keys the card accepts, in the catalogue's own order.
    with activate_tenant_context(assistant(person)):
        (card,) = execute_plan([invocation("profiles.organization.read@1", {})])
    assert sorted(categories) == card.output["categories"]
    assert sorted(towns) == card.output["cities"]
    assert writes(queries) == []


def test_a_company_without_a_card_gets_one_from_its_first_change() -> None:
    person = _no_card("card-first", "profiles.organization.update@1")
    acting = assistant(person)
    plan = [invocation("profiles.organization.update@1", _fields(headline="Domki nad jeziorem"))]
    with activate_tenant_context(acting):
        (group,) = preview_plan(plan).groups
    assert group.calls[0].preview.effects[0].kind == "created"

    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)

    assert result.status == "done", result
    card = PublicProfile.all_objects.get(organization_id=person.organization_id)
    assert card.headline == "Domki nad jeziorem"


def test_changing_a_listed_card_is_a_publication() -> None:
    person = owner("card-listed", "profiles.organization.update@1")
    card = PublicProfile.all_objects.get(organization_id=person.organization_id)
    _place_entry(card, person.organization_id)
    plan = [
        invocation("profiles.organization.update@1", _fields(headline="Nowe zdanie")),
        invocation(
            "organization.update@1",
            {
                "name": "Domki",
                "default_locale": None,
                "timezone": "Europe/Berlin",
                "currency": None,
            },
        ),
    ]
    with activate_tenant_context(assistant(person)):
        groups = preview_plan(plan).groups

    # The card's change has a click of its own; the company's settings share one.
    assert sorted((group.risk, len(group.calls)) for group in groups) == [
        ("apply", 1),
        ("publish", 1),
    ]
