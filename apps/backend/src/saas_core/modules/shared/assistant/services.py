"""What the panel asks of the assistant: start, write, read, answer a consent.

A conversation belongs to one person's membership; nobody else in the company
reads it. Every entry checks the person here, not in the view (the same
services serve a command or a task), and none of them calls a model: a
message only queues its turn for the `ai` worker (`turns.run_turn`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Max, QuerySet
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from saas_core.modules.core.organizations.api import (
    Invocation,
    UnknownCommand,
    command,
    execute_plan,
    handles_in,
    known_people,
    offer_plan,
    pending_consent,
    person_cards,
    platform_setting,
)
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    decide_feature,
    operation_cost,
    reserve_credits,
)
from saas_core.modules.shared.model_port.api import task_status

from . import setup, topics
from .models import (
    TURN_OPEN,
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    ConversationKind,
    MessageRole,
    TurnState,
)
from .permissions import ASSISTANT_USE, CREDIT_OPERATION, TASK, TEXT_FEATURE
from .settings_spec import (
    DAILY_TURNS,
    SETUP_TURNS_PER_COMPANY,
    SETUP_TURNS_PER_DAY,
    STARTS_PER_HOUR,
    TURNS_PER_MINUTE,
)
from .turns import (
    append_message,
    close_open_calls,
    conversation_ref,
    people_book,
    people_of,
    record_plan,
    record_results,
    warning,
)

#: Set while a worker consumes the `ai` queue (`tasks.assistant_heartbeat`);
#: without it a message would wait for nobody, so the chat says it is closed.
WORKER_SEEN = "assistant:worker-seen"
WORKER_SEEN_TTL = 300

MAX_MESSAGE_CHARACTERS = 4000
#: A turn's credit hold, should its worker never come back for it.
HOLD_MINUTES = 30

UNAVAILABLE_WORKER = "worker_unavailable"
UNAVAILABLE_CEILING = "daily_ceiling"
UNAVAILABLE_FEATURE = "feature_disabled"


class AssistantPersonOnly(PermissionDenied):
    default_detail = "Z asystentem rozmawia osoba zalogowana w panelu."
    default_code = "assistant_person_only"


class AssistantUnavailable(APIException):
    status_code = 503
    default_detail = "Asystent nie jest teraz dostępny. Skorzystaj z panelu."
    default_code = "assistant_unavailable"


class AssistantLimited(APIException):
    status_code = 429
    default_detail = "Za dużo wiadomości naraz. Spróbuj ponownie za chwilę."
    default_code = "assistant_rate_limited"


class ConversationNotFound(NotFound):
    default_detail = "Nie ma takiej rozmowy."
    default_code = "assistant_conversation_not_found"


class TurnInProgress(APIException):
    status_code = 409
    default_detail = "Asystent jeszcze odpowiada na poprzednią wiadomość."
    default_code = "assistant_turn_in_progress"


class ConsentNotAwaited(APIException):
    status_code = 409
    default_detail = "Ta wiadomość nie czeka już na zgodę."
    default_code = "assistant_consent_not_awaited"


class SetupBudgetSpent(APIException):
    """The free setup conversation has used its messages. Nothing is lost:
    what was settled stays in the company's profile."""

    status_code = 429
    default_detail = (
        "Limit bezpłatnych wiadomości na ustawianie firmy jest wykorzystany. To, co ustalone, "
        "zostaje w notatkach o firmie. Resztę ustawisz w panelu — Wizytówka, Zespół, "
        "Ustawienia › Usługi i grafik — albo w zwykłej rozmowie z asystentem."
    )
    default_code = "assistant_setup_budget"


class SetupBudgetSpentToday(SetupBudgetSpent):
    default_detail = (
        "Dzisiejszy limit bezpłatnych wiadomości na ustawianie firmy jest wykorzystany. To, co "
        "ustalone, zostaje w notatkach o firmie. Wróć jutro albo ustaw resztę w panelu — "
        "Wizytówka, Zespół, Ustawienia › Usługi i grafik."
    )
    default_code = "assistant_setup_daily_budget"


class IdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Ten klucz Idempotency-Key był już użyty do innej wiadomości."
    default_code = "assistant_idempotency_conflict"


# --- Who may talk ------------------------------------------------------------------


def _person() -> TenantContext:
    """The signed-in person, deciding for themselves: not an integration, not
    something already acting for them."""
    context = authorize(ASSISTANT_USE)
    if context.principal_kind != "membership" or context.acting_via:
        raise AssistantPersonOnly
    return context


def conversation_context(
    context: TenantContext, conversation: AssistantConversation
) -> TenantContext:
    """The person's membership acting through this conversation (ADR-076 §6)."""
    return acting_context(context, via="assistant", ref=conversation_ref(conversation.id))


# --- The offer ---------------------------------------------------------------------


def assistant_offer() -> dict[str, Any]:
    """Whether the person can talk to the assistant now, and why not."""
    context = _person()
    reasons = _unavailable()
    feature = decide_feature(TEXT_FEATURE, operation=FeatureOperation.WRITE).allowed
    if not feature:
        reasons.append(UNAVAILABLE_FEATURE)
    company, today = _setup_turns_left(context)
    return {
        "available": not reasons,
        "reasons": reasons,
        "in_plan": feature,
        "credits_per_message": operation_cost(CREDIT_OPERATION),
        "max_message_characters": MAX_MESSAGE_CHARACTERS,
        "setup": {
            "allowed": context.has_permission(SETTINGS_MANAGE),
            "turns_left": company,
            "turns_left_today": today,
        },
    }


def _unavailable() -> list[str]:
    reasons: list[str] = []
    port = task_status(TASK)
    if port.reason is not None:
        reasons.append(port.reason)
    if not cache.get(WORKER_SEEN):
        reasons.append(UNAVAILABLE_WORKER)
    if (cache.get(_day_key()) or 0) >= int(platform_setting(DAILY_TURNS.key)):
        reasons.append(UNAVAILABLE_CEILING)
    return reasons


def _require_open() -> None:
    if _unavailable():
        # Why not is the offer's to say (`assistant_offer`), not an error's.
        raise AssistantUnavailable
    decision = decide_feature(TEXT_FEATURE, operation=FeatureOperation.WRITE)
    if not decision.allowed:
        raise PermissionDenied(
            "Asystent nie jest w planie tej firmy.", code="assistant_not_in_plan"
        )


# --- Limits ------------------------------------------------------------------------


def _day_key() -> str:
    return f"assistant:turns:{datetime.now(UTC):%Y%m%d}"


def _count(key: str, *, limit: int, window_seconds: int, code: str) -> None:
    cache.add(key, 0, timeout=window_seconds)
    if cache.incr(key) > limit:
        raise AssistantLimited(code=code)


