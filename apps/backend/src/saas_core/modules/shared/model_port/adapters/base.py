"""What an adapter receives and returns: transport only (ADR-068 pkt 3).

The port core validates the request, admits it against the ceilings, picks
the structured-output mode, and checks what comes back — tool arguments
against their schemas, structured output against its schema. An adapter turns
one call into one provider request and the provider's answer into raw parts,
or raises `ModelError` with the kind its status means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..matrix import ModelProfile
from ..types import Continuation, ModelRequest, TaskSpec, Usage

StructuredMode = Literal["none", "json_schema", "json_mode"]


@dataclass(frozen=True, slots=True)
class AdapterCall:
    spec: TaskSpec
    request: ModelRequest
    model: ModelProfile
    max_tokens: int
    #: `time.monotonic()` by which the answer must have arrived.
    deadline: float
    #: Salted HMAC of the organization; never the id itself.
    user: str
    zdr: bool
    structured: StructuredMode
    #: Only hosts that do not collect what they are sent — not to train on and
    #: not for anything else (`model_port.privacy.no_training_providers`;
    #: always so for `personal`). An adapter that cannot ask its provider for
    #: that must refuse the call instead of sending it.
    no_training: bool = True
    #: Continuations of another model already removed by the core.
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawToolCall:
    id: str
    name: str
    arguments_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    text: str | None = field(repr=False)
    tool_calls: tuple[RawToolCall, ...]
    #: "stop", "length", "tool_calls", "content_filter", "refusal", "error".
    finish_reason: str
    usage: Usage
    #: The provider's own cost, or None when the response did not carry it.
    cost_usd_micros: int | None
    resolved_model: str
    resolved_provider: str
    provider_request_id: str
    continuation: Continuation | None = field(default=None, repr=False)
    #: A refusal the provider stated outright (e.g. a `refusal` field).
    refusal: bool = False


class Adapter(Protocol):
    key: str

    def complete(self, call: AdapterCall) -> AdapterResult: ...
