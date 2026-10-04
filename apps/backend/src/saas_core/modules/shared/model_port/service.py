"""The port's core: validate, admit, call, check the answer, record (ADR-068).

`complete(request)` is a plain synchronous function — a view, a Celery task
and a command call it alike, and it queues nothing. It never retries on its
own and never switches the model: it returns a response or raises
`ModelError` with a kind the caller decides on (docs/architecture/model-port.md).
Every call, failed or not, leaves one telemetry row without content.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import jsonschema
from django.conf import settings
from django.utils.crypto import salted_hmac

from saas_core.modules.core.organizations.api import platform_setting

from . import admission, metrics, state
from .adapters.base import Adapter, AdapterCall, AdapterResult, StructuredMode
from .matrix import (
    IN_PROCESS_ADAPTER,
    ModelProfile,
    listed_hosts,
    model_profile,
    processor_listed,
)
from .models import EntryState, UsageEntry
from .registry import task_spec
from .settings_spec import CLAUDE_MODELS, CLAUDE_PROVIDER, CLAUDE_PROVIDERS, NO_TRAINING
from .test_double import routed
from .types import (
    DATA_CLASS_RANK,
    FieldError,
    Message,
    ModelError,
    ModelRequest,
    ModelResponse,
    NamedTool,
    TaskSpec,
    ToolCall,
)

PROMPT_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
PROMPT_VERSION = re.compile(r"^[a-z0-9_.-]{1,40}$")
REFERENCE = re.compile(r"^[a-z][a-z0-9_]{0,40}:[0-9a-f-]{36}$")
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
ERROR_CODE = re.compile(r"^[a-z0-9_.:-]{1,80}$")
#: One token per two characters: on purpose more than any model needs, so the
#: estimate leans towards keeping money, never towards overspending it.
CHARACTERS_PER_TOKEN = 2
REQUEST_MAX_CHARACTERS = 2 * 1024 * 1024
WEB_TIMEOUT_MARGIN = 2.0
SWEEP_GRACE = timedelta(seconds=60)

_ADAPTERS: dict[str, Adapter] = {}
_in_web_request: ContextVar[bool] = ContextVar("model_port_in_web_request", default=False)
_web_slots: threading.BoundedSemaphore | None = None
_web_slots_lock = threading.Lock()


def register_adapter(adapter: Adapter) -> None:
    _ADAPTERS[adapter.key] = adapter


def adapter_for(key: str) -> Adapter | None:
    return _ADAPTERS.get(key)


@contextmanager
def web_request() -> Iterator[None]:
    """Marks the calls made while an HTTP request is handled (the port's middleware)."""
    token = _in_web_request.set(True)
    try:
        yield
    finally:
        _in_web_request.reset(token)


def _web_semaphore() -> threading.BoundedSemaphore:
    global _web_slots
    with _web_slots_lock:
        if _web_slots is None:
            _web_slots = threading.BoundedSemaphore(
                max(1, int(settings.MODEL_PORT_WEB_CALLS_PER_PROCESS))
            )
        return _web_slots


def user_tag(organization_id: UUID | None) -> str:
    """What OpenRouter sees of the company: a salted HMAC, never the id."""
    return salted_hmac(
        "saas_core.model_port.user",
        str(organization_id) if organization_id else "platform",
        algorithm="sha256",
    ).hexdigest()


def complete(request: ModelRequest) -> ModelResponse:
    # A browser test's company on a local stack gets the stand-in (TL15d).
    spec = routed(_spec(request.task), request.context.organization_id)
    profile = _profile(spec, request)
    purpose = _purpose(request)
    _validate(request, spec, profile, purpose)
    adapter = adapter_for(profile.adapter)
    if adapter is None:
        _refuse(spec, "configuration", "adapter_unknown")
    _gates(spec, profile, purpose)
    max_tokens = _max_tokens(spec, profile, request)
    estimate = _estimate(profile, request, max_tokens)
    ask = admission.Ask(
        spec=spec,
        context=request.context,
        purpose=purpose,
        estimate_usd_micros=estimate,
        model=profile.model,
        data_class=request.data_class,
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        reference=request.reference or "",
        resend_of=request.resend_of,
    )
    web = _in_web_request.get()
    timeout = float(request.timeout_seconds or spec.timeout_seconds)
    if web:
        timeout = min(timeout, float(settings.GUNICORN_GRACEFUL_TIMEOUT) - WEB_TIMEOUT_MARGIN)
    slot = _web_semaphore() if web else None
    if slot is not None and not slot.acquire(blocking=False):
        _refuse(spec, "retryable", "web_capacity", retry_after=2)
    try:
        entry = _admitted(request, ask)
        messages, dropped = _without_foreign_continuations(
            request.messages, {profile.model, *profile.dated_variants}
        )
        # Personal data goes only to hosts that keep and train on nothing,
        # whatever the platform's setting says about the rest.
        personal = request.data_class == "personal"
        no_training = personal or bool(platform_setting(NO_TRAINING.key))
        call = AdapterCall(
            spec=spec,
            request=replace(request, messages=messages),
            model=profile,
            max_tokens=max_tokens,
            deadline=time.monotonic() + timeout,
            user=user_tag(request.context.organization_id),
            zdr=personal or (no_training and "zdr" in profile.capabilities),
            structured=_structured_mode(request, profile),
            no_training=no_training,
            provider=_pinned_provider(profile),
            parameters=dict(spec.defaults),
        )
        UsageEntry.objects.using(admission.alias()).filter(
            pk=entry.id, state=EntryState.ADMITTED
        ).update(
            state=EntryState.CALLING,
            adapter=profile.adapter,
            continuations_dropped=dropped,
            expires_at=admission.now() + timedelta(seconds=timeout) + SWEEP_GRACE,
        )
        started = time.monotonic()
        try:
            result = adapter.complete(call)  # type: ignore[union-attr]
        except Exception as error:
            if not isinstance(error, ModelError):
                # A bug in an adapter still closes its row instead of leaving it
                # `calling` until the sweep.
                _finish(
                    entry.id,
                    spec,
                    outcome="unknown_outcome",
                    code="adapter_exception",
                    started=started,
                )
                metrics.ESTIMATED.labels(spec.key, profile.adapter).inc(estimate)
                raise
            _apply_block(error, spec, profile)
            _finish(entry.id, spec, outcome=error.kind, code=error.code, started=started)
            if error.kind == "unknown_outcome":
                # The cost stays unknown; the ceilings count the estimate meanwhile.
                metrics.ESTIMATED.labels(spec.key, profile.adapter).inc(estimate)
            error.usage_entry_id = entry.id
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        return _interpret(result, request, spec, profile, entry.id, latency_ms)
    finally:
        if slot is not None:
            slot.release()


def _spec(task: str) -> TaskSpec:
    spec = task_spec(task)
    if spec is None:
        raise ModelError("invalid_request", "task_unknown")
    if not spec.enabled:
        _refuse(spec, "configuration", "task_disabled")
    return spec


def _profile(spec: TaskSpec, request: ModelRequest) -> ModelProfile:
    explicit = request.model is not None
    if explicit and request.context.purpose not in {"eval", "probe"}:
        _refuse(spec, "invalid_request", "model_override_not_allowed")
    model = request.model if explicit else spec.model
    if not model:
        _refuse(spec, "configuration", "model_not_selected")
    profile = model_profile(spec.adapter, str(model))
    if profile is None:
        _refuse(spec, "configuration", "model_not_allowed")
    assert profile is not None
    # A probe is how a row gets confirmed, so only a probe may call an unconfirmed one.
    if profile.probed is None and request.context.purpose != "probe":
        _refuse(spec, "configuration", "model_not_allowed")
    if not spec.capabilities <= profile.capabilities:
        _refuse(spec, "configuration", "model_lacks_capability")
    return profile


def _purpose(request: ModelRequest) -> str:
    if request.context.purpose in {"eval", "probe"}:
        return str(request.context.purpose)
    from saas_core.modules.core.organizations.platform_workspace import platform_workspace

    workspace = _platform_workspace_id(platform_workspace)
    if workspace is not None and request.context.organization_id == workspace:
        return "platform"
    return "customer"


_PLATFORM_ID: list[UUID | None] = []


def _platform_workspace_id(lookup: Any) -> UUID | None:
    """The publisher's id, read through its counted door once per process."""
    if not _PLATFORM_ID:
        workspace = lookup()
        if workspace is None:
            return None
        _PLATFORM_ID.append(workspace.id)
    return _PLATFORM_ID[0]


def _validate(request: ModelRequest, spec: TaskSpec, profile: ModelProfile, purpose: str) -> None:
    def refuse(code: str) -> None:
        _refuse(spec, "invalid_request", code)

    if spec.purposes is not None and purpose not in spec.purposes:
        refuse("purpose_not_allowed")
    if PROMPT_ID.fullmatch(request.prompt_id) is None:
        refuse("prompt_id_invalid")
    if PROMPT_VERSION.fullmatch(request.prompt_version) is None:
        refuse("prompt_version_invalid")
    if request.reference is not None and REFERENCE.fullmatch(request.reference) is None:
        refuse("reference_invalid")
    _validate_context(request, spec, purpose, refuse)
    _validate_messages(request.messages, refuse)
    _validate_tools(request, profile, refuse)
    if request.response_format is not None:
        _check_schema(request.response_format.schema, refuse)
        if request.tools and "json_schema_with_tools" not in profile.capabilities:
            _refuse(spec, "invalid_request", "capability_not_supported")
        if not {"json_schema", "json_mode"} & profile.capabilities:
            _refuse(spec, "invalid_request", "capability_not_supported")
    if request.data_class == "health":
        refuse("data_class_not_sendable")
    if DATA_CLASS_RANK[request.data_class] > DATA_CLASS_RANK[spec.max_data_class]:
        refuse("data_class_not_sendable")
    if request.data_class not in settings.MODEL_PORT_SENDABLE_DATA_CLASSES:
        refuse("data_class_not_sendable")
    if request.data_class == "personal" and "zdr" not in profile.capabilities:
        _refuse(spec, "invalid_request", "capability_not_supported")
    rule_cap = spec.max_tokens_rule[2]
    if request.max_tokens is not None and (
        request.max_tokens < 1 or request.max_tokens > min(rule_cap, profile.max_output_tokens)
    ):
        refuse("max_tokens_invalid")
    if (
        request.timeout_seconds is not None
        and not 0 < request.timeout_seconds <= spec.timeout_seconds
    ):
        refuse("timeout_invalid")
    if _characters(request) > REQUEST_MAX_CHARACTERS:
        refuse("request_too_large")
    if _content_tokens(request) > profile.context_window:
        refuse("request_too_large")
    if request.resend_of is not None:
        original = UsageEntry.objects.using(admission.alias()).filter(pk=request.resend_of).first()
        if (
            not spec.resend_unknown
            or original is None
            or original.outcome != "unknown_outcome"
            or original.task != spec.key
            or original.requested_model != profile.model
            or UsageEntry.objects.using(admission.alias())
            .filter(resend_of=request.resend_of)
            .exists()
        ):
            refuse("resend_not_allowed")


def _validate_context(request: ModelRequest, spec: TaskSpec, purpose: str, refuse: Any) -> None:
    context = request.context
    if context.organization_id is None and purpose not in {"eval", "probe"}:
        refuse("context_missing")
    if purpose not in {"eval", "probe"}:
        for name in spec.required_context:
            if getattr(context, name) is None:
                refuse("context_missing")
    from saas_core.modules.core.organizations.context import current_tenant_context

    tenant = current_tenant_context()
    if tenant is not None:
        if context.organization_id != tenant.organization_id:
            refuse("context_mismatch")
        if context.actor_id is not None and context.actor_id != tenant.actor_id:
            refuse("context_mismatch")
        # An assistant's call spends its own conversation's budget, never another's.
        acting_ref = str(getattr(tenant, "acting_ref", "") or "")
        if (
            getattr(tenant, "acting_via", "") == "assistant"
            and acting_ref.startswith("conversation:")
            and str(context.conversation_id) != acting_ref.removeprefix("conversation:")
        ):
            refuse("context_mismatch")


def _validate_messages(messages: tuple[Message, ...], refuse: Any) -> None:
    if not messages:
        refuse("messages_empty")
    seen_other = False
    open_calls: set[str] = set()
    for message in messages:
        if message.role == "system":
            if seen_other:
                refuse("system_not_first")
            continue
        seen_other = True
        if (message.tool_calls or message.continuation is not None) and message.role != "assistant":
            refuse("message_shape_invalid")
        if message.role == "tool":
            if message.content is None:
                refuse("message_shape_invalid")
            if message.tool_call_id not in open_calls:
                refuse("tool_result_unexpected")
            open_calls.discard(str(message.tool_call_id))
            continue
        if open_calls:
            refuse("tool_result_missing")
        if message.role == "assistant":
            open_calls = {call.id for call in message.tool_calls}


def _validate_tools(request: ModelRequest, profile: ModelProfile, refuse: Any) -> None:
    names = [tool.name for tool in request.tools]
    if len(set(names)) != len(names) or any(TOOL_NAME.fullmatch(name) is None for name in names):
        refuse("tool_name_invalid")
    for tool in request.tools:
        _check_schema(tool.input_schema, refuse)
    choice = request.tool_choice
    if not request.tools:
        if choice not in (None, "none") or request.parallel_tool_calls is not None:
            refuse("tool_choice_invalid")
        return
    capabilities = profile.capabilities

    def unsupported() -> None:
        raise ModelError("invalid_request", "capability_not_supported")

    if "tools" not in capabilities:
        unsupported()
    if choice == "required" and "tool_choice_required" not in capabilities:
        unsupported()
    if isinstance(choice, NamedTool):
        if choice.name not in names:
            refuse("tool_choice_invalid")
        if "tool_choice_named" not in capabilities:
            unsupported()
    if request.parallel_tool_calls is False and "parallel_tool_calls_off" not in capabilities:
        unsupported()


def _check_schema(schema: Mapping[str, Any], refuse: Any) -> None:
    if schema.get("type") != "object":
        refuse("schema_invalid")
    try:
        jsonschema.Draft202012Validator.check_schema(dict(schema))
    except jsonschema.SchemaError:
        refuse("schema_invalid")


def _gates(spec: TaskSpec, profile: ModelProfile, purpose: str) -> None:
    if profile.adapter == "openrouter":
        if not settings.MODEL_PORT_OPENROUTER_API_KEY_MOUNTED:
            _refuse(spec, "configuration", "key_not_mounted")
        if not settings.MODEL_PORT_OPENROUTER_API_KEY:
            _refuse(spec, "configuration", "adapter_unconfigured")
    if purpose == "customer" and not settings.MODEL_PORT_PROCESSOR_LISTED:
        _refuse(spec, "configuration", "processor_not_listed")
    # Whoever chose the task's model — an operator before the rule, `.env`,
    # a default in code — a company's content goes only to a processor the
    # privacy documents name (`matrix.LISTED_PROCESSORS`).
    if purpose == "customer" and not processor_listed(profile.adapter, profile.model):
        _refuse(spec, "configuration", "processor_not_listed")
    # …and only at the host they name for it: a pin outside the listed chain —
    # stored before the setting refused it — serves no company.
    if purpose == "customer" and profile.adapter != IN_PROCESS_ADAPTER:
        named = _pinned_provider(profile)
        if named is not None and named not in listed_hosts(profile.adapter, profile.model):
            _refuse(spec, "configuration", "processor_not_listed")
    block = state.active_block(profile.adapter, spec.key, profile.model)
    if block is not None:
        until, kind, code = block
        _refuse(spec, kind, code, until=until)


def _content_tokens(request: ModelRequest) -> int:
    characters = sum(len(message.content or "") for message in request.messages)
    return characters // CHARACTERS_PER_TOKEN + 1


def _characters(request: ModelRequest) -> int:
    total = sum(
        len(message.content or "") + sum(len(call.arguments_json) for call in message.tool_calls)
        for message in request.messages
    )
    total += sum(len(json.dumps(dict(tool.input_schema))) for tool in request.tools)
    if request.response_format is not None:
        total += len(json.dumps(dict(request.response_format.schema)))
    return total


def _max_tokens(spec: TaskSpec, profile: ModelProfile, request: ModelRequest) -> int:
    factor, reserve, cap = spec.max_tokens_rule
    body = sum(len(m.content or "") for m in request.messages if m.role != "system")
    rule = min(int(factor * (body // CHARACTERS_PER_TOKEN + 1)) + reserve, cap)
    rule = min(rule, profile.max_output_tokens)
    return min(request.max_tokens, rule) if request.max_tokens is not None else rule


def _estimate(profile: ModelProfile, request: ModelRequest, max_tokens: int) -> int:
    input_tokens = _characters(request) // CHARACTERS_PER_TOKEN + 1
    return max(1, profile.estimate_usd_micros(input_tokens=input_tokens, output_tokens=max_tokens))


def estimate(task: str, *, input_characters: int, max_tokens: int | None = None) -> int:
    """USD micros a call of this size may cost at most, by the task's model's prices."""
    spec = task_spec(task)
    if spec is None or not spec.model:
        raise ModelError("configuration", "model_not_selected")
    profile = model_profile(spec.adapter, spec.model)
    if profile is None:
        raise ModelError("configuration", "model_not_allowed")
    factor, reserve, cap = spec.max_tokens_rule
    output = max_tokens or min(
        int(factor * (input_characters // CHARACTERS_PER_TOKEN + 1)) + reserve,
        cap,
        profile.max_output_tokens,
    )
    return max(
        1,
        profile.estimate_usd_micros(
            input_tokens=input_characters // CHARACTERS_PER_TOKEN + 1, output_tokens=output
        ),
    )


def _structured_mode(request: ModelRequest, profile: ModelProfile) -> StructuredMode:
    if request.response_format is None:
        return "none"
    if "json_schema" in profile.capabilities and _strict_subset(request.response_format.schema):
        return "json_schema"
    return "json_mode"


def _strict_subset(schema: Mapping[str, Any]) -> bool:
    from .adapters.openrouter import strict_compatible

    return strict_compatible(schema)


def highest_data_class(*classes: str) -> str:
    """The class a request carries: the most sensitive of its parts."""
    return max(classes, key=lambda name: DATA_CLASS_RANK[name])


def _without_foreign_continuations(
    messages: tuple[Message, ...], models: set[str]
) -> tuple[tuple[Message, ...], int]:
    """A continuation from another model is dropped and counted — a model change
    in the settings mid-conversation must not end the conversation."""
    dropped = 0
    kept: list[Message] = []
    for message in messages:
        if message.continuation is not None and message.continuation.model not in models:
            kept.append(replace(message, continuation=None))
            dropped += 1
        else:
            kept.append(message)
    return tuple(kept), dropped


def _admitted(request: ModelRequest, ask: admission.Ask) -> UsageEntry:
    if request.admission_id is not None:
        entry = admission.use_reservation(request.admission_id, ask)
        if entry is not None:
            return entry
    verdict, entry = admission.admit(ask)
    if verdict.decision != "granted" or entry is None:
        _refuse(ask.spec, "budget", str(verdict.reason), until=verdict.until)
    assert entry is not None
    return entry


def _pinned_provider(profile: ModelProfile) -> str | None:
    """The one host that may serve this model, or None: a Claude model called
    through OpenRouter goes where the platform's setting says — by default to
    Google's Vertex AI, European region requested, the processor the privacy documents name."""
    if not profile.model.startswith(CLAUDE_MODELS):
        return None
    return str(platform_setting(CLAUDE_PROVIDER.key))


def _interpret(
    result: AdapterResult,
    request: ModelRequest,
    spec: TaskSpec,
    profile: ModelProfile,
    entry_id: UUID,
    latency_ms: int,
) -> ModelResponse:
    cost, cost_source = _cost(result, profile)
    resolved_ok = result.resolved_model in {profile.model, *profile.dated_variants}
    # The host that answered is the host that was named, where one was.
    named = _pinned_provider(profile)
    provider_ok = named is None or result.resolved_provider == CLAUDE_PROVIDERS.get(named)

    def finish(outcome: str, code: str = "") -> None:
        _finish(
            entry_id,
            spec,
            outcome=outcome,
            code=code,
            latency_ms=latency_ms,
            result=result,
            cost=cost,
            cost_source=cost_source,
        )

    tool_calls = tuple(
        ToolCall(id=call.id, name=call.name, arguments_json=call.arguments_json)
        for call in result.tool_calls
    )
    response = ModelResponse(
        text=result.text,
        tool_calls=tool_calls,
        output=None,
        finish_reason="tool_calls"
        if tool_calls
        else ("length" if result.finish_reason == "length" else "stop"),
        usage=result.usage,
        cost_usd_micros=cost,
        cost_source=cost_source,  # type: ignore[arg-type]
        adapter=profile.adapter,
        requested_model=profile.model,
        resolved_model=result.resolved_model,
        resolved_provider=result.resolved_provider,
        provider_request_id=result.provider_request_id,
        latency_ms=latency_ms,
        usage_entry_id=entry_id,
        # Stamped with the task's model, not the dated name the provider
        # answered with, so the next turn of the same model gets it back.
        continuation=(
            replace(result.continuation, model=profile.model)
            if result.continuation is not None
            else None
        ),
    )
    if not resolved_ok:
        finish("configuration", "resolved_model_mismatch")
        raise ModelError("configuration", "resolved_model_mismatch", usage_entry_id=entry_id)
    if not provider_ok:
        finish("configuration", "resolved_provider_mismatch")
        raise ModelError("configuration", "resolved_provider_mismatch", usage_entry_id=entry_id)
    finish_reason = result.finish_reason
    if result.refusal or finish_reason in {"content_filter", "refusal"}:
        finish("refused", "model_refused")
        raise ModelError("refused", "model_refused", usage_entry_id=entry_id)
    if finish_reason == "error":
        finish("unknown_outcome", "provider_finish_error")
        raise ModelError("unknown_outcome", "provider_finish_error", usage_entry_id=entry_id)
    truncated = finish_reason == "length"
    if truncated and (request.response_format is not None or tool_calls):
        finish("invalid_output", "output_truncated")
        raise ModelError(
            "invalid_output", "output_truncated", response=response, usage_entry_id=entry_id
        )
    if not truncated and not tool_calls and not (result.text or "").strip():
        finish("refused", "empty_output")
        raise ModelError("refused", "empty_output", usage_entry_id=entry_id)
    ids = [call.id for call in tool_calls]
    if any(not call_id for call_id in ids) or len(set(ids)) != len(ids):
        finish("invalid_output", "tool_call_id_invalid")
        raise ModelError("invalid_output", "tool_call_id_invalid", usage_entry_id=entry_id)
    if tool_calls:
        checked, errors = _checked_tool_calls(tool_calls, request)
        response = replace(response, tool_calls=checked)
        if errors:
            finish("tool_args_invalid", "tool_args_invalid")
            raise ModelError(
                "tool_args_invalid",
                "tool_args_invalid",
                errors=errors,
                response=response,
                usage_entry_id=entry_id,
            )
        finish("ok")
        return response
    if request.response_format is not None:
        try:
            output = json.loads(result.text or "")
            jsonschema.validate(output, dict(request.response_format.schema))
        except (ValueError, jsonschema.ValidationError):
            finish("invalid_output", "output_schema_invalid")
            raise ModelError(
                "invalid_output",
                "output_schema_invalid",
                response=response,
                usage_entry_id=entry_id,
            ) from None
        if not isinstance(output, dict):
            finish("invalid_output", "output_schema_invalid")
            raise ModelError("invalid_output", "output_schema_invalid", usage_entry_id=entry_id)
        response = replace(response, output=output)
    finish("ok")
    return response


def _checked_tool_calls(
    calls: tuple[ToolCall, ...], request: ModelRequest
) -> tuple[tuple[ToolCall, ...], tuple[FieldError, ...]]:
    schemas = {tool.name: tool.input_schema for tool in request.tools}
    checked: list[ToolCall] = []
    errors: list[FieldError] = []
    for call in calls:
        prefix = f"tool_calls.{call.id}"
        schema = schemas.get(call.name)
        if schema is None:
            errors.append(FieldError(f"{prefix}.name", "tool_unknown", "Narzędzia nie oferowano."))
            checked.append(call)
            continue
        try:
            arguments = json.loads(call.arguments_json)
        except ValueError:
            errors.append(
                FieldError(f"{prefix}.arguments", "not_json", "Argumenty nie są obiektem JSON.")
            )
            checked.append(call)
            continue
        if not isinstance(arguments, dict):
            errors.append(
                FieldError(f"{prefix}.arguments", "not_object", "Argumenty nie są obiektem JSON.")
            )
            checked.append(call)
            continue
        found = sorted(
            jsonschema.Draft202012Validator(dict(schema)).iter_errors(arguments),
            key=lambda error: list(error.absolute_path),
        )
        for error in found:
            path = ".".join(str(part) for part in error.absolute_path)
            errors.append(
                FieldError(
                    f"{prefix}.arguments" + (f".{path}" if path else ""),
                    str(error.validator),
                    "Wartość nie spełnia schematu narzędzia.",
                )
            )
        checked.append(replace(call, arguments=None if found else arguments))
    return tuple(checked), tuple(errors)


def _cost(result: AdapterResult, profile: ModelProfile) -> tuple[int, str]:
    if result.cost_usd_micros is not None:
        return result.cost_usd_micros, "provider"
    return (
        profile.estimate_usd_micros(
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
        ),
        "computed",
    )


def _apply_block(error: ModelError, spec: TaskSpec, profile: ModelProfile) -> None:
    if error.kind == "account_limit" or error.code == "openrouter_unauthorized":
        error.until = state.block_adapter(profile.adapter, error.kind, error.code)
    elif error.code == "no_provider":
        error.until = state.block_pair(spec.key, profile.model, error.code)


def _finish(
    entry_id: UUID,
    spec: TaskSpec,
    *,
    outcome: str,
    code: str = "",
    started: float | None = None,
    latency_ms: int | None = None,
    result: AdapterResult | None = None,
    cost: int | None = None,
    cost_source: str = "",
) -> None:
    """Closes the row with a conditional update: a row erased with its company
    mid-call stays erased (an update of nothing never becomes an insert)."""
    if latency_ms is None and started is not None:
        latency_ms = int((time.monotonic() - started) * 1000)
    values: dict[str, Any] = {
        "state": EntryState.DONE,
        "outcome": outcome,
        "error_code": code if ERROR_CODE.fullmatch(code or "x") else "code_invalid",
        "latency_ms": latency_ms,
        "finished_at": admission.now(),
    }
    if result is not None:
        values.update(
            resolved_model=result.resolved_model[:120],
            resolved_provider=result.resolved_provider[:80],
            provider_request_id=result.provider_request_id[:120],
            finish_reason=result.finish_reason[:16],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            reasoning_tokens=result.usage.reasoning_tokens,
            cached_input_tokens=result.usage.cached_input_tokens,
            cost_usd_micros=cost,
            cost_source=cost_source,
        )
    UsageEntry.objects.using(admission.alias()).filter(
        pk=entry_id, state__in=[EntryState.ADMITTED, EntryState.CALLING]
    ).update(**values)
    adapter = (
        UsageEntry.objects.using(admission.alias())
        .filter(pk=entry_id)
        .values_list("adapter", flat=True)
        .first()
        or spec.adapter
    )
    metrics.CALLS.labels(spec.key, adapter, outcome).inc()
    if cost is not None:
        metrics.COST.labels(spec.key, adapter).inc(cost)
    if latency_ms is not None:
        metrics.LATENCY.labels(spec.key).observe(latency_ms / 1000)


def _refuse(spec: TaskSpec, kind: str, code: str, **extra: Any) -> None:
    metrics.REFUSED_BEFORE_CALL.labels(spec.key, kind).inc()
    raise ModelError(kind, code, **extra)  # type: ignore[arg-type]
