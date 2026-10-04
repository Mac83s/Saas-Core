"""One turn of a conversation: the model reads, proposes and reports (ADR-076, A3).

The loop runs in the `ai` worker, a model call at a time:

1. the turn's transcript and the person's tools go to the model — outside any
   transaction, so no row stays locked while a provider thinks;
2. the tool calls of one answer are one plan of registered commands, with
   step ids the server gives; reads run at once and their results go back to
   the model; a plan with a write stops the turn until the person clicks;
3. after the click the web request runs the plan (`services.answer_consent`)
   and the loop goes on, so the model reports from the receipts.

The model's text is never a consent and never evidence that something was
done: only a step's result is. Everything here acts as the person's own
membership through the conversation (`acting_via="assistant"`), so a command
checks their permissions and plan exactly as the panel would.

What must not depend on a model remembering a rule, the server does itself
(uzupełnienie 2026-10-04 L3): beside a plan with a step nobody
can take back it writes that sentence in its own words (`warning`), and an
answer with a Polish verb that has a gender goes back once to be written again
(`style`). An ordinary conversation is offered the tools of the areas it has
touched, not the whole registry (`topics`), and the transcript is marked for
the provider's cache up to its last message.

A person in a tool's answer is a handle (uzupełnienie 2026-10-04 „karty
osób”): the conversation keeps which record each handle stands for with the
tool result that carried it (`result["people"]`, never part of what a model
is sent), runs its plans with that book, and the panel reads a card per
handle from the record itself.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.http.exceptions import problem_code, problem_errors
from saas_core.modules.core.organizations.api import (
    CallResult,
    Invocation,
    Plan,
    UnknownCommand,
    command_for_tool,
    command_tools,
    execute_plan,
    handles_in,
    known_people,
    offer_plan,
    platform_setting,
)
from saas_core.modules.core.organizations.context import (
    TenantContext,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    deferred_tenant_context,
)
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    commit_credits,
    decide_feature,
    release_credits,
)
from saas_core.modules.shared.model_port.api import (
    Continuation,
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolSpec,
    complete,
)

from . import setup, style, topics
from .models import (
    AssistantConversation,
    AssistantMessage,
    AssistantTurn,
    ConversationKind,
    MessageRole,
    TurnState,
)
from .permissions import ASSISTANT_USE, TASK, TEXT_FEATURE
from .prompts import (
    PROMPT_ID,
    PROMPT_VERSION,
    SETUP_PROMPT_ID,
    SETUP_PROMPT_VERSION,
    system_prompt,
)
from .settings_spec import SETUP_STEPS_PER_TURN, STEPS_PER_TURN

logger = logging.getLogger("saas_core.assistant")

#: A tool result longer than this is not sent back: the model asks narrower.
MAX_TOOL_RESULT_CHARACTERS = 24_000

#: Why a turn failed, as the panel explains it (never a provider's message).
FAILURE_BUDGET_CONVERSATION = "conversation_budget"
FAILURE_BUDGET = "budget"
FAILURE_REFUSED = "refused"
FAILURE_UNAVAILABLE = "unavailable"
FAILURE_STEP_LIMIT = "step_limit"
FAILURE_REVOKED = "authorization_revoked"
FAILURE_TIMEOUT = "timeout"


#: The server's own sentence beside a plan with a step that cannot be taken
#: back, before what that step does in the words of its preview: one step, more.
IRREVERSIBLE = {
    "pl": (
        "Zanim się zgodzisz: tego kroku nie da się cofnąć.",
        "Zanim się zgodzisz: tych kroków nie da się cofnąć.",
    ),
    "en": (
        "Before you agree: this step cannot be undone.",
        "Before you agree: these steps cannot be undone.",
    ),
}


class _Stop(Exception):
    """The turn is gone. Raised only where nothing was written: an exception
    leaving `_scope` rolls its transaction back."""


@dataclass(frozen=True, slots=True)
class _Scope:
    context: TenantContext
    turn: AssistantTurn
    conversation: AssistantConversation


#: handle → (kind, the record's id), as `core.organizations.api` keeps it.
type People = dict[str, tuple[str, UUID]]


def conversation_ref(conversation_id: UUID) -> str:
    return f"conversation:{conversation_id}"


def people_of(rows: Iterable[AssistantMessage]) -> People:
    """The conversation's book of people: every handle one of its tool results
    carried, and the record it stands for. A handle outside it stands for
    nobody here — another conversation's, another company's, a made-up one."""
    book: People = {}
    for row in rows:
        for handle, (kind, subject_id) in ((row.result or {}).get("people") or {}).items():
            book[handle] = (kind, UUID(subject_id))
    return book


def people_book(conversation_id: UUID) -> People:
    return people_of(
        AssistantMessage.all_objects.filter(
            conversation_id=conversation_id, role=MessageRole.TOOL
        ).only("result")
    )


def run_turn(organization_id: UUID, turn_id: UUID) -> None:
    """Runs the turn until it is done, failed or waits for the person."""
    go_on = True
    while go_on:
        try:
            request = _next_request(organization_id, turn_id)
            if request is None:
                return
            try:
                response = complete(request)
            except ModelError as error:
                if error.kind == "tool_args_invalid" and error.response is not None:
                    go_on = _record_invalid_calls(organization_id, turn_id, error)
                    continue
                _fail(organization_id, turn_id, _failure_code(error))
                return
            form = "" if response.tool_calls else style.gendered(response.text or "")
            if form:
                response = _rewritten(organization_id, turn_id, request, response, form)
            go_on = _record_answer(organization_id, turn_id, response)
        except _Stop:
            return
        except InvalidTenantTaskContext:
            _fail(organization_id, turn_id, FAILURE_REVOKED)
            return


@contextmanager
def _scope(organization_id: UUID, turn_id: UUID) -> Iterator[_Scope]:
    """The turn, locked, under its person's membership acting through the
    conversation — one short transaction, committed when the block ends."""
    with transaction.atomic():
        # Before anything is read, and for this whole transaction: the turn,
        # its conversation and the membership are all rows of this company.
        set_local_organization_id(organization_id)
        found = (
            AssistantTurn.all_objects.select_related("conversation")
            .filter(pk=turn_id, organization_id=organization_id)
            .first()
        )
        if found is None:
            raise _Stop
        conversation = found.conversation
        with deferred_tenant_context(
            organization_id=organization_id,
            membership_id=conversation.membership_id,
            actor_id=conversation.created_by_id,
            causation_id=f"assistant_turn:{turn_id}",
            acting_via="assistant",
            acting_ref=conversation_ref(conversation.id),
        ) as context:
            turn = (
                AssistantTurn.all_objects.select_for_update()
                .filter(pk=turn_id, organization_id=organization_id)
                .first()
            )
            if turn is None:
                raise _Stop
            yield _Scope(context=context, turn=turn, conversation=conversation)


def _next_request(organization_id: UUID, turn_id: UUID) -> ModelRequest | None:
    """The next call to the model, or None when the turn is over."""
    with _scope(organization_id, turn_id) as scope:
        turn = scope.turn
        if turn.state not in (TurnState.QUEUED, TurnState.RUNNING):
            return None
        allowed = scope.context.has_permission(ASSISTANT_USE) and (
            decide_feature(TEXT_FEATURE, operation=FeatureOperation.WRITE).allowed
        )
        if not allowed:
            _finish(scope, TurnState.FAILED, FAILURE_REVOKED)
            return None
        if turn.steps_used >= _step_limit(scope.conversation):
            _finish(scope, TurnState.FAILED, FAILURE_STEP_LIMIT)
            return None
        turn.state = TurnState.RUNNING
        turn.steps_used += 1
        turn.save(update_fields=["state", "steps_used", "updated_at"])
        return _request(scope)


def _step_limit(conversation: AssistantConversation) -> int:
    setting_up = conversation.kind == ConversationKind.SETUP
    return int(platform_setting((SETUP_STEPS_PER_TURN if setting_up else STEPS_PER_TURN).key))


def _rows(conversation_id: UUID) -> list[AssistantMessage]:
    return list(
        AssistantMessage.all_objects.filter(conversation_id=conversation_id).order_by("index")
    )


def offered_tools(context: TenantContext, rows: Sequence[AssistantMessage]) -> list[Any]:
    """The registry's tools an ordinary conversation is offered now: those of
    the areas its messages and its calls have touched (`topics.select`)."""
    events: list[Sequence[str]] = []
    for row in rows:
        if row.role == MessageRole.USER:
            events.append(topics.said(row.content))
        elif row.role == MessageRole.ASSISTANT:
            events.extend(
                topics.called(call["name"], call["arguments_json"]) for call in row.tool_calls
            )
    return topics.select(command_tools(context), events)


def _request(scope: _Scope) -> ModelRequest:
    conversation = scope.conversation
    rows = _rows(conversation.id)
    # A conversation that sets the company up gets its own three tools and no
    # command of the registry (ADR-076, A3-2): the plan is the configurator's.
    setting_up = conversation.kind == ConversationKind.SETUP
    tools = tuple(
        ToolSpec(
            name=tool["name"], description=tool["description"], input_schema=tool["input_schema"]
        )
        for tool in (setup.TOOLS if setting_up else offered_tools(scope.context, rows))
    )
    return ModelRequest(
        task=TASK,
        messages=(
            Message(
                role="system",
                content=system_prompt(language=conversation.language, setup=setting_up),
                cache=True,
            ),
            *cached_tail(_messages(rows)),
        ),
        prompt_id=SETUP_PROMPT_ID if setting_up else PROMPT_ID,
        prompt_version=SETUP_PROMPT_VERSION if setting_up else PROMPT_VERSION,
        context=ModelContext(
            organization_id=scope.context.organization_id,
            actor_id=scope.context.actor_id,
            conversation_id=conversation.id,
            purpose="eval" if _is_proof(conversation) else None,
        ),
        # What a person types and what their tools return is theirs: the
        # registry lets no command return a health field (ADR-076 §1).
        data_class="personal",
        tools=tools,
        cache_tools=True,
        reference=conversation_ref(conversation.id),
    )


def _is_proof(conversation: AssistantConversation) -> bool:
    """Whether the conversation is a proof's: its person is one of the accounts
    the stack names in `ASSISTANT_PROOF_ACCOUNTS`. Its calls are then counted
    with the evals — against the monthly ceilings only, and in no person's or
    company's day. Off unless a local stack names an account; a stack served
    over https names none (`checks.py`)."""
    accounts = proof_accounts()
    if not accounts:
        return False
    email = (
        get_user_model()
        .objects.filter(pk=conversation.created_by_id)
        .values_list("email", flat=True)
        .first()
    )
    return (email or "").strip().lower() in accounts


def proof_accounts() -> frozenset[str]:
    if settings.PUBLIC_SITE_SCHEME == "https":
        return frozenset()
    return frozenset(settings.ASSISTANT_PROOF_ACCOUNTS)


def cached_tail(messages: Sequence[Message]) -> tuple[Message, ...]:
    """The transcript with its last message marked for the provider's cache:
    the next call reads everything up to it at a tenth of the price instead of
    paying for every earlier tool result again. One mark only — a provider
    takes four in a request, and the tools and the prompt have theirs."""
    if not messages:
        return ()
    return (*messages[:-1], replace(messages[-1], cache=True))


def transcript(conversation_id: UUID) -> tuple[Message, ...]:
    """The conversation as the model reads it, oldest first."""
    return _messages(_rows(conversation_id))


def _messages(rows: Sequence[AssistantMessage]) -> tuple[Message, ...]:
    messages: list[Message] = []
    for row in rows:
        if row.role == MessageRole.USER:
            # The time reaches the model with each message, so the system
            # prompt stays the same text for the whole conversation.
            stamp = row.created_at.strftime("%Y-%m-%d %H:%M")
            messages.append(Message(role="user", content=f"[{stamp}] {row.content}"))
        elif row.role == MessageRole.TOOL:
            messages.append(
                Message(role="tool", content=row.content, tool_call_id=row.tool_call_id)
            )
        else:
            messages.append(
                Message(
                    role="assistant",
                    content=row.content or None,
                    tool_calls=tuple(
                        ToolCall(
                            id=call["id"], name=call["name"], arguments_json=call["arguments_json"]
                        )
                        for call in row.tool_calls
                    ),
                    continuation=(
                        Continuation(
                            model=row.continuation["model"], state=row.continuation["state"]
                        )
                        if row.continuation
                        else None
                    ),
                )
            )
    return tuple(messages)


def _rewritten(
    organization_id: UUID, turn_id: UUID, request: ModelRequest, response: ModelResponse, form: str
) -> ModelResponse:
    """The answer written again without the verb form that has a gender — one
    more call, once. The first answer stands when the turn has no call left,
    the call fails or what comes back is not an answer in words."""
    with _scope(organization_id, turn_id) as scope:
        turn = scope.turn
        if turn.state != TurnState.RUNNING or turn.steps_used >= _step_limit(scope.conversation):
            return response
        turn.steps_used += 1
        turn.save(update_fields=["steps_used", "updated_at"])
    again = replace(request, messages=(*request.messages, *style.rewrite_messages(response, form)))
    try:
        second = complete(again)
    except ModelError:
        return response
    if second.tool_calls or not (second.text or "").strip():
        return response
    return second


def warning(plan: Plan, language: str) -> str:
    """What the server itself says beside a plan that holds a step nobody can
    take back: that it cannot be undone, and what it does — in the words of
    the step's preview, the ones its consent shows. Empty for any other plan."""
    lines: list[str] = []
    for group in plan.groups:
        for call in group.calls:
            if call.risk != "irreversible":
                continue
            effects = call.preview.effects if call.preview is not None else ()
            lines += [effect.summary[language] for effect in effects] or [
                f"{call.spec.title[language]}."
            ]
    return irreversible_words(lines, language)


