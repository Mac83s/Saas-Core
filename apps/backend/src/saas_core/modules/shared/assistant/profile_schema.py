"""The company profile: what the owner told the assistant about the company (A2).

A document, not a form: who the company is, what it sells, where and who
works. Every value says where it came from and whether the owner confirmed it,
and only a confirmed value is ever written to the account (`configurator.py`).

The schema below is the contract
`packages/contracts/assistant/company-profile.v1.schema.json`; that file is
written from here (`manage.py assistant_contract`) and nothing reads it at run
time.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator
from rest_framework.exceptions import ValidationError
from rest_framework.settings import api_settings

SCHEMA_ID = "company-profile.v1"
#: Where a value comes from: the owner's own words in a conversation, what the
#: account already holds, the company's earlier site, a preset's default or
#: the assistant's proposal. Only the first two are facts.
ORIGINS = ("owner", "account", "existing_site", "preset_default", "assistant")
#: A profile is an interview's notes, not an archive.
MAX_PROFILE_BYTES = 64_000
#: The tax rates a price may carry, as the price list's commands name them
#: (`booking.price.save@1`). Kept here as words of the contract: the assistant
#: reaches other modules only through the registry (ADR-076 pkt 9).
VAT_CODES = ("23", "8", "5", "0", "zw", "np")

_KEY = {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,31}$"}
_KEYS = {"type": "array", "maxItems": 50, "uniqueItems": True, "items": _KEY}


def _said(value: dict[str, Any], description: str) -> dict[str, Any]:
    """A value with its origin and whether the owner confirmed it."""
    return {
        "type": "object",
        "description": description,
        "additionalProperties": False,
        "required": ["value", "origin", "confirmed"],
        "properties": {
            "value": value,
            "origin": {"type": "string", "enum": list(ORIGINS)},
            "confirmed": {"type": "boolean"},
        },
    }


def _text(limit: int, description: str) -> dict[str, Any]:
    return _said({"type": "string", "minLength": 1, "maxLength": limit}, description)


def _number(low: int, high: int, description: str) -> dict[str, Any]:
    return _said({"type": "integer", "minimum": low, "maximum": high}, description)


def _section(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required or [],
        "properties": properties,
    }


_HOURS = {
    "type": "array",
    "maxItems": 50,
    "items": _section(
        {
            "weekday": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "0 = Monday.",
            },
            "start": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
            "end": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
            "place": {**_KEY, "description": "The key of the place the person works at then."},
        },
        ["weekday", "start", "end", "place"],
    ),
}
_PRICE = _section(
    {
        # Below the price list's own bound of 1 000 000.00 (`booking.price.save@1`).
        "amount": {"type": "string", "pattern": "^[0-9]{1,6}(\\.[0-9]{2})?$"},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "per": {"type": "string", "enum": ["booking", "person", "hour", "day", "night"]},
    },
    ["amount", "currency", "per"],
)

PROFILE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"{SCHEMA_ID}.schema.json",
    "title": "Company profile",
    "description": (
        "What the owner told the assistant about the company (assistant plan, A2). Every "
        "value carries its origin and whether the owner confirmed it; the configurator "
        "writes only confirmed values to the account. Personal data: the owner's words and "
        "the names of the company's people."
    ),
    **_section(
        {
            "schema": {"const": SCHEMA_ID},
            "company": _section({
                "name": _text(160, "The company's name."),
                "activity": _text(400, "What the company does, in the owner's words."),
                "city": _text(120, "The town it works in, as the owner names it."),
                "category": _said(
                    {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,63}$"},
                    "Its category in the public directory (a key from "
                    "profiles.catalog_options.read).",
                ),
                "address": _text(240, "Its public street address."),
                "phone": _text(40, "Its public phone number."),
                "email": _text(254, "Its public e-mail address."),
            }),
            "card": _section({
                "headline": _text(200, "One sentence about the company."),
                "description": _text(4000, "A longer description of the company."),
            }),
            "languages": _said(
                {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^[a-z]{2}$"},
                },
                "The languages the company speaks to its customers in.",
            ),
            "places": {
                "type": "array",
                "maxItems": 20,
                "items": _section(
                    {
                        "key": _KEY,
                        "name": _text(160, "The place's name as customers see it."),
                        "address": _text(240, "Its street address."),
                    },
                    ["key"],
                ),
            },
            "people": {
                "type": "array",
                "maxItems": 50,
                "items": _section(
                    {
                        "key": _KEY,
                        "name": _text(160, "The person's name as customers see it."),
                        "hours": _said(_HOURS, "The person's working week."),
                    },
                    ["key"],
                ),
            },
            "offers": {
                "type": "array",
                "maxItems": 50,
                "items": _section(
                    {
                        "key": _KEY,
                        "name": _text(160, "What is sold, as customers see it."),
                        "preset": _said(
                            {"type": "string", "pattern": "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$"},
                            "The kind of booking: a preset id from booking.preset.list.",
                        ),
                        "duration_minutes": _number(5, 1440, "How long one visit takes."),
                        "units": _number(1, 1000, "How many identical units there are."),
                        "capacity": _number(1, 1000, "How many people one unit takes."),
                        "price": _said(
                            _PRICE,
                            "What it costs: the amount the owner gave, never a guess.",
                        ),
                        "vat": _said(
                            {"type": "string", "enum": list(VAT_CODES)},
                            "The tax rate of its price as a code: 23, 8, 5, 0, zw (exempt), "
                            "np (outside VAT). The owner's answer, never a default.",
                        ),
                        "places": _said(_KEYS, "The keys of the places it is offered at."),
                        "people": _said(_KEYS, "The keys of the people who do it."),
                        "inputs": {
                            "type": "object",
                            "description": "What the preset requires of the company "
                            "(its requiredInputs), by key.",
                            "maxProperties": 20,
                            "propertyNames": {"pattern": "^[a-z][a-z0-9_]{0,63}$"},
                            "additionalProperties": _said({}, "The owner's answer."),
                        },
                    },
                    ["key"],
                ),
            },
            "sources": {
                "type": "array",
                "maxItems": 20,
                "description": "Where `existing_site` values were read from.",
                "items": _section(
                    {
                        "kind": {"type": "string", "enum": ["website", "document"]},
                        "ref": {"type": "string", "minLength": 1, "maxLength": 2000},
                    },
                    ["kind", "ref"],
                ),
            },
        },
        ["schema"],
    ),
}

_VALIDATOR = Draft202012Validator(PROFILE_SCHEMA)
#: Lists whose entries are named by `key` and what may point at them.
_KEYED = ("places", "people", "offers")


def empty_profile() -> dict[str, Any]:
    return {"schema": SCHEMA_ID}


def validate_profile(document: Any) -> None:
    """Refuses a document that is not a profile, naming each field the way
    every other 400 does (`offers.0.duration_minutes.value`)."""
    errors: dict[str, list[str]] = {}
    for violation in _VALIDATOR.iter_errors(document):
        path = ".".join(str(segment) for segment in violation.absolute_path)
        errors.setdefault(path, []).append(violation.message)
    if not errors:
        for path, message in _dangling(document):
            errors.setdefault(path, []).append(message)
    if errors:
        raise ValidationError({"changes": _nested(errors)})


def _nested(errors: dict[str, list[str]]) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for path, messages in sorted(errors.items()):
        node = detail
        # The document as a whole stands for the level above it.
        *parents, last = path.split(".") if path else [api_settings.NON_FIELD_ERRORS_KEY]
        for segment in parents:
            node = node.setdefault(segment, {})
            if not isinstance(node, dict):
                # Its parent failed as a whole (sorted first): that says it.
                break
        else:
            node[last] = messages
    return detail


def _dangling(document: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Keys are names inside one document: unique per list, and a reference
    names an entry that is there."""
    known: dict[str, set[str]] = {}
    for name in _KEYED:
        seen: set[str] = set()
        for index, entry in enumerate(document.get(name, [])):
            if entry["key"] in seen:
                yield f"{name}.{index}.key", "Ten klucz już jest na liście."
            seen.add(entry["key"])
        known[name] = seen
    references = (
        *(
            (f"offers.{index}.{target}.value", target, offer.get(target, {}).get("value", []))
            for index, offer in enumerate(document.get("offers", []))
            for target in ("places", "people")
        ),
        *(
            (
                f"people.{index}.hours.value",
                "places",
                [rule["place"] for rule in person.get("hours", {}).get("value", [])],
            )
            for index, person in enumerate(document.get("people", []))
        ),
    )
    for path, target, keys in references:
        for key in keys:
            if key not in known[target]:
                yield path, f"Nie ma wpisu „{key}” na liście {target}."
