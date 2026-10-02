"""Run a translation job (ADR-069 pkt 13, 19–21, 24; docs/architecture/translation-sources.md §9).

The shape is `image_generation/worker.py`: items are claimed in a committed
block with a lease, the model is called outside any transaction, and every
result is written in a block that checks the lease. The job acts as the
membership of the person who ordered it, through `acting_via="ai_translation"`,
so the history says so and person-only gates refuse it; that membership is
checked again at every claim.

What is billed is what was delivered: units the source wrote live, as a draft
or waiting for a person — never ones the hard checks or the source's gate
refused, ones the soft checks flagged, or a model's refusal. A part settles
when its last item is done or its deadline passes.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from saas_core.content_protocol.policy import Trigger
from saas_core.content_protocol.provenance import ORIGIN_AI, Provenance, unit_hash
from saas_core.content_protocol.registry import translation_source
from saas_core.content_protocol.sources import SourceRead, WriteBatch, WriteItem, WriteOutcome
from saas_core.content_protocol.units import Unit, sendable_units, visible_characters
from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    WORKING_ORGANIZATION_STATUSES,
    Membership,
    MembershipStatus,
    Organization,
)
from saas_core.modules.shared.billing.api import settle_credits
from saas_core.modules.shared.model_port.api import ModelContext, ModelError, complete

from .glossary import GlossaryEntry, entries_for, protected_entries
from .jobs import PART_DEADLINE_MAX, start_part
from .models import (
    ITEM_ACTIVE,
    JOB_TERMINAL,
    ItemState,
    JobState,
    PartState,
    ReviewState,
    TranslationGlossaryTerm,
    TranslationJob,
    TranslationJobItem,
    TranslationJobPart,
    TranslationReviewItem,
)
from .permissions import TRANSLATION_REQUEST
from .prompts import PROMPT_VERSION, answered, build_request
from .quality import check_hard, check_soft
from .quotes import billed_units
from .segments import MAX_CALL_ITEMS, Call, plan_calls

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
#: One task run works this long, then hands the job to the next tick.
RUN_BUDGET_SECONDS = 240
MAX_ATTEMPTS = 3
#: Outcomes that cost the provider's work and are billed (ADR-069 pkt 24).
_BILLED_STATES = frozenset({"live", "draft", "pending"})
_FREE_REASONS = frozenset({"gate_failed", "qa_flagged"})

# Why an item ends without a translation.
AUTHORIZATION_REVOKED = "authorization_revoked"
MODEL_REFUSED = "model_refused"
QA_FAILED = "qa_failed"
DEADLINE = "deadline_passed"


@dataclass
class _Work:
    item: TranslationJobItem
    read: SourceRead
    units: tuple[Unit, ...]
    proposals: frozenset[str]
    glossary: tuple[GlossaryEntry, ...] = ()
    # Unit key → translated text, past the hard checks.
    texts: dict[str, str] = field(default_factory=dict)
    flagged: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)
    model: str = ""


# --- Contexts ---------------------------------------------------------------------


def job_context(job: TranslationJob) -> TenantContext | None:
    """The ordering person's membership, still active and still allowed, acting
    through this job — or None, and the job stops (`authorization_revoked`)."""
    membership = (
        Membership.objects.select_related("role", "user", "organization")
        .filter(
            pk=job.membership_id,
            organization_id=job.organization_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
            organization__status__in=WORKING_ORGANIZATION_STATUSES,
        )
        .first()
    )
    if membership is None:
        return None
    context = context_from_membership(membership)
    if not context.has_permission(TRANSLATION_REQUEST):
        return None
    return acting_context(
        context, via="ai_translation", ref=f"translation_job:{job.id}", trigger=job.cause
    )


def _settlement_context(job: TranslationJob) -> TenantContext:
    # The persisted authorization of the order, not a member who may have left:
    # it settles this job's holds only.
    return TenantContext(
        organization_id=job.organization_id,
        membership_id=job.membership_id,
        actor_id=job.created_by_id,
        role_key="translation_job",
        permissions=frozenset(),
        principal_kind="translation_job",
    )


# --- Claiming ------------------------------------------------------------------------


def _locked_job(organization_id: UUID, job_id: UUID) -> TranslationJob | None:
    return (
        TranslationJob.all_objects.select_for_update(of=("self",))
        .filter(pk=job_id, organization_id=organization_id)
        .first()
    )


@transaction.atomic
def _claim(organization_id: UUID, job_id: UUID) -> list[TranslationJobItem]:
    """Up to 20 queued items of the job's running part, one language, leased."""
    set_local_organization_id(organization_id)
    now = timezone.now()
    job = _locked_job(organization_id, job_id)
    if job is None or job.state in JOB_TERMINAL or job.next_attempt_at > now:
        return []
    if job.confirmation_required and job.confirmed_at is None:
        return []  # Waits for the operator's confirmation (ADR-069 pkt 26).
    part = job.parts.filter(state=PartState.RUNNING).order_by("index").first()
    if part is None:
        return []
    # A lease that ran out puts its items back in the queue.
    part.items.filter(state=ItemState.RUNNING, lease_until__lte=now).update(
        state=ItemState.QUEUED, lease_token=None, lease_until=None
    )
    queued = part.items.filter(state=ItemState.QUEUED).order_by("position")
    first = queued.first()
    if first is None:
        return []
    items = list(queued.filter(locale=first.locale)[:MAX_CALL_ITEMS])
    token = uuid4()
    for item in items:
        item.state = ItemState.RUNNING
        item.lease_token = token
        item.lease_until = now + LEASE
        item.attempts += 1
        item.save(update_fields=["state", "lease_token", "lease_until", "attempts", "updated_at"])
    return items


