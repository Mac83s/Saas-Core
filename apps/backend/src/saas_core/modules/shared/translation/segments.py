"""What one model call carries (ADR-069 pkt 5 and 9).

A call is one company, one job and one target language: one item, or a pack of
up to 20 small items, at most 6,000 characters and 80 segments together. A
segment is one unit's text with web addresses, e-mail addresses, phone numbers
and fill-in slots masked as `⟦m:k⟧`; the masks are put back after the checks.
An item too big for one call is split across calls by its units, never inside
a unit — a single unit over the limits goes alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from saas_core.content_protocol.tokens import mask
from saas_core.content_protocol.units import Unit, visible_characters

MAX_CALL_CHARACTERS = 6_000
MAX_CALL_SEGMENTS = 80
MAX_CALL_ITEMS = 20


@dataclass(frozen=True, slots=True)
class Segment:
    # Short and per call ("s1"): what the model echoes back.
    id: str
    # Index of the item in the job (object × language) and the unit's key there.
    item: int
    key: str
    unit: Unit
    # The unit's text as the model sees it.
    masked: str
    spans: dict[int, str] = field(default_factory=dict)

    @property
    def characters(self) -> int:
        return visible_characters(self.unit.text)


@dataclass(frozen=True, slots=True)
class Call:
    segments: tuple[Segment, ...]

    @property
    def characters(self) -> int:
        return sum(segment.characters for segment in self.segments)

    @property
    def items(self) -> frozenset[int]:
        return frozenset(segment.item for segment in self.segments)


def plan_calls(items: Sequence[Sequence[Unit]]) -> tuple[Call, ...]:
    """Packs the units to send of each item, in order, into calls."""
    calls: list[Call] = []
    current: list[tuple[int, Unit]] = []

    def close() -> None:
        if current:
            calls.append(_call(current))
            current.clear()

    for index, units in enumerate(items):
        for unit in units:
            if current:
                characters = sum(visible_characters(u.text) for _i, u in current)
                items_in = {i for i, _u in current} | {index}
                if (
                    characters + visible_characters(unit.text) > MAX_CALL_CHARACTERS
                    or len(current) + 1 > MAX_CALL_SEGMENTS
                    or len(items_in) > MAX_CALL_ITEMS
                ):
                    close()
            current.append((index, unit))
    close()
    return tuple(calls)


def _call(units: list[tuple[int, Unit]]) -> Call:
    segments = []
    for number, (item, unit) in enumerate(units, start=1):
        masked, spans = mask(unit.text)
        segments.append(
            Segment(id=f"s{number}", item=item, key=unit.key, unit=unit, masked=masked, spans=spans)
        )
    return Call(segments=tuple(segments))
