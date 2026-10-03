"""What every source checks on a translation write, the same way
(docs/architecture/translation-sources.md §6.3).

The gate refuses a text that is empty, too long, breaks the marks, changes a
fact (a price, a time, a contact) or loses a protected name; the digest
recognises a repeated item under one idempotency key; the outcome dictionaries
keep a write's answer in a source's receipt, to answer a repeat with it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from .facts import extract_facts
from .sources import FieldError, ProtectedTerm, WriteItem, WriteOutcome
from .tokens import validate_tokens
from .units import Unit

GATE_REQUIRED = "required"
GATE_TOO_LONG = "too_long"
GATE_FACTS_CHANGED = "facts_changed"
GATE_UNKNOWN_UNIT = "unknown_unit"
GATE_PROTECTED_TERM = "protected_term_changed"


def write_gate(unit: Unit, text: str, terms: Sequence[ProtectedTerm] = ()) -> FieldError | None:
    name = f"units.{unit.key}"
    if not text.strip():
        return FieldError(name, GATE_REQUIRED, "The translation is empty.")
    problems = validate_tokens(unit.text, text)
    if problems:
        return FieldError(name, problems[0], "The marks differ from the source.")
    if unit.max_length is not None and len(text) > unit.max_length:
        return FieldError(name, GATE_TOO_LONG, "The translation is too long.")
    if extract_facts(unit.text) != extract_facts(text):
        return FieldError(name, GATE_FACTS_CHANGED, "A price, time or contact differs.")
    for term in terms:
        if term.text in unit.text and term.text not in text:
            return FieldError(name, GATE_PROTECTED_TERM, "A name is translated or missing.")
    return None


def item_digest(item: WriteItem) -> str:
    texts = {key: text for key, (text, _provenance) in item.texts.items()}
    payload = json.dumps(
        [str(item.object_id), item.locale, item.basis, item.requested, item.reason, texts],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def outcome_to_dict(outcome: WriteOutcome) -> dict[str, Any]:
    return {
        "object_id": str(outcome.object_id),
        "locale": outcome.locale,
        "state": outcome.state,
        "keys": list(outcome.keys),
        "reason": outcome.reason,
        "errors": [[e.field, e.code, e.message] for e in outcome.errors],
        "target_version": outcome.target_version,
    }


def outcome_from_dict(stored: Mapping[str, Any]) -> WriteOutcome:
    return WriteOutcome(
        object_id=UUID(stored["object_id"]),
        locale=stored["locale"],
        state=stored["state"],
        keys=tuple(stored["keys"]),
        reason=stored["reason"],
        errors=tuple(FieldError(*error) for error in stored["errors"]),
        target_version=stored["target_version"],
    )
