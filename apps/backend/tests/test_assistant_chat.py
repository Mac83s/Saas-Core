"""The assistant's chat (ADR-076, A3): a model proposes, a person clicks, a
command runs — and nothing the model writes is a consent or a proof.

The model is the port's scripted fake, so each test states what a model
answered and asserts what the server did about it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations import (
    command_executor,
    command_registry,
    platform_settings,
)
from saas_core.modules.core.organizations.command_registry import (
    CommandSpec,
    Effect,
    Preview,
    register_command,
)
from saas_core.modules.core.organizations.models import (
    CommandReceipt,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.core.organizations.permissions import ORGANIZATION_READ, SETTINGS_MANAGE
from saas_core.modules.core.organizations.retention import dry_run as retention_dry_run
from saas_core.modules.core.organizations.retention import registered_sweeps
from saas_core.modules.core.organizations.retention import run as run_retention
from saas_core.modules.shared.assistant.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    TurnState,
)
from saas_core.modules.shared.assistant.services import WORKER_SEEN
from saas_core.modules.shared.assistant.tasks import reconcile_assistant_turns
from saas_core.modules.shared.billing.models import (
    CreditReservation,
    CreditReservationState,
    EntitlementSnapshot,
)
from saas_core.modules.shared.model_port import registry as model_registry
from saas_core.modules.shared.model_port.adapters.base import RawToolCall
from saas_core.modules.shared.model_port.adapters.fake import FAKE, FakeFailure, FakeReply
from saas_core.modules.shared.model_port.matrix import MODELS, ModelProfile, register_model
from test_command_executor import INPUT, OUTPUT, allow_all
from test_sites_api import PASSWORD, csrf_value, sites_client

pytestmark = pytest.mark.django_db

BASE = "/api/v1/assistant/"
CONSENT = "/api/v1/organizations/current/command-consents/{}/"
MODEL = "fake/assistant"
NOTE = {"name": "Domki nad jeziorem", "address": None, "items": []}

RAN: list[str] = []


def _note(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    RAN.append(arguments["name"])
    return {"name": arguments["name"]}


def _note_preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(
        effects=(
            Effect(
                kind="updated",
                resource="organization",
                resource_id=str(call.context.organization_id),
                summary={"pl": f"Nazwa: {arguments['name']}", "en": f"Name: {arguments['name']}"},
            ),
        ),
        observed_versions={},
    )


def _peek(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return {"name": Organization.objects.get(pk=call.context.organization_id).name}


def _specs() -> tuple[CommandSpec, CommandSpec]:
    common: dict[str, Any] = {
        "version": 1,
        "module": "core.organizations",
        "summary": {"pl": "Firma.", "en": "Company."},
        "output_schema": OUTPUT,
    }
    note = CommandSpec(
        name="organization.note",
        title={"pl": "Zmień nazwę firmy", "en": "Rename the company"},
        model_description="Renames the company.",
        input_schema=INPUT,
        permission=SETTINGS_MANAGE,
        risk="apply",
        run=_note,
        undo="none:a note stays",
        preview=_note_preview,
        no_version_reason="A note has no version.",
        **common,
    )
    peek = CommandSpec(
        name="organization.peek",
        title={"pl": "Odczytaj dane firmy", "en": "Read the company"},
        model_description="Reads the company's name.",
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        permission=ORGANIZATION_READ,
        risk="read",
        run=_peek,
        undo="none:a read changes nothing",
        no_preview_reason="A read changes nothing to preview.",
        no_version_reason="A read has no version to check.",
        **common,
    )
    return note, peek


@pytest.fixture(autouse=True)
def chat(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A model for the task, a worker seen, and two commands of the company."""
    register_model(
        ModelProfile(
            adapter="fake",
            model=MODEL,
            capabilities=frozenset({"tools", "zdr", "continuation", "prompt_cache"}),
            forbidden_parameters=frozenset(),
            input_usd_per_mtok=1.0,
            output_usd_per_mtok=5.0,
            context_window=100_000,
            max_output_tokens=16_000,
            probed="2026-10-03",
        )
    )
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_ADAPTER", "fake")
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL", MODEL)
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ("public", "public_personal", "personal")
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_registry, "_unretitled", {})
    monkeypatch.setattr(command_executor, "_gates", {"features": allow_all})
    for spec in _specs():
        register_command(spec)
    cache.clear()
    cache.set(WORKER_SEEN, 1, 300)
    FAKE.reset()
    RAN.clear()
    yield
    FAKE.reset()
    MODELS.pop(("fake", MODEL), None)