def irreversible_words(lines: Sequence[str], language: str) -> str:
    if not lines:
        return ""
    return " ".join([IRREVERSIBLE[language][len(lines) > 1], *lines])


def _record_answer(organization_id: UUID, turn_id: UUID, response: ModelResponse) -> bool:
    """Records what the model answered and acts on it; False ends the loop."""
    with _scope(organization_id, turn_id) as scope:
        if scope.turn.state != TurnState.RUNNING:
            return False
        calls = _stepped(response.tool_calls)
        _append(
            scope,
            role=MessageRole.ASSISTANT,
            content=response.text or "",
            tool_calls=calls,
            continuation=_stored_continuation(response.continuation),
            usage_entry_id=response.usage_entry_id,
        )
        if not calls:
            _finish(scope, TurnState.DONE)
            return False
        if scope.conversation.kind == ConversationKind.SETUP:
            return _run_setup_calls(scope, calls)
        # The assistant's own tool for more tools is answered here; the rest
        # of the answer is the plan.
        asked = [call for call in calls if call["name"] == topics.MORE_TOOLS]
        if asked:
            available = command_tools(scope.context)
            for call in asked:
                _append_result(
                    scope,
                    call,
                    status="done",
                    output=topics.opened(call["arguments_json"], available),
                )
            calls = [call for call in calls if call["name"] != topics.MORE_TOOLS]
            if not calls:
                return True
        invocations = [
            Invocation(
                command=call["name"],
                arguments=json.loads(call["arguments_json"]),
                step_id=call["step_id"],
            )
            for call in calls
        ]
        # The people this conversation was told of: their handles resolve, and
        # the ones a command issues now are kept with its result.
        people = people_book(scope.conversation.id)
        with known_people(people):
            plan = offer_plan(invocations)
            results = [] if plan.refusals or plan.groups else execute_plan(invocations)
        if plan.refusals:
            refused = {refusal.step_id: refusal for refusal in plan.refusals}
            for call in calls:
                refusal = refused.get(call["step_id"])
                _append_result(
                    scope,
                    call,
                    status="refused" if refusal else "skipped",
                    code=refusal.code if refusal else "plan_not_run",
                    errors=refusal.errors if refusal else (),
                )
            return True
        if plan.groups:
            scope.turn.pending = {
                "calls": calls,
                "groups": [
                    {
                        "id": group.id,
                        "digest": group.digest,
                        "steps": [call.step_id for call in group.calls],
                    }
                    for group in plan.groups
                ],
                "said": warning(plan, scope.conversation.language),
            }
            scope.turn.state = TurnState.AWAITING_CONSENT
            scope.turn.save(update_fields=["pending", "state", "updated_at"])
            return False
        record_results(scope.turn, scope.conversation, calls, results, people=people)
        return True


