"""A product's words for the settings registry (UX-082, ADR-078 addendum)."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from saas_core.modules.core.organizations import command_registry, settings_registry
from saas_core.modules.core.organizations.basic_settings import organization_options
from saas_core.modules.core.organizations.command_registry import command
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.security_settings import MFA_REQUIRED
from saas_core.modules.core.organizations.settings_registry import (
    relabel_settings,
    relabeled_group_keys,
    setting_group,
    setting_spec,
    unrelabeled_group,
)
from test_booking import membership
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

SECURITY = "organization.security"
READ = "organization.settings_security.read@1"
SCHEMA = "/api/v1/organizations/current/settings/schema/"


@pytest.fixture(autouse=True)
def own_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every relabel here stays in this test: the registry and the commands are
    the process's, and the rest of the suite reads core's words."""
    for name in ("_groups", "_keys", "_areas", "_base_groups", "_base_areas"):
        monkeypatch.setattr(settings_registry, name, dict(getattr(settings_registry, name)))
    monkeypatch.setattr(settings_registry, "_type_words", {})
    monkeypatch.setattr(command_registry, "_commands", dict(command_registry._commands))


def words(pl: str, en: str) -> dict[str, str]:
    return {"pl": pl, "en": en}


def security_in(schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    group = next(item for item in schema["groups"] if item["key"] == SECURITY)
    area = next(item for item in schema["areas"] if item["key"] == "security")
    return group, area


def test_a_products_words_reach_the_schema_the_options_and_the_commands() -> None:
    read_before = command(READ)
    # A product suite runs this too, with its own words already in the registry.
    labels_before = {value: labels["pl"] for value, labels in setting_spec(MFA_REQUIRED).values}
    relabel_settings({
        "area:security.title": words("Bezpieczeństwo gabinetu", "Practice security"),
        f"group:{SECURITY}.description": words(
            "Czy personel gabinetu loguje się z 2FA.", "Whether the practice's staff use 2FA."
        ),
        f"setting:{MFA_REQUIRED}.label": words("Wymagaj 2FA od personelu", "Require 2FA of staff"),
        f"setting:{MFA_REQUIRED}.value:managers": words("Rejestracja i właściciel", "Front desk"),
        "setting:organization.currency.label": words("Waluta gabinetu", "Practice currency"),
    })

    group, area = security_in(authenticated_client(membership("relabel")).get(SCHEMA).json())
    assert area["title"] == words("Bezpieczeństwo gabinetu", "Practice security")
    assert group["description"]["pl"] == "Czy personel gabinetu loguje się z 2FA."
    (entry,) = group["keys"]
    assert entry["label"]["pl"] == "Wymagaj 2FA od personelu"
    assert [value["label"]["pl"] for value in entry["values"]] == [
        labels_before["none"],
        "Rejestracja i właściciel",
        labels_before["all"],
    ]
    # Only words: the key, the type, the values and the default stay core's.
    assert (entry["key"], entry["type"], entry["default"]) == (MFA_REQUIRED, "enum", "none")
    assert [value["value"] for value in entry["values"]] == ["none", "managers", "all"]

    # An options endpoint reads its module's constants; the registry's words win.
    currency = next(
        key for key in organization_options()["keys"] if key["key"] == "organization.currency"
    )
    assert currency["label"]["pl"] == "Waluta gabinetu"

    # The assistant reads the same words; only the texts of its command changed.
    read = command(READ)
    assert read.summary["pl"] == "Czy personel gabinetu loguje się z 2FA."
    assert "Whether the practice's staff use 2FA." in read.model_description
    assert read.input_schema is read_before.input_schema
    assert (read.run, read.risk, read.tool_name) == (
        read_before.run,
        read_before.risk,
        read_before.tool_name,
    )
    # Core's words stay at hand for core's manifest.
    assert unrelabeled_group(SECURITY).description["pl"].startswith("Czy osoby w firmie")
    assert {SECURITY, "organization"} <= relabeled_group_keys()
    assert setting_group(SECURITY).spec("mfa_required") is setting_spec(MFA_REQUIRED)

    # The same words again change nothing.
    relabel_settings({
        f"setting:{MFA_REQUIRED}.label": words("Wymagaj 2FA od personelu", "Require 2FA of staff")
    })
    assert command(READ) == read


def test_an_address_nobody_registered_stops_the_start() -> None:
    relabeled_before = relabeled_group_keys()
    with pytest.raises(ImproperlyConfigured, match="nie ma takiego tekstu"):
        relabel_settings({"group:nobody.title": words("A", "B")})
    with pytest.raises(ImproperlyConfigured, match="nie ma takiej wartości"):
        relabel_settings({f"setting:{MFA_REQUIRED}.value:sometimes": words("A", "B")})
    with pytest.raises(ImproperlyConfigured, match="pl i en"):
        relabel_settings({f"group:{SECURITY}.title": {"pl": "Tylko pl"}})
    with pytest.raises(ImproperlyConfigured, match="area:, group: albo setting:"):
        relabel_settings({f"spec:{MFA_REQUIRED}.label": words("A", "B")})
    # A broken map changes nothing, not even its good addresses.
    with pytest.raises(ImproperlyConfigured):
        relabel_settings({
            f"group:{SECURITY}.title": words("Nowe", "New"),
            "group:nobody.title": words("A", "B"),
        })
    assert relabeled_group_keys() == relabeled_before


def test_a_types_words_reach_only_its_organizations() -> None:
    farm = membership("relabel-farm")
    company = membership("relabel-company")
    Organization.objects.filter(pk=farm.organization_id).update(organization_type="farm")
    Organization.objects.filter(pk=company.organization_id).update(organization_type="business")
    title_before = setting_group(SECURITY).title["pl"]
    command_before = command(READ).title
    relabeled_before = relabeled_group_keys()
    relabel_settings(
        {
            f"group:{SECURITY}.title": words("Bezpieczeństwo gospodarstwa", "Farm security"),
            f"setting:{MFA_REQUIRED}.label": words("Wymagaj 2FA w gospodarstwie", "Farm 2FA"),
        },
        organization_type="farm",
    )

    group, _ = security_in(authenticated_client(farm).get(SCHEMA).json())
    assert group["title"]["pl"] == "Bezpieczeństwo gospodarstwa"
    assert group["keys"][0]["label"]["pl"] == "Wymagaj 2FA w gospodarstwie"
    other, _ = security_in(authenticated_client(company).get(SCHEMA).json())
    assert other["title"]["pl"] == title_before
    # The registry, the commands and so the manifest keep the product's words.
    assert relabeled_group_keys() == relabeled_before
    assert command(READ).title == command_before