def person(slug: str, *, role_key: str = "owner", credits: int = 10) -> APIClient:
    client, organization, _user = sites_client(slug=slug, role_key=role_key)
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features={"sites.enabled": True, "assistant.text.enabled": True},
        quotas={"credits.monthly": credits},
        sources={
            "assistant.text.enabled": {"kind": "plan"},
            "credits.monthly": {"kind": "plan"},
        },
    )
    return client


def tool(name: str, arguments: Mapping[str, Any], call_id: str = "c1") -> FakeReply:
    return FakeReply(
        tool_calls=(RawToolCall(id=call_id, name=name, arguments_json=json.dumps(arguments)),),
        finish_reason="tool_calls",
    )


class Chat:
    """One person's conversation, with queued work run as the worker would."""

    def __init__(self, client: APIClient, capture: Any, kind: str = "operate") -> None:
        self.client = client
        self._capture = capture
        started = self.post("conversations/", {"language": "pl", "kind": kind}, key="start")
        assert started.status_code == 201, started.data
        self.id = started.data["id"]

    def post(
        self, path: str, data: Mapping[str, Any], *, key: str | None = None, run: bool = True
    ) -> Any:
        headers = {"HTTP_X_CSRFTOKEN": csrf_value(self.client)}
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        # The turn is queued on commit and, in tests, runs at once — unless
        # the test wants to be the worker itself.
        with self._capture(execute=run):
            return self.client.post(f"{BASE}{path}", data, format="json", **headers)

    def say(self, text: str, key: str = "t1", *, run: bool = True) -> Any:
        return self.post(f"conversations/{self.id}/turns/", {"text": text}, key=key, run=run)

    def read(self) -> Any:
        response = self.client.get(f"{BASE}conversations/{self.id}/")
        assert response.status_code == 200, response.data
        return response.data

    def last(self) -> Any:
        return self.read()["turns"][-1]

    def consent(self, **body: Any) -> Any:
        turn = self.last()
        return self.post(f"conversations/{self.id}/turns/{turn['id']}/consents/", body)

    def click(self, digest: str) -> str:
        minted = self.client.post(CONSENT.format(digest), HTTP_X_CSRFTOKEN=csrf_value(self.client))
        assert minted.status_code == 201, minted.data
        return str(minted.data["consent_token"])


@pytest.fixture
def talk(django_capture_on_commit_callbacks: Any) -> Any:
    return lambda client, kind="operate": Chat(client, django_capture_on_commit_callbacks, kind)


def sent_tool_results(call_index: int) -> list[dict[str, Any]]:
    """The tool results the model was shown on its n-th call."""
    return [
        json.loads(message.content or "{}")
        for message in FAKE.calls[call_index].request.messages
        if message.role == "tool"
    ]


def test_a_question_is_answered_from_a_read_without_a_click(talk: Any) -> None:
    chat = talk(person("chat-read"))
    FAKE.script(tool("organization_peek_v1", {}), FakeReply(text="Firma nazywa się chat-read."))

    assert chat.say("Jak nazywa się moja firma?").status_code == 202

    turn = chat.last()
    assert (turn["state"], turn["text"]) == ("done", "Jak nazywa się moja firma?")
    action, answer = turn["items"]
    assert (action["kind"], action["status"], action["risk"]) == ("action", "done", "read")
    assert action["title"] == {"pl": "Odczytaj dane firmy", "en": "Read the company"}
    assert answer == {"kind": "text", "text": "Firma nazywa się chat-read."}
    assert turn["consents"] == []
    # The model reads what the command returned, and the time of the message.
    assert sent_tool_results(1) == [{"status": "done", "output": {"name": "chat-read"}}]
    first = FAKE.calls[0].request
    assert first.messages[1].content.endswith("] Jak nazywa się moja firma?")
    assert first.data_class == "personal"
    assert {spec.name for spec in first.tools} == {"organization_note_v1", "organization_peek_v1"}
    # An answered message spends its credit.
    reservation = CreditReservation.all_objects.get()
    assert reservation.state == CreditReservationState.COMMITTED