def _run_setup_calls(scope: _Scope, calls: list[dict[str, Any]]) -> bool:
    """A setup conversation's calls, in the order the model made them: a note
    and a status are answered at once; the plan waits for the person, and what
    follows it in the same answer is not run. False ends the loop."""
    for position, call in enumerate(calls):
        try:
            waits = _run_setup_call(scope, call)
        except APIException as error:
            # Wrong notes, a profile too long, a permission taken away: said
            # to the model field by field, like a command's refusal.
            _append_result(
                scope,
                call,
                status="refused",
                code=problem_code(error),
                errors=tuple(
                    {key: entry.get(key) for key in ("field", "code", "message")}
                    for entry in problem_errors(error)
                ),
            )
            continue
        if waits:
            for later in calls[position + 1 :]:
                _append_result(scope, later, status="skipped", code="plan_not_run")
            return False
    return True


def _run_setup_call(scope: _Scope, call: Mapping[str, Any]) -> bool:
    """Runs one of the assistant's own tools; True when the turn now waits for
    the person's click on the configurator's plan."""
    name = call["name"]
    if name not in setup.TOOL_NAMES:
        # No command of the registry is reachable from here, whatever is named.
        _append_result(scope, call, status="refused", code="unknown_tool")
        return False
    if name == setup.PROFILE_NOTE:
        output = setup.note(
            json.loads(call["arguments_json"]),
            owner_words=owner_words(scope.conversation),
            key=f"note:{call['step_id']}",
        )
    elif name == setup.SETUP_STATUS:
        output = setup.status(scope.context, language=scope.conversation.language)
    else:
        steps = setup.planned(scope.context)
        plan = offer_plan(setup.invocations(steps)) if steps else None
        if plan is None:
            _append_result(
                scope, call, status="done", output={"steps": [], "note": "Nothing is ready."}
            )
            return False
        if plan.refusals:
            refusal = plan.refusals[0]
            _append_result(scope, call, status="refused", code=refusal.code, errors=refusal.errors)
            return False
        if plan.groups:
            scope.turn.pending = {
                "calls": [dict(call)],
                "steps": steps,
                "groups": [
                    {
                        "id": group.id,
                        "digest": group.digest,
                        "steps": [planned.step_id for planned in group.calls],
                    }
                    for group in plan.groups
                ],
                "said": warning(plan, scope.conversation.language),
            }
            scope.turn.state = TurnState.AWAITING_CONSENT
            scope.turn.save(update_fields=["pending", "state", "updated_at"])
            return True
        # The configurator plans writes only, and a write always takes a click.
        _append_result(scope, call, status="refused", code="plan_without_consent")
        return False
    _append_result(scope, call, status="done", output=output)
    return False


