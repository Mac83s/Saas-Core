"""A scripted adapter for tests (ADR-068 pkt 10).

Registered only when `APP_ENV` is test or local. A test scripts the answers —
text, tool calls, structured output, refusals, errors — and the fake plays
them in order through the same port core as the real adapter: gates,
admission, validation and telemetry all run, only HTTP does not. A call the
script did not expect fails the test; every call received is kept for asserts.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from ..types import Continuation, ErrorKind, ModelError, Usage
from .base import AdapterCall, AdapterResult, RawToolCall


@dataclass(frozen=True, slots=True)
class FakeReply:
    text: str | None = None
    tool_calls: tuple[RawToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: Usage = Usage(input_tokens=100, output_tokens=50)
    cost_usd_micros: int | None = 1_000
    resolved_model: str | None = None
    resolved_provider: str = "fake"
    provider_request_id: str = "fake-request"
    latency_seconds: float = 0.0
    continuation_state: object | None = field(default=None, repr=False)
    refusal: bool = False


@dataclass(frozen=True, slots=True)
class FakeFailure:
    kind: ErrorKind
    code: str
    retry_after: float | None = None


class FakeAdapter:
    key = "fake"

    def __init__(self) -> None:
        self._script: deque[FakeReply | FakeFailure] = deque()
        self.calls: list[AdapterCall] = []

    def script(self, *steps: FakeReply | FakeFailure) -> None:
        self._script.extend(steps)

    def reset(self) -> None:
        self._script.clear()
        self.calls.clear()

    @property
    def pending(self) -> int:
        return len(self._script)

    def complete(self, call: AdapterCall) -> AdapterResult:
        self.calls.append(call)
        if not self._script:
            raise AssertionError("FakeAdapter: wywołanie spoza skryptu.")
        step = self._script.popleft()
        if isinstance(step, FakeFailure):
            raise ModelError(step.kind, step.code, retry_after=step.retry_after)
        if step.latency_seconds:
            time.sleep(step.latency_seconds)
        resolved = step.resolved_model or call.model.model
        return AdapterResult(
            text=step.text,
            tool_calls=step.tool_calls,
            finish_reason=step.finish_reason,
            usage=step.usage,
            cost_usd_micros=step.cost_usd_micros,
            resolved_model=resolved,
            resolved_provider=step.resolved_provider,
            provider_request_id=step.provider_request_id,
            continuation=(
                Continuation(model=resolved, state=step.continuation_state)
                if step.continuation_state is not None
                else None
            ),
            refusal=step.refusal,
        )


#: The one instance the registry hands out; tests script and reset it.
FAKE = FakeAdapter()
