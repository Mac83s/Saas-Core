"""Shared, versioned section decoration, separate from each block's content schema."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import APIException


class InvalidSectionDecoration(APIException):
    status_code = 400
    default_code = "invalid_section_decoration"
    default_detail = "Dekoracja sekcji nie spełnia kanonicznego kontraktu."


@cache
def decoration_validator() -> Draft202012Validator:
    path = Path(settings.SITE_BLOCK_CONTRACTS_PATH) / "section-decoration.v1.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as error:
        raise ImproperlyConfigured("Nieprawidłowy kontrakt dekoracji sekcji.") from error
    return Draft202012Validator(schema)


def validate_decoration(value: Any) -> None:
    # NULL means reset/default; legacy blocks must not acquire a new hash field.
    if value is None:
        return
    if not isinstance(value, dict) or next(decoration_validator().iter_errors(value), None):
        raise InvalidSectionDecoration


def normalize_block(block: dict[str, Any]) -> dict[str, Any]:
    decoration = block.get("decoration")
    validate_decoration(decoration)
    return {
        "block_type": block["block_type"],
        "schema_version": block["schema_version"],
        "data": block["data"],
        **({"decoration": deepcopy(decoration)} if decoration is not None else {}),
    }


def stored_block_payload(block: Any) -> dict[str, Any]:
    """One projection for drafts, publications, change sets and approval digests."""
    return normalize_block({
        "block_type": block.block_type,
        "schema_version": block.schema_version,
        "data": block.data,
        "decoration": block.decoration,
    })
