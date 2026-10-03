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
    offer_plan,
    pending_consent,
    platform_setting,
)
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
)
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    decide_feature,
    operation_cost,
    reserve_credits,
)
from saas_core.modules.shared.model_port.api import task_status

from .models import (
    TURN_OPEN,
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    MessageRole,
    TurnState,
)
from .permissions import ASSISTANT_USE, CREDIT_OPERATION, TASK, TEXT_FEATURE
from .settings_spec import DAILY_TURNS, STARTS_PER_HOUR, TURNS_PER_MINUTE
from .turns import (
    append_message,
    close_open_calls,
    conversation_ref,
    record_results,
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
    _person()
    reasons = _unavailable()
    feature = decide_feature(TEXT_FEATURE, operation=FeatureOperation.WRITE).allowed
    if not feature:
        reasons.append(UNAVAILABLE_FEATURE)
    return {
        "available": not reasons,
        "reasons": reasons,
        "in_plan": feature,
        "credits_per_message": operation_cost(CREDIT_OPERATION),
        "max_message_characters": MAX_MESSAGE_CHARACTERS,
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


# --- Conversations -----------------------------------------------------------------


@transaction.atomic
def start_conversation(
    *, language: str, idempotency_key: str, address: str
) -> AssistantConversation:
    context = _person()
    existing = _conversations(context).filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    _require_open()
    _count_start(address)
    return AssistantConversation.all_objects.create(
        organization_id=context.organization_id,
        membership_id=context.membership_id,
        created_by_id=context.actor_id,
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
    return {
        "conversation": conversation,
        "turns": [_shown_turn(turn, messages) for turn in turns],
    }


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
    reservation = reserve_credits(
        CREDIT_OPERATION,
        idempotency_key=f"assistant_turn:{turn.id}",
        expires_at=timezone.now() + timedelta(minutes=HOLD_MINUTES),
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
    calls: list[dict[str, Any]] = turn.pending["calls"]
    if declined:
        close_open_calls(turn, conversation, "consent_declined")
    else:
        with activate_tenant_context(conversation_context(context, conversation)):
            results = execute_plan(_invocations(calls), dict(consents))
        record_results(turn, conversation, calls, results)
        turn.pending = None
    turn.state = TurnState.RUNNING
    turn.save(update_fields=["pending", "state", "updated_at"])
    _queue(turn)
    return turn


def _invocations(calls: list[dict[str, Any]]) -> list[Invocation]:
    return [
        Invocation(
            command=call["name"],
            arguments=json.loads(call["arguments_json"]),
            step_id=call["step_id"],
        )
        for call in calls
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
    with activate_tenant_context(conversation_context(context, conversation)), transaction.atomic():
        plan = offer_plan(_invocations(pending["calls"]))
    groups = [
        {"id": group.id, "digest": group.digest, "steps": [call.step_id for call in group.calls]}
        for group in plan.groups
    ]
    if groups != pending["groups"]:
        turn.pending = {**pending, "groups": groups}
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
            items.append({
                "kind": "action",
                "step_id": call["step_id"],
                **_command_words(call["command"]),
                "status": results.get(call["id"], {}).get("status", "pending"),
                "code": results.get(call["id"], {}).get("code", ""),
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


def _command_words(key: str) -> dict[str, Any]:
    """The command as a person reads it: its title, never its key."""
    try:
        spec = command(key)
    except UnknownCommand:
        return {"title": _UNKNOWN_TITLE, "risk": "read"}
    return {"title": dict(spec.title), "risk": spec.risk}
