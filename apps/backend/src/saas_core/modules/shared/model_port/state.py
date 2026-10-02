"""Blocks that act as gates, kept in the cache (ADR-068 pkt 6, model-port.md „Błędy”).

A 402 blocks the adapter for an hour, a 401 too; a 503 with no host meeting
the requirements blocks one task–model pair for 15 minutes, and the third such
block in a day holds the pair until an operator lifts it. While a block lasts,
calls end at once with the same kind of error and its time, without the
network. Losing the cache only lets one more call find out again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.core.cache import cache

ADAPTER_BLOCK = timedelta(hours=1)
PAIR_BLOCK = timedelta(minutes=15)
PAIR_BLOCKS_BEFORE_OPERATOR = 3
OPERATOR_HOLD = timedelta(days=365)


def _now() -> datetime:
    return datetime.now(UTC)


def _adapter_key(adapter: str) -> str:
    return f"model_port:block:adapter:{adapter}"


def _pair_key(task: str, model: str) -> str:
    return f"model_port:block:pair:{task}:{model}"


def block_adapter(adapter: str, kind: str, code: str) -> datetime:
    until = _now() + ADAPTER_BLOCK
    cache.set(
        _adapter_key(adapter), (until.isoformat(), kind, code), int(ADAPTER_BLOCK.total_seconds())
    )
    return until


def block_pair(task: str, model: str, code: str) -> datetime:
    day = _now().date().isoformat()
    counter = f"model_port:block:pair_count:{task}:{model}:{day}"
    count = cache.get(counter, 0) + 1
    cache.set(counter, count, 2 * 24 * 3600)
    duration = OPERATOR_HOLD if count >= PAIR_BLOCKS_BEFORE_OPERATOR else PAIR_BLOCK
    until = _now() + duration
    cache.set(
        _pair_key(task, model),
        (until.isoformat(), "configuration", code),
        int(duration.total_seconds()),
    )
    return until


def active_block(adapter: str, task: str, model: str) -> tuple[datetime, str, str] | None:
    for key in (_adapter_key(adapter), _pair_key(task, model)):
        value = cache.get(key)
        if value:
            until = datetime.fromisoformat(value[0])
            if until > _now():
                return until, value[1], value[2]
    return None


def unblock(task: str, model: str, adapter: str) -> None:
    cache.delete_many([_pair_key(task, model), _adapter_key(adapter)])