def _end_items(items: Sequence[TranslationJobItem], state: str, error_code: str) -> None:
    now = timezone.now()
    for item in items:
        item.state = state
        item.error_code = error_code
        item.lease_token = None
        item.lease_until = None
        item.delivered = {}
        item.finished_at = now
        item.save()


# --- Running -------------------------------------------------------------------------


def run_job(organization_id: UUID, job_id: UUID) -> None:
    started = time.monotonic()
    while time.monotonic() - started < RUN_BUDGET_SECONDS:
        items = _claim(organization_id, job_id)
        if not items:
            break
        _process(organization_id, job_id, items)
    finish_parts(organization_id, job_id)


def _process(organization_id: UUID, job_id: UUID, items: list[TranslationJobItem]) -> None:
    with transaction.atomic():
        set_local_organization_id(organization_id)
        job = TranslationJob.all_objects.get(pk=job_id, organization_id=organization_id)
        context = job_context(job)
        if context is None:
            _end_items(items, ItemState.FAILED, AUTHORIZATION_REVOKED)
            return
        with activate_tenant_context(context):
            work = _prepare(job, context, items)
    if not work:
        return
    _translate(job, work)
    for one in work:
        _write(organization_id, job, one)


def _prepare(
    job: TranslationJob, context: TenantContext, items: list[TranslationJobItem]
) -> list[_Work]:
    """Reads every item again, just before sending: what the model sees is what
    the source holds now (§9.3)."""
    sendable = frozenset(settings.MODEL_PORT_SENDABLE_DATA_CLASSES) & {"public", "public_personal"}
    work: list[_Work] = []
    terms = list(TranslationGlossaryTerm.all_objects.filter(organization_id=job.organization_id))
    for item in items:
        source = translation_source(item.source_key)
        try:
            source.authorize(context=context, action="translate", object_ids=[item.object_id])
            read = source.read(
                context=context,
                object_id=item.object_id,
                locale=item.locale,
                basis=item.basis,  # type: ignore[arg-type]
            )
        except Exception as error:
            code = getattr(error, "default_code", "") or "source_unavailable"
            _end_items([item], ItemState.FAILED, str(code)[:80])
            continue
        if read.excluded:
            _end_items([item], ItemState.WRITTEN, read.excluded)
            continue
        selection = sendable_units(
            read.units,
            read.targets,
            sendable=sendable,
            protected=job.protected,  # type: ignore[arg-type]
            include_unverified=job.include_unverified,
        )
        if not selection.units:
            _end_items([item], ItemState.WRITTEN, "")
            continue
        item.scope = read.scope
        item.save(update_fields=["scope", "updated_at"])
        company_terms = [
            GlossaryEntry(
                term=term.term,
                rule=term.rule,
                source_locale=term.source_locale,
                target_locale=term.target_locale,
                translation=term.translation,
                forms=tuple(term.forms),
            )
            for term in terms
        ]
        protected = protected_entries(
            source.protected_terms(context=context, object_id=item.object_id),
            source_locale=read.source_locale,
        )
        glossary = entries_for(
            [*company_terms, *protected],
            source_locale=read.source_locale,
            target_locale=item.locale,
            texts=[unit.text for unit in selection.units],
        )
        work.append(
            _Work(
                item=item,
                read=read,
                units=selection.units,
                proposals=selection.proposals,
                glossary=glossary,
            )
        )
    return work


