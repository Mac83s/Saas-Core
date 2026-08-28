from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import APIException, NotFound

from .block_contracts import validate_site_block


class PageTemplateNotFound(NotFound):
    default_detail = "Szablon strony albo jego wersja nie istnieje."
    default_code = "page_template_not_found"


@dataclass(frozen=True, slots=True)
class PageTemplate:
    id: str
    version: int
    category: str
    labels: dict[str, dict[str, str]]
    required_entitlements: tuple[str, ...]
    blocks: tuple[dict[str, Any], ...]

    def draft_blocks(self) -> list[dict[str, Any]]:
        return deepcopy(list(self.blocks))


@dataclass(frozen=True, slots=True)
class PageTemplateCatalog:
    templates: dict[str, dict[int, PageTemplate]]

    def get(self, *, template_id: str, version: int) -> PageTemplate:
        template = self.templates.get(template_id, {}).get(version)
        if template is None:
            raise PageTemplateNotFound
        return template


@cache
def page_template_catalog() -> PageTemplateCatalog:
    contract_directory = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    manifest = _read_json(contract_directory / "manifest.json")
    try:
        schema_path = manifest["recipe"]
        manifest_templates = manifest["templates"]
        if manifest["schemaVersion"] != 1:
            raise TypeError
        if not isinstance(schema_path, str) or not isinstance(manifest_templates, list):
            raise TypeError
        schema = _read_json(contract_directory / schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except (KeyError, TypeError, SchemaError) as error:
        raise ImproperlyConfigured("Manifest szablonów stron jest nieprawidłowy") from error

    templates: dict[str, dict[int, PageTemplate]] = {}
    try:
        for item in manifest_templates:
            template_id = item["id"]
            latest_version = item["latestVersion"]
            version_paths = item["versions"]
            if (
                not isinstance(template_id, str)
                or not isinstance(latest_version, int)
                or not isinstance(version_paths, dict)
            ):
                raise TypeError
            versions = {int(version): path for version, path in version_paths.items()}
            if sorted(versions) != list(range(1, latest_version + 1)):
                raise ImproperlyConfigured(
                    f"Wersje szablonu {template_id} nie tworzą liniowej historii"
                )
            if template_id in templates:
                raise ImproperlyConfigured(f"Powielony szablon strony: {template_id}")
            templates[template_id] = {}
            for version, relative_path in versions.items():
                if not isinstance(relative_path, str):
                    raise TypeError
                recipe = _read_json(contract_directory / relative_path)
                if next(validator.iter_errors(recipe), None) is not None:
                    raise ImproperlyConfigured(
                        f"Recepta {template_id} v{version} nie spełnia kontraktu"
                    )
                if recipe["id"] != template_id or recipe["version"] != version:
                    raise ImproperlyConfigured(
                        f"Recepta {template_id} v{version} nie zgadza się z manifestem"
                    )
                blocks = tuple(recipe["blocks"])
                for block in blocks:
                    validate_site_block(
                        block_type=block["block_type"],
                        schema_version=block["schema_version"],
                        data=block["data"],
                    )
                templates[template_id][version] = PageTemplate(
                    id=template_id,
                    version=version,
                    category=recipe["category"],
                    labels=recipe["labels"],
                    required_entitlements=tuple(recipe.get("requiredEntitlements", [])),
                    blocks=blocks,
                )
    except (APIException, KeyError, TypeError, ValueError) as error:
        raise ImproperlyConfigured("Manifest szablonów stron jest nieprawidłowy") from error
    return PageTemplateCatalog(templates=templates)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Nie można odczytać kontraktu szablonu: {path}") from error
    if not isinstance(value, dict):
        raise ImproperlyConfigured(f"Kontrakt szablonu nie jest obiektem JSON: {path}")
    return value