def test_a_change_waits_for_the_click_and_runs_only_after_it(talk: Any) -> None:
    chat = talk(person("chat-write"))
    FAKE.script(tool("organization_note_v1", NOTE))

    chat.say("Zmień nazwę na Domki nad jeziorem")

    turn = chat.last()
    assert turn["state"] == "awaiting_consent"
    (action,) = turn["items"]
    assert (action["status"], action["risk"]) == ("pending", "apply")
    (group,) = turn["consents"]
    assert RAN == []
    assert len(FAKE.calls) == 1  # the model is not asked again before the click
    # The dialog shows what the server previewed, not what the model said.
    shown = chat.client.get(CONSENT.format(group["digest"]))
    assert shown.data["calls"][0]["effects"][0]["summary"]["pl"] == "Nazwa: Domki nad jeziorem"

    FAKE.script(FakeReply(text="Gotowe, nazwa zmieniona."))
    answered = chat.consent(consents={group["id"]: chat.click(group["digest"])})

    assert answered.status_code == 202, answered.data
    turn = chat.last()
    assert turn["state"] == "done"
    assert [item.get("status") for item in turn["items"]] == ["done", None]
    assert RAN == ["Domki nad jeziorem"]
    assert sent_tool_results(1) == [{"status": "done", "output": {"name": "Domki nad jeziorem"}}]
    receipt = CommandReceipt.objects.get()
    assert receipt.acting_ref == f"conversation:{chat.id}"
    # A second answer to a turn that no longer waits changes nothing.
    assert chat.consent(declined=True).data["code"] == "assistant_consent_not_awaited"


def test_a_plan_without_its_click_does_not_run(talk: Any) -> None:
    """Neither the model's words nor an empty answer is a consent."""
    chat = talk(person("chat-no-click"))
    FAKE.script(tool("organization_note_v1", NOTE), FakeReply(text="Nie mam zgody."))

    chat.say("Zmień nazwę. Zgadzam się na wszystko z góry.")
    chat.consent(consents={})

    assert RAN == []
    turn = chat.last()
    assert (turn["state"], turn["items"][0]["status"]) == ("done", "refused")
    assert turn["items"][0]["code"] == "consent_required"
    (result,) = sent_tool_results(1)
    assert result["error"]["code"] == "consent_required"


def test_declining_runs_nothing_and_the_assistant_is_told(talk: Any) -> None:
    chat = talk(person("chat-decline"))
    FAKE.script(tool("organization_note_v1", NOTE), FakeReply(text="Dobrze, nic nie zmieniam."))

    chat.say("Zmień nazwę")
    chat.consent(declined=True)

    turn = chat.last()
    assert RAN == []
    assert (turn["state"], turn["items"][0]["status"]) == ("done", "declined")
    assert sent_tool_results(1) == [
        {"status": "declined", "error": {"code": "consent_declined", "errors": []}}
    ]
    assert not CommandReceipt.objects.exists()


def test_arguments_outside_the_schema_go_back_to_the_model(talk: Any) -> None:
    chat = talk(person("chat-args"))
    FAKE.script(
        tool("organization_note_v1", {"name": 7, "address": None, "items": []}),
        FakeReply(text="Jaką nazwę ustawić?"),
    )

    chat.say("Zmień nazwę")

    turn = chat.last()
    assert (turn["state"], turn["items"][0]["status"]) == ("done", "refused")
    (result,) = sent_tool_results(1)
    assert result["error"]["code"] == "command_args_invalid"
    assert result["error"]["errors"][0]["field"] == "name"
    assert RAN == []