def owner_words(conversation: AssistantConversation) -> str:
    """Everything the person wrote in this conversation — the only thing a
    value can be the owner's own word for (ADR-076, A3-2 pkt 3)."""
    return "\n".join(
        AssistantMessage.all_objects.filter(
            conversation=conversation, role=MessageRole.USER
        ).values_list("content", flat=True)
    )


def record_plan(
    turn: AssistantTurn,
    conversation: AssistantConversation,
    call: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    results: Sequence[CallResult],
    said: str = "",
) -> None:
    """The configurator's plan after the person's click: one tool message for
    the one call that offered it, with every step's own result. A step that
    set an offer up is kept with the service it made (`made`): the notes'
    offer is then known by where it came from, whatever it is called later."""
    by_step = {result.step_id: result for result in results}
    done = all(by_step[step["step_id"]].status == "done" for step in steps)
    append_message(
        turn,
        conversation,
        role=MessageRole.TOOL,
        content=_json({
            "status": "done" if done else "failed",
            "output": {
                "steps": [
                    {
                        "step": step["ref"],
                        "status": by_step[step["step_id"]].status,
                        "error": by_step[step["step_id"]].code,
                    }
                    for step in steps
                ]
            },
        }),
        tool_call_id=call["id"],
        result={
            "step_id": call["step_id"],
            "command": "",
            "status": "done" if done else "failed",
            "code": "",
            "steps": [
                {
                    "step_id": step["step_id"],
                    "command": step["command"],
                    "status": by_step[step["step_id"]].status,
                    "code": by_step[step["step_id"]].code or "",
                    **_made(step, by_step[step["step_id"]]),
                }
                for step in steps
            ],
            **({"said": said} if said else {}),
        },
    )


