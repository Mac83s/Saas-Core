"""The block types a site may carry, read from the contract directory.

The core's own types are `manifest.json` of `SITE_BLOCK_CONTRACTS_PATH`. A
shared or vertical module brings its own beside them, from files of its own
(`modules/<module id>/manifest.json`, docs/architecture/site-block-types.md):
they are read only where the deployment composes that module, so a product
that does not take the module does not know the type — nothing it is sent may
carry it, and nothing it offers names it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import APIException


class UnknownSiteBlockType(APIException):
    status_code = 400
    default_detail = "Typ bloku nie jest zarejestrowany."
    default_code = "unknown_site_block_type"


class UnknownSiteBlockVersion(APIException):
    status_code = 400
    default_detail = "Wersja schematu bloku nie jest obsługiwana."
    default_code = "unknown_site_block_version"


class InvalidSiteBlockData(APIException):
    status_code = 400
    default_detail = "Dane bloku nie spełniają kanonicznego kontraktu."
    default_code = "invalid_site_block_data"


class ServerBuiltSiteBlock(APIException):
    status_code = 400
    default_detail = (
        "Ten blok buduje serwer z zatwierdzonych danych firmy; nie zapisuje się go w treści."
    )
    default_code = "server_built_site_block"


#: The schema a module's manifest follows, a file of the core's directory.
MODULE_MANIFEST_SCHEMA = "module-manifest.v1.schema.json"


@dataclass(frozen=True, slots=True)
class BlockTranslation:
    """What a module says about its block's strings beyond its schema
    (`translation` in the module's manifest). Paths use `/` between names and
    `*` for any array index, and hold for every schema version."""

    #: Prose that is the same in every language, by the unit kind it is
    #: copied as (`name`, `address`).
    copied: Mapping[str, str] = field(default_factory=dict)
    #: Free strings that are data, not prose: no unit.
    data: frozenset[str] = frozenset()
    #: Text about real people: the whole block, or the named places.
    personal: bool = False
    personal_fields: frozenset[str] = frozenset()

    def paths(self) -> frozenset[str]:
        """Every place the module names, whatever it says about it."""
        return frozenset({*self.copied, *self.data, *self.personal_fields})


@dataclass(frozen=True, slots=True)
class SiteBlockContracts:
    validators: dict[str, dict[int, Draft202012Validator]]
    #: Blocks only the server builds, for a page nobody edits (`serverBuilt`
    #: in the manifest: a company's document, `core.document`; a module's
    #: block of a record's own page). Their schema says what the renderer is
    #: handed; nothing a person or an automation writes — a draft, an entry,
    #: a template, a change set — may carry one.
    server_built: frozenset[str] = frozenset()
    #: The module each type that is not the core's own came with.
    modules: Mapping[str, str] = field(default_factory=dict)
    #: What a module's manifest says about the strings of its blocks.
    translation: Mapping[str, BlockTranslation] = field(default_factory=dict)

    def validate(
        self, *, block_type: str, schema_version: int, data: Any, built: bool = False
    ) -> None:
        if block_type in self.server_built and not built:
            raise ServerBuiltSiteBlock
        versions = self.validators.get(block_type)
        if versions is None:
            raise UnknownSiteBlockType
        validator = versions.get(schema_version)
        if validator is None:
            raise UnknownSiteBlockVersion
        if not isinstance(data, dict):
            raise InvalidSiteBlockData
        if next(validator.iter_errors(data), None) is not None:
            raise InvalidSiteBlockData


def validate_site_block(*, block_type: str, schema_version: int, data: Any) -> None:
    site_block_contracts().validate(
        block_type=block_type,
        schema_version=schema_version,
        data=data,
    )


def validate_built_site_block(*, block_type: str, schema_version: int, data: Any) -> None:
    """A block a module builds for a record's own page, held to its schema.

    The site hands such a block to the renderer as the module gave it, so the
    module's own tests are where a wrong shape is caught: this is
    `validate_site_block` without the refusal of what only the server builds.
    """
    site_block_contracts().validate(
        block_type=block_type, schema_version=schema_version, data=data, built=True
    )


def module_block_prefix(module: str) -> str:
    """What every block type of a module starts with: its id and a dot, a
    hyphen of the id written as an underscore (`shared.model-port` →
    `shared.model_port.`) — a block type has no hyphens."""
    return f"{module.replace('-', '_')}."


def module_contract_directories() -> Iterator[tuple[str, Path]]:
    """The directory of every composed module that brings block types, in
    the order the deployment composes its modules."""
    root = Path(settings.SITE_BLOCK_MODULE_CONTRACTS_PATH)
    for module in settings.ACTIVE_MODULES:
        directory = root / module
        if (directory / "manifest.json").is_file():
            yield module, directory


@cache
def site_block_contracts() -> SiteBlockContracts:
    contract_directory = Path(settings.SITE_BLOCK_CONTRACTS_PATH)
    manifest = _read_json(contract_directory / "manifest.json")
    try:
        blocks = manifest["blocks"]
    except (KeyError, TypeError) as error:
        raise ImproperlyConfigured("Manifest kontraktów bloków jest nieprawidłowy") from error
    if not isinstance(blocks, list):
        raise ImproperlyConfigured("Manifest kontraktów bloków nie zawiera listy bloków")

    validators: dict[str, dict[int, Draft202012Validator]] = {}
    server_built: set[str] = set()
    modules: dict[str, str] = {}
    translation: dict[str, BlockTranslation] = {}
    try:
        _read_blocks(contract_directory, blocks, validators, server_built)
        for module, directory in module_contract_directories():
            declared = _module_manifest(contract_directory, module, directory)
            _read_blocks(directory, declared["blocks"], validators, server_built)
            for block in declared["blocks"]:
                modules[block["type"]] = module
                if "translation" in block:
                    translation[block["type"]] = _translation(block["translation"])
    except (KeyError, TypeError, ValueError, SchemaError) as error:
        raise ImproperlyConfigured("Manifest kontraktów bloków jest nieprawidłowy") from error
    return SiteBlockContracts(
        validators=validators,
        server_built=frozenset(server_built),
        modules=modules,
        translation=translation,
    )


def _read_blocks(
    directory: Path,
    blocks: list[Any],
    validators: dict[str, dict[int, Draft202012Validator]],
    server_built: set[str],
) -> None:
    """The validators of one manifest's blocks, each schema a file of that
    manifest's own directory."""
    for block in blocks:
        block_type = block["type"]
        latest_version = block["latestVersion"]
        schema_paths = block["schemas"]
        if (
            not isinstance(block_type, str)
            or not isinstance(latest_version, int)
            or not isinstance(schema_paths, dict)
        ):
            raise TypeError
        versions = {int(version): path for version, path in schema_paths.items()}
        if sorted(versions) != list(range(1, latest_version + 1)):
            raise ImproperlyConfigured(
                f"Schematy {block_type} nie tworzą liniowej historii wersji"
            )
        block_validators: dict[int, Draft202012Validator] = {}
        for version, relative_path in versions.items():
            if not isinstance(relative_path, str):
                raise TypeError
            schema = _read_json(directory / relative_path)
            Draft202012Validator.check_schema(schema)
            block_validators[version] = Draft202012Validator(schema)
        if block_type in validators:
            raise ImproperlyConfigured(f"Powielony typ bloku: {block_type}")
        validators[block_type] = block_validators
        if block.get("serverBuilt") is True:
            server_built.add(block_type)


def _module_manifest(contract_directory: Path, module: str, directory: Path) -> dict[str, Any]:
    """A module's manifest, held to its schema and to its own name: the
    directory names the module, and every type carries the module's id."""
    manifest = _read_json(directory / "manifest.json")
    schema = _read_json(contract_directory / MODULE_MANIFEST_SCHEMA)
    problem = next(Draft202012Validator(schema).iter_errors(manifest), None)
    if problem is not None:
        raise ImproperlyConfigured(
            f"Manifest bloków modułu {module} nie spełnia kontraktu: "
            f"{'/'.join(str(part) for part in problem.absolute_path) or '.'} — {problem.message}"
        )
    if manifest["module"] != module:
        raise ImproperlyConfigured(
            f"Manifest bloków w katalogu {module} nazywa moduł {manifest['module']}."
        )
    prefix = module_block_prefix(module)
    for block in manifest["blocks"]:
        if not block["type"].startswith(prefix):
            raise ImproperlyConfigured(
                f"Typ bloku {block['type']} nie nosi nazwy modułu {module} ({prefix}…)."
            )
        if block.get("serverBuilt") is True and "sections" in block:
            raise ImproperlyConfigured(
                f"Blok {block['type']} buduje serwer: nie ma sekcji w bibliotece."
            )
    return manifest


def _translation(declared: Mapping[str, Any]) -> BlockTranslation:
    personal = declared.get("personal", ())
    return BlockTranslation(
        copied=dict(declared.get("copied", {})),
        data=frozenset(declared.get("data", ())),
        personal=personal is True,
        personal_fields=frozenset(() if personal is True else personal),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Nie można odczytać kontraktu bloków: {path}") from error
    if not isinstance(value, dict):
        raise ImproperlyConfigured(f"Kontrakt bloków nie jest obiektem JSON: {path}")
    return value
