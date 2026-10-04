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

from saas_core.modules.core.organizations import platform_settings
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.model_port import registry
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
    ToolCall,
    ToolSpec,
    Usage,
    admit,
    complete,
    task_status,
)
from saas_core.modules.shared.model_port.matrix import (
    LISTED_PROCESSOR,
    MODELS,
    ModelProfile,
    register_model,
)
from saas_core.modules.shared.model_port.models import EntryState, UsageEntry
from saas_core.modules.shared.model_port.registry import task_spec
from saas_core.modules.shared.model_port.service import web_request
from saas_core.modules.shared.model_port.settings_spec import NO_TRAINING

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
                dated_variants=frozenset({f"{model}-20261001"}),
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


def test_the_tasks_that_send_a_companys_content_use_the_processor_the_documents_name() -> None:
    """The privacy documents name one processor (the owner's answer of 04.10):
    a task's default model that is another one would make them untrue. Change
    the documents, the panel's words and `LISTED_PROCESSOR` together —
    docs/architecture/model-port.md, „Podmiot przetwarzający”."""
    assert LISTED_PROCESSOR == ("openrouter", "anthropic/claude-sonnet-5.5")
    assert MODELS[LISTED_PROCESSOR].probed is not None
    assert not MODELS[LISTED_PROCESSOR].evaluation_only
    assert {(spec.adapter, spec.model) for spec in registry.DEFAULT_TASKS} == {LISTED_PROCESSOR}


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


