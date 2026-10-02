"""A page body in another language: text units bound to the source structure (ADR-070).

A language version has the source version's blocks, images, links and layout;
only text differs. So it is stored as text units, and its blocks are assembled
from the source version it is bound to — the structure cannot drift, because
the language version has none of its own.

What is text comes from the block schemas: a string with no `enum`, `pattern`,
`const` or `format` is prose, everything else is structure. A short table names
the prose that is the same in every language — an address, a person's name —
and the strings that are data. An inline run of `core.rich_text` is one unit,
its marks numbered tokens (`saas_core.content_protocol.tokens`), so a sentence
is translated whole and its links keep their targets.

A unit's key is the block's position and the JSON path inside it. Positions are
stable because a language version is bound to one source version; a new source
version is a new binding, and the translation memory carries text across by
the hash of the source text, not by key.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from saas_core.content_protocol.provenance import unit_hash
from saas_core.content_protocol.tokens import (
    PLACEHOLDER_PATTERN,
    TokenError,
    close_token,
    flat_segments,
    open_token,
    validate_tokens,
)

from .block_contracts import InvalidSiteBlockData, site_block_contracts, validate_site_block
from .models import canonical_json_hash

UNIT_TEXT = "text"
UNIT_INLINE = "inline"
UNIT_NAME = "name"
UNIT_ADDRESS = "address"
# Copied into every language rather than translated, and never sent to a
# model; a script that needs it (Cyrillic) gets a transliteration by code.
COPIED_KINDS = frozenset({UNIT_NAME, UNIT_ADDRESS})

DATA_PUBLIC = "public"
DATA_PUBLIC_PERSONAL = "public_personal"

UNIT_TOO_LONG = "too_long"
UNIT_REQUIRED = "required"
UNIT_UNKNOWN = "unknown_unit"
UNIT_TOKEN_EMPTY = "token_empty"
# The assembled block breaks its schema in a way no single unit explains.
BLOCK_INVALID = "block_invalid"

# Paths use `*` for any array index and hold for every schema version.
COPIED_FIELDS: Mapping[tuple[str, str], str] = {
    ("core.contact", "address"): UNIT_ADDRESS,
    ("core.testimonials", "items/*/author"): UNIT_NAME,
    ("core.quote", "author"): UNIT_NAME,
    ("core.quote", "voices/*/author"): UNIT_NAME,
    ("core.rich_text", "author/name"): UNIT_NAME,
    ("core.rich_text", "content/*/author"): UNIT_NAME,
}
# Strings the schema leaves free that are data, not prose.
DATA_FIELDS = frozenset({("core.entry_list", "items/*/published_at")})
# Text about real people: their words and their roles.
PERSONAL_BLOCKS = frozenset({"core.testimonials", "core.quote"})
PERSONAL_FIELDS = frozenset({("core.rich_text", "author/role")})

_CONSTRAINED = ("enum", "pattern", "const", "format")
_MARKS = ("bold", "italic", "href", "rel")


@dataclass(frozen=True, slots=True)
class Field:
    kind: str
    max_length: int | None
    required: bool


@dataclass(frozen=True, slots=True)
class TextUnit:
    key: str
    kind: str
    # The source text; an inline unit carries its marks as tokens.
    text: str
    source_hash: str
    data_class: str
    max_length: int | None
    required: bool
    # Holds an owner's `[Uzupełnij: …]` slot: never sent anywhere, and the
    # language version waits until the owner fills the source.
    placeholder: bool

    @property
    def copied(self) -> bool:
        return self.kind in COPIED_KINDS


@dataclass(frozen=True, slots=True)
class UnitProblem:
    key: str
    code: str


class LocaleUnitsInvalid(ValueError):
    def __init__(self, problems: Sequence[UnitProblem]) -> None:
        super().__init__(", ".join(f"{problem.key}: {problem.code}" for problem in problems))
        self.problems = tuple(problems)


@dataclass(frozen=True, slots=True)
class AssembledBody:
    blocks: list[dict[str, Any]]
    # Prose units no text was given for; the source text stands in.
    missing: tuple[str, ...]


@cache
def text_fields(block_type: str, schema_version: int) -> Mapping[str, Field]:
    """Every text place of one block schema version, by path pattern."""
    root = site_block_contracts().validators[block_type][schema_version].schema
    fields: dict[str, Field] = {}
    if not isinstance(root, Mapping):
        return fields
    _collect(root, root, (), required=False, block_type=block_type, into=fields)
    return fields


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    while "$ref" in schema:
        schema = root["$defs"][schema["$ref"].removeprefix("#/$defs/")]
    return schema


def _is_inline(schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    if schema.get("type") != "array":
        return False
    item = _resolve(schema.get("items", {}), root)
    properties = item.get("properties", {})
    return "text" in properties and any(mark in properties for mark in _MARKS)


def _collect(
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: tuple[str, ...],
    *,
    required: bool,
    block_type: str,
    into: dict[str, Field],
) -> None:
    schema = _resolve(schema, root)
    for combinator in ("oneOf", "anyOf"):
        for branch in schema.get(combinator, ()):
            _collect(branch, root, path, required=required, block_type=block_type, into=into)
    pattern = "/".join(path)
    if _is_inline(schema, root):
        _add(into, pattern, Field(UNIT_INLINE, None, required))
        return
    kind = schema.get("type")
    if kind == "object":
        mandatory = set(schema.get("required", ()))
        for name, child in schema.get("properties", {}).items():
            _collect(
                child,
                root,
                (*path, name),
                required=name in mandatory,
                block_type=block_type,
                into=into,
            )
    elif kind == "array":
        _collect(
            schema.get("items", {}),
            root,
            (*path, "*"),
            required=True,
            block_type=block_type,
            into=into,
        )
    elif kind == "string" and not any(key in schema for key in _CONSTRAINED):
        if (block_type, pattern) in DATA_FIELDS:
            return
        unit_kind = COPIED_FIELDS.get((block_type, pattern), UNIT_TEXT)
        _add(
            into,
            pattern,
            Field(
                unit_kind,
                schema.get("maxLength"),
                required and schema.get("minLength", 0) > 0,
            ),
        )


def _add(into: dict[str, Field], pattern: str, field: Field) -> None:
    existing = into.get(pattern)
    if existing is None:
        into[pattern] = field
        return
    if existing.kind != field.kind:
        raise ValueError(f"Path {pattern!r} is both {existing.kind} and {field.kind}")
    limits = [limit for limit in (existing.max_length, field.max_length) if limit is not None]
    into[pattern] = Field(
        existing.kind, min(limits) if limits else None, existing.required or field.required
    )


def _data_class(block_type: str, pattern: str) -> str:
    if block_type in PERSONAL_BLOCKS or (block_type, pattern) in PERSONAL_FIELDS:
        return DATA_PUBLIC_PERSONAL
    return DATA_PUBLIC


def _places(
    value: Any, fields: Mapping[str, Field], path: tuple[str | int, ...]
) -> Iterator[tuple[tuple[str | int, ...], Field, Any]]:
    pattern = "/".join("*" if isinstance(part, int) else part for part in path)
    field = fields.get(pattern)
    if field is not None and (
        (field.kind == UNIT_INLINE and isinstance(value, list))
        or (field.kind != UNIT_INLINE and isinstance(value, str))
    ):
        yield path, field, value
        return
    if isinstance(value, dict):
        for name, child in value.items():
            yield from _places(child, fields, (*path, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _places(child, fields, (*path, index))


def _key(position: int, path: tuple[str | int, ...]) -> str:
    return "/".join((str(position), *(str(part) for part in path)))


def inline_text(spans: Sequence[Mapping[str, Any]]) -> str:
    """An inline run as one unit: marked spans become numbered tokens."""
    parts: list[str] = []
    number = 0
    for span in spans:
        text = str(span.get("text", ""))
        if any(mark in span for mark in _MARKS):
            number += 1
            parts.append(f"{open_token(number)}{text}{close_token(number)}")
        else:
            parts.append(text)
    return "".join(parts)


def _marks(spans: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {mark: span[mark] for mark in _MARKS if mark in span}
        for span in spans
        if any(mark in span for mark in _MARKS)
    ]


def extract_units(blocks: Sequence[Mapping[str, Any]]) -> list[TextUnit]:
    """The text units of a body, in block order."""
    units: list[TextUnit] = []
    for position, block in enumerate(blocks):
        block_type = str(block["block_type"])
        fields = text_fields(block_type, int(block["schema_version"]))
        for path, field, value in _places(block["data"], fields, ()):
            text = inline_text(value) if field.kind == UNIT_INLINE else value
            pattern = "/".join("*" if isinstance(part, int) else part for part in path)
            units.append(
                TextUnit(
                    key=_key(position, path),
                    kind=field.kind,
                    text=text,
                    source_hash=unit_hash(field.kind, text),
                    data_class=_data_class(block_type, pattern),
                    max_length=field.max_length,
                    required=field.required,
                    placeholder=PLACEHOLDER_PATTERN.search(text) is not None,
                )
            )
    return units


def assemble(blocks: Sequence[Mapping[str, Any]], texts: Mapping[str, str]) -> AssembledBody:
    """The source blocks with each unit's text replaced by the given one.

    A unit with no text keeps the source text and is reported as missing,
    except a copied one (an address, a name), which is the same in every
    language. Every problem is reported at once, by unit key.
    """
    units = {unit.key: unit for unit in extract_units(blocks)}
    problems = [UnitProblem(key, UNIT_UNKNOWN) for key in texts if key not in units]
    assembled = [copy.deepcopy(dict(block)) for block in blocks]
    missing: list[str] = []
    for key, unit in units.items():
        text = texts.get(key)
        if text is None:
            if not unit.copied:
                missing.append(key)
            continue
        problem = _check(unit, text)
        if problem is not None:
            problems.append(UnitProblem(key, problem))
            continue
        position, *path = key.split("/")
        target = assembled[int(position)]["data"]
        steps = [int(step) if step.isdigit() else step for step in path]
        for step in steps[:-1]:
            target = target[step]
        if unit.kind == UNIT_INLINE:
            target[steps[-1]] = _spans(target[steps[-1]], unit.text, text)
        else:
            target[steps[-1]] = text
    if not problems:
        for index, block in enumerate(assembled):
            try:
                validate_site_block(
                    block_type=block["block_type"],
                    schema_version=block["schema_version"],
                    data=block["data"],
                )
            except InvalidSiteBlockData:
                problems.append(UnitProblem(str(index), BLOCK_INVALID))
    if problems:
        raise LocaleUnitsInvalid(problems)
    return AssembledBody(assembled, tuple(missing))


def _check(unit: TextUnit, text: str) -> str | None:
    token_problems = validate_tokens(unit.text, text)
    if token_problems:
        return token_problems[0]
    if unit.kind == UNIT_INLINE:
        try:
            segments = flat_segments(text)
        except TokenError as error:
            return error.code
        marked = {segment.mark for segment in segments if segment.mark is not None}
        if marked != {segment.mark for segment in flat_segments(unit.text) if segment.mark}:
            return UNIT_TOKEN_EMPTY
        if unit.required and not "".join(segment.text for segment in segments).strip():
            return UNIT_REQUIRED
        return None
    if unit.required and not text.strip():
        return UNIT_REQUIRED
    if unit.max_length is not None and len(text) > unit.max_length:
        return UNIT_TOO_LONG
    return None


def _spans(source: list[dict[str, Any]], source_text: str, text: str) -> list[dict[str, Any]]:
    if text == source_text:
        return source
    marks = _marks(source)
    return [
        {**(marks[segment.mark - 1] if segment.mark is not None else {}), "text": segment.text}
        for segment in flat_segments(text)
        if segment.text
    ]


def structure_signature(blocks: Sequence[Mapping[str, Any]]) -> str:
    """The body with its text taken out: equal for every language version.

    An inline run keeps its marks — a link's target is structure — but not how
    its plain text happens to be split into spans.
    """
    skeleton: list[dict[str, Any]] = []
    for block in blocks:
        fields = text_fields(str(block["block_type"]), int(block["schema_version"]))
        skeleton.append({
            **{key: value for key, value in block.items() if key != "data"},
            "data": _blanked(block["data"], fields, ()),
        })
    return canonical_json_hash(skeleton)


def _blanked(value: Any, fields: Mapping[str, Field], path: tuple[str | int, ...]) -> Any:
    pattern = "/".join("*" if isinstance(part, int) else part for part in path)
    field = fields.get(pattern)
    if field is not None and field.kind == UNIT_INLINE and isinstance(value, list):
        return {"unit": UNIT_INLINE, "marks": _marks(value)}
    if field is not None and isinstance(value, str):
        return {"unit": field.kind}
    if isinstance(value, dict):
        return {name: _blanked(child, fields, (*path, name)) for name, child in value.items()}
    if isinstance(value, list):
        return [_blanked(child, fields, (*path, index)) for index, child in enumerate(value)]
    return value