def test_only_the_person_reads_their_conversation(talk: Any) -> None:
    owner = person("chat-private")
    chat = talk(owner)
    FAKE.script(FakeReply(text="Dzień dobry."))
    chat.say("Cześć")
    organization = Organization.objects.get(slug="chat-private")
    colleague_user = type(organization.memberships.first().user).objects.create_user(
        email="colleague@example.test", password=PASSWORD
    )
    colleague_user.status = "active"
    colleague_user.save()
    Membership.objects.create(
        organization=organization,
        user=colleague_user,
        role=Role.objects.get(key="admin", organization=None, organization_type=""),
    )
    colleague = APIClient()
    colleague.force_login(colleague_user)
    session = colleague.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    stranger = person("chat-elsewhere")

    for other in (colleague, stranger):
        listed = other.get(f"{BASE}conversations/")
        detail = other.get(f"{BASE}conversations/{chat.id}/")
        if listed.status_code == 200:
            assert listed.data["items"] == []
        assert detail.status_code in {403, 404}, detail.data

    assert [item["id"] for item in owner.get(f"{BASE}conversations/").data["items"]] == [chat.id]


def test_one_turn_at_a_time_and_a_repeated_key_is_the_same_turn(talk: Any) -> None:
    chat = talk(person("chat-order"))
    FAKE.script(tool("organization_note_v1", NOTE))
    first = chat.say("Zmień nazwę", key="a")

    again = chat.say("Zmień nazwę", key="a")
    other_text = chat.say("Co innego", key="a")
    second = chat.say("I jeszcze to", key="b")

    assert again.data["id"] == first.data["id"]
    assert other_text.data["code"] == "assistant_idempotency_conflict"
    assert second.status_code == 409
    assert second.data["code"] == "assistant_turn_in_progress"
    assert AssistantTurn.all_objects.count() == 1