def test_evals_and_proofs_are_counted_only_in_the_months(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call that is not held to the daily ceilings does not use them up
    either: a proof run as a person leaves that person's day as it was."""
    from saas_core.modules.shared.model_port.api import budget_state

    monkeypatch.setenv("MODEL_PORT_BUDGET_ASSISTANT_PERSON_DAY", "0.05")
    request = conversation(organization())
    proof = replace(request, context=replace(request.context, purpose="eval"))
    FAKE.script(*(FakeReply(text="ok", cost_usd_micros=40_000) for _ in range(5)))

    # Three calls of four cents each: past the person's five cents twice over.
    for _ in range(3):
        complete(proof)
    assert complete(request).text == "ok"

    levels = budget_state(request.task, request.context).levels
    spent = {level.level: level.spent_usd_micros for level in levels}
    assert spent["platform_month"] == 160_000
    assert (spent["pool_day"], spent["company_day"], spent["person_day"]) == (40_000,) * 3
    assert spent["conversation"] == 40_000
    # The person's own calls are what their day stops.
    complete(request)
    with pytest.raises(ModelError) as stopped:
        complete(request)
    assert (stopped.value.kind, stopped.value.code) == ("budget", "person_day")


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
    # A task a module registered before anybody picked its model on the evals.
    unpicked = replace(registry._TASKS["assistant.extract_profile"], model="")
    monkeypatch.setitem(registry._TASKS, "assistant.extract_profile", unpicked)

    assert task_status("translation.text").available
    status = task_status("assistant.extract_profile")
    assert (status.available, status.reason) == (False, "model_not_selected")


def test_the_assistants_tasks_run_on_the_owners_choice_and_haiku_is_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answer 59a of 03.10: Claude Sonnet 5.5 in code; Claude Haiku 4.5 stays a
    probed model an operator falls back to through the environment."""
    for key in ("assistant.conversation", "assistant.extract_profile"):
        # As declared: this module's fixtures point the conversation at the fake.
        spec = registry._TASKS[key]
        assert (spec.adapter, spec.model) == ("openrouter", "anthropic/claude-sonnet-5.5")
        profile = MODELS[spec.adapter, spec.model]
        assert profile.probed is not None and spec.capabilities <= profile.capabilities

    haiku = "anthropic/claude-haiku-4.5"
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_ADAPTER", "openrouter")
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL", haiku)
    fallback = task_spec("assistant.conversation", platform=False)
    assert fallback is not None and fallback.model == haiku
    profile = MODELS[fallback.adapter, haiku]
    assert profile.probed is not None and fallback.capabilities <= profile.capabilities


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
        (404, "No endpoints found matching your data policy", {}, "configuration", "no_provider"),
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


STRICT = {"data_collection": "deny", "require_parameters": True, "zdr": True}


@pytest.mark.django_db
def test_a_request_goes_only_to_hosts_that_collect_nothing_unless_the_platform_lets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`model_port.privacy.no_training_providers`: on unless an operator turns
    it off, and a request with personal data does not ask."""
    org = organization("port-prywatnosc")
    assert (NO_TRAINING.default, NO_TRAINING.scopes) == (True, ("platform",))

    def sent() -> list[dict[str, Any]]:
        FAKE.reset()
        FAKE.script(
            reply_json({"translations": [{"id": "1", "text": "Good morning"}]}),
            FakeReply(text="Dzień dobry."),
        )
        complete(translation(org))
        complete(conversation(org))
        # What OpenRouter would be asked for each: the adapter's own body.
        return [request_body(call)["provider"] for call in FAKE.calls]

    # Nobody chose anything: no host that stores prompts or trains on them,
    # and zero data retention where the model has it.
    assert sent() == [STRICT, STRICT]

    monkeypatch.setattr(platform_settings, "platform_overrides", lambda: {NO_TRAINING.key: False})

    # Switched off, a public text may go to any host of the model; a
    # conversation is personal and goes the strict way whatever the switch says.
    assert sent() == [{"data_collection": "allow", "require_parameters": True}, STRICT]


def test_no_host_within_the_data_policy_closes_the_call_and_nothing_is_sent_again() -> None:
    """Fail closed: the preferences only narrow the hosts. With none left the
    call ends as a configuration problem; there is no second request with less."""
    refused = json.dumps({
        "error": {"message": "No endpoints found matching your data policy.", "code": 404}
    }).encode()
    transport = Transport(HttpAnswer(status=404, headers={}, body=refused))
    adapter = OpenRouterAdapter(
        transport=transport, api_key="test-key", base_url="https://openrouter.test/api/v1"
    )
    request = ModelRequest(
        task="assistant.conversation",
        messages=(Message(role="user", content="Czy pan Kowalski zapłacił?"),),
        prompt_id="assistant.operate",
        prompt_version="4",
        context=ModelContext(organization_id=uuid.uuid4()),
        data_class="personal",
    )

    with pytest.raises(ModelError) as error:
        adapter.complete(adapter_call(request, OPUS, structured="none"))

    assert (error.value.kind, error.value.code) == ("configuration", "no_provider")
    (body,) = transport.bodies
    assert body["provider"] == STRICT
    # The same 200-with-an-error shape OpenRouter also uses.
    wrapped = Transport(HttpAnswer(status=200, headers={}, body=refused))
    with pytest.raises(ModelError) as inside:
        OpenRouterAdapter(
            transport=wrapped, api_key="test-key", base_url="https://openrouter.test/api/v1"
        ).complete(adapter_call(request, OPUS, structured="none"))
    assert (inside.value.kind, inside.value.code) == ("configuration", "no_provider")
    assert len(wrapped.bodies) == 1


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


def test_a_tool_turn_and_its_reasoning_go_round_to_the_next_call_of_the_same_model() -> None:
    org = organization()
    FAKE.script(
        FakeReply(
            tool_calls=(
                RawToolCall(
                    id="c1", name="sites_page_create_v1", arguments_json='{"title": "O nas"}'
                ),
            ),
            finish_reason="tool_calls",
            # The provider answers with a dated name of the model.
            resolved_model="fake/assistant-20261001",
            continuation_state=[{"type": "reasoning.encrypted", "data": "podpis"}],
        ),
        FakeReply(text="Strona założona"),
    )
    first_request = conversation(org)
    first = complete(first_request)
    assert first.continuation is not None and first.continuation.model == "fake/assistant"
    assert first.tool_calls[0].arguments == {"title": "O nas"}

    second = complete(
        replace(
            first_request,
            messages=(
                *first_request.messages,
                first.as_message(),
                Message(role="tool", tool_call_id="c1", content='{"ok": true}'),
            ),
        )
    )

    assert second.text == "Strona założona"
    sent = FAKE.calls[1].request.messages
    assert sent[1].continuation is not None
    assert sent[1].continuation.state == [{"type": "reasoning.encrypted", "data": "podpis"}]
    assert UsageEntry.objects.order_by("created_at").last().continuations_dropped == 0


def test_strict_mode_gets_a_copy_without_the_constraints_it_cannot_take() -> None:
    from saas_core.modules.shared.model_port.adapters.openrouter import strict_schema

    request = conversation(organization(), data_class="public")
    body = request_body(adapter_call(request, OPUS, structured="none"))

    function = body["tools"][0]["function"]
    assert function["strict"] is True
    assert "maxLength" not in json.dumps(function["parameters"])
    # The caller's schema is untouched; the port still validates the full one.
    assert TOOL.input_schema["properties"]["title"]["maxLength"] == 20
    assert strict_schema({"type": "object", "$defs": {}, "properties": {}}) is None


def test_empty_or_repeated_tool_call_ids_are_invalid_output() -> None:
    org = organization()
    call = RawToolCall(id="same", name="sites_page_create_v1", arguments_json='{"title": "A"}')
    FAKE.script(FakeReply(tool_calls=(call, call), finish_reason="tool_calls"))

    with pytest.raises(ModelError) as error:
        complete(conversation(org))

    assert (error.value.kind, error.value.code) == ("invalid_output", "tool_call_id_invalid")


def test_health_data_and_an_empty_tool_result_never_leave() -> None:
    org = organization()
    with pytest.raises(ModelError) as health:
        complete(conversation(org, data_class="health"))
    bad_turn = (
        Message(role="user", content="Hej"),
        Message(
            role="assistant",
            tool_calls=(ToolCall(id="c1", name="sites_page_create_v1", arguments_json="{}"),),
        ),
        Message(role="tool", tool_call_id="c1", content=None),
    )
    with pytest.raises(ModelError) as empty:
        complete(conversation(org, messages=bad_turn))

    assert health.value.code == "data_class_not_sendable"
    assert empty.value.code == "message_shape_invalid"
    assert FAKE.calls == []


def test_an_adapter_bug_still_closes_its_row(monkeypatch: pytest.MonkeyPatch) -> None:
    org = organization()

    def broken(call: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(FAKE, "complete", broken)
    with pytest.raises(RuntimeError):
        complete(translation(org))

    row = UsageEntry.objects.get()
    assert (row.state, row.outcome, row.error_code) == (
        EntryState.DONE,
        "unknown_outcome",
        "adapter_exception",
    )


def _serve(handler: Any) -> Any:
    import threading
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_transport_keeps_its_total_deadline_and_follows_no_redirect() -> None:
    from http.server import BaseHTTPRequestHandler

    from saas_core.modules.shared.model_port.adapters.openrouter import (
        HttpClientTransport,
        http_error,
    )

    class Trickle(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "https://elsewhere.test/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.1)

        def log_message(self, *args: Any) -> None:
            pass

    server = _serve(Trickle)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    transport = HttpClientTransport()
    try:
        started = time.monotonic()
        with pytest.raises(Exception) as lost:
            transport.post(base + "/slow", headers={}, body=b"{}", deadline=time.monotonic() + 0.5)
        elapsed = time.monotonic() - started
        answer = transport.post(
            base + "/redirect", headers={}, body=b"{}", deadline=time.monotonic() + 5
        )
    finally:
        server.shutdown()

    assert type(lost.value).__name__ == "_Lost"
    assert elapsed < 1.5
    assert answer.status == 302
    assert (http_error(answer).kind, http_error(answer).code) == (
        "invalid_request",
        "openrouter_http_302",
    )
