"""Translatable units, their state against a target, and what goes to a model.

A unit is the text of one translatable place (docs/architecture/translation-
sources.md §3). Its state against the text standing in its place in a target
language — missing, fresh, stale, unverified, blocked, copied — follows from
the provenance written beside that text (§4), so it is computed, never stored.

`sendable_units` turns the states and the data classes into the one answer to
"what costs credits and what reaches the model"; the quote, the automation's
planning and the contract test suite all call it, so the two cannot drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .provenance import (
    ORIGIN_COPY,
    ORIGIN_UNTRANSLATED,
    PROTECTED_ORIGINS,
    Provenance,
    normalize_unit_text,
    unit_hash,
)
from .tokens import TOKEN_PATTERN, mask

type UnitKind = Literal["text", "inline", "name", "address"]
type DataClass = Literal["public", "public_personal", "health"]
type UnitStatus = Literal["missing", "fresh", "stale", "unverified", "blocked", "copied"]
type ProtectedMode = Literal["skip", "propose", "overwrite"]

UNIT_TEXT = "text"
UNIT_INLINE = "inline"
UNIT_NAME = "name"
UNIT_ADDRESS = "address"
UNIT_KINDS = frozenset({UNIT_TEXT, UNIT_INLINE, UNIT_NAME, UNIT_ADDRESS})
# Copied into every language rather than translated, and never sent to a
# model; a script that needs it (Cyrillic) gets a transliteration by code.
COPIED_KINDS = frozenset({UNIT_NAME, UNIT_ADDRESS})

DATA_PUBLIC = "public"
DATA_PUBLIC_PERSONAL = "public_personal"
# Health data about people: never sent, whatever a profile says.
DATA_HEALTH = "health"
DATA_CLASSES = frozenset({DATA_PUBLIC, DATA_PUBLIC_PERSONAL, DATA_HEALTH})

# Why a unit stays out of what is sent, as a quote reports it.
SKIP_FRESH = "fresh"
SKIP_BLOCKED = "blocked"
SKIP_COPIED = "copied"
SKIP_NOT_SENDABLE = "not_sendable"
SKIP_PROTECTED = "protected"
SKIP_UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class Unit:
    # Stable within the current source structure only.
    key: str
    kind: str
    # The source text; inline marks as tokens.
    text: str
    data_class: str
    # Hard limit in code points.
    max_length: int | None
    # A publishable target needs it.
    required: bool = True
    # Holds an owner's `[Uzupełnij: …]` slot: never sent, blocks completeness.
    placeholder: bool = False

    def __post_init__(self) -> None:
        if self.kind not in UNIT_KINDS:
            raise ValueError(f"Unknown unit kind: {self.kind!r}")
        if self.data_class not in DATA_CLASSES:
            raise ValueError(f"Unknown data class: {self.data_class!r}")

    @property
    def source_hash(self) -> str:
        return unit_hash(self.kind, self.text)

    @property
    def copied(self) -> bool:
        return self.kind in COPIED_KINDS


@dataclass(frozen=True, slots=True)
class Target:
    text: str
    # None: written before provenance existed — protected and unverified.
    provenance: Provenance | None


@dataclass(frozen=True, slots=True)
class UnitState:
    status: str
    # Written by a person or an integration, or edited since the engine wrote
    # it: automation proposes, never overwrites.
    protected: bool


def unit_state(unit: Unit, target: Target | None) -> UnitState:
    if unit.placeholder:
        return UnitState("blocked", protected=False)
    if unit.copied:
        return UnitState("copied", protected=False)
    if target is None or not target.text.strip():
        return UnitState("missing", protected=False)
    provenance = target.provenance
    if provenance is None:
        return UnitState("unverified", protected=True)
    if provenance.origin in (ORIGIN_COPY, ORIGIN_UNTRANSLATED):
        return UnitState("missing", protected=False)
    protected = provenance.origin in PROTECTED_ORIGINS or bool(
        provenance.written_hash and unit_hash(unit.kind, target.text) != provenance.written_hash
    )
    status = "fresh" if provenance.source_hash == unit.source_hash else "stale"
    return UnitState(status, protected=protected)


def unit_states(units: Iterable[Unit], targets: Mapping[str, Target]) -> dict[str, UnitState]:
    return {unit.key: unit_state(unit, targets.get(unit.key)) for unit in units}


def visible_characters(text: str) -> int:
    """What a reader sees of a unit and a translator translates, in code points.

    Mark tokens, web and e-mail addresses, phone numbers and fill-in slots are
    not counted: they are structure or copied as they are.
    """
    masked, _spans = mask(text)
    return len(normalize_unit_text(TOKEN_PATTERN.sub(" ", masked)))


@dataclass(frozen=True, slots=True)
class Selection:
    # To send, in source order.
    units: tuple[Unit, ...]
    # Keys whose result waits beside a protected target (`overwrites_human`).
    proposals: frozenset[str]
    # Key → why it is not sent (`SKIP_*`).
    skipped: Mapping[str, str]

    @property
    def characters(self) -> int:
        return sum(visible_characters(unit.text) for unit in self.units)

    @property
    def proposal_characters(self) -> int:
        return sum(
            visible_characters(unit.text) for unit in self.units if unit.key in self.proposals
        )


def sendable_units(
    units: Iterable[Unit],
    targets: Mapping[str, Target],
    *,
    sendable: Iterable[str],
    protected: ProtectedMode,
    include_unverified: bool = False,
) -> Selection:
    """Which units go to a model, and which of them only as proposals.

    `sendable` is what the deployment profile lets leave (ADR-068 pkt 9);
    `health` never does. `protected` is how targets a person or an integration
    wrote are treated: skipped, sent as proposals that wait for the person, or
    — a person's click with "overwrite edits" only — overwritten.
    """
    allowed = frozenset(sendable) - {DATA_HEALTH}
    chosen: list[Unit] = []
    proposals: set[str] = set()
    skipped: dict[str, str] = {}
    for unit in units:
        state = unit_state(unit, targets.get(unit.key))
        if state.status in ("fresh", "blocked", "copied"):
            skipped[unit.key] = {"fresh": SKIP_FRESH, "blocked": SKIP_BLOCKED}.get(
                state.status, SKIP_COPIED
            )
            continue
        if unit.data_class not in allowed:
            skipped[unit.key] = SKIP_NOT_SENDABLE
            continue
        if state.status == "unverified":
            if protected == "overwrite":
                chosen.append(unit)
            elif protected == "propose" and include_unverified:
                chosen.append(unit)
                proposals.add(unit.key)
            else:
                skipped[unit.key] = SKIP_UNVERIFIED
            continue
        if state.status == "stale" and state.protected:
            if protected == "skip":
                skipped[unit.key] = SKIP_PROTECTED
                continue
            if protected == "propose":
                proposals.add(unit.key)
        chosen.append(unit)
    return Selection(units=tuple(chosen), proposals=frozenset(proposals), skipped=skipped)