def test_the_chat_is_closed_without_a_worker_a_model_or_the_plan(
    talk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = person("chat-closed")
    chat = talk(client)
    assert client.get(f"{BASE}offer/").data["available"] is True

    cache.delete(WORKER_SEEN)
    offer = client.get(f"{BASE}offer/").data
    assert (offer["available"], offer["reasons"]) == (False, ["worker_unavailable"])
    refused = chat.say("Cześć")
    assert (refused.status_code, refused.data["code"]) == (503, "assistant_unavailable")

    cache.set(WORKER_SEEN, 1, 300)
    # An empty value in the environment is no override: the task has to lose
    # its model in the registry for nobody to have picked one.
    monkeypatch.delenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL")
    unpicked = replace(model_registry._TASKS["assistant.conversation"], model="")
    monkeypatch.setitem(model_registry._TASKS, "assistant.conversation", unpicked)
    assert client.get(f"{BASE}offer/").data["reasons"] == ["model_not_selected"]

    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL", MODEL)
    EntitlementSnapshot.all_objects.update(features={"sites.enabled": True})
    offer = client.get(f"{BASE}offer/").data
    assert (offer["in_plan"], offer["reasons"]) == (False, ["feature_disabled"])
    assert chat.say("Cześć", key="t2").data["code"] == "assistant_not_in_plan"
    assert not AssistantTurn.all_objects.exists()


def test_the_limits_are_the_platforms_settings(talk: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        platform_settings,
        "platform_overrides",
        lambda: {
            "assistant.limits.turns_per_person_per_minute": 1,
            "assistant.limits.model_steps_per_turn": 1,
        },
    )
    chat = talk(person("chat-limits"))
    # One model call per message: the read is made, the report is not.
    FAKE.script(tool("organization_peek_v1", {}))

    chat.say("Jak nazywa się firma?", key="a")
    too_soon = chat.say("A teraz?", key="b")

    turn = chat.last()
    assert (turn["state"], turn["failure_code"]) == ("failed", "step_limit")
    assert (too_soon.status_code, too_soon.data["code"]) == (429, "assistant_rate_limited")
    # A turn that failed gives its credit back.
    assert CreditReservation.all_objects.get().state == CreditReservationState.RELEASED


def test_a_model_failure_ends_the_turn_with_a_reason_and_no_charge(talk: Any) -> None:
    chat = talk(person("chat-failure"))
    FAKE.script(FakeFailure(kind="refused", code="content_filter"))

    chat.say("Cześć")

    turn = chat.last()
    assert (turn["state"], turn["failure_code"]) == ("failed", "refused")
    assert CreditReservation.all_objects.get().state == CreditReservationState.RELEASED


def test_a_person_who_left_the_company_gets_no_turn_run(talk: Any) -> None:
    client = person("chat-left")
    chat = talk(client)
    FAKE.script(tool("organization_note_v1", NOTE))
    chat.say("Zmień nazwę")
    turn = AssistantTurn.all_objects.get()
    # The plan waits; the person is removed; the worker comes back to the turn.
    AssistantTurn.all_objects.filter(pk=turn.pk).update(state=TurnState.RUNNING)
    Membership.objects.update(status=MembershipStatus.SUSPENDED)

    from saas_core.modules.shared.assistant.turns import run_turn

    run_turn(turn.organization_id, turn.id)

    turn.refresh_from_db()
    assert (turn.state, turn.failure_code) == (TurnState.FAILED, "authorization_revoked")
    assert RAN == []
    assert len(FAKE.calls) == 1


def _assert_tenant_set_first(queries: list[dict[str, str]], *tables: str) -> None:
    sql = [query["sql"] for query in queries]
    tenant = next(
        (i for i, statement in enumerate(sql) if "app.organization_id" in statement), None
    )
    assert tenant is not None, "nikt nie ustawił tenanta"
    for table in tables:
        touched = next((i for i, statement in enumerate(sql) if table in statement), None)
        assert touched is not None, f"nie dotknięto {table}"
        assert tenant < touched, f"{table} odczytana przed SET LOCAL — pod RLS byłaby pusta"


def test_background_work_sets_the_tenant_before_it_reads(talk: Any) -> None:
    """The test database bypasses RLS, so only the order of queries shows that
    the worker, the sweep and the purge would see their rows in production."""
    chat = talk(person("chat-rls"))
    queued = chat.say("Cześć", run=False)
    turn = AssistantTurn.all_objects.get(pk=queued.data["id"])
    assert turn.state == TurnState.QUEUED
    FAKE.script(FakeReply(text="Dzień dobry."))

    from saas_core.modules.shared.assistant.turns import run_turn

    with CaptureQueriesContext(connection) as worker:
        run_turn(turn.organization_id, turn.id)
    _assert_tenant_set_first(
        worker.captured_queries,
        "assistant_assistantturn",
        "organizations_membership",
        "assistant_assistantmessage",
    )
    assert chat.last()["state"] == "done"

    with CaptureQueriesContext(connection) as sweep:
        reconcile_assistant_turns()
    _assert_tenant_set_first(sweep.captured_queries, "assistant_assistantturn")
    # The purge is the common privacy run's (`assistant/retention.py`): it
    # sets the tenant before either of the assistant's tables is read.
    with CaptureQueriesContext(connection) as purge:
        run_retention()
    _assert_tenant_set_first(
        purge.captured_queries,
        "assistant_assistantconversation",
        "assistant_assistantprofileversion",
    )


def test_stale_turns_are_closed_and_old_conversations_leave(talk: Any) -> None:
    chat = talk(person("chat-sweep"))
    FAKE.script(tool("organization_note_v1", NOTE))
    chat.say("Zmień nazwę")
    waiting = AssistantTurn.all_objects.get()
    # A turn somebody is deciding about is not stale; a running one nobody
    # touched for minutes is.
    long_ago = timezone.now() - timedelta(minutes=10)
    AssistantTurn.all_objects.filter(pk=waiting.pk).update(updated_at=long_ago)
    assert reconcile_assistant_turns() == 0
    AssistantTurn.all_objects.filter(pk=waiting.pk).update(
        state=TurnState.RUNNING, updated_at=long_ago
    )

    assert reconcile_assistant_turns() == 1

    waiting.refresh_from_db()
    assert (waiting.state, waiting.failure_code) == (TurnState.FAILED, "timeout")
    # Its open call is answered, so the transcript can be shown to a model again.
    assert AssistantMessage.all_objects.filter(role="tool").count() == 1


def _removed(organization_id: Any) -> dict[str, tuple[str, int]]:
    """What the common privacy run removed in the company, by sweep."""
    return {
        done.sweep: (done.period, done.count)
        for done in run_retention().removed
        if done.organization_id == organization_id
    }


def test_old_conversations_leave_with_the_common_privacy_run(talk: Any) -> None:
    """The module has no purge task of its own: its retention is registered
    under the nightly run, on the platform's days."""
    chat = talk(person("chat-retention"))
    FAKE.script(FakeReply(text="Dzień dobry."))
    chat.say("Cześć")
    conversation = AssistantConversation.all_objects.get()
    assert {"assistant.conversations", "assistant.profile_versions"} <= {
        sweep.key for sweep in registered_sweeps()
    }

    assert _removed(conversation.organization_id) == {}
    AssistantConversation.all_objects.update(updated_at=timezone.now() - timedelta(days=91))
    # What a run would take is told first, without a grace period: the days
    # are the platform's, not a company's click.
    (due,) = [
        item
        for item in retention_dry_run()
        if item.organization_id == conversation.organization_id
        and item.sweep == "assistant.conversations"
    ]
    assert (due.period, due.count, due.waits_until) == ("90 dni", 1, None)

    assert _removed(conversation.organization_id) == {"assistant.conversations": ("90 dni", 1)}
    assert not AssistantMessage.all_objects.exists()
    assert not AssistantTurn.all_objects.exists()
    # The history says a count, never a word of the conversation.
    entry = OrganizationAuditEntry.objects.filter(
        organization_id=conversation.organization_id, action="privacy.retention.run"
    ).get()
    assert entry.metadata == {"sweep": "assistant.conversations", "period": "90 dni", "removed": 1}


# --- What the server does itself: the sentence beside a plan, the words, the tools ----


def _wipe_preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(
        effects=(
            Effect(
                kind="deleted",
                resource="organization",
                resource_id=str(call.context.organization_id),
                summary={
                    "pl": f"Usunięcie notatki „{arguments['name']}”.",
                    "en": f"Removal of the note “{arguments['name']}”.",
                },
            ),
        ),
        observed_versions={},
    )


def _wipe() -> CommandSpec:
    return CommandSpec(
        name="organization.wipe",
        version=1,
        module="core.organizations",
        title={"pl": "Usuń notatkę", "en": "Remove the note"},
        summary={"pl": "Firma.", "en": "Company."},
        model_description="Removes a note for good.",
        input_schema=INPUT,
        output_schema=OUTPUT,
        permission=SETTINGS_MANAGE,
        risk="irreversible",
        run=_note,
        undo="none:a removed note is gone",
        preview=_wipe_preview,
        no_version_reason="A note has no version.",
    )


SAID = "Zanim się zgodzisz: tego kroku nie da się cofnąć. Usunięcie notatki „Domki nad jeziorem”."


def test_the_server_says_beside_the_plan_that_a_step_cannot_be_undone(talk: Any) -> None:
    """The model offers the removal without a word; the sentence is the
    server's, in the words of the step's preview — while the plan waits and
    in the conversation ever after."""
    register_command(_wipe())
    chat = talk(person("chat-for-good"))
    FAKE.script(tool("organization_wipe_v1", NOTE))

    chat.say("Usuń notatkę")

    turn = chat.last()
    assert turn["state"] == "awaiting_consent"
    said, action = turn["items"]
    assert said == {"kind": "text", "text": SAID}
    assert (action["status"], action["risk"]) == ("pending", "irreversible")

    FAKE.script(FakeReply(text="Nic nie usunięto."))
    chat.consent(declined=True)

    turn = chat.last()
    assert [item.get("text") or item["status"] for item in turn["items"]] == [
        SAID,
        "declined",
        "Nic nie usunięto.",
    ]
    assert RAN == []
    # The model is told how the step ended, as before — not the server's words.
    assert sent_tool_results(1) == [
        {"status": "declined", "error": {"code": "consent_declined", "errors": []}}
    ]


def test_the_sentence_stays_after_the_click_and_a_plan_one_can_take_back_has_none(
    talk: Any,
) -> None:
    register_command(_wipe())
    chat = talk(person("chat-for-good-done"))
    FAKE.script(tool("organization_wipe_v1", NOTE))
    chat.say("Usuń notatkę")
    (group,) = chat.last()["consents"]

    FAKE.script(FakeReply(text="Usunięto."))
    chat.consent(consents={group["id"]: chat.click(group["digest"])})

    turn = chat.last()
    assert [item.get("text") or item["status"] for item in turn["items"]] == [
        SAID,
        "done",
        "Usunięto.",
    ]
    assert RAN == ["Domki nad jeziorem"]

    FAKE.script(tool("organization_note_v1", NOTE))
    chat.say("Zmień nazwę", key="t2")
    (action,) = chat.last()["items"]
    assert action["status"] == "pending"


def test_an_answer_with_a_gendered_verb_is_written_again_before_anyone_reads_it(talk: Any) -> None:
    chat = talk(person("chat-words"))
    FAKE.script(
        FakeReply(text="Sprawdziłem: firma nazywa się chat-words."),
        FakeReply(text="Firma nazywa się chat-words."),
    )

    chat.say("Jak nazywa się moja firma?")

    turn = chat.last()
    assert turn["items"] == [{"kind": "text", "text": "Firma nazywa się chat-words."}]
    # The second call got the held answer and the panel's note, naming the form.
    held, note = FAKE.calls[1].request.messages[-2:]
    assert (held.role, held.content) == ("assistant", "Sprawdziłem: firma nazywa się chat-words.")
    assert note.role == "user" and note.content.startswith("[panel]")
    assert '"Sprawdziłem"' in note.content
    # Neither is kept: the transcript has the answer the person read.
    kept = AssistantMessage.all_objects.order_by("index").values_list("role", "content")
    assert list(kept) == [
        ("user", "Jak nazywa się moja firma?"),
        ("assistant", "Firma nazywa się chat-words."),
    ]
    assert AssistantTurn.all_objects.get().steps_used == 2


def test_the_first_answer_stands_when_it_cannot_be_written_again(
    talk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = talk(person("chat-words-once"))
    # Once only: a second answer with such a form is shown as it is.
    FAKE.script(FakeReply(text="Zmieniłem."), FakeReply(text="Żebym to zmienił, podaj nazwę."))
    chat.say("Zmień", key="a")
    assert chat.last()["items"] == [{"kind": "text", "text": "Żebym to zmienił, podaj nazwę."}]
    assert len(FAKE.calls) == 2

    # A failed rewrite, or a tool call instead of words, leaves the first answer.
    FAKE.script(FakeReply(text="Dodałam."), FakeFailure(kind="unavailable", code="provider_down"))
    chat.say("Dodaj", key="b")
    assert chat.last()["items"] == [{"kind": "text", "text": "Dodałam."}]
    FAKE.script(FakeReply(text="Mógłbym sprawdzić."), tool("organization_peek_v1", {}))
    chat.say("Sprawdź", key="c")
    assert chat.last()["items"] == [{"kind": "text", "text": "Mógłbym sprawdzić."}]

    # No call left for it in this message: no rewrite is asked for.
    monkeypatch.setattr(
        platform_settings,
        "platform_overrides",
        lambda: {"assistant.limits.model_steps_per_turn": 1},
    )
    FAKE.reset()
    FAKE.script(FakeReply(text="Ustawiłem."))
    chat.say("Ustaw", key="d")
    assert chat.last()["items"] == [{"kind": "text", "text": "Ustawiłem."}]
    assert len(FAKE.calls) == 1


def test_a_conversation_gets_the_tools_of_what_it_is_about(
    talk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Of the company's area first the tool that reads; the one that changes
    comes when the model asks for it — or when the person asks for a change."""
    from saas_core.modules.shared.assistant import topics

    monkeypatch.setattr(topics, "SELECT_ABOVE", 0)
    chat = talk(person("chat-tools"))
    FAKE.script(
        tool("more_tools", {"topics": ["company"], "change": True}),
        tool("organization_note_v1", NOTE, "c2"),
    )

    chat.say("Jak nazywa się moja firma? Ma być inaczej.")

    first, second = (call.request for call in FAKE.calls)
    assert [spec.name for spec in first.tools] == ["more_tools", "organization_peek_v1"]
    assert "- company: the company's name" in first.tools[0].description
    assert [spec.name for spec in second.tools] == [
        "more_tools",
        "organization_peek_v1",
        "organization_note_v1",
    ]
    assert sent_tool_results(1) == [
        {"status": "done", "output": {"opened": ["company"], "unknown": [], "change": True}}
    ]
    turn = chat.last()
    opened, change = turn["items"]
    assert (opened["status"], opened["risk"]) == ("done", "read")
    assert opened["title"]["pl"] == "Sięgnij po kolejny obszar panelu"
    assert (turn["state"], change["status"]) == ("awaiting_consent", "pending")

    # The person's own words for a change bring both at once.
    other = talk(person("chat-tools-change"))
    FAKE.reset()
    FAKE.script(FakeReply(text="Jaką nazwę ustawić?"))
    other.say("Zmień nazwę firmy")
    assert [spec.name for spec in FAKE.calls[0].request.tools] == [
        "more_tools",
        "organization_peek_v1",
        "organization_note_v1",
    ]
    # Words that name no area: the one tool that lists them all.
    FAKE.script(FakeReply(text="Cześć."))
    other.say("Cześć", key="t2")
    assert [spec.name for spec in FAKE.calls[1].request.tools][:1] == ["more_tools"]


def test_the_transcript_is_marked_for_the_cache_and_results_carry_no_nulls(talk: Any) -> None:
    from saas_core.modules.shared.assistant import turns

    chat = talk(person("chat-cache"))
    FAKE.script(tool("organization_peek_v1", {}), FakeReply(text="Firma nazywa się chat-cache."))

    chat.say("Jak nazywa się moja firma?")

    first, second = (call.request for call in FAKE.calls)
    # One mark, on the last message; the prompt keeps its own.
    assert [message.cache for message in first.messages] == [True, True]
    assert [message.cache for message in second.messages] == [True, False, False, True]
    stored = AssistantMessage.all_objects.get(role="tool").content
    assert stored == '{"status":"done","output":{"name":"chat-cache"}}'
    assert turns._lean({"a": None, "b": [{"c": None, "d": 0, "e": ""}], "f": []}) == {  # noqa: SLF001
        "b": [{"d": 0, "e": ""}],
        "f": [],
    }


def test_a_proof_accounts_conversation_is_counted_with_the_evals(talk: Any, settings: Any) -> None:
    from django.contrib.auth import get_user_model
    from django.core.checks import run_checks

    from saas_core.modules.shared.model_port.models import UsageEntry

    client = person("chat-proof")
    email = get_user_model().objects.get().email
    chat = talk(client)
    settings.PUBLIC_SITE_SCHEME = "http"
    settings.ASSISTANT_PROOF_ACCOUNTS = (email.lower(),)
    FAKE.script(FakeReply(text="Cześć."), FakeReply(text="Cześć."), FakeReply(text="Cześć."))

    chat.say("Cześć", key="a")
    assert UsageEntry.objects.get().purpose == "eval"
    assert not [found for found in run_checks() if found.id == "assistant.E001"]

    # Any other account, and every account of a stack served over https, is a customer.
    settings.ASSISTANT_PROOF_ACCOUNTS = ("ktos-inny@saas.test",)
    chat.say("Cześć", key="b")
    settings.ASSISTANT_PROOF_ACCOUNTS = (email.lower(),)
    settings.PUBLIC_SITE_SCHEME = "https"
    chat.say("Cześć", key="c")
    purposes = list(UsageEntry.objects.order_by("created_at").values_list("purpose", flat=True))
    assert purposes == ["eval", "customer", "customer"]
    # …and such a stack does not start.
    assert [found.id for found in run_checks() if found.id == "assistant.E001"] == [
        "assistant.E001"
    ]
