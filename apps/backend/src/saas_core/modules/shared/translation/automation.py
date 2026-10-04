"""Automatic jobs from the demand that is due (TL21b, translation-sources.md §8.3).

Once a minute each company's due demand becomes at most one job, quoted and
held exactly like a click, as the person who consented to the automation and
acting through it. The consent is checked now, not when it was given: the
person must still be an active member allowed to manage translations, and the
source must let them publish. Only objects with a public surface are planned,
and only into languages already live in their scope (ADR-070 pkt 7): adding a
language stays a person's act.

What cannot start waits with a reason until `check_at`: the month's limit of
the automation until the next month, the rest an hour. A pair already in a
running job waits for it; a demand with nothing left to send is dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.content_protocol.registry import translation_source
from saas_core.content_protocol.sources import ObjectRef, TranslationSource
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import is_platform_workspace
from saas_core.modules.shared.billing.api import CreditsExhausted

from .jobs import (
    EXCLUDED_IN_PROGRESS,
    TargetRequest,
    TranslationUnavailable,
    _create_job,
    build_job_quote,
)
from .models import DemandState, TranslationDemand, TranslationJobPart, TranslationSettings
from .notify import notify_automation_paused
from .permissions import TRANSLATION_MANAGE, TRANSLATION_REQUEST
from .services import settings_state, translation_offer
from .settings_spec import AUTO_CHANGES, AUTO_MONTHLY_LIMIT, demand_wait
from .worker import person_context

logger = logging.getLogger(__name__)

#: Objects one company's tick plans; the rest waits for the next minute.
MAX_OBJECTS = 200
#: How long a blocked demand waits before it is tried again (not the limit).
BLOCKED_RETRY = timedelta(hours=1)

CONSENT_LOST = "consent_lost"
PUBLISH_DENIED = "publish_denied"
MONTHLY_LIMIT = "monthly_limit"
CREDITS_EXHAUSTED = "credits_exhausted"


class Blocked(Exception):
    """The due demand cannot start now: it waits with the reason until `check_at`."""

    def __init__(self, reason: str, check_at: datetime) -> None:
        super().__init__(reason)
        self.reason = reason
        self.check_at = check_at


def _month_start(now: datetime) -> datetime:
    local = timezone.localtime(now)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: datetime) -> datetime:
    start = _month_start(now)
    return (start + timedelta(days=32)).replace(day=1)


def automatic_credits_this_month(organization_id: UUID, now: datetime) -> int:
    """Credits the automation spent or holds this month: settled parts at what
    they cost, running ones at their hold."""
    parts = TranslationJobPart.all_objects.filter(
        organization_id=organization_id,
        job__trigger="automatic",
        job__created_at__gte=_month_start(now),
    )
    settled = parts.filter(settled_at__isnull=False).aggregate(total=Sum("settled_credits"))[
        "total"
    ]
    held = sum(
        units * (unit_cost or 0)
        for units, unit_cost in parts.filter(
            settled_at__isnull=True, reservation_key__gt=""
        ).values_list("units", "job__unit_cost")
    )
    return int(settled or 0) + held


def automation_reading(
    organization_id: UUID, consent_membership_id: UUID | None, now: datetime | None = None
) -> dict[str, Any]:
    """What a reader of the settings sees beside the switch: whether the
    consent still holds — the check a run makes — and what the monthly limit
    is measured against, with when the count starts anew."""
    now = now or timezone.now()
    return {
        "consent_holds": consent_membership_id is not None
        and person_context(
            organization_id, consent_membership_id, TRANSLATION_MANAGE, TRANSLATION_REQUEST
        )
        is not None,
        "month_credits": automatic_credits_this_month(organization_id, now),
        "month_resets_at": _next_month(now),
    }


def run_due_demand() -> int:
    """Each company with due demand: one job at most. Returns the jobs started."""
    from saas_core.modules.shared.billing.api import billing_organization_ids  # noqa: PLC0415

    started = 0
    for organization_id in billing_organization_ids():
        try:
            if start_due_demand(organization_id) is not None:
                started += 1
        except Exception:
            logger.exception(
                "translation_demand_failed", extra={"organization_id": str(organization_id)}
            )
    return started


def start_due_demand(organization_id: UUID, now: datetime | None = None) -> UUID | None:
    now = now or timezone.now()
    with transaction.atomic():
        set_local_organization_id(organization_id)
        rows = list(
            TranslationDemand.all_objects.select_for_update(skip_locked=True)
            .filter(organization_id=organization_id, due_at__lte=now)
            .filter(Q(state=DemandState.WAITING) | Q(state=DemandState.BLOCKED, check_at__lte=now))
            .order_by("due_at", "id")[:MAX_OBJECTS]
        )
        if not rows:
            return None
        try:
            job_id = _start(organization_id, rows, now)
        except Blocked as blocked:
            TranslationDemand.all_objects.filter(pk__in=[row.pk for row in rows]).update(
                state=DemandState.BLOCKED, reason=blocked.reason, check_at=blocked.check_at
            )
            local = timezone.localtime(now)
            notify_automation_paused(
                organization_id,
                reason=blocked.reason,
                period=local.strftime("%Y-%m" if blocked.reason == MONTHLY_LIMIT else "%Y-%m-%d"),
            )
            return None
    if job_id is not None:
        from .tasks import enqueue_job  # noqa: PLC0415

        enqueue_job(organization_id, job_id)
    return job_id


def _automation_context(
    organization_id: UUID, rows: Sequence[TranslationDemand], job_id: UUID
) -> TenantContext | None:
    """The consenting person acting through the job about to start, or None
    when the automation is off (the demand is dropped). A consent the person
    can no longer give blocks it."""
    row = TranslationSettings.all_objects.filter(organization_id=organization_id).first()
    if row is None or row.auto_consent_membership_id is None:
        return None
    if not settings_state(organization_id)["values"][AUTO_CHANGES.key]["effective"]:
        return None
    person = person_context(
        organization_id, row.auto_consent_membership_id, TRANSLATION_MANAGE, TRANSLATION_REQUEST
    )
    if person is None:
        raise Blocked(CONSENT_LOST, timezone.now() + BLOCKED_RETRY)
    return acting_context(
        person,
        via="ai_translation",
        ref=f"translation_job:{job_id}",
        trigger=f"schedule:{rows[0].id}",
    )


def _start(organization_id: UUID, rows: list[TranslationDemand], now: datetime) -> UUID | None:
    job_id = uuid7()
    context = _automation_context(organization_id, rows, job_id)
    if context is None:
        _drop(rows)
        return None
    with activate_tenant_context(context):
        reasons = translation_offer()["reasons"]
        if reasons:
            raise Blocked(str(reasons[0])[:40], now + BLOCKED_RETRY)
        organization = Organization.objects.get(pk=organization_id)
        targets, idle = _targets(context, organization, rows)
        _drop(idle)
        if not targets:
            return None
        quote, _ = build_job_quote(
            context,
            organization,
            targets,
            protected="propose",
            include_unverified=False,
            automatic=True,
        )
        busy = {
            (line.source_key, line.object_id)
            for line in quote.lines
            if line.excluded == EXCLUDED_IN_PROGRESS
        }
        if busy:
            # A pair already in a job: its object waits for that job, alone.
            waiting = [row for row in rows if (row.source_key, row.object_id) in busy]
            TranslationDemand.all_objects.filter(pk__in=[row.pk for row in waiting]).update(
                due_at=now + demand_wait()
            )
            rows = [row for row in rows if row not in waiting and row not in idle]
            targets = [t for t in targets if (t.source_key, t.object_id) not in busy]
            if not targets:
                return None
            quote, _ = build_job_quote(
                context,
                organization,
                targets,
                protected="propose",
                include_unverified=False,
                automatic=True,
            )
        if quote.units == 0:
            _drop(rows)
            return None
        if not is_platform_workspace(organization):
            limit = settings_state(organization_id)["values"][AUTO_MONTHLY_LIMIT.key]["effective"]
            if automatic_credits_this_month(organization_id, now) + quote.credits > limit:
                raise Blocked(MONTHLY_LIMIT, _next_month(now))
        try:
            with transaction.atomic():
                job = _create_job(
                    context, organization, quote, "propose", False, automatic=True, job_id=job_id
                )
        except CreditsExhausted as error:
            raise Blocked(CREDITS_EXHAUSTED, now + BLOCKED_RETRY) from error
        except TranslationUnavailable as error:
            raise Blocked(error.reasons[0][:40], now + BLOCKED_RETRY) from error
    _drop(rows)
    return job.id


def _drop(rows: Sequence[TranslationDemand]) -> None:
    if rows:
        TranslationDemand.all_objects.filter(pk__in=[row.pk for row in rows]).delete()


def _targets(
    context: TenantContext, organization: Organization, rows: Sequence[TranslationDemand]
) -> tuple[list[TargetRequest], list[TranslationDemand]]:
    """Public objects, homes first, into the languages their scope publishes;
    and the demand that has nothing to plan."""
    targets: list[TargetRequest] = []
    idle: list[TranslationDemand] = []
    by_source: dict[str, dict[UUID, TranslationDemand]] = {}
    for row in rows:
        by_source.setdefault(row.source_key, {})[row.object_id] = row
    for source_key, demand in by_source.items():
        try:
            source = translation_source(source_key)
        except LookupError:
            idle.extend(demand.values())
            continue
        try:
            source.authorize(context=context, action="publish", object_ids=list(demand))
        except APIException as error:
            # No right, no plan for it, or nothing there: a person has to act.
            raise Blocked(PUBLISH_DENIED, timezone.now() + BLOCKED_RETRY) from error
        planned: set[UUID] = set()
        for ref in _public_refs(source, context, set(demand)):
            for locale in organization.public_locales or ():
                read = source.read(
                    context=context, object_id=ref.object_id, locale=locale, basis="published"
                )
                if read.excluded is None and read.facts.locale_live:
                    targets.append(
                        TargetRequest(source_key=source_key, object_id=ref.object_id, locale=locale)
                    )
                    planned.add(ref.object_id)
        idle.extend(row for object_id, row in demand.items() if object_id not in planned)
    return targets, idle


def _public_refs(
    source: TranslationSource, context: TenantContext, wanted: set[UUID]
) -> list[ObjectRef]:
    """The source's own view of the objects: only those with a public surface,
    homes (`priority` 0) first."""
    found: dict[UUID, ObjectRef] = {}
    cursor: str | None = None
    while True:
        page = source.list_objects(context=context, cursor=cursor, limit=200)
        for ref in page.items:
            if ref.object_id in wanted and ref.public:
                found[ref.object_id] = ref
        cursor = page.next_cursor
        if cursor is None or len(found) == len(wanted):
            return sorted(found.values(), key=lambda ref: ref.priority)
