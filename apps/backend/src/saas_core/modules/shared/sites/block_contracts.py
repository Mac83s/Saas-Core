from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class SiteBlockContracts:
    validators: dict[str, dict[int, Draft202012Validator]]

    def validate(self, *, block_type: str, schema_version: int, data: Any) -> None:
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
    try:
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
                schema = _read_json(contract_directory / relative_path)
                Draft202012Validator.check_schema(schema)
                block_validators[version] = Draft202012Validator(schema)
            if block_type in validators:
                raise ImproperlyConfigured(f"Powielony typ bloku: {block_type}")
            validators[block_type] = block_validators
    except (KeyError, TypeError, ValueError, SchemaError) as error:
        raise ImproperlyConfigured("Manifest kontraktów bloków jest nieprawidłowy") from error
    return SiteBlockContracts(validators=validators)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Nie można odczytać kontraktu bloków: {path}") from error
    if not isinstance(value, dict):
        raise ImproperlyConfigured(f"Kontrakt bloków nie jest obiektem JSON: {path}")
    return value