def _locale(code: str) -> tuple[str, str]:
    """The language's English name for the prompt and its script."""
    registered = settings.LOCALE_REGISTRY.get(code)
    if registered is None:
        return code, "Latn"
    return registered.english_name, registered.script


def _call_model(job: TranslationJob, call: Call, work: list[_Work]) -> tuple[Any, str]:
    first = work[call.segments[0].item].read
    (source_name, _), (target_name, target_script) = (
        _locale(first.source_locale),
        _locale(first.locale),
    )
    glossary = {
        entry.term.casefold(): entry
        for index in sorted(call.items)
        for entry in work[index].glossary
    }
    request = build_request(
        call,
        source_locale=first.source_locale,
        target_locale=first.locale,
        source_name=source_name,
        target_name=target_name,
        target_script=target_script,
        glossary=tuple(glossary.values()),
        context=ModelContext(
            organization_id=job.organization_id,
            actor_id=job.created_by_id,
            purpose="platform" if job.billing == "platform_budget" else "customer",
        ),
    )
    response = complete(request)
    return answered(response), response.resolved_model


def _translate(job: TranslationJob, work: list[_Work]) -> None:
    """Calls the model, checks the answers, retries hard failures once."""
    _, target_script = _locale(work[0].read.locale)
    pending: list[tuple[int, Unit]] = []
    for index, one in enumerate(work):
        for unit in one.units:
            reused = one.item.delivered.get(unit.source_hash)
            if reused is None:
                pending.append((index, unit))
                continue
            one.texts[unit.key] = reused
            segment = plan_calls([[unit]])[0].segments[0]
            if check_soft(segment, reused, glossary=one.glossary, target_script=target_script):
                one.flagged.add(unit.key)
    for attempt in range(2):
        if not pending:
            return
        calls = plan_calls(_by_item(pending, len(work)))
        retry: list[tuple[int, Unit]] = []
        for call in calls:
            try:
                answers, model = _call_model(job, call, work)
            except ModelError as error:
                _model_failed(job, call, work, error)
                continue
            checked = check_hard(call, answers)
            for segment in call.segments:
                one = work[segment.item]
                one.model = model
                if segment.id in checked.passed:
                    text = checked.passed[segment.id]
                    one.texts[segment.key] = text
                    if check_soft(
                        segment, text, glossary=one.glossary, target_script=target_script
                    ):
                        one.flagged.add(segment.key)
                elif attempt == 0:
                    retry.append((segment.item, segment.unit))
                else:
                    one.failed[segment.key] = QA_FAILED
        pending = retry


def _by_item(pending: list[tuple[int, Unit]], count: int) -> list[list[Unit]]:
    grouped: list[list[Unit]] = [[] for _ in range(count)]
    for index, unit in pending:
        grouped[index].append(unit)
    return grouped


