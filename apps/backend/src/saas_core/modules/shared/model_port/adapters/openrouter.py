"""OpenRouter chat completions on stdlib HTTP (ADR-068 pkt 4).

`http.client` rather than urllib: it follows no redirects, and the deadline
is the call's total time, not one socket operation's — the connection gets
what is left, and so does every 64 KiB read of the answer. Nothing here logs;
errors carry a kind and a code, never a provider's message (a moderation
error carries the flagged input).

Exactly the model asked for: no `models` list, no `openrouter/auto` and
`transforms: []`, so OpenRouter neither swaps the model nor trims the
conversation. Another host of the same model is fine; another model never is
(ADR-033:152-155).

Which hosts: the request's provider preferences say it, every time
(`provider.data_collection: "deny"` — no host that stores prompts or trains on
them — and `provider.zdr: true` — only zero-data-retention endpoints). They
restrict routing and are never relaxed here: when no host of the model meets
them, OpenRouter answers that it has no endpoint, the call fails as
`configuration` / `no_provider`, and nothing is sent again with less. A call
that names its host (`AdapterCall.provider`) goes to that host alone:
`provider.order` and `provider.only` hold its slug and `allow_fallbacks` is
false.
"""

from __future__ import annotations

import http.client
import json
import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from django.conf import settings

from ..types import Continuation, ModelError, NamedTool, Usage
from .base import AdapterCall, AdapterResult, RawToolCall

REQUEST_MAX_BYTES = 2 * 1024 * 1024
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
ERROR_BODY_MAX_BYTES = 64 * 1024
CHUNK_BYTES = 64 * 1024
#: Words of OpenRouter's answer (a 404 or a 503) when no host meets `deny`,
#: ZDR and the parameters.
NO_PROVIDER_MARKERS = ("no endpoints", "no allowed providers", "no providers")


@dataclass(frozen=True, slots=True)
class HttpAnswer:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes, deadline: float
    ) -> HttpAnswer: ...


class _Unsent(Exception):
    """The request never left: safe to send again."""


class _Lost(Exception):
    """The request left and the answer did not arrive: it may have been paid for."""


class HttpClientTransport:
    """One POST with a total deadline and no redirects."""

    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes, deadline: float
    ) -> HttpAnswer:
        parts = urlsplit(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _Unsent("deadline")
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.hostname or "",
                parts.port,
                timeout=remaining,
                context=ssl.create_default_context(),
            )
        else:
            connection = http.client.HTTPConnection(
                parts.hostname or "", parts.port, timeout=remaining
            )
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            try:
                connection.connect()
            except OSError as error:
                raise _Unsent("connect") from error
            try:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise _Unsent("deadline")
                if connection.sock is not None:
                    connection.sock.settimeout(left)
                connection.request("POST", path, body=body, headers=dict(headers))
                response = connection.getresponse()
                chunks: list[bytes] = []
                size = 0
                limit = RESPONSE_MAX_BYTES if response.status < 400 else ERROR_BODY_MAX_BYTES
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise _Lost("deadline")
                    if connection.sock is not None:
                        connection.sock.settimeout(left)
                    # One receive at most per round, so a trickling answer meets
                    # the deadline instead of filling a whole chunk first.
                    chunk = response.read1(CHUNK_BYTES)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        if response.status < 400:
                            raise ModelError("invalid_output", "openrouter_response_too_large")
                        break
                    chunks.append(chunk)
            except ModelError:
                raise
            except (TimeoutError, OSError, http.client.HTTPException) as error:
                raise _Lost("transport") from error
            return HttpAnswer(
                status=response.status,
                headers={key.lower(): value for key, value in response.getheaders()},
                body=b"".join(chunks),
            )
        finally:
            connection.close()


class OpenRouterAdapter:
    key = "openrouter"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._transport = transport or HttpClientTransport()
        self._api_key = api_key
        self._base_url = base_url

    def complete(self, call: AdapterCall) -> AdapterResult:
        key = settings.MODEL_PORT_OPENROUTER_API_KEY if self._api_key is None else self._api_key
        base = str(self._base_url or settings.MODEL_PORT_OPENROUTER_BASE_URL).rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ModelError("configuration", "base_url_invalid")
        if not key:
            raise ModelError("configuration", "adapter_unconfigured")
        body = json.dumps(request_body(call), ensure_ascii=False).encode()
        if len(body) > REQUEST_MAX_BYTES:
            raise ModelError("invalid_request", "request_too_large")
        try:
            answer = self._transport.post(
                base + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                body=body,
                deadline=call.deadline,
            )
        except _Unsent as error:
            raise ModelError("retryable", "openrouter_unsent", retry_after=2) from error
        except _Lost as error:
            raise ModelError("unknown_outcome", "openrouter_result_unknown") from error
        if answer.status >= 400:
            raise http_error(answer)
        try:
            payload = json.loads(answer.body)
        except ValueError as error:
            raise ModelError("invalid_output", "openrouter_response_malformed") from error
        if not isinstance(payload, dict):
            raise ModelError("invalid_output", "openrouter_response_malformed")
        return parse_response(payload, call, answer.headers)


