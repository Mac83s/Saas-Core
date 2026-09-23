"""Shared, versioned block envelopes (decoration, presentation) and page presentation,
separate from each block's content schema."""

from __future__ import annotations

import json
from collections.abc import Callable
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


class InvalidSectionPresentation(APIException):
    status_code = 400
    default_code = "invalid_section_presentation"
    default_detail = "Wygląd sekcji nie spełnia kanonicznego kontraktu."


class InvalidPagePresentation(APIException):
    status_code = 400
    default_code = "invalid_page_presentation"
    default_detail = "Wygląd strony nie spełnia kanonicznego kontraktu."


def _envelope_validator(filename: str, message: str) -> Draft202012Validator:
    path = Path(settings.SITE_BLOCK_CONTRACTS_PATH) / filename
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as error:
        raise ImproperlyConfigured(message) from error
    return Draft202012Validator(schema)


@cache
def decoration_validator() -> Draft202012Validator:
    return _envelope_validator(
        "section-decoration.v1.schema.json", "Nieprawidłowy kontrakt dekoracji sekcji."
    )


# Both presentation envelopes pick their contract by `schemaVersion`; older
# versions stay valid for blocks and pages already stored with them.
PRESENTATION_VERSIONS = (1, 2)


@cache
def presentation_validator(version: int) -> Draft202012Validator:
    return _envelope_validator(
        f"section-presentation.v{version}.schema.json", "Nieprawidłowy kontrakt wyglądu sekcji."
    )


@cache
def page_presentation_validator(version: int) -> Draft202012Validator:
    return _envelope_validator(
        f"page-presentation.v{version}.schema.json", "Nieprawidłowy kontrakt wyglądu strony."
    )


def _is_invalid(value: Any, validator: Callable[[int], Draft202012Validator]) -> bool:
    if not isinstance(value, dict):
        return True
    version = value.get("schemaVersion")
    if version not in PRESENTATION_VERSIONS:
        return True
    # `true` and `1.0` compare equal to 1 but would name another file; int()
    # picks the contract, whose `const` still refuses `true`.
    return next(validator(int(version)).iter_errors(value), None) is not None


def validate_decoration(value: Any) -> None:
    # NULL means reset/default; legacy blocks must not acquire a new hash field.
    if value is None:
        return
    if not isinstance(value, dict) or next(decoration_validator().iter_errors(value), None):
        raise InvalidSectionDecoration


def validate_presentation(value: Any) -> None:
    # Same rule as decoration: NULL keeps the legacy rendering and the legacy hash.
    if value is None:
        return
    if _is_invalid(value, presentation_validator):
        raise InvalidSectionPresentation


def validate_page_presentation(value: Any) -> None:
    if value is None:
        return
    if _is_invalid(value, page_presentation_validator):
        raise InvalidPagePresentation


def normalize_block(block: dict[str, Any]) -> dict[str, Any]:
    decoration = block.get("decoration")
    presentation = block.get("presentation")
    validate_decoration(decoration)
    validate_presentation(presentation)
    return {
        "block_type": block["block_type"],
        "schema_version": block["schema_version"],
        "data": block["data"],
        **({"decoration": deepcopy(decoration)} if decoration is not None else {}),
        **({"presentation": deepcopy(presentation)} if presentation is not None else {}),
    }


def stored_block_payload(block: Any) -> dict[str, Any]:
    """One projection for drafts, publications, change sets and approval digests."""
    return normalize_block({
        "block_type": block.block_type,
        "schema_version": block.schema_version,
        "data": block.data,
        "decoration": block.decoration,
        "presentation": block.presentation,
    })