def _made(step: Mapping[str, Any], result: CallResult) -> dict[str, Any]:
    """The service a done step of the notes' offer answered with, under the
    name it then had."""
    kind, _, key = str(step["ref"]).partition(":")
    output = result.output or {}
    if kind != "offer" or result.status != "done" or "service_id" not in output:
        return {}
    return {
        "made": {
            "offer": key,
            "service_id": str(output["service_id"]),
            "name": str(output.get("name") or ""),
        }
    }


def _record_invalid_calls(organization_id: UUID, turn_id: UUID, error: ModelError) -> bool:
    """Arguments outside a tool's schema: the answer goes back as it was, each
    call with what was wrong, and the model tries again (ADR-068)."""
    response = error.response
    assert response is not None
    with _scope(organization_id, turn_id) as scope:
        if scope.turn.state != TurnState.RUNNING:
            return False
        calls = _stepped(response.tool_calls)
        _append(
            scope,
            role=MessageRole.ASSISTANT,
            content=response.text or "",
            tool_calls=calls,
            continuation=_stored_continuation(response.continuation),
            usage_entry_id=error.usage_entry_id,
        )
        for call in calls:
            prefix = f"tool_calls.{call['id']}.arguments"
            errors = tuple(
                {
                    "field": item.field.removeprefix(prefix).lstrip(".") or None,
                    "code": item.code,
                    "message": item.message,
                }
                for item in error.errors
                if item.field.startswith(prefix)
            )
            _append_result(
                scope,
                call,
                status="refused" if errors else "skipped",
                code="command_args_invalid" if errors else "plan_not_run",
                errors=errors,
            )
        return True


