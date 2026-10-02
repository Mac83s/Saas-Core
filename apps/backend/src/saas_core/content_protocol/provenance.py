"""Who wrote a unit's text, against which source text, and the unit's hash."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

ORIGIN_AI = "ai"
ORIGIN_HUMAN = "human"
ORIGIN_INTEGRATION = "integration"
ORIGIN_TEMPLATE = "template"
ORIGIN_IMPORT = "import"
# The source text standing in for a translation: shown, never counted as one.
ORIGIN_COPY = "copy"
ORIGIN_UNTRANSLATED = "untranslated"
ORIGINS = frozenset({
    ORIGIN_AI,
    ORIGIN_HUMAN,
    ORIGIN_INTEGRATION,
    ORIGIN_TEMPLATE,
    ORIGIN_IMPORT,
    ORIGIN_COPY,
    ORIGIN_UNTRANSLATED,
})
# What automation must never overwrite without a person's review.
PROTECTED_ORIGINS = frozenset({ORIGIN_HUMAN, ORIGIN_INTEGRATION})

_WHITESPACE = re.compile(r"\s+")


def normalize_unit_text(text: str) -> str:
    """One spelling for text that reads the same: NFC, whitespace collapsed."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def unit_hash(kind: str, text: str) -> str:
    """The key of a source unit in the translation memory.

    The kind takes part: the same words as a page title and as a link label
    are translated differently.
    """
    return hashlib.sha256(f"{kind}\n{normalize_unit_text(text)}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    origin: str
    # `unit_hash` of the source text this text translates.
    source_hash: str
    # `unit_hash` of this text when it was written: a later edit shows as a
    # mismatch without keeping the history in the unit.
    written_hash: str = ""
    model: str = ""
    # ISO 8601.
    at: str = ""

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ValueError(f"Unknown provenance origin: {self.origin!r}")
        if not self.source_hash:
            raise ValueError("Provenance needs the source hash it translates.")

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("origin", self.origin),
                ("source_hash", self.source_hash),
                ("written_hash", self.written_hash),
                ("model", self.model),
                ("at", self.at),
            )
            if value
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Provenance:
        return cls(
            origin=str(value["origin"]),
            source_hash=str(value["source_hash"]),
            written_hash=str(value.get("written_hash", "")),
            model=str(value.get("model", "")),
            at=str(value.get("at", "")),
        )
