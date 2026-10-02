"""The port's request, response and error types (ADR-068, docs/architecture/model-port.md).

Plain frozen dataclasses with no Django in them, so callers, adapters and tests
share one vocabulary. Fields that carry content — message text, tool
arguments, structured output, provider state — are `repr=False`: a type that
ends up in a log line or an exception never prints what a customer wrote.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

Role = Literal["system", "user", "assistant", "tool"]
DataClass = Literal["public", "public_personal", "personal", "health"]
Purpose = Literal["customer", "platform", "eval", "probe"]
FinishReason = Literal["stop", "length", "tool_calls"]
CostSource = Literal["provider", "computed"]
ErrorKind = Literal[
    "refused",
    "retryable",
    "unknown_outcome",
    "account_limit",
    "configuration",
    "invalid_request",
    "invalid_output",
    "tool_args_invalid",
    "budget",
]
Decision = Literal["granted", "deferred", "denied"]

#: Highest class first: a request is as sensitive as its most sensitive part.
DATA_CLASS_RANK: Mapping[str, int] = {
    "public": 0,
    "public_personal": 1,
    "personal": 2,
    "health": 3,
}


@dataclass(frozen=True, slots=True)
class NamedTool:
    name: str


ToolChoice = Literal["auto", "none", "required"] | NamedTool


@dataclass(frozen=True, slots=True)
class Continuation:
    """Opaque provider state a model needs back on its next turn (signed
    reasoning blocks), with the model it came from: another model never gets it."""

    model: str
    state: Any = field(repr=False)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    #: The model's exact text, treated as content.
    arguments_json: str = field(repr=False)
    #: Set only when the text parses and satisfies the tool's input schema.
    arguments: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str | None = field(default=None, repr=False)
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    continuation: Continuation | None = field(default=None, repr=False)
    #: A cache hint for the provider; dropped where the model has no cache.
    cache: bool = False


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class JsonSchemaFormat:
    name: str
    schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ModelContext:
    organization_id: UUID | None
    actor_id: UUID | None = None
    conversation_id: UUID | None = None
    purpose: Purpose | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: str
    messages: tuple[Message, ...]
    prompt_id: str
    prompt_version: str
    context: ModelContext
    data_class: DataClass
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice | None = None
    parallel_tool_calls: bool | None = None
    cache_tools: bool = False
    response_format: JsonSchemaFormat | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    #: Only with purpose eval or probe: the candidates and the judge of evals.
    model: str | None = None
    #: `<kind>:<uuid>` of what the caller is doing, for telemetry.
    reference: str | None = None
    resend_of: UUID | None = None
    admission_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    #: Including reasoning.
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str | None = field(repr=False)
    tool_calls: tuple[ToolCall, ...]
    output: Mapping[str, Any] | None = field(repr=False)
    finish_reason: FinishReason
    usage: Usage
    cost_usd_micros: int | None
    cost_source: CostSource | None
    adapter: str
    requested_model: str
    resolved_model: str
    resolved_provider: str
    provider_request_id: str
    latency_ms: int
    usage_entry_id: UUID | None = None
    continuation: Continuation | None = field(default=None, repr=False)

    def as_message(self) -> Message:
        """The assistant turn to send back, tool calls and provider state verbatim."""
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=self.tool_calls,
            continuation=self.continuation,
        )


@dataclass(frozen=True, slots=True)
class FieldError:
    """The A1a field error (ADR-076 §5): a dot path, a code, a message without values."""

    field: str
    code: str
    message: str


class ModelError(Exception):
    """What went wrong, as a kind for the caller's decision and a code for the record.

    `str(error)` is the code: nothing a customer or a provider wrote.
    """

    def __init__(
        self,
        kind: ErrorKind,
        code: str,
        *,
        retry_after: float | None = None,
        until: datetime | None = None,
        errors: tuple[FieldError, ...] = (),
        response: ModelResponse | None = None,
        usage_entry_id: UUID | None = None,
    ) -> None:
        super().__init__(code)
        self.kind = kind
        self.code = code
        self.retry_after = retry_after
        self.until = until
        self.errors = errors
        self.response = response
        self.usage_entry_id = usage_entry_id


@dataclass(frozen=True, slots=True)
class Admission:
    decision: Decision
    reason: str | None = None
    until: datetime | None = None
    id: UUID | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskSpec:
    key: str
    pool: str
    adapter: str
    model: str
    timeout_seconds: float
    #: `(factor, reserve, cap)`: max_tokens = factor × content tokens + reserve, at most cap.
    max_tokens_rule: tuple[float, int, int]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    #: Capabilities the task's model must have, e.g. {"json_schema"}.
    capabilities: frozenset[str] = frozenset()
    max_data_class: DataClass = "public_personal"
    #: Context fields a request must carry.
    required_context: frozenset[str] = frozenset({"organization_id"})
    resend_unknown: bool = False
    enabled: bool = True
    admission_ttl: timedelta = timedelta(minutes=10)
    daily_cap_usd: float | None = None
    #: Purposes this task accepts; None means customer and platform.
    purposes: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class TaskStatus:
    task: str
    available: bool
    reason: str | None
    until: datetime | None
    model: str
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class BudgetLevel:
    level: str
    spent_usd_micros: int
    cap_usd_micros: int | None


@dataclass(frozen=True, slots=True)
class BudgetState:
    task: str
    levels: tuple[BudgetLevel, ...]