def record_results(
    turn: AssistantTurn,
    conversation: AssistantConversation,
    calls: Sequence[Mapping[str, Any]],
    results: Sequence[CallResult],
    said: str = "",
    people: People | None = None,
) -> None:
    """Each step's result as the tool message that answers its call. `said`
    is the server's sentence the plan waited under: kept with its first call,
    so the conversation still shows it. `people` is the book the plan ran
    with: a result keeps the record of every handle it carries."""
    by_step = {result.step_id: result for result in results}
    for position, call in enumerate(calls):
        result = by_step[call["step_id"]]
        _write_result(
            turn,
            conversation,
            call,
            status=result.status,
            code=result.code,
            errors=result.errors,
            output=_lean(result.output),
            said="" if position else said,
            people=people,
        )


def close_open_calls(turn: AssistantTurn, conversation: AssistantConversation, code: str) -> None:
    """Answers the calls of a plan that will not run — declined, timed out —
    so the transcript stays one the model can be shown again."""
    pending = turn.pending or {}
    for position, call in enumerate(pending.get("calls", ())):
        _write_result(
            turn,
            conversation,
            call,
            status="declined",
            code=code,
            said="" if position else pending.get("said", ""),
        )
    turn.pending = None


def _stepped(tool_calls: Sequence[ToolCall]) -> list[dict[str, Any]]:
    """The model's calls, each with the step id the server gives it: the
    idempotency key and the receipt derive from that id, never from anything a
    model or a provider wrote (ADR-076 §3)."""
    calls = []
    for call in tool_calls:
        try:
            command = command_for_tool(call.name).key
        except UnknownCommand:
            command = ""
        calls.append({
            "id": call.id,
            "name": call.name,
            "arguments_json": call.arguments_json,
            "step_id": str(uuid.uuid4()),
            "command": command,
        })
    return calls


def _stored_continuation(continuation: Continuation | None) -> dict[str, Any] | None:
    if continuation is None:
        return None
    return {"model": continuation.model, "state": continuation.state}


def _append(scope: _Scope, **fields: Any) -> AssistantMessage:
    return append_message(scope.turn, scope.conversation, **fields)


def append_message(
    turn: AssistantTurn, conversation: AssistantConversation, **fields: Any
) -> AssistantMessage:
    # The base manager: a turn is also closed with no person to act as
    # (`fail_without_person`); the tenant is set either way.
    last = AssistantMessage.all_objects.filter(conversation=conversation).aggregate(
        last=Max("index")
    )
    return AssistantMessage.all_objects.create(
        organization_id=conversation.organization_id,
        conversation=conversation,
        turn=turn,
        index=(last["last"] or 0) + 1,
        **fields,
    )