def _model_failed(job: TranslationJob, call: Call, work: list[_Work], error: ModelError) -> None:
    logger.warning(
        "translation_model_failed",
        extra={"job_id": str(job.id), "kind": error.kind, "code": error.code},
    )
    for segment in call.segments:
        one = work[segment.item]
        if error.kind == "refused":
            one.failed[segment.key] = MODEL_REFUSED
        else:
            # Budget, transient or unknown: the item goes back to the queue;
            # the job waits until the pool or the provider allows again.
            one.failed[segment.key] = f"retry:{error.kind}"
            if error.until is not None:
                _defer(job, error.until)


def _defer(job: TranslationJob, until: Any) -> None:
    """Waiting for the pool is an hour to come back at, not an error; it moves
    the running part's deadline, at most to 7 days from its start (pkt 20)."""
    with transaction.atomic():
        set_local_organization_id(job.organization_id)
        TranslationJob.all_objects.filter(pk=job.id).update(next_attempt_at=until)
        part = (
            TranslationJobPart.all_objects.select_for_update()
            .filter(job_id=job.id, state=PartState.RUNNING)
            .order_by("index")
            .first()
        )
        if part is not None and part.started_at is not None and part.deadline_at is not None:
            latest = part.started_at + PART_DEADLINE_MAX
            part.deadline_at = min(max(part.deadline_at, until), latest)
            part.save(update_fields=["deadline_at"])


def _provenance(unit: Unit, text: str, model: str) -> Provenance:
    return Provenance(
        origin=ORIGIN_AI,
        source_hash=unit.source_hash,
        written_hash=unit_hash(unit.kind, text),
        model=model,
        at=timezone.now().isoformat(),
    )


def _write(organization_id: UUID, job: TranslationJob, one: _Work) -> None:
    item = one.item
    retry = {key for key, code in one.failed.items() if code.startswith("retry:")}
    with transaction.atomic():
        set_local_organization_id(organization_id)
        current = (
            TranslationJobItem.all_objects.select_for_update()
            .filter(pk=item.id, lease_token=item.lease_token)
            .first()
        )
        if current is None:
            return  # The lease was lost: another run owns the item now.
        context = job_context(job)
        if context is None:
            _end_items([current], ItemState.FAILED, AUTHORIZATION_REVOKED)
            return
        units = {unit.key: unit for unit in one.units}
        live = {
            key: (text, _provenance(units[key], text, one.model))
            for key, text in one.texts.items()
            if key not in one.flagged
        }
        flagged = {
            key: (text, _provenance(units[key], text, one.model))
            for key, text in one.texts.items()
            if key in one.flagged
        }
        requested = "draft" if item.basis == "working" else "live"
        write_items = [
            WriteItem(
                object_id=item.object_id,
                locale=item.locale,
                basis=item.basis,  # type: ignore[arg-type]
                basis_version=one.read.basis_version,
                target_version=one.read.target_version,
                texts=texts,
                requested=target,  # type: ignore[arg-type]
                reason=reason,
            )
            for texts, target, reason in (
                (live, requested, None),
                (flagged, "pending", "qa_flagged"),
            )
            if texts
        ]
        outcomes: tuple[WriteOutcome, ...] = ()
        if write_items:
            source = translation_source(item.source_key)
            published = set(
                TranslationJobItem.all_objects.filter(
                    job_id=job.id, state=ItemState.WRITTEN, outcomes__contains=[{"state": "live"}]
                ).values_list("object_id", flat=True)
            )
            with activate_tenant_context(context):
                outcomes = source.write(
                    context=context,
                    batch=WriteBatch(
                        source_key=item.source_key,
                        scope=one.read.scope,
                        trigger=Trigger(
                            kind=job.trigger, job_ref=f"translation_job:{job.id}", cause=job.cause
                        ),
                        protected=job.protected,  # type: ignore[arg-type]
                        items=tuple(write_items),
                        idempotency_key=f"{job.id}:{item.id}:{current.attempts}",
                        published_in_job=frozenset(published),
                    ),
                )
        if outcomes:
            record_reviews(job, current, one.read, outcomes, {**live, **flagged})
        # Billed is what this attempt delivered; a requeued item keeps it.
        current.delivered_characters += sum(
            visible_characters(units[key].text)
            for outcome in outcomes
            if outcome.state in _BILLED_STATES and outcome.reason not in _FREE_REASONS
            for key in outcome.keys
            if key in units
        )
        current.outcomes = [
            *current.outcomes,
            *(
                {"state": outcome.state, "reason": outcome.reason, "keys": len(outcome.keys)}
                for outcome in outcomes
                if outcome.state != "conflict"
            ),
        ]
        current.model = one.model or current.model
        current.prompt_version = PROMPT_VERSION
        current.lease_token = None
        current.lease_until = None
        conflicted = any(outcome.state == "conflict" for outcome in outcomes)
        if (conflicted or retry) and current.attempts < MAX_ATTEMPTS:
            # Read again on the next claim; what passed the checks is reused by
            # its source hash, without a second model call (§6.3).
            current.delivered = {
                units[key].source_hash: text for key, text in one.texts.items() if key in units
            }
            current.state = ItemState.QUEUED
            current.save()
            return
        current.outcomes = [
            *current.outcomes,
            *(
                {"state": "failed", "reason": code.split(":")[0], "keys": 1}
                for code in one.failed.values()
            ),
        ]
        failed_reasons = Counter(code.split(":")[0] for code in one.failed.values())
        for reason, count in sorted(failed_reasons.items()):
            open_review(job, current, one.read, reason=reason, keys=count)
        written = any(entry["state"] not in ("refused", "failed") for entry in current.outcomes)
        current.state = ItemState.WRITTEN if written or not one.failed else ItemState.FAILED
        current.error_code = "" if written else next(iter(one.failed.values()), "")[:80]
        current.delivered = {}
        current.finished_at = timezone.now()
        current.save()