def request_body(call: AdapterCall) -> dict[str, Any]:
    """The JSON OpenRouter receives: the matrix decides every optional part."""
    request = call.request
    capabilities = call.model.capabilities
    messages = [_message(message, capabilities) for message in request.messages]
    if call.structured == "json_mode" and request.response_format is not None:
        # The schema goes in as an instruction; our validation still checks it.
        messages.insert(
            0,
            {
                "role": "system",
                "content": "Odpowiedz wyłącznie obiektem JSON zgodnym z tym schematem: "
                + json.dumps(request.response_format.schema, ensure_ascii=False),
            },
        )
    # Preferences that only narrow the hosts: with none left the provider
    # refuses the request, and the port does not ask again with fewer.
    provider: dict[str, Any] = {
        "data_collection": "deny" if call.no_training else "allow",
        "require_parameters": True,
    }
    if call.zdr:
        provider["zdr"] = True
    if call.provider:
        # This host: nobody else first, and nobody else instead.
        provider.update(order=[call.provider], only=[call.provider], allow_fallbacks=False)
    body: dict[str, Any] = {
        "model": call.model.model,
        "messages": messages,
        "max_tokens": call.max_tokens,
        "transforms": [],
        "provider": provider,
        "usage": {"include": True},
        "user": call.user,
    }
    if request.tools:
        strict = "strict_tools" in capabilities
        body["tools"] = [_tool(tool, strict=strict) for tool in request.tools]
        if request.tool_choice is not None:
            body["tool_choice"] = (
                {"type": "function", "function": {"name": request.tool_choice.name}}
                if isinstance(request.tool_choice, NamedTool)
                else request.tool_choice
            )
        if request.parallel_tool_calls is not None:
            body["parallel_tool_calls"] = request.parallel_tool_calls
        if request.cache_tools and "prompt_cache" in capabilities and body["tools"]:
            body["tools"][-1]["cache_control"] = {"type": "ephemeral"}
    if call.structured == "json_schema" and request.response_format is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_format.name,
                "strict": True,
                "schema": strict_schema(request.response_format.schema),
            },
        }
    elif call.structured == "json_mode":
        body["response_format"] = {"type": "json_object"}
    forbidden = call.model.forbidden_parameters
    effort = call.parameters.get("reasoning_effort")
    if effort and "reasoning_effort" in capabilities and "reasoning" not in forbidden:
        body["reasoning"] = {"effort": effort}
    temperature = call.parameters.get("temperature")
    if temperature is not None and "temperature" in capabilities:
        body["temperature"] = temperature
    for name in forbidden:
        body.pop(name, None)
    return body


def _tool(tool: Any, *, strict: bool) -> dict[str, Any]:
    stripped = strict_schema(tool.input_schema) if strict else None
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": stripped
            if stripped is not None
            else json.loads(json.dumps(dict(tool.input_schema))),
            **({"strict": True} if stripped is not None else {}),
        },
    }


def _message(message: Any, capabilities: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role}
    content = message.content
    if message.cache and "prompt_cache" in capabilities and content is not None:
        out["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    else:
        out["content"] = content
    if message.role == "assistant" and message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments_json},
            }
            for call in message.tool_calls
        ]
    if message.role == "tool":
        out["tool_call_id"] = message.tool_call_id
    if (
        message.role == "assistant"
        and message.continuation is not None
        and "continuation" in capabilities
    ):
        out["reasoning_details"] = message.continuation.state
    return out


