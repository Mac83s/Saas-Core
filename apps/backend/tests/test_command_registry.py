"""The command registry refuses a declaration that breaks ADR-076 §1 at start.

A model calls what the registry offers with arguments it makes up, so the
contract is checked where it is declared, not where a conversation first trips
over it: a schema the strict tool mode cannot hold, an output field with no data
class, a permission no module grants, two commands under one tool name.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
from django.core.exceptions import ImproperlyConfigured

from saas_core.modules.core.organizations import command_registry
from saas_core.modules.core.organizations.command_registry import (
    CommandSpec,
    Preview,
    UnknownCommand,
    command,
    command_for_tool,
    command_tools,
    register_command,
    registered_commands,
    retitle_command,
)
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_registry, "_unretitled", {})
    monkeypatch.setattr(command_registry, "_unretitled", {})


def _run(arguments: Any, invocation: Any) -> dict[str, str]:
    return {"name": arguments["name"]}


def _preview(arguments: Any, invocation: Any) -> Preview:
    return Preview(effects=(), observed_versions={})


def spec(**changes: Any) -> CommandSpec:
    declaration: dict[str, Any] = {
        "name": "organization.update",
        "version": 1,
        "module": "core.organizations",
        "title": {"pl": "Zmień dane firmy", "en": "Update company details"},
        "summary": {"pl": "Nazwa firmy.", "en": "The company's name."},
        "model_description": "Renames the company. Use when the person asks to.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "address"],
            "properties": {
                "name": {"type": ["string", "null"], "description": "New name; null keeps it."},
                "address": {
                    "type": "object",
                    "description": "Where the company is.",
                    "additionalProperties": False,
                    "required": ["city"],
                    "properties": {"city": {"type": "string", "description": "City."}},
                },
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "x-data-class": "public"}},
        },
        "permission": SETTINGS_MANAGE,
        "risk": "apply",
        "run": _run,
        "undo": "restore_version",
        "preview": _preview,
        "version_field": "version",
    }
    declaration.update(changes)
    return CommandSpec(**declaration)


def test_a_declaration_registers_under_its_key_and_tool_name() -> None:
    register_command(spec())

    assert command("organization.update@1").tool_name == "organization_update_v1"
    assert command_for_tool("organization_update_v1").key == "organization.update@1"
    assert [entry.key for entry in registered_commands()] == ["organization.update@1"]
    with pytest.raises(UnknownCommand):
        command("organization.update@2")
    with pytest.raises(UnknownCommand):
        command_for_tool("organization_update_v2")


def test_tool_name_follows_the_adr_example() -> None:
    assert spec(name="booking.offer.create").tool_name == "booking_offer_create_v1"


def test_the_same_declaration_may_register_twice_and_a_different_one_may_not() -> None:
    register_command(spec())
    register_command(spec())

    with pytest.raises(ImproperlyConfigured, match="zarejestrowane inaczej"):
        register_command(spec(risk="publish"))


def test_a_product_retitles_a_command_and_nothing_else() -> None:
    """`relabel_settings` (UX-082): a product's words for a command another
    module registered; its name, schemas, risk and run stay the very same."""
    register_command(spec())
    before = command(spec().key)
    title = {"pl": "Odczytaj ustawienia gabinetu", "en": "Read the practice's settings"}
    summary = {"pl": "Ustawienia gabinetu.", "en": "The practice's settings."}

    retitle_command(before.key, title=title, summary=summary, model_description="Reads them.")
    after = command(before.key)
    assert (after.title, after.summary, after.model_description) == (
        title,
        summary,
        "Reads them.",
    )
    assert after.input_schema is before.input_schema
    assert after.output_schema is before.output_schema
    assert (after.run, after.risk, after.tool_name) == (before.run, before.risk, before.tool_name)
    # The same words again are no change, like registering the same declaration.
    retitle_command(before.key, title=title, summary=summary, model_description="Reads them.")
    assert command(before.key) == after
    # Its module declaring it again is no conflict either; the words stay.
    register_command(spec())
    assert command(before.key) == after

    with pytest.raises(ImproperlyConfigured):
        retitle_command(
            before.key, title={"pl": "", "en": "Read"}, summary=summary, model_description="x"
        )
    with pytest.raises(UnknownCommand):
        retitle_command("nobody.read@1", title=title, summary=summary, model_description="x")


def test_two_names_with_one_tool_name_are_refused() -> None:
    register_command(spec(name="organization.a_b"))

    with pytest.raises(ImproperlyConfigured, match="organization_a_b_v1"):
        register_command(spec(name="organization_a.b"))


def _input(**properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


TEXT = {"type": "string", "description": "Text."}

REFUSED: dict[str, tuple[dict[str, Any], str]] = {
    "name without a module segment": ({"name": "update"}, "nazwa"),
    "version zero": ({"version": 0}, "wersja"),
    "module the profile does not compose": ({"module": "vertical.nothing"}, "nie jest złożony"),
    "permission no module declares": ({"permission": "organization.everything"}, "uprawnienia"),
    "entitlement no module declares": ({"entitlement": "nothing.enabled"}, "entitlementu"),
    "unknown extra feature": ({"extra_features": frozenset({"assistant.x"})}, "cechy"),
    "title without English": ({"title": {"pl": "Zmień"}}, "title"),
    "no model description": ({"model_description": " "}, "model_description"),
    "unknown risk": ({"risk": "write"}, "klasa ryzyka"),
    "unknown modifier": ({"modifiers": frozenset({"cheap"})}, "modyfikatory"),
    "read that spends": (
        {"risk": "read", "modifiers": frozenset({"spends_credits"})},
        "odczyt",
    ),
    "neither preview nor reason": ({"preview": None}, "podgląd"),
    "both preview and reason": ({"no_preview_reason": "bo tak"}, "podgląd"),
    "neither version field nor reason": ({"version_field": None}, "pole wersji"),
    "undo in free text": ({"undo": "ask support"}, "undo"),
    "empty exposure": ({"exposure": frozenset()}, "ekspozycja"),
    "unknown exposure": ({"exposure": frozenset({"web"})}, "ekspozycja"),
    "input root is a list": ({"input_schema": {"type": "array", "items": TEXT}}, "korzeniem"),
    "input root without its type": (
        {
            "input_schema": {
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": TEXT},
            }
        },
        "korzeniem",
    ),
    "input field without description": (
        {"input_schema": _input(name={"type": "string"})},
        "input_schema.name: pole wymaga description",
    ),
    "input object left open": (
        {"input_schema": {"type": "object", "required": ["name"], "properties": {"name": TEXT}}},
        "additionalProperties",
    ),
    "optional input field missing from required": (
        {
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {"name": TEXT},
            }
        },
        "required",
    ),
    "nested object in a list left open": (
        {
            "input_schema": _input(
                items={
                    "type": "array",
                    "description": "Items.",
                    "items": {"type": "object", "required": [], "properties": {}},
                }
            )
        },
        r"input_schema\.items\[\]: obiekt wymaga additionalProperties",
    ),
    "x- word in the input": (
        {"input_schema": _input(name={**TEXT, "x-data-class": "public"})},
        "x-data-class",
    ),
    "input that is not JSON Schema": (
        {"input_schema": {"type": "object", "properties": {"name": {"type": 7}}}},
        "2020-12",
    ),
    "output field without a data class": (
        {"output_schema": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "output_schema.name: pole wymaga x-data-class",
    ),
    "output with an unknown data class": (
        {
            "output_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "x-data-class": "secret"}},
            }
        },
        "nieznana klasa danych",
    ),
    "output with health data": (
        {
            "output_schema": {
                "type": "object",
                "properties": {"note": {"type": "string", "x-data-class": "health"}},
            }
        },
        "health",
    ),
    "personal output without a purpose": (
        {
            "output_schema": {
                "type": "object",
                "properties": {"email": {"type": "string", "x-data-class": "personal"}},
            }
        },
        "personal_purpose",
    ),
    "untrusted marker that is not a boolean": (
        {
            "output_schema": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string", "x-data-class": "public", "x-untrusted": "yes"}
                },
            }
        },
        "x-untrusted",
    ),
}


@pytest.mark.parametrize("changes,message", REFUSED.values(), ids=REFUSED.keys())
def test_a_declaration_that_breaks_the_contract_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        register_command(spec(**changes))
    assert registered_commands() == ()


def test_a_data_class_covers_the_fields_below_it_and_personal_needs_a_purpose() -> None:
    output = {
        "type": "object",
        "properties": {
            "contact": {
                "type": "object",
                "x-data-class": "personal",
                "properties": {"email": {"type": "string"}, "phone": {"type": "string"}},
            }
        },
    }
    register_command(spec(output_schema=output, personal_purpose="Show the contact to its owner."))


@pytest.mark.django_db
def test_tools_offered_follow_permission_exposure_and_the_organizations_type(
    settings: Any,
) -> None:
    organization = Organization.objects.create(name="Domki", slug="domki")
    register_command(spec())
    register_command(spec(name="organization.archive", exposure=frozenset({"mcp"})))
    register_command(
        spec(name="sites.page.read", module="shared.sites", permission="site.content.edit")
    )

    def tools(*permissions: str) -> list[str]:
        context = TenantContext(
            organization_id=organization.id,
            membership_id=uuid7(),
            actor_id=uuid7(),
            role_key="owner",
            permissions=frozenset(permissions),
        )
        return [tool["name"] for tool in command_tools(context)]

    assert tools(SETTINGS_MANAGE, "site.content.edit") == [
        "organization_update_v1",
        "sites_page_read_v1",
    ]
    assert tools("site.content.edit") == ["sites_page_read_v1"]

    business = settings.ORGANIZATION_TYPES[organization.organization_type]
    settings.ORGANIZATION_TYPES = {
        organization.organization_type: replace(business, modules=frozenset())
    }
    assert tools(SETTINGS_MANAGE, "site.content.edit") == ["organization_update_v1"]


def test_a_tool_is_the_ports_tool_spec() -> None:
    register_command(spec())
    tool = {
        "name": "organization_update_v1",
        "description": spec().model_description,
        "input_schema": spec().input_schema,
    }
    context = TenantContext(
        organization_id=uuid7(),
        membership_id=uuid7(),
        actor_id=uuid7(),
        role_key="owner",
        permissions=frozenset({SETTINGS_MANAGE}),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(command_registry, "organization_modules", lambda _id: {"core.organizations"})
        assert command_tools(context) == [tool]