def _append_result(scope: _Scope, call: Mapping[str, Any], **outcome: Any) -> None:
    _write_result(scope.turn, scope.conversation, call, **outcome)


def _write_result(
    turn: AssistantTurn,
    conversation: AssistantConversation,
    call: Mapping[str, Any],
    *,
    status: str,
    code: str | None = None,
    errors: Sequence[Mapping[str, str | None]] = (),
    output: Mapping[str, Any] | None = None,
    said: str = "",
    people: People | None = None,
) -> None:
    content = _tool_content(status, code, errors, output)
    # Beside the result, never in it: which record each handle the model now
    # reads stands for. The panel makes the cards from these.
    book = people or {}
    carried = {
        handle: [book[handle][0], str(book[handle][1])] for handle in handles_in(content, book)
    }
    append_message(
        turn,
        conversation,
        role=MessageRole.TOOL,
        content=content,
        tool_call_id=call["id"],
        result={
            "step_id": call["step_id"],
            "command": call["command"],
            "status": status,
            "code": code or "",
            **({"said": said} if said else {}),
            **({"people": carried} if carried else {}),
        },
    )


def _lean(output: Any) -> Any:
    """A command's output without the fields that say nothing: a null is
    „not set”, and a company's setup has hundreds. Every later call of the
    model pays for the transcript again."""
    if isinstance(output, Mapping):
        return {key: _lean(value) for key, value in output.items() if value is not None}
    if isinstance(output, list | tuple):
        return [_lean(item) for item in output]
    return output


def _tool_content(
    status: str,
    code: str | None,
    errors: Sequence[Mapping[str, str | None]],
    output: Mapping[str, Any] | None,
) -> str:
    if status == "done":
        content = _json({"status": "done", "output": output or {}})
        if len(content) <= MAX_TOOL_RESULT_CHARACTERS:
            return content
        code, errors = "output_too_large", ()
    return _json({"status": status, "error": {"code": code or status, "errors": list(errors)}})


def _json(value: Any) -> str:
    # Without the spaces json puts after every comma and colon: the model
    # reads it the same and pays for less.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _failure_code(error: ModelError) -> str:
    if error.kind == "budget":
        return (
            FAILURE_BUDGET_CONVERSATION if error.code == "conversation_budget" else FAILURE_BUDGET
        )
    if error.kind == "refused":
        return FAILURE_REFUSED
    return FAILURE_UNAVAILABLE


def _fail(organization_id: UUID, turn_id: UUID, code: str) -> None:
    try:
        with _scope(organization_id, turn_id) as scope:
            if scope.turn.state in (TurnState.QUEUED, TurnState.RUNNING):
                _finish(scope, TurnState.FAILED, code)
    except _Stop:
        return
    except InvalidTenantTaskContext:
        # The person is gone from the company: no context to act in, so the
        # turn is closed by its organization alone and its hold expires.
        fail_without_person(organization_id, turn_id, code)


def fail_without_person(organization_id: UUID, turn_id: UUID, code: str) -> None:
    with transaction.atomic():
        set_local_organization_id(organization_id)
        turn = (
            AssistantTurn.all_objects.select_for_update()
            .select_related("conversation")
            .filter(pk=turn_id, organization_id=organization_id)
            .exclude(state__in=[TurnState.DONE, TurnState.FAILED])
            .first()
        )
        if turn is None:
            return
        close_open_calls(turn, turn.conversation, code)
        turn.state = TurnState.FAILED
        turn.failure_code = code
        turn.finished_at = timezone.now()
        turn.save(update_fields=["pending", "state", "failure_code", "finished_at", "updated_at"])


def _finish(scope: _Scope, state: str, code: str = "") -> None:
    """Ends the turn and settles its credit: spent for an answer, given back
    for a failure."""
    turn = scope.turn
    close_open_calls(turn, scope.conversation, code or "turn_ended")
    turn.state = state
    turn.failure_code = code
    turn.finished_at = timezone.now()
    turn.save(update_fields=["pending", "state", "failure_code", "finished_at", "updated_at"])
    if turn.credit_reservation_key:
        if state == TurnState.DONE:
            commit_credits(turn.credit_reservation_key)
        else:
            release_credits(turn.credit_reservation_key)
    AssistantConversation.all_objects.filter(pk=scope.conversation.pk).update(
        updated_at=timezone.now()
    )