#: Constraints strict mode does not take (Anthropic's strict tool use and
#: structured outputs). They are left out of what the provider sees and still
#: checked by our own validation of the full schema, as the SDKs do.
STRICT_UNSUPPORTED = frozenset({
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
})


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """The schema as strict mode may see it, or None when it cannot fit at all.

    Fits: every object closed and fully required, no references (recursion is
    not supported). Constraints strict mode does not take are dropped from a
    deep copy; the caller's schema is never changed.
    """
    if "$ref" in schema or "$defs" in schema or "definitions" in schema:
        return None
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in STRICT_UNSUPPORTED:
            continue
        if key == "properties" and isinstance(value, Mapping):
            children = {}
            for name, child in value.items():
                stripped = strict_schema(child) if isinstance(child, Mapping) else None
                if stripped is None:
                    return None
                children[name] = stripped
            out[key] = children
        elif key == "items" and isinstance(value, Mapping):
            stripped = strict_schema(value)
            if stripped is None:
                return None
            out[key] = stripped
        elif key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list):
            parts = [strict_schema(part) if isinstance(part, Mapping) else None for part in value]
            if any(part is None for part in parts):
                return None
            out[key] = parts
        else:
            out[key] = value
    if out.get("type") == "object":
        properties = out.get("properties") or {}
        if out.get("additionalProperties") is not False:
            return None
        if set(out.get("required") or ()) != set(properties):
            return None
    return out


def strict_compatible(schema: Mapping[str, Any]) -> bool:
    return strict_schema(schema) is not None


def parse_response(
    payload: Mapping[str, Any], call: AdapterCall, headers: Mapping[str, str]
) -> AdapterResult:
    error = payload.get("error")
    if isinstance(error, Mapping):
        # A 200 carrying an error object means what its code would mean as a
        # status; its message says only whether no host was left.
        body = json.dumps({"error": {"message": str(error.get("message") or "")}}).encode()
        raise http_error(HttpAnswer(status=_int(error.get("code"), 500), headers={}, body=body))
    try:
        choice = payload["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError) as error_:
        raise ModelError("invalid_output", "openrouter_response_malformed") from error_
    finish = str(choice.get("finish_reason") or choice.get("native_finish_reason") or "stop")
    calls = tuple(
        RawToolCall(
            id=str(item.get("id") or ""),
            name=str((item.get("function") or {}).get("name") or ""),
            arguments_json=str((item.get("function") or {}).get("arguments") or ""),
        )
        for item in message.get("tool_calls") or ()
    )
    usage = payload.get("usage") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    cost = usage.get("cost")
    resolved = str(payload.get("model") or call.model.model)
    reasoning = message.get("reasoning_details")
    return AdapterResult(
        text=message.get("content") if isinstance(message.get("content"), str) else None,
        tool_calls=calls,
        finish_reason=finish,
        usage=Usage(
            input_tokens=_int(usage.get("prompt_tokens")),
            output_tokens=_int(usage.get("completion_tokens")),
            reasoning_tokens=_int(completion_details.get("reasoning_tokens")),
            cached_input_tokens=_int(prompt_details.get("cached_tokens")),
        ),
        cost_usd_micros=round(float(cost) * 1_000_000) if isinstance(cost, int | float) else None,
        resolved_model=resolved,
        resolved_provider=str(payload.get("provider") or ""),
        provider_request_id=str(payload.get("id") or headers.get("x-request-id") or ""),
        continuation=Continuation(model=resolved, state=reasoning) if reasoning else None,
        refusal=bool(message.get("refusal")),
    )


def http_error(answer: HttpAnswer) -> ModelError:
    """A status as a kind for the caller and a code for the record (model-port.md)."""
    status = answer.status
    message = ""
    try:
        detail = json.loads(answer.body or b"{}").get("error") or {}
        message = str(detail.get("message") or "").lower()
    except (ValueError, AttributeError, TypeError):
        pass
    retry_after = _retry_after(answer.headers)
    if status == 402:
        return ModelError("account_limit", "openrouter_http_402")
    if status == 403:
        # OpenRouter's moderation: one company's text, not everyone's problem.
        return ModelError("refused", "openrouter_moderation")
    if status == 401:
        return ModelError("configuration", "openrouter_unauthorized")
    if status == 404 and any(marker in message for marker in NO_PROVIDER_MARKERS):
        # „No endpoints found matching your data policy”: closed, not relaxed.
        return ModelError("configuration", "no_provider")
    if status == 404:
        return ModelError("configuration", "openrouter_not_found")
    if status in {408, 502, 504}:
        return ModelError("unknown_outcome", f"openrouter_http_{status}")
    if status == 429:
        return ModelError("retryable", "openrouter_http_429", retry_after=retry_after or 5)
    if status == 503 and any(marker in message for marker in NO_PROVIDER_MARKERS):
        return ModelError("configuration", "no_provider")
    if status == 503:
        return ModelError("retryable", "openrouter_http_503", retry_after=retry_after or 5)
    if status >= 500:
        if retry_after is not None:
            return ModelError("retryable", f"openrouter_http_{status}", retry_after=retry_after)
        return ModelError("unknown_outcome", f"openrouter_http_{status}")
    return ModelError("invalid_request", f"openrouter_http_{status}")


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