# --- What waits for a person ------------------------------------------------------


def open_review(
    job: TranslationJob,
    item: TranslationJobItem,
    read: SourceRead,
    *,
    reason: str,
    keys: int,
    texts: dict[str, Any] | None = None,
    target_version: str | None = None,
) -> TranslationReviewItem:
    """One result waiting for a person; a newer one for the same pair and
    reason supersedes the open one (ADR-069 pkt 19)."""
    TranslationReviewItem.all_objects.filter(
        organization_id=job.organization_id,
        source_key=item.source_key,
        object_id=item.object_id,
        locale=item.locale,
        reason=reason,
        state=ReviewState.OPEN,
    ).update(state=ReviewState.SUPERSEDED, texts={}, updated_at=timezone.now())
    return TranslationReviewItem.all_objects.create(
        organization_id=job.organization_id,
        job=job,
        source_key=item.source_key,
        object_id=item.object_id,
        locale=item.locale,
        basis=item.basis,
        basis_version=read.basis_version,
        target_version=target_version or read.target_version or "",
        reason=reason,
        keys=keys,
        texts=texts or {},
    )


def record_reviews(
    job: TranslationJob,
    item: TranslationJobItem,
    read: SourceRead,
    outcomes: Sequence[WriteOutcome],
    texts: dict[str, tuple[str, Provenance]],
) -> None:
    """Every `pending` the source answered becomes a review item. A live record
    keeps nothing pending, so its texts wait here (§6.3)."""
    live_record = translation_source(item.source_key).staging == "live_record"
    for outcome in outcomes:
        if outcome.state != "pending":
            continue
        kept = (
            {key: [texts[key][0], texts[key][1].as_dict()] for key in outcome.keys if key in texts}
            if live_record and outcome.reason != "gate_failed"
            else {}
        )
        open_review(
            job,
            item,
            read,
            reason=outcome.reason or "pending",
            keys=len(outcome.keys),
            texts=kept,
            target_version=outcome.target_version,
        )


