"""The model port (ADR-068, docs/architecture/model-port.md).

Everything but HTTP runs through the scripted fake adapter; the OpenRouter
adapter's request shape and status mapping run against a fake transport.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any

import pytest

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.model_port.adapters.base import AdapterCall, RawToolCall
from saas_core.modules.shared.model_port.adapters.fake import FAKE, FakeFailure, FakeReply
from saas_core.modules.shared.model_port.adapters.openrouter import (
    HttpAnswer,
    OpenRouterAdapter,
    request_body,
)
from saas_core.modules.shared.model_port.api import (
    Continuation,
    JsonSchemaFormat,
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    NamedTool,
    ToolSpec,
    Usage,
    admit,
    complete,
    task_status,
)
from saas_core.modules.shared.model_port.matrix import MODELS, ModelProfile, register_model
from saas_core.modules.shared.model_port.models import EntryState, UsageEntry
from saas_core.modules.shared.model_port.registry import task_spec
from saas_core.modules.shared.model_port.service import web_request

pytestmark = pytest.mark.django_db

FAKE_MODEL = "fake/translator"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["translations"],
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "text"],
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            },
        }
    },
}
TOOL = ToolSpec(
    name="sites_page_create_v1",
    description="Creates a page.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["title"],
        "properties": {"title": {"type": "string", "maxLength": 20}},
    },
)


@pytest.fixture(autouse=True)
def fake_models(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for model, capabilities in (
        (FAKE_MODEL, {"json_schema", "json_mode", "zdr"}),
        (
            "fake/assistant",
            {"tools", "json_schema", "json_schema_with_tools", "zdr", "continuation"},
        ),
    ):
        register_model(
            ModelProfile(
                adapter="fake",
                model=model,
                capabilities=frozenset(capabilities),
                forbidden_parameters=frozenset(),
                input_usd_per_mtok=1.0,
                output_usd_per_mtok=5.0,
                context_window=100_000,
                max_output_tokens=16_000,
                probed="2026-10-02",
            )
        )
    for task, model in (
        ("TRANSLATION_TEXT", FAKE_MODEL),
        ("ASSISTANT_CONVERSATION", "fake/assistant"),
    ):
        monkeypatch.setenv(f"MODEL_PORT_TASK_{task}_ADAPTER", "fake")
        monkeypatch.setenv(f"MODEL_PORT_TASK_{task}_MODEL", model)
    from django.core.cache import cache

    cache.clear()
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ("public", "public_personal", "personal")
    FAKE.reset()
    yield
    FAKE.reset()
    for model in (FAKE_MODEL, "fake/assistant"):
        MODELS.pop(("fake", model), None)


def organization(slug: str = "port-firma") -> Organization:
    return Organization.objects.create(name=slug, slug=slug)


def translation(org: Organization, text: str = "Dzień dobry", **extra: Any) -> ModelRequest:
    return replace(_translation(org, text), **extra)


def _translation(org: Organization, text: str) -> ModelRequest:
    return ModelRequest(
        task="translation.text",
        messages=(
            Message(role="system", content="Tłumacz dosłownie."),
            Message(role="user", content=text),
        ),
        prompt_id="translation.v1",
        prompt_version="1",
        context=ModelContext(organization_id=org.id),
        data_class="public",
        response_format=JsonSchemaFormat(name="translations", schema=SCHEMA),
    )


def conversation(org: Organization, **extra: Any) -> ModelRequest:
    return replace(_conversation(org), **extra)


def _conversation(org: Organization) -> ModelRequest:
    return ModelRequest(
        task="assistant.conversation",
        messages=(Message(role="user", content="Załóż stronę"),),
        prompt_id="assistant.setup",
        prompt_version="1",
        context=ModelContext(
            organization_id=org.id, actor_id=uuid.uuid4(), conversation_id=uuid.uuid4()
        ),
        data_class="personal",
        tools=(TOOL,),
    )


def reply_json(value: Mapping[str, Any], **extra: Any) -> FakeReply:
    return FakeReply(text=json.dumps(value), **extra)


def test_a_call_returns_checked_json_and_leaves_one_row_without_content() -> None:
    org = organization()
    FAKE.script(reply_json({"translations": [{"id": "1", "text": "Good morning"}]}))

    response = complete(translation(org, text="SEKRET-TRESCI"))

    assert response.output == {"translations": [{"id": "1", "text": "Good morning"}]}
    assert response.cost_usd_micros == 1_000 and response.cost_source == "provider"
    row = UsageEntry.objects.get()
    assert row.state == EntryState.DONE and row.outcome == "ok"
    assert (row.task, row.pool, row.organization_id) == ("translation.text", "translation", org.id)
    assert (row.input_tokens, row.output_tokens, row.cost_usd_micros) == (100, 50, 1_000)
    assert row.latency_ms is not None
    stored = json.dumps({field.name: str(getattr(row, field.name)) for field in row._meta.fields})
    assert "SEKRET" not in stored and "Good morning" not in stored


def test_a_refusal_answered_as_200_is_a_refusal_with_its_cost_and_nothing_else() -> None:
    org = organization()
    FAKE.script(FakeReply(text="", finish_reason="content_filter"))

    with pytest.raises(ModelError) as error:
        complete(translation(org))

    assert (error.value.kind, error.value.code) == ("refused", "model_refused")
    row = UsageEntry.objects.get()
    assert (row.outcome, row.error_code, row.cost_usd_micros) == ("refused", "model_refused", 1_000)


def test_output_outside_the_schema_and_truncated_output_are_invalid_output() -> None:
    org = organization()
    FAKE.script(
        reply_json({"wrong": True}),
        FakeReply(text='{"translations": [', finish_reason="length"),
    )

    with pytest.raises(ModelError) as wrong:
        complete(translation(org))
    with pytest.raises(ModelError) as cut:
        complete(translation(org))

    assert (wrong.value.kind, wrong.value.code) == ("invalid_output", "output_schema_invalid")
    assert (cut.value.kind, cut.value.code) == ("invalid_output", "output_truncated")


def test_bad_tool_arguments_come_back_as_field_errors_with_the_turn_to_resend() -> None:
    org = organization()
    FAKE.script(
        FakeReply(
            tool_calls=(
                RawToolCall(
                    id="call-1", name="sites_page_create_v1", arguments_json='{"title": 7}'
                ),
                RawToolCall(id="call-2", name="sites_page_create_v1", arguments_json="nie json"),
            ),
            finish_reason="tool_calls",
        )
    )

    with pytest.raises(ModelError) as error:
        complete(conversation(org))

    assert error.value.kind == "tool_args_invalid"
    assert [(e.field, e.code) for e in error.value.errors] == [
        ("tool_calls.call-1.arguments.title", "type"),
        ("tool_calls.call-2.arguments", "not_json"),
    ]
    assert error.value.response is not None
    turn = error.value.response.as_message()
    assert turn.role == "assistant"
    assert [call.arguments_json for call in turn.tool_calls] == ['{"title": 7}', "nie json"]


def test_a_continuation_from_another_model_is_dropped_and_counted() -> None:
    org = organization()
    FAKE.script(FakeReply(text="Gotowe"))
    history = (
        Message(role="user", content="Hej"),
        Message(
            role="assistant",
            content="Cześć",
            continuation=Continuation(model="other/model", state=[{"signature": "x"}]),
        ),
        Message(role="user", content="Dalej"),
    )

    complete(conversation(org, messages=history))

    assert all(message.continuation is None for message in FAKE.calls[0].request.messages)
    assert UsageEntry.objects.get().continuations_dropped == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"tool_choice": "required"}, "capability_not_supported"),
        ({"tool_choice": NamedTool("sites_page_create_v1")}, "capability_not_supported"),
        ({"model": "fake/assistant"}, "model_override_not_allowed"),
        ({"prompt_id": "Zły Prompt"}, "prompt_id_invalid"),
        (
            {"messages": (Message(role="user", content="a"), Message(role="system", content="b"))},
            "system_not_first",
        ),
    ],
)
def test_a_request_breaking_a_rule_never_reaches_the_model(
    changes: dict[str, Any], code: str
) -> None:
    org = organization()

    with pytest.raises(ModelError) as error:
        complete(conversation(org, **changes))

    assert (error.value.kind, error.value.code) == ("invalid_request", code)
    assert FAKE.calls == [] and not UsageEntry.objects.exists()


def test_a_conversation_without_its_conversation_id_cannot_skip_its_budget() -> None:
    org = organization()
    request = conversation(org)
    request = ModelRequest(**{
        **{f: getattr(request, f) for f in request.__dataclass_fields__},
        "context": ModelContext(organization_id=org.id, actor_id=uuid.uuid4()),
    })

    with pytest.raises(ModelError) as error:
        complete(request)

    assert error.value.code == "context_missing"


def test_customer_content_waits_for_the_processor_flag_the_publisher_does_not(
    settings: Any,
) -> None:
    from saas_core.modules.core.organizations.platform_workspace import ensure_platform_workspace
    from saas_core.modules.shared.model_port import service

    settings.MODEL_PORT_PROCESSOR_LISTED = False
    service._PLATFORM_ID.clear()
    customer = organization()
    publisher, _ = ensure_platform_workspace()
    FAKE.script(reply_json({"translations": []}))

    with pytest.raises(ModelError) as error:
        complete(translation(customer))
    complete(translation(publisher))

    assert error.value.code == "processor_not_listed"
    assert UsageEntry.objects.get().purpose == "platform"
    service._PLATFORM_ID.clear()


def test_a_flood_of_translations_stops_at_the_ceiling_and_the_assistant_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_PORT_BUDGET_TRANSLATION_DAY", "0.05")
    org = organization()
    FAKE.script(*(reply_json({"translations": []}, cost_usd_micros=20_000) for _ in range(5)))
    done = 0
    with pytest.raises(ModelError) as stopped:
        for _ in range(5):
            complete(translation(org))
            done += 1

    assert stopped.value.kind == "budget" and stopped.value.code == "pool_day"
    assert stopped.value.until is not None
    assert done < 5
    FAKE.reset()
    FAKE.script(FakeReply(text="Jestem"))
    assert complete(conversation(org)).text == "Jestem"


def test_a_company_over_its_share_waits_only_while_another_one_is_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.core.cache import cache

    cache.delete("model_port:asking:translation")
    monkeypatch.setenv("MODEL_PORT_BUDGET_TRANSLATION_DAY", "1")
    big, small = organization("duza"), organization("mala")
    FAKE.script(*(reply_json({"translations": []}, cost_usd_micros=100_000) for _ in range(8)))

    for _ in range(3):
        complete(translation(big))
    complete(translation(small))
    with pytest.raises(ModelError) as waiting:
        complete(translation(big))

    assert waiting.value.code == "company_share"
    cache.delete("model_port:asking:translation")
    complete(translation(big))


def test_an_unknown_outcome_is_sent_again_once_and_only_for_translations() -> None:
    org = organization()
    FAKE.script(
        FakeFailure("unknown_outcome", "openrouter_result_unknown"),
        reply_json({"translations": []}),
    )
    with pytest.raises(ModelError) as lost:
        complete(translation(org))
    first = lost.value.usage_entry_id
    assert UsageEntry.objects.get(pk=first).cost_usd_micros is None

    complete(translation(org, resend_of=first))
    with pytest.raises(ModelError) as again:
        complete(translation(org, resend_of=first))

    assert again.value.code == "resend_not_allowed"


def test_the_web_limiter_holds_calls_from_a_request_not_from_a_worker(settings: Any) -> None:
    from saas_core.modules.shared.model_port import service

    settings.MODEL_PORT_WEB_CALLS_PER_PROCESS = 1
    service._web_slots = None
    org = organization()
    semaphore = service._web_semaphore()
    assert semaphore.acquire(blocking=False)
    try:
        with web_request(), pytest.raises(ModelError) as busy:
            complete(conversation(org))
        FAKE.script(FakeReply(text="Z workera"))
        assert complete(conversation(org)).text == "Z workera"
    finally:
        semaphore.release()
        service._web_slots = None

    assert (busy.value.kind, busy.value.code, busy.value.retry_after) == (
        "retryable",
        "web_capacity",
        2,
    )


def test_an_admission_is_a_reservation_the_call_then_uses() -> None:
    org = organization()
    context = ModelContext(organization_id=org.id)
    verdict = admit("translation.text", 5_000, context)
    assert verdict.decision == "granted" and verdict.id is not None
    FAKE.script(reply_json({"translations": []}))

    complete(translation(org, admission_id=verdict.id))

    assert UsageEntry.objects.count() == 1
    assert UsageEntry.objects.get().state == EntryState.DONE


def test_task_status_names_the_reason_a_task_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_EXTRACT_PROFILE_MODEL", "")

    assert task_status("translation.text").available
    status = task_status("assistant.extract_profile")
    assert (status.available, status.reason) == (False, "model_not_selected")


def test_rows_leave_with_their_organization_and_a_late_call_does_not_bring_them_back() -> None:
    from saas_core.modules.core.organizations.erasure_checks import registered_erasure_rows

    org = organization()
    FAKE.script(reply_json({"translations": []}))
    complete(translation(org))
    entry = UsageEntry.objects.get()
    assert (UsageEntry, "organization_id") in registered_erasure_rows()

    UsageEntry.objects.filter(organization_id=org.id).delete()
    from saas_core.modules.shared.model_port.service import _finish

    _finish(entry.id, task_spec("translation.text"), outcome="ok")  # type: ignore[arg-type]

    assert not UsageEntry.objects.filter(pk=entry.id).exists()


class Transport:
    def __init__(self, *answers: HttpAnswer) -> None:
        self.answers = list(answers)
        self.bodies: list[dict[str, Any]] = []

    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes, deadline: float
    ) -> HttpAnswer:
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        self.bodies.append(json.loads(body))
        return self.answers.pop(0)


def adapter_call(
    request: ModelRequest, profile: ModelProfile, *, structured: str = "json_schema"
) -> AdapterCall:
    spec = task_spec(request.task)
    assert spec is not None
    return AdapterCall(
        spec=spec,
        request=request,
        model=profile,
        max_tokens=2048,
        deadline=time.monotonic() + 30,
        user="hmac-of-org",
        zdr=True,
        structured=structured,  # type: ignore[arg-type]
        parameters={"reasoning_effort": "low", "temperature": 0.2},
    )


OPUS = ModelProfile(
    adapter="openrouter",
    model="anthropic/claude-opus-5.5",
    capabilities=frozenset({"tools", "strict_tools", "json_schema", "reasoning_effort", "zdr"}),
    forbidden_parameters=frozenset({"temperature", "top_p"}),
    input_usd_per_mtok=4,
    output_usd_per_mtok=20,
    context_window=200_000,
    max_output_tokens=32_000,
)


def test_the_openrouter_request_keeps_the_model_denies_collection_and_obeys_the_matrix() -> None:
    org_id = uuid.uuid4()
    request = ModelRequest(
        task="translation.text",
        messages=(Message(role="user", content="Dzień dobry", cache=True),),
        prompt_id="translation.v1",
        prompt_version="1",
        context=ModelContext(organization_id=org_id),
        data_class="public",
        response_format=JsonSchemaFormat(name="translations", schema=SCHEMA),
    )

    body = request_body(adapter_call(request, OPUS))

    assert body["model"] == "anthropic/claude-opus-5.5"
    assert "models" not in body and body["transforms"] == []
    assert body["provider"] == {"data_collection": "deny", "require_parameters": True, "zdr": True}
    assert body["usage"] == {"include": True} and body["user"] == "hmac-of-org"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning"] == {"effort": "low"}
    assert "temperature" not in body
    # The model has no prompt cache in this row, so the hint is dropped.
    assert body["messages"][0]["content"] == "Dzień dobry"


@pytest.mark.parametrize(
    ("status", "message", "headers", "kind", "code"),
    [
        (402, "", {}, "account_limit", "openrouter_http_402"),
        (403, "flagged", {}, "refused", "openrouter_moderation"),
        (401, "", {}, "configuration", "openrouter_unauthorized"),
        (404, "", {}, "configuration", "openrouter_not_found"),
        (408, "", {}, "unknown_outcome", "openrouter_http_408"),
        (502, "", {}, "unknown_outcome", "openrouter_http_502"),
        (429, "", {"retry-after": "7"}, "retryable", "openrouter_http_429"),
        (503, "No endpoints found matching your data policy", {}, "configuration", "no_provider"),
        (503, "overloaded", {}, "retryable", "openrouter_http_503"),
        (500, "", {"retry-after": "3"}, "retryable", "openrouter_http_500"),
        (500, "", {}, "unknown_outcome", "openrouter_http_500"),
        (400, "bad", {}, "invalid_request", "openrouter_http_400"),
    ],
)
def test_every_status_maps_to_one_kind(
    status: int, message: str, headers: dict[str, str], kind: str, code: str
) -> None:
    body = json.dumps({"error": {"message": message}}).encode()
    adapter = OpenRouterAdapter(
        transport=Transport(HttpAnswer(status=status, headers=headers, body=body)),
        api_key="test-key",
        base_url="https://openrouter.test/api/v1",
    )
    request = ModelRequest(
        task="translation.text",
        messages=(Message(role="user", content="x"),),
        prompt_id="translation.v1",
        prompt_version="1",
        context=ModelContext(organization_id=uuid.uuid4()),
        data_class="public",
    )

    with pytest.raises(ModelError) as error:
        adapter.complete(adapter_call(request, OPUS, structured="none"))

    assert (error.value.kind, error.value.code) == (kind, code)
    assert message not in str(error.value) or message == ""


def test_the_openrouter_answer_gives_tokens_cost_resolved_model_and_tool_calls() -> None:
    payload = {
        "id": "gen-1",
        "model": "anthropic/claude-opus-5.5",
        "provider": "Anthropic",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "t", "arguments": "{}"},
                        }
                    ],
                    "reasoning_details": [{"type": "reasoning.encrypted", "data": "x"}],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 40,
            "completion_tokens_details": {"reasoning_tokens": 10},
            "prompt_tokens_details": {"cached_tokens": 100},
            "cost": 0.00123,
        },
    }
    adapter = OpenRouterAdapter(
        transport=Transport(HttpAnswer(status=200, headers={}, body=json.dumps(payload).encode())),
        api_key="test-key",
        base_url="https://openrouter.test/api/v1",
    )
    request = ModelRequest(
        task="translation.text",
        messages=(Message(role="user", content="x"),),
        prompt_id="translation.v1",
        prompt_version="1",
        context=ModelContext(organization_id=uuid.uuid4()),
        data_class="public",
    )

    result = adapter.complete(adapter_call(request, OPUS, structured="none"))

    assert result.usage == Usage(
        input_tokens=120, output_tokens=40, reasoning_tokens=10, cached_input_tokens=100
    )
    assert result.cost_usd_micros == 1230
    assert (result.resolved_model, result.resolved_provider, result.provider_request_id) == (
        "anthropic/claude-opus-5.5",
        "Anthropic",
        "gen-1",
    )
    assert result.tool_calls[0].arguments_json == "{}"
    assert (
        result.continuation is not None and result.continuation.model == "anthropic/claude-opus-5.5"
    )