def _count_start(address: str) -> None:
    bucket = int(timezone.now().timestamp() // 3600)
    digest = hashlib.sha256(address.encode()).hexdigest()[:32]
    _count(
        f"assistant:starts:{digest}:{bucket}",
        limit=int(platform_setting(STARTS_PER_HOUR.key)),
        window_seconds=3600,
        code="assistant_rate_limited",
    )


def _count_turn(context: TenantContext) -> None:
    bucket = int(timezone.now().timestamp() // 60)
    _count(
        f"assistant:person:{context.actor_id}:{bucket}",
        limit=int(platform_setting(TURNS_PER_MINUTE.key)),
        window_seconds=60,
        code="assistant_rate_limited",
    )
    cache.add(_day_key(), 0, timeout=2 * 24 * 3600)
    cache.incr(_day_key())


def _setup_turns_left(context: TenantContext) -> tuple[int, int]:
    """Free setup messages left for the company and for this person today
    (decision 23 b: setting a company up costs no credits, within budgets)."""
    turns = AssistantTurn.all_objects.filter(
        organization_id=context.organization_id, conversation__kind=ConversationKind.SETUP
    )
    midnight = timezone.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = turns.filter(
        conversation__membership_id=context.membership_id, created_at__gte=midnight
    )
    return (
        max(0, int(platform_setting(SETUP_TURNS_PER_COMPANY.key)) - turns.count()),
        max(0, int(platform_setting(SETUP_TURNS_PER_DAY.key)) - today.count()),
    )


def setup_overview(conversation_id: UUID) -> dict[str, Any]:
    """Where the company's setup stands, for the panel beside a setup
    conversation: what is known and from whom, what is still asked, what is
    ready, what waits and what cannot be done yet.

    The account is read through the registry, and the registry's commands run
    only for the assistant acting for a person — so the read is this
    conversation's, as its own `setup_status` is."""
    context = _person()
    conversation = _own(context, conversation_id)
    if conversation.kind != ConversationKind.SETUP:
        raise ConversationNotFound
    acting = conversation_context(context, conversation)
    with activate_tenant_context(acting):
        return setup.overview(acting)


# --- Conversations -----------------------------------------------------------------


@transaction.atomic
def start_conversation(
    *, language: str, idempotency_key: str, address: str, kind: str = ConversationKind.OPERATE
) -> AssistantConversation:
    context = _person()
    existing = _conversations(context).filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if kind == ConversationKind.SETUP:
        # The profile is the company's: whoever sets it up manages its settings.
        authorize(SETTINGS_MANAGE)
    _require_open()
    _count_start(address)
    return AssistantConversation.all_objects.create(
        organization_id=context.organization_id,
        membership_id=context.membership_id,
        created_by_id=context.actor_id,
        kind=kind,
        language=language,
        idempotency_key=idempotency_key,
    )


def list_conversations(*, limit: int) -> list[AssistantConversation]:
    context = _person()
    return list(_conversations(context).order_by("-updated_at", "-id")[:limit])


def get_conversation(conversation_id: UUID) -> dict[str, Any]:
    context = _person()
    conversation = _own(context, conversation_id)
    turns = list(_turns(conversation).order_by("index"))
    waiting = next((turn for turn in turns if turn.state == TurnState.AWAITING_CONSENT), None)
    if waiting is not None:
        _offer_again(context, conversation, waiting)
    messages = list(
        AssistantMessage.all_objects.filter(conversation=conversation).order_by("index")
    )
    shown = [_shown_turn(turn, messages) for turn in turns]
    _show_people(shown, messages)
    return {"conversation": conversation, "turns": shown}


def _conversations(context: TenantContext) -> QuerySet[AssistantConversation]:
    """The person's own conversations in this company: nobody else's."""
    return AssistantConversation.all_objects.filter(
        organization_id=context.organization_id, membership_id=context.membership_id
    )


def _turns(conversation: AssistantConversation) -> QuerySet[AssistantTurn]:
    return AssistantTurn.all_objects.filter(conversation=conversation)


def _own(
    context: TenantContext, conversation_id: UUID, *, lock: bool = False
) -> AssistantConversation:
    queryset = _conversations(context).filter(pk=conversation_id)
    if lock:
        queryset = queryset.select_for_update()
    conversation = queryset.first()
    if conversation is None:
        # Another person's conversation and none at all look the same.
        raise ConversationNotFound
    return conversation


# --- Turns -------------------------------------------------------------------------


@transaction.atomic
def add_turn(*, conversation_id: UUID, text: str, idempotency_key: str) -> AssistantTurn:
    """Takes the person's message and queues the assistant's turn."""
    context = _person()
    conversation = _own(context, conversation_id, lock=True)
    turns = _turns(conversation)
    repeated = turns.filter(idempotency_key=idempotency_key).first()
    if repeated is not None:
        first = (
            AssistantMessage.all_objects.filter(turn=repeated, role=MessageRole.USER)
            .order_by("index")
            .first()
        )
        if first is None or first.content != text:
            raise IdempotencyConflict
        return repeated
    if turns.filter(state__in=TURN_OPEN).exists():
        raise TurnInProgress
    _require_open()
    setting_up = conversation.kind == ConversationKind.SETUP
    if setting_up:
        company, today = _setup_turns_left(context)
        if not company:
            raise SetupBudgetSpent
        if not today:
            raise SetupBudgetSpentToday
    _count_turn(context)
    last = turns.aggregate(last=Max("index"))["last"] or 0
    try:
        with transaction.atomic():
            turn = AssistantTurn.all_objects.create(
                organization_id=context.organization_id,
                conversation=conversation,
                index=last + 1,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        raise TurnInProgress from None
    # A message that sets the company up is free; any other holds its credit.
    reservation = (
        None
        if setting_up
        else reserve_credits(
            CREDIT_OPERATION,
            idempotency_key=f"assistant_turn:{turn.id}",
            expires_at=timezone.now() + timedelta(minutes=HOLD_MINUTES),
        )
    )
    if reservation is not None:
        turn.credit_reservation_key = f"assistant_turn:{turn.id}"
        turn.save(update_fields=["credit_reservation_key", "updated_at"])
    append_message(turn, conversation, role=MessageRole.USER, content=text)
    if not conversation.title:
        conversation.title = " ".join(text.split())[:120]
    conversation.save(update_fields=["title", "updated_at"])
    _queue(turn)
    return turn


def _queue(turn: AssistantTurn) -> None:
    from .tasks import run_assistant_turn  # noqa: PLC0415 — tasks import this module

    organization_id, turn_id = str(turn.organization_id), str(turn.id)
    transaction.on_commit(lambda: run_assistant_turn.delay(organization_id, turn_id))


@transaction.atomic
def answer_consent(
    *, conversation_id: UUID, turn_id: UUID, consents: Mapping[str, str], declined: bool
) -> AssistantTurn:
    """Runs the plan the person agreed to — or closes it, if they declined —
    and lets the assistant report.

    `consents` maps a consent group's id to the token its click minted
    (`POST …/command-consents/{digest}/`). A group without a token does not
    run. The plan runs here, in the person's own request, so a token never
    leaves it; the worker only continues the conversation afterwards.
    """
    context = _person()
    conversation = _own(context, conversation_id, lock=True)
    turn = _turns(conversation).select_for_update().filter(pk=turn_id).first()
    if turn is None:
        raise ConversationNotFound
    if turn.state != TurnState.AWAITING_CONSENT or not turn.pending:
        raise ConsentNotAwaited
    pending: dict[str, Any] = turn.pending
    calls: list[dict[str, Any]] = pending["calls"]
    if declined:
        close_open_calls(turn, conversation, "consent_declined")
    else:
        people = people_book(conversation.id)
        with (
            activate_tenant_context(conversation_context(context, conversation)),
            known_people(people),
        ):
            results = execute_plan(_pending_invocations(pending), dict(consents))
        said = pending.get("said", "")
        if "steps" in pending:
            record_plan(turn, conversation, calls[0], pending["steps"], results, said)
        else:
            record_results(turn, conversation, calls, results, said, people)
        turn.pending = None
    turn.state = TurnState.RUNNING
    turn.save(update_fields=["pending", "state", "updated_at"])
    _queue(turn)
    return turn


def _pending_invocations(pending: Mapping[str, Any]) -> list[Invocation]:
    """What a waiting plan runs: the configurator's steps in a setup
    conversation (one call of the model offered them all), else the model's
    own calls."""
    if "steps" in pending:
        return setup.invocations(pending["steps"])
    return [
        Invocation(
            command=call["name"],
            arguments=json.loads(call["arguments_json"]),
            step_id=call["step_id"],
        )
        for call in pending["calls"]
    ]


def _offer_again(
    context: TenantContext, conversation: AssistantConversation, turn: AssistantTurn
) -> None:
    """A plan may wait for its click longer than the server keeps its preview
    (`COMMAND_PENDING_TTL`): then the same steps are offered again, on the
    state of now."""
    pending: dict[str, Any] = turn.pending or {}
    if all(pending_consent(context, group["digest"]) for group in pending["groups"]):
        return
    with (
        activate_tenant_context(conversation_context(context, conversation)),
        known_people(people_book(conversation.id)),
        transaction.atomic(),
    ):
        plan = offer_plan(_pending_invocations(pending))
    groups = [
        {"id": group.id, "digest": group.digest, "steps": [call.step_id for call in group.calls]}
        for group in plan.groups
    ]
    if groups != pending["groups"]:
        # The server's sentence beside the plan follows the plan as it is now.
        said = warning(plan, conversation.language)
        turn.pending = {**pending, "groups": groups, "said": said}
        turn.save(update_fields=["pending", "updated_at"])


# --- What the panel shows -----------------------------------------------------------

_UNKNOWN_TITLE = {"pl": "Działanie", "en": "Action"}


def _shown_turn(turn: AssistantTurn, messages: list[AssistantMessage]) -> dict[str, Any]:
    own = [message for message in messages if message.turn_id == turn.id]
    results = {
        message.tool_call_id: message.result or {}
        for message in own
        if message.role == MessageRole.TOOL
    }
    items: list[dict[str, Any]] = []
    for message in own:
        if message.role != MessageRole.ASSISTANT:
            continue
        if message.content:
            items.append({"kind": "text", "text": message.content})
        for call in message.tool_calls:
            result = results.get(call["id"], {})
            said = _said(turn, call, result)
            if said:
                items.append({"kind": "text", "text": said})
            steps = _plan_steps(turn, call, result)
            if steps:
                items.extend(steps)
                continue
            items.append({
                "kind": "action",
                "step_id": call["step_id"],
                **_command_words(call["command"], call["name"]),
                "status": result.get("status", "pending"),
                "code": result.get("code", ""),
            })
    person = next((message for message in own if message.role == MessageRole.USER), None)
    return {
        "turn": turn,
        "text": person.content if person else "",
        "items": items,
        "consents": (turn.pending or {}).get("groups", [])
        if turn.state == TurnState.AWAITING_CONSENT
        else [],
    }


def _show_people(turns: list[dict[str, Any]], messages: list[AssistantMessage]) -> None:
    """Puts a card beside each text of the assistant that names a person by a
    handle of this conversation. The model wrote the handle and never had the
    card: it is read here, from the record as it is now and as the person
    reading may see it in the panel. A handle the conversation was never given
    stays the text it is."""
    book = people_of(messages)
    texts = [item for turn in turns for item in turn["items"] if item["kind"] == "text"]
    if not book:
        return
    named = {item["text"]: handles_in(item["text"], book) for item in texts}
    mentioned = {handle: book[handle] for handles in named.values() for handle in handles}
    if not mentioned:
        return
    cards = person_cards(mentioned)
    for item in texts:
        people = [cards[handle] for handle in named[item["text"]]]
        if people:
            item["people"] = people


def _said(turn: AssistantTurn, call: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """The server's own sentence beside the plan this call began — that a
    step of it cannot be undone — while the plan waits and ever after. It is
    the server's, not the model's: no model has to remember to say it."""
    pending = turn.pending or {}
    if (
        turn.state == TurnState.AWAITING_CONSENT
        and pending.get("calls")
        and pending["calls"][0]["id"] == call["id"]
    ):
        return str(pending.get("said") or "")
    return str(result.get("said") or "")


def _plan_steps(
    turn: AssistantTurn, call: Mapping[str, Any], result: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The steps of the configurator's plan one call offered: as they wait for
    the click, and as each ended after it."""
    pending = turn.pending or {}
    waiting = turn.state == TurnState.AWAITING_CONSENT and "steps" in pending
    if waiting and pending["calls"][0]["id"] == call["id"]:
        steps = [{**step, "status": "pending", "code": ""} for step in pending["steps"]]
    else:
        steps = result.get("steps", [])
    return [
        {
            "kind": "action",
            "step_id": step["step_id"],
            **_command_words(step["command"]),
            "status": step["status"],
            "code": step["code"],
        }
        for step in steps
    ]


def _command_words(key: str, tool: str = "") -> dict[str, Any]:
    """The command as a person reads it: its title, never its key."""
    if tool in setup.TITLES:
        return {"title": setup.TITLES[tool], "risk": "read"}
    if tool == topics.MORE_TOOLS:
        return {"title": topics.TITLE, "risk": "read"}
    try:
        spec = command(key)
    except UnknownCommand:
        return {"title": _UNKNOWN_TITLE, "risk": "read"}
    return {"title": dict(spec.title), "risk": spec.risk}
