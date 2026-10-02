"""Writes, or with `--check` compares, the manifest of registered commands.

The manifest is the commands as a model, an MCP client and a reviewer see them
(ADR-076 §4): name, class, permission, schemas, undo. Nothing reads it at run
time — the assistant takes its tools from the registry in memory — so it is a
contract under review, not configuration: `pnpm api:check` fails when the code
and the file disagree. A product's vertical commands go to their own file, so
a product never edits the one it receives from Saas-Core (ADR-049).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.organizations.command_registry import (
    CommandSpec,
    registered_commands,
)

MANIFEST_VERSION = 1
CORE_MANIFEST = "manifest.json"
PRODUCT_MANIFEST = "manifest.product.json"


def manifests() -> dict[str, str]:
    core: list[dict[str, Any]] = []
    product: list[dict[str, Any]] = []
    for spec in registered_commands():
        vertical = settings.MODULE_CATALOG[spec.module].layer == "vertical"
        (product if vertical else core).append(describe(spec))
    documents = {CORE_MANIFEST: _render(core)}
    if product:
        documents[PRODUCT_MANIFEST] = _render(product)
    return documents


def describe(spec: CommandSpec) -> dict[str, Any]:
    return {
        "command": spec.key,
        "tool_name": spec.tool_name,
        "module": spec.module,
        "title": dict(spec.title),
        "summary": dict(spec.summary),
        "model_description": spec.model_description,
        "risk": spec.risk,
        "modifiers": sorted(spec.modifiers),
        "permission": spec.permission,
        "entitlement": spec.entitlement,
        "extra_features": sorted(spec.extra_features),
        "exposure": sorted(spec.exposure),
        "input_schema": spec.input_schema,
        "output_schema": spec.output_schema,
        "preview": spec.preview is not None,
        "no_preview_reason": spec.no_preview_reason or None,
        "version_field": spec.version_field,
        "no_version_reason": spec.no_version_reason or None,
        "undo": spec.undo,
        "person_gates": sorted(spec.person_gates),
        "personal_purpose": spec.personal_purpose or None,
    }


def _render(commands: list[dict[str, Any]]) -> str:
    document = {"version": MANIFEST_VERSION, "commands": commands}
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Zapisuje albo sprawdza manifest zarejestrowanych poleceń asystenta."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--directory",
            default=str(
                Path(settings.BASE_DIR).parent.parent / "packages" / "contracts" / "commands"
            ),
        )
        parser.add_argument("--check", action="store_true")

    def handle(self, *args: Any, directory: str, check: bool, **options: Any) -> None:
        stale: list[str] = []
        for name, text in manifests().items():
            path = Path(directory) / name
            if not check:
                path.write_text(text, encoding="utf-8")
            elif not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        if stale:
            raise CommandError(
                f"Manifest poleceń nie zgadza się z kodem: {', '.join(stale)}. "
                "Uruchom pnpm commands:manifest."
            )
        self.stdout.write(
            "Manifest poleceń jest aktualny." if check else "Zapisano manifest poleceń."
        )
