"""A wall clock that never runs backwards, for the suite.

The code compares one reading of `timezone.now()` with a later one: a job is
due when its `next_attempt_at` — the clock at its creation — is not after the
clock at the claim. A wall clock that is stepped back between the two readings
makes the fresh job "not yet due"; in production the next tick picks it up, in
a test the single run does nothing and the assertion after it fails.

A developer's WSL machine does exactly that: its clock is stepped back about
100 ms every 30 s (measured 2026-10-03). A busy machine widens the gap between
the two readings, which is why the failure showed up beside a second gate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

_TICK = timedelta(microseconds=1)


def never_backwards(clock: Callable[[], datetime]) -> Callable[[], datetime]:
    """`clock`, except that every reading is later than the one before it.

    Strictly later, not merely "not earlier": readings held equal while the
    real clock catches up would tie rows that are ordered by their timestamps.
    """
    last = clock()

    def now() -> datetime:
        nonlocal last
        last = max(clock(), last + _TICK)
        return last

    return now