# --- Parts and the end of a job --------------------------------------------------------


def finish_parts(organization_id: UUID, job_id: UUID) -> None:
    """Settles every part whose items are done or whose deadline passed, starts
    the next part, and closes the job when nothing is left."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        job = _locked_job(organization_id, job_id)
        if job is None or job.state in JOB_TERMINAL:
            return
        now = timezone.now()
        for part in job.parts.filter(state=PartState.RUNNING).order_by("index"):
            overdue = part.deadline_at is not None and part.deadline_at <= now
            if part.items.filter(state__in=list(ITEM_ACTIVE)).exists() and not overdue:
                return
            if overdue:
                _end_items(
                    list(part.items.filter(state__in=list(ITEM_ACTIVE))),
                    ItemState.CANCELED,
                    DEADLINE,
                )
            _settle(job, part)
        following = job.parts.filter(state=PartState.QUEUED).order_by("index").first()
        if following is not None:
            with activate_tenant_context(_settlement_context(job)):
                try:
                    start_part(job, following)
                except Exception as error:
                    code = getattr(error, "default_code", "") or "part_not_started"
                    _end_items(
                        list(following.items.filter(state__in=list(ITEM_ACTIVE))),
                        ItemState.CANCELED,
                        str(code),
                    )
                    following.state = PartState.SETTLED
                    following.save()
                    _close(job)
            return
        _close(job)


def _settle(job: TranslationJob, part: TranslationJobPart) -> None:
    delivered = sum(part.items.values_list("delivered_characters", flat=True))
    units = min(billed_units(delivered), part.units)
    if part.reservation_key:
        with activate_tenant_context(_settlement_context(job)):
            reservation = settle_credits(part.reservation_key, units)
        part.settled_credits = reservation.cost if reservation.state == "committed" else 0
    part.delivered_characters = delivered
    part.settled_units = units
    part.settled_at = timezone.now()
    part.state = PartState.SETTLED
    part.save()
    publish_scopes(job, part)


def publish_scopes(job: TranslationJob, part: TranslationJobPart) -> None:
    """One derived publication per source and scope for what went out live
    (ADR-069 pkt 21); a live record needs none."""
    context = job_context(job)
    if context is None:
        return
    scopes = set(
        part.items.filter(state=ItemState.WRITTEN, outcomes__contains=[{"state": "live"}])
        .exclude(scope="")
        .values_list("source_key", "scope")
    )
    with activate_tenant_context(context):
        for source_key, scope in sorted(scopes):
            translation_source(source_key).publish(
                context=context,
                scope=scope,
                job_ref=f"translation_job:{job.id}",
                idempotency_key=f"{job.id}:{part.index}:{source_key}:{scope}",
            )


def _close(job: TranslationJob) -> None:
    items = job.items.all()
    written = items.filter(state=ItemState.WRITTEN).count()
    total = items.count()
    job.state = (
        JobState.CANCELED
        if job.error_code == "canceled"
        else JobState.SUCCEEDED
        if written == total
        else (JobState.PARTIAL if written else JobState.FAILED)
    )
    job.finished_at = timezone.now()
    job.save(update_fields=["state", "finished_at", "updated_at"])
    if job.state in (JobState.PARTIAL, JobState.FAILED):
        from .notify import notify_job_problem

        notify_job_problem(job, written=written, total=total)
    record_audit(
        organization=Organization.objects.get(pk=job.organization_id),
        action=f"translation.job_{job.state}",
        # The job is the ordering person's, wherever it ends.
        actor=job.created_by,
        target_type="translation.job",
        target_id=job.id,
        metadata={
            "job_id": str(job.id),
            "pairs": total,
            "written": written,
            "characters": sum(part.delivered_characters for part in job.parts.all()),
            "units": sum(part.settled_units for part in job.parts.all()),
            "credits": sum(part.settled_credits for part in job.parts.all()),
        },
    )
