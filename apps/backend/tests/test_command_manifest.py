"""The command manifest is the registry as a reviewer reads it (ADR-076 §4):
written from the code, byte for byte the same on every run, with a product's
vertical commands in a file of its own; and the commands ADR-076 §2 announces
but nobody has built yet are names, classes and owners — never also registered.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from saas_core.modules.core.organizations import command_registry
from saas_core.modules.core.organizations.command_registry import (
    _NAME_PATTERN,
    MODIFIERS,
    RISKS,
    CommandSpec,
    register_command,
    registered_commands,
)
from saas_core.modules.core.organizations.management.commands.command_manifest import (
    CORE_MANIFEST,
    PRODUCT_MANIFEST,
    manifests,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

PLANNED = (
    Path(settings.BASE_DIR).parent.parent / "packages" / "contracts" / "commands" / "planned.json"
)


def _run(arguments: Any, call: Any) -> dict[str, Any]:
    return {}


def spec(**changes: Any) -> CommandSpec:
    declaration: dict[str, Any] = {
        "name": "organization.rename",
        "version": 1,
        "module": "core.organizations",
        "title": {"pl": "Zmień nazwę", "en": "Rename"},
        "summary": {"pl": "Nazwa firmy.", "en": "Company name."},
        "model_description": "Renames the company.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Name."}},
        },
        "output_schema": {"type": "object", "properties": {}},
        "permission": SETTINGS_MANAGE,
        "risk": "apply",
        "run": _run,
        "undo": "restore_version",
        "no_preview_reason": "Shown as the new name only.",
        "version_field": "version",
    }
    declaration.update(changes)
    return CommandSpec(**declaration)


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})


@pytest.mark.usefixtures("registry")
def test_the_manifest_is_written_the_same_and_checked_against_the_code(tmp_path: Path) -> None:
    register_command(spec())
    assert manifests() == manifests()

    call_command("command_manifest", directory=str(tmp_path))
    document = json.loads((tmp_path / CORE_MANIFEST).read_text(encoding="utf-8"))
    assert [entry["command"] for entry in document["commands"]] == ["organization.rename@1"]
    assert document["commands"][0]["tool_name"] == "organization_rename_v1"
    call_command("command_manifest", directory=str(tmp_path), check=True)

    register_command(spec(name="organization.describe"))
    with pytest.raises(CommandError, match=CORE_MANIFEST):
        call_command("command_manifest", directory=str(tmp_path), check=True)


@pytest.mark.usefixtures("registry")
def test_a_products_vertical_commands_have_a_file_of_their_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = dict(settings.MODULE_CATALOG)
    catalog["core.organizations"] = replace(catalog["core.organizations"], layer="vertical")
    register_command(spec())
    monkeypatch.setattr(settings, "MODULE_CATALOG", catalog)

    documents = manifests()

    assert json.loads(documents[CORE_MANIFEST])["commands"] == []
    commands = json.loads(documents[PRODUCT_MANIFEST])["commands"]
    assert [entry["command"] for entry in commands] == ["organization.rename@1"]


def test_announced_commands_are_names_classes_and_owners_never_also_registered() -> None:
    planned = json.loads(PLANNED.read_text(encoding="utf-8"))["commands"]
    registered = {entry.key for entry in registered_commands()}
    for entry in planned:
        assert set(entry) == {"command", "risk", "modifiers", "owner"}, entry
        name, _, version = entry["command"].partition("@")
        assert _NAME_PATTERN.fullmatch(name) and version.isdigit(), entry
        assert entry["risk"] in RISKS and set(entry["modifiers"]) <= MODIFIERS, entry
        assert entry["owner"].strip(), entry
        assert entry["command"] not in registered, (
            f"{entry['command']} jest już zarejestrowane — usuń je z planned.json"
        )
