"""The quote: what a translation would cost, sealed by a digest (ADR-069 pkt 18, 19, 23).

A quote counts visible source characters of the units `sendable_units` would
send per (object, language), says what waits for a person and why, and splits
a job bigger than 500 units into parts. One unit is 1,000 characters in one
target language; a person's job rounds up once per part, at least one unit.
The digest is a SHA-256 of the canonical quote with the source versions and
unit hashes, the price, the mode and the options: the order carries it, and a
source that changed in between makes it stale (409 `translation_quote_changed`).
Customer text — labels, unit texts — never enters the digest or a log.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from saas_core.content_protocol.policy import (
    PublicationDecision,
    TranslationPolicy,
    Trigger,
    WriteTarget,
    decide_publication,
)
from saas_core.content_protocol.sources import SourceRead
from saas_core.content_protocol.units import ProtectedMode, Selection

#: Characters per billed unit, in one target language.
UNIT_CHARACTERS = 1_000
#: Units per part of a job; each part reserves its credits when it starts.
PART_UNITS = 500


@dataclass(frozen=True, slots=True)
class QuoteLine:
    source_key: str
    object_id: UUID
    locale: str
    basis: str
    basis_version: str
    target_version: str | None
    # (unit key, source hash) of what is sent, in order.
    units: tuple[tuple[str, str], ...]
    characters: int
    proposals: tuple[str, ...]
    proposal_characters: int
    # Skip reason → how many units.
    skipped: tuple[tuple[str, int], ...]
    # Where the results land unless something changes (§7 rules).
    outcome: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class Quote:
    lines: tuple[QuoteLine, ...]
    # Line indexes per part, in order.
    parts: tuple[tuple[int, ...], ...]
    characters: int
    units: int
    operation_key: str
    unit_cost: int
    credits: int
    mode: str
    protected: str
    include_unverified: bool
    digest: str

    @property
    def waiting(self) -> dict[str, int]:
        """Lines whose results wait for a person, by reason."""
        return dict(
            Counter(line.reason for line in self.lines if line.outcome == "pending" and line.reason)
        )


def quote_line(
    *,
    source_key: str,
    read: SourceRead,
    selection: Selection,
    policy: TranslationPolicy,
    trigger: Trigger,
) -> QuoteLine:
    requested: WriteTarget = "draft" if read.basis == "working" else "live"
    decision: PublicationDecision = decide_publication(
        policy=policy,
        requested=requested,
        requested_reason=None,
        trigger=trigger,
        facts=read.facts,
    )
    return QuoteLine(
        source_key=source_key,
        object_id=read.object_id,
        locale=read.locale,
        basis=read.basis,
        basis_version=read.basis_version,
        target_version=read.target_version,
        units=tuple((unit.key, unit.source_hash) for unit in selection.units),
        characters=selection.characters,
        proposals=tuple(sorted(selection.proposals)),
        proposal_characters=selection.proposal_characters,
        skipped=tuple(sorted(Counter(selection.skipped.values()).items())),
        outcome=decision.outcome,
        reason=decision.reason,
    )


def billed_units(characters: int) -> int:
    """A person's job: rounded up once, at least one unit when anything is sent."""
    return max(1, math.ceil(characters / UNIT_CHARACTERS)) if characters > 0 else 0


def split_parts(lines: Sequence[QuoteLine]) -> tuple[tuple[int, ...], ...]:
    """Lines in order, a new part whenever the next would pass 500 units.

    A line is never split; one larger than a part is a part of its own.
    """
    limit = PART_UNITS * UNIT_CHARACTERS
    parts: list[list[int]] = []
    size = 0
    for index, line in enumerate(lines):
        if not line.characters:
            continue
        if not parts or size + line.characters > limit:
            parts.append([])
            size = 0
        parts[-1].append(index)
        size += line.characters
    return tuple(tuple(part) for part in parts)


def build_quote(
    lines: Sequence[QuoteLine],
    *,
    operation_key: str,
    unit_cost: int,
    mode: str,
    protected: ProtectedMode,
    include_unverified: bool,
) -> Quote:
    ordered = tuple(lines)
    parts = split_parts(ordered)
    units = sum(billed_units(sum(ordered[index].characters for index in part)) for part in parts)
    canonical = {
        "lines": [
            {
                "source_key": line.source_key,
                "object_id": str(line.object_id),
                "locale": line.locale,
                "basis": line.basis,
                "basis_version": line.basis_version,
                "target_version": line.target_version,
                "units": [list(unit) for unit in line.units],
                "characters": line.characters,
                "proposals": list(line.proposals),
                "outcome": line.outcome,
                "reason": line.reason,
            }
            for line in ordered
        ],
        "parts": [list(part) for part in parts],
        "operation_key": operation_key,
        "unit_cost": unit_cost,
        "units": units,
        "mode": mode,
        "protected": protected,
        "include_unverified": include_unverified,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Quote(
        lines=ordered,
        parts=parts,
        characters=sum(line.characters for line in ordered),
        units=units,
        operation_key=operation_key,
        unit_cost=unit_cost,
        credits=units * unit_cost,
        mode=mode,
        protected=protected,
        include_unverified=include_unverified,
        digest=digest,
    )
