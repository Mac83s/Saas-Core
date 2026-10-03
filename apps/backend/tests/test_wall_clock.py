"""The suite's clock (`saas_core.testing.clock`, applied in `conftest.py`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from saas_core.testing.clock import never_backwards


def test_a_clock_stepped_back_is_never_read_as_earlier_than_before() -> None:
    start = datetime(2026, 10, 3, 20, 25, tzinfo=UTC)
    # The host sync takes 100 ms back; the clock then runs on from there.
    readings = iter(
        start + timedelta(milliseconds=offset) for offset in (0, 40, -60, -59, -20, 30, 70)
    )
    now = never_backwards(lambda: next(readings))
    seen = [now() for _ in range(6)]
    assert seen == sorted(set(seen))
    # Once the real clock has caught up, it is the clock again.
    assert seen[-1] == start + timedelta(milliseconds=70)


def test_the_suite_reads_the_guarded_clock() -> None:
    first, second = timezone.now(), timezone.now()
    assert timezone.now.__qualname__.startswith("never_backwards")
    assert first < second
