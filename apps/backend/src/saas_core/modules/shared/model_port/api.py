"""Public use-case API of the model port (ADR-068, docs/architecture/model-port.md).

The only surface other modules import. Translations and the assistant call
`complete`; consumers that queue work admit it first; products add tasks.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from . import admission
from .budgets import current_budgets, micros
from .matrix import model_profile
from .models import EntryKind, EntryState, UsageEntry
from .registry import register_task, task_spec
from .service import complete, estimate, highest_data_class
from .state import active_block
from .test_double import routed
from .types import (
    Admission,
    BudgetLevel,
    BudgetState,
    Continuation,
    FieldError,
    JsonSchemaFormat,
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    ModelResponse,
    NamedTool,
    TaskSpec,
    TaskStatus,
    ToolCall,
    ToolSpec,
    Usage,
)


def admit(task: str, estimate_usd_micros: int, context: ModelContext) -> Admission:
    """Reserve room under the ceilings for a call to come, e.g. in a worker after
    taking a lease; `complete` with the returned id uses the reservation."""
    spec = task_spec(task)
    if spec is None:
        raise ModelError("invalid_request", "task_unknown")
    purpose = context.purpose or "customer"
    verdict, _entry = admission.admit(
        admission.Ask(
            spec=spec,
            context=context,
            purpose=purpose,
            estimate_usd_micros=estimate_usd_micros,
            model=spec.model,
            data_class="",
        )
    )
    return verdict


def release(admission_id: UUID) -> None:
    admission.release(admission_id)


def task_status(task: str, context: ModelContext | None = None) -> TaskStatus:
    """Whether the task can be called now, why not, and what its model can do.

    With a context, as that company calls it: a browser test's company on a
    local stack is answered by the stand-in, whatever the real provider does."""
    spec = task_spec(task)
    if spec is None:
        raise ModelError("invalid_request", "task_unknown")
    if context is not None:
        spec = routed(spec, context.organization_id)
    profile = model_profile(spec.adapter, spec.model) if spec.model else None
    reason: str | None = None
    until = None
    if not spec.enabled:
        reason = "task_disabled"
    elif profile is None:
        reason = "model_not_selected" if not spec.model else "model_not_allowed"
    elif profile.probed is None:
        reason = "model_not_allowed"
    else:
        block = active_block(profile.adapter, spec.key, profile.model)
        if block is not None:
            until, _kind, reason = block
    return TaskStatus(
        task=spec.key,
        available=reason is None,
        reason=reason,
        until=until,
        model=spec.model,
        capabilities=profile.capabilities if profile else frozenset(),
    )


def budget_state(task: str, context: ModelContext) -> BudgetState:
    """What is spent and what is allowed at each level that applies to this task."""
    spec = task_spec(task)
    if spec is None:
        raise ModelError("invalid_request", "task_unknown")
    budgets = current_budgets()
    at = admission.now()
    month = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    levels = [
        BudgetLevel(
            "platform_month",
            admission._spent(created_at__gte=month),
            micros(budgets.platform_month),
        ),
    ]
    if spec.pool == "translation":
        levels += [
            BudgetLevel(
                "pool_month",
                admission._spent(pool=spec.pool, created_at__gte=month),
                micros(budgets.translation_month),
            ),
            BudgetLevel(
                "pool_day",
                admission._spent(apart=True, pool=spec.pool, created_at__gte=day),
                micros(budgets.translation_day),
            ),
        ]
    else:
        levels += [
            BudgetLevel(
                "pool_day",
                admission._spent(apart=True, pool=spec.pool, created_at__gte=day),
                micros(budgets.assistant_day),
            ),
        ]
        if context.organization_id is not None:
            levels.append(
                BudgetLevel(
                    "company_day",
                    admission._spent(
                        apart=True,
                        pool=spec.pool,
                        organization_id=context.organization_id,
                        created_at__gte=day,
                    ),
                    micros(budgets.assistant_org_day),
                )
            )
        if context.conversation_id is not None:
            levels.append(
                BudgetLevel(
                    "conversation",
                    admission._spent(
                        apart=True, pool=spec.pool, conversation_id=context.conversation_id
                    ),
                    micros(budgets.assistant_conversation),
                )
            )
        if context.actor_id is not None:
            levels.append(
                BudgetLevel(
                    "person_day",
                    admission._spent(
                        apart=True, pool=spec.pool, actor_id=context.actor_id, created_at__gte=day
                    ),
                    micros(budgets.assistant_person_day),
                )
            )
    return BudgetState(task=spec.key, levels=tuple(levels))


def record_settlement(
    task: str,
    context: ModelContext,
    *,
    reference: str,
    credits: int,
    units: int,
    unit: str,
) -> None:
    """A consumer's billing next to the cost, for the margin; not counted to ceilings."""
    spec = task_spec(task)
    if spec is None:
        raise ModelError("invalid_request", "task_unknown")
    UsageEntry.objects.using(admission.alias()).create(
        kind=EntryKind.SETTLEMENT,
        state=EntryState.DONE,
        task=spec.key,
        pool=spec.pool,
        organization_id=context.organization_id,
        actor_id=context.actor_id,
        purpose=context.purpose or "customer",
        reference=reference[:120],
        credits=credits,
        units=units,
        unit=unit[:40],
        outcome="ok",
        finished_at=admission.now() + timedelta(0),
    )


__all__ = [
    "Admission",
    "BudgetLevel",
    "BudgetState",
    "Continuation",
    "FieldError",
    "JsonSchemaFormat",
    "Message",
    "ModelContext",
    "ModelError",
    "ModelRequest",
    "ModelResponse",
    "NamedTool",
    "TaskSpec",
    "TaskStatus",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "admit",
    "budget_state",
    "complete",
    "estimate",
    "highest_data_class",
    "record_settlement",
    "register_task",
    "release",
    "task_status",
]
