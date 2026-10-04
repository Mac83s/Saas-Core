"""Admission against the ceilings, before every call (ADR-068 pkt 7).

One short transaction on the port's own database alias, under one advisory
lock: sum, check, write the reservation. Two processes never take the same
last dollar, and the reservation is visible to every other process at once
because it does not wait for the caller's request to commit. Sums count every
admitted, running and finished call at its cost or — while unknown — at its
estimate. Day and month are UTC.

Order, the first failure decides: the estimate fits every hard ceiling at all
→ platform month → pool month with the assistant's reserve → pool day → task
day → company → conversation → person. Calls for evals and probes check only
the monthly ceilings — and are counted only in them: a ceiling such a call is
not held to is not used up by it either, so an eval or a proof never takes a
person's, a company's or the pool's day away from customers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import connections, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce

from .budgets import Budgets, current_budgets, micros
from .models import COUNTED_STATES, EntryKind, EntryState, UsageEntry
from .types import Admission, ModelContext, TaskSpec

#: How long a company counts as waiting for its share of a pool.
WAITING_WINDOW = timedelta(minutes=5)
SHARE_RETRY = timedelta(minutes=5)
_LOCK = "model_port_admission"
#: Purposes held to the monthly ceilings only, and counted only in them.
MONTHLY_ONLY = ("eval", "probe")


@dataclass(frozen=True, slots=True)
class Ask:
    spec: TaskSpec
    context: ModelContext
    purpose: str
    estimate_usd_micros: int
    model: str
    data_class: str
    prompt_id: str = ""
    prompt_version: str = ""
    reference: str = ""
    resend_of: UUID | None = None


def alias() -> str:
    return str(settings.MODEL_PORT_DATABASE_ALIAS)


def now() -> datetime:
    return datetime.now(UTC)


def _day_start(at: datetime) -> datetime:
    return at.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(at: datetime) -> datetime:
    return _day_start(at).replace(day=1)


def _next_day(at: datetime) -> datetime:
    return _day_start(at) + timedelta(days=1)


def _next_month(at: datetime) -> datetime:
    start = _month_start(at)
    return (start + timedelta(days=32)).replace(day=1)


def _spent(*, apart: bool = False, **filters: Any) -> int:
    """`apart` leaves out the calls counted only in the months (evals, probes)."""
    rows = UsageEntry.objects.using(alias()).filter(
        kind=EntryKind.CALL, state__in=COUNTED_STATES, **filters
    )
    if apart:
        rows = rows.exclude(purpose__in=MONTHLY_ONLY)
    total = rows.aggregate(total=Sum(Coalesce(F("cost_usd_micros"), F("estimate_usd_micros"))))[
        "total"
    ]
    return int(total or 0)


def admit(ask: Ask) -> tuple[Admission, UsageEntry | None]:
    """Reserve the estimate, or say when it may be tried again and why not."""
    budgets = current_budgets()
    at = now()
    with transaction.atomic(using=alias()):
        with connections[alias()].cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_LOCK])
        refusal = _refusal(ask, budgets, at)
        if refusal is not None:
            return refusal, None
        entry = UsageEntry.objects.using(alias()).create(
            kind=EntryKind.CALL,
            state=EntryState.ADMITTED,
            task=ask.spec.key,
            pool=ask.spec.pool,
            adapter=ask.spec.adapter,
            requested_model=ask.model,
            organization_id=ask.context.organization_id,
            actor_id=ask.context.actor_id,
            conversation_id=ask.context.conversation_id,
            purpose=ask.purpose,
            prompt_id=ask.prompt_id,
            prompt_version=ask.prompt_version,
            data_class=ask.data_class,
            reference=ask.reference,
            resend_of=ask.resend_of,
            estimate_usd_micros=ask.estimate_usd_micros,
            expires_at=at + ask.spec.admission_ttl,
        )
    return (
        Admission(decision="granted", id=entry.id, expires_at=entry.expires_at),
        entry,
    )


def _refusal(ask: Ask, budgets: Budgets, at: datetime) -> Admission | None:
    spec, context, estimate = ask.spec, ask.context, ask.estimate_usd_micros
    pool = spec.pool
    month, day = _month_start(at), _day_start(at)
    monthly_only = ask.purpose in MONTHLY_ONLY

    hard = [micros(budgets.platform_month)]
    if pool == "translation":
        hard += [micros(budgets.translation_month)]
        if not monthly_only:
            hard += [micros(budgets.translation_day)]
    if pool == "assistant" and not monthly_only:
        hard += [
            micros(budgets.assistant_day),
            micros(budgets.assistant_org_day),
            micros(budgets.assistant_conversation),
            micros(budgets.assistant_person_day),
        ]
    if spec.daily_cap_usd is not None and not monthly_only:
        hard.append(micros(spec.daily_cap_usd))
    if estimate > min(hard):
        return Admission(decision="denied", reason="estimate_exceeds_ceiling")

    platform = _spent(created_at__gte=month)
    if platform + estimate > micros(budgets.platform_month):
        return Admission(decision="deferred", reason="platform_month", until=_next_month(at))
    if pool != "assistant":
        assistant_month = _spent(pool="assistant", created_at__gte=month)
        reserve_left = max(0, micros(budgets.assistant_reserve_month) - assistant_month)
        if platform + estimate > micros(budgets.platform_month) - reserve_left:
            return Admission(decision="deferred", reason="assistant_reserve", until=_next_month(at))
    if pool == "translation" and _spent(pool=pool, created_at__gte=month) + estimate > micros(
        budgets.translation_month
    ):
        return Admission(decision="deferred", reason="pool_month", until=_next_month(at))
    if monthly_only:
        return None

    pool_day_cap = micros(
        budgets.translation_day if pool == "translation" else budgets.assistant_day
    )
    if _spent(apart=True, pool=pool, created_at__gte=day) + estimate > pool_day_cap:
        return Admission(decision="deferred", reason="pool_day", until=_next_day(at))
    if spec.daily_cap_usd is not None and _spent(
        apart=True, task=spec.key, created_at__gte=day
    ) + estimate > micros(spec.daily_cap_usd):
        return Admission(decision="deferred", reason="task_day", until=_next_day(at))

    if pool == "translation" and context.organization_id is not None:
        company = _spent(
            apart=True, pool=pool, organization_id=context.organization_id, created_at__gte=day
        )
        within = company + estimate <= int(pool_day_cap * budgets.translation_org_share)
        others = _note_asking(pool, context.organization_id, within, at)
        if not within and others:
            return Admission(decision="deferred", reason="company_share", until=at + SHARE_RETRY)
    if pool == "assistant":
        if context.organization_id is not None and _spent(
            apart=True, pool=pool, organization_id=context.organization_id, created_at__gte=day
        ) + estimate > micros(budgets.assistant_org_day):
            return Admission(decision="deferred", reason="company_day", until=_next_day(at))
        if context.conversation_id is not None and _spent(
            apart=True, pool=pool, conversation_id=context.conversation_id
        ) + estimate > micros(budgets.assistant_conversation):
            return Admission(decision="denied", reason="conversation_budget")
        if context.actor_id is not None and _spent(
            apart=True, pool=pool, actor_id=context.actor_id, created_at__gte=day
        ) + estimate > micros(budgets.assistant_person_day):
            return Admission(decision="deferred", reason="person_day", until=_next_day(at))
    return None


def _note_asking(pool: str, organization_id: UUID, within_share: bool, at: datetime) -> bool:
    """Records this company's ask and says whether another company within its share
    asked in the last five minutes. Runs under the admission lock, so the
    read-modify-write cannot interleave; losing the cache only weakens fairness —
    the ceilings themselves are summed from the database."""
    key = f"model_port:asking:{pool}"
    asking: dict[str, tuple[str, bool]] = cache.get(key) or {}
    horizon = at - WAITING_WINDOW
    asking = {
        org: (stamp, within)
        for org, (stamp, within) in asking.items()
        if datetime.fromisoformat(stamp) > horizon
    }
    others = any(within for org, (_stamp, within) in asking.items() if org != str(organization_id))
    asking[str(organization_id)] = (at.isoformat(), within_share)
    cache.set(key, asking, int(WAITING_WINDOW.total_seconds()) * 2)
    return others


def use_reservation(admission_id: UUID, ask: Ask) -> UsageEntry | None:
    """The reservation `admission_id` names, still valid for this ask, or None when
    it expired, was used or released — then the call is admitted afresh."""
    entry = UsageEntry.objects.using(alias()).filter(pk=admission_id).first()
    if entry is None:
        return None
    if (
        entry.task != ask.spec.key
        or entry.organization_id != ask.context.organization_id
        or entry.actor_id != ask.context.actor_id
        or entry.conversation_id != ask.context.conversation_id
    ):
        from .types import ModelError

        raise ModelError("invalid_request", "admission_mismatch")
    if entry.state != EntryState.ADMITTED or (entry.expires_at and entry.expires_at <= now()):
        return None
    if ask.estimate_usd_micros > entry.estimate_usd_micros:
        # Only the overrun needs room: checked under the same lock, and the
        # reservation grows to the new estimate instead of a second row.
        overrun = replace(
            ask, estimate_usd_micros=ask.estimate_usd_micros - entry.estimate_usd_micros
        )
        with transaction.atomic(using=alias()):
            with connections[alias()].cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [_LOCK])
            if _refusal(overrun, current_budgets(), now()) is not None:
                return None
            UsageEntry.objects.using(alias()).filter(pk=entry.id, state=EntryState.ADMITTED).update(
                estimate_usd_micros=ask.estimate_usd_micros
            )
    return entry


def release(admission_id: UUID) -> None:
    UsageEntry.objects.using(alias()).filter(pk=admission_id, state=EntryState.ADMITTED).update(
        state=EntryState.EXPIRED, finished_at=now()
    )


def sweep(at: datetime | None = None) -> tuple[int, int]:
    """Expires reservations past their time and turns calls stuck in `calling`
    past their task's limit into unknown outcomes. Returns both counts."""
    at = at or now()
    expired = (
        UsageEntry.objects.using(alias())
        .filter(state=EntryState.ADMITTED, expires_at__lte=at)
        .update(state=EntryState.EXPIRED, finished_at=at)
    )
    stuck = (
        UsageEntry.objects.using(alias())
        .filter(state=EntryState.CALLING)
        .filter(Q(expires_at__lte=at))
        .update(
            state=EntryState.DONE,
            outcome="unknown_outcome",
            error_code="call_abandoned",
            finished_at=at,
        )
    )
    return expired, stuck
