from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import APIException, NotFound

from .block_contracts import validate_site_block
from .block_decoration import validate_decoration


class PageTemplateNotFound(NotFound):
    default_detail = "Szablon strony albo jego wersja nie istnieje."
    default_code = "page_template_not_found"


@dataclass(frozen=True, slots=True)
class ApprovedTemplateMedia:
    id: str
    source_path: Path
    filename: str
    content_type: str
    sha256: str

    def read(self) -> bytes:
        try:
            content = self.source_path.read_bytes()
        except OSError as error:
            raise ImproperlyConfigured(
                f"Nie można odczytać zatwierdzonego medium: {self.source_path}"
            ) from error
        if not content or hashlib.sha256(content).hexdigest() != self.sha256:
            raise ImproperlyConfigured(
                f"Zatwierdzone medium ma nieprawidłową sumę: {self.source_path}"
            )
        return content


@dataclass(frozen=True, slots=True)
class PageTemplate:
    id: str
    version: int
    category: str
    labels: dict[str, dict[str, str]]
    required_entitlements: tuple[str, ...]
    media: tuple[ApprovedTemplateMedia, ...]
    blocks: tuple[dict[str, Any], ...]

    localized_blocks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    media_bindings: tuple[dict[str, Any], ...] = ()

    def draft_blocks(self, locale: str = "pl") -> list[dict[str, Any]]:
        return deepcopy(self.localized_blocks.get(locale, list(self.blocks)))

    def bind_media(self, blocks: list[dict[str, Any]], assets: dict[str, str], locale: str) -> None:
        for binding in self.media_bindings:
            blocks[binding["blockPosition"]]["data"]["image"] = {
                "asset_id": assets[binding["mediaId"]],
                "alt": binding["alt"][locale],
            }


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
                for block in [*blocks, *recipe.get("localizedBlocks", {}).get("en", [])]:
                    validate_decoration(block.get("decoration"))
                    validate_site_block(
                        block_type=block["block_type"],
                        schema_version=block["schema_version"],
                        data=block["data"],
                    )
                media = _approved_media(
                    contract_directory=contract_directory,
                    recipe=recipe,
                )
                localized = recipe.get("localizedBlocks", {})
                if any(len(translated) != len(blocks) for translated in localized.values()):
                    raise ImproperlyConfigured("Localized template block counts differ")
                bindings = tuple(recipe.get("mediaBindings", []))
                positions: set[int] = set()
                media_ids = {item.id for item in media}
                for binding in bindings:
                    position = binding["blockPosition"]
                    if (
                        position >= len(blocks)
                        or position in positions
                        or binding["mediaId"] not in media_ids
                    ):
                        raise ImproperlyConfigured("Invalid template media binding")
                    positions.add(position)
                    for variant in [list(blocks), *localized.values()]:
                        candidate = deepcopy(variant[position])
                        candidate["data"]["image"] = {
                            "asset_id": "00000000-0000-4000-8000-000000000000",
                            "alt": binding["alt"]["pl"],
                        }
                        validate_site_block(
                            block_type=candidate["block_type"],
                            schema_version=candidate["schema_version"],
                            data=candidate["data"],
                        )
                templates[template_id][version] = PageTemplate(
                    id=template_id,
                    version=version,
                    category=recipe["category"],
                    labels=recipe["labels"],
                    required_entitlements=tuple(recipe.get("requiredEntitlements", [])),
                    media=media,
                    blocks=blocks,
                    localized_blocks=localized,
                    media_bindings=bindings,
                )
    except (APIException, KeyError, TypeError, ValueError) as error:
        raise ImproperlyConfigured("Manifest szablonów stron jest nieprawidłowy") from error
    return PageTemplateCatalog(templates=templates)


def _approved_media(
    *,
    contract_directory: Path,
    recipe: dict[str, Any],
) -> tuple[ApprovedTemplateMedia, ...]:
    asset_directory = (contract_directory / "assets").resolve()
    approved: list[ApprovedTemplateMedia] = []
    seen_ids: set[str] = set()
    for item in recipe.get("media", []):
        media_id = item["id"]
        if media_id in seen_ids:
            raise ImproperlyConfigured(f"Powielone medium recepty: {media_id}")
        seen_ids.add(media_id)
        source_path = (contract_directory / item["source"]).resolve()
        if not source_path.is_relative_to(asset_directory):
            raise ImproperlyConfigured("Medium recepty wychodzi poza katalog assets")
        approved.append(
            ApprovedTemplateMedia(
                id=media_id,
                source_path=source_path,
                filename=item["filename"],
                content_type=item["contentType"],
                sha256=item["sha256"],
            )
        )
    return tuple(approved)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Nie można odczytać kontraktu szablonu: {path}") from error
    if not isinstance(value, dict):
        raise ImproperlyConfigured(f"Kontrakt szablonu nie jest obiektem JSON: {path}")
    return value
