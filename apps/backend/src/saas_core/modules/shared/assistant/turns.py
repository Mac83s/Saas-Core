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
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.http.exceptions import problem_code, problem_errors
from saas_core.modules.core.organizations.api import (
    CallResult,
    Invocation,
    UnknownCommand,
    command_for_tool,
    command_tools,
    execute_plan,
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

from . import setup
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
from .settings_spec import STEPS_PER_TURN

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


class _Stop(Exception):
    """The turn is gone. Raised only where nothing was written: an exception
    leaving `_scope` rolls its transaction back."""


@dataclass(frozen=True, slots=True)
class _Scope:
    context: TenantContext
    turn: AssistantTurn
    conversation: AssistantConversation


def conversation_ref(conversation_id: UUID) -> str:
    return f"conversation:{conversation_id}"


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
        if turn.steps_used >= int(platform_setting(STEPS_PER_TURN.key)):
            _finish(scope, TurnState.FAILED, FAILURE_STEP_LIMIT)
            return None
        turn.state = TurnState.RUNNING
        turn.steps_used += 1
        turn.save(update_fields=["state", "steps_used", "updated_at"])
        return _request(scope)


def _request(scope: _Scope) -> ModelRequest:
    conversation = scope.conversation
    # A conversation that sets the company up gets its own three tools and no
    # command of the registry (ADR-076, A3-2): the plan is the configurator's.
    setting_up = conversation.kind == ConversationKind.SETUP
    tools = tuple(
        ToolSpec(
            name=tool["name"], description=tool["description"], input_schema=tool["input_schema"]
        )
        for tool in (setup.TOOLS if setting_up else command_tools(scope.context))
    )
    return ModelRequest(
        task=TASK,
        messages=(
            Message(
                role="system",
                content=system_prompt(language=conversation.language, setup=setting_up),
                cache=True,
            ),
            *transcript(conversation.id),
        ),
        prompt_id=SETUP_PROMPT_ID if setting_up else PROMPT_ID,
        prompt_version=SETUP_PROMPT_VERSION if setting_up else PROMPT_VERSION,
        context=ModelContext(
            organization_id=scope.context.organization_id,
            actor_id=scope.context.actor_id,
            conversation_id=conversation.id,
        ),
        # What a person types and what their tools return is theirs: the
        # registry lets no command return a health field (ADR-076 §1).
        data_class="personal",
        tools=tools,
        cache_tools=True,
        reference=conversation_ref(conversation.id),
    )


def transcript(conversation_id: UUID) -> tuple[Message, ...]:
    """The conversation as the model reads it, oldest first."""
    messages: list[Message] = []
    rows = AssistantMessage.all_objects.filter(conversation_id=conversation_id).order_by("index")
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
        invocations = [
            Invocation(
                command=call["name"],
                arguments=json.loads(call["arguments_json"]),
                step_id=call["step_id"],
            )
            for call in calls
        ]
        plan = offer_plan(invocations)
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
            }
            scope.turn.state = TurnState.AWAITING_CONSENT
            scope.turn.save(update_fields=["pending", "state", "updated_at"])
            return False
        record_results(scope.turn, scope.conversation, calls, execute_plan(invocations))
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
) -> None:
    """The configurator's plan after the person's click: one tool message for
    the one call that offered it, with every step's own result."""
    by_step = {result.step_id: result for result in results}
    done = all(by_step[step["step_id"]].status == "done" for step in steps)
    append_message(
        turn,
        conversation,
        role=MessageRole.TOOL,
        content=json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
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
                }
                for step in steps
            ],
        },
    )


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
) -> None:
    """Each step's result as the tool message that answers its call."""
    by_step = {result.step_id: result for result in results}
    for call in calls:
        result = by_step[call["step_id"]]
        _write_result(
            turn,
            conversation,
            call,
            status=result.status,
            code=result.code,
            errors=result.errors,
            output=result.output,
        )


def close_open_calls(turn: AssistantTurn, conversation: AssistantConversation, code: str) -> None:
    """Answers the calls of a plan that will not run — declined, timed out —
    so the transcript stays one the model can be shown again."""
    pending = turn.pending or {}
    for call in pending.get("calls", ()):
        _write_result(turn, conversation, call, status="declined", code=code)
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
) -> None:
    append_message(
        turn,
        conversation,
        role=MessageRole.TOOL,
        content=_tool_content(status, code, errors, output),
        tool_call_id=call["id"],
        result={
            "step_id": call["step_id"],
            "command": call["command"],
            "status": status,
            "code": code or "",
        },
    )


def _tool_content(
    status: str,
    code: str | None,
    errors: Sequence[Mapping[str, str | None]],
    output: Mapping[str, Any] | None,
) -> str:
    if status == "done":
        content = json.dumps({"status": "done", "output": output or {}}, ensure_ascii=False)
        if len(content) <= MAX_TOOL_RESULT_CHARACTERS:
            return content
        code, errors = "output_too_large", ()
    return json.dumps(
        {"status": status, "error": {"code": code or status, "errors": list(errors)}},
        ensure_ascii=False,
    )


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
