"""What waits for a person, and the person's decisions (ADR-069 pkt 19, 21, 22;
docs/architecture/translation-sources.md §6.6).

Accepting, discarding and taking back a job are a person's decisions: a job
or the assistant on its own is refused at the person gate, and the assistant
passes only with a consent click (ADR-076). A versioned source decides through
its `review` and `revert`; a live record keeps nothing pending, so an
acceptance is a write with the `acceptance` trigger of the text that waited
here. Credits do not come back with a revert — a refund is the operator's
audited correction (pkt 22).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound

from saas_core.content_protocol.policy import Trigger
from saas_core.content_protocol.provenance import Provenance
from saas_core.content_protocol.registry import translation_source
from saas_core.content_protocol.sources import ReviewItem, WriteBatch, WriteItem, WriteOutcome
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required

from .models import (
    JOB_TERMINAL,
    ItemState,
    ReviewState,
    TranslationJob,
    TranslationJobItem,
    TranslationReviewItem,
)
from .permissions import TRANSLATION_REQUEST
from .services import Saved, field_errors, translation_write

#: Person-only labels (`assert_person_required`).
REVIEW_DECISION = "Decyzja o tłumaczeniu AI"
JOB_REVERT = "Cofnięcie zlecenia tłumaczeń"

#: Reasons with no text to accept: the person translates by hand or orders again.
NOT_ACCEPTABLE = frozenset({"qa_failed", "model_refused", "gate_failed"})


class ReviewChanged(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Pozycja przeglądu zmieniła się albo już ją rozstrzygnięto. Odśwież listę."
    default_code = "translation_review_changed"


@dataclass(frozen=True, slots=True)
class ReviewChoice:
    id: UUID
    version: int


def _actor(context: TenantContext) -> User | None:
    return User.objects.filter(pk=context.actor_id).first()


def list_review(
    *, cursor: str | None, limit: int, reason: str | None = None
) -> tuple[list[TranslationReviewItem], str | None]:
    context = authorize(TRANSLATION_REQUEST)
    rows = TranslationReviewItem.all_objects.filter(
        organization_id=context.organization_id, state=ReviewState.OPEN
    ).order_by("created_at", "id")
    if reason:
        rows = rows.filter(reason=reason)
    start = int(cursor) if cursor and cursor.isdigit() else 0
    page = list(rows[start : start + limit + 1])
    return page[:limit], (str(start + limit) if len(page) > limit else None)


def review_payload(row: TranslationReviewItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "job_id": row.job_id,
        "source_key": row.source_key,
        "object_id": row.object_id,
        "locale": row.locale,
        "reason": row.reason,
        "keys": row.keys,
        "acceptable": row.reason not in NOT_ACCEPTABLE,
        "state": row.state,
        "created_at": row.created_at,
    }


def decide_review(
    *, action: str, choices: Sequence[ReviewChoice], idempotency_key: str
) -> Saved[list[dict[str, Any]]]:
    """Accepts or discards the chosen results at the versions the person saw."""
    if action not in ("accept", "discard"):
        raise ValueError(action)
    context = authorize(TRANSLATION_REQUEST)
    assert_person_required(context, REVIEW_DECISION)
    organization = Organization.objects.get(pk=context.organization_id)
    if not choices:
        raise field_errors({"items": "required"})
    ids = [choice.id for choice in choices]

    def write() -> Saved[list[dict[str, Any]]]:
        rows = {
            row.id: row
            for row in TranslationReviewItem.all_objects.select_for_update().filter(
                organization=organization, pk__in=ids
            )
        }
        errors: dict[str, str] = {}
        for index, choice in enumerate(choices):
            row = rows.get(choice.id)
            if row is None:
                raise NotFound("Nie ma takiej pozycji przeglądu.")
            if row.state != ReviewState.OPEN or row.version != choice.version:
                raise ReviewChanged
            if action == "accept" and row.reason in NOT_ACCEPTABLE:
                errors[f"items.{index}"] = "not_acceptable"
        if errors:
            raise field_errors(errors)
        ordered = [rows[choice.id] for choice in choices]
        outcomes = _apply(context, action, ordered)
        now = timezone.now()
        decided = ReviewState.ACCEPTED if action == "accept" else ReviewState.DISCARDED
        results = []
        for row in ordered:
            row.state = decided
            row.texts = {}
            row.version += 1
            row.decided_at = now
            row.decided_by_membership_id = context.membership_id
            row.save()
            results.append({**review_payload(row), "outcomes": outcomes.get(row.id, [])})
        record_audit(
            organization=organization,
            action=f"translation.review_{'accepted' if action == 'accept' else 'discarded'}",
            actor=_actor(context),
            target_type="translation.review",
            target_id=ordered[0].id,
            metadata={
                "items": len(ordered),
                "reasons": dict(Counter(row.reason for row in ordered)),
            },
        )
        return Saved(results, ordered[0].id, 0, created=False)

    def replay(_first: UUID) -> Saved[list[dict[str, Any]]]:
        rows = TranslationReviewItem.all_objects.filter(organization=organization, pk__in=ids)
        return Saved([review_payload(row) for row in rows], _first, 0, created=False, replayed=True)

    return translation_write(
        context=context,
        action=f"review.{action}",
        target_id=None,
        request={"items": [[str(c.id), c.version] for c in choices]},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=replay,
    )


def _apply(
    context: TenantContext, action: str, rows: Sequence[TranslationReviewItem]
) -> dict[UUID, list[dict[str, Any]]]:
    """Hands the decision to each source, one call per source (§6.6)."""
    by_source: dict[str, list[TranslationReviewItem]] = defaultdict(list)
    for row in rows:
        by_source[row.source_key].append(row)
    outcomes: dict[UUID, list[dict[str, Any]]] = {}
    for source_key, group in by_source.items():
        source = translation_source(source_key)
        if source.staging == "live_record":
            if action == "discard":
                continue
            for row in group:
                outcomes[row.id] = _summaries(_accept_live(context, source, row))
            continue
        answered = source.review(
            context=context,
            action=action,  # type: ignore[arg-type]
            items=[
                ReviewItem(
                    object_id=row.object_id,
                    locale=row.locale,
                    expected_version=row.target_version or None,
                )
                for row in group
            ],
            idempotency_key=f"review:{action}:{group[0].id}",
        )
        for row in group:
            outcomes[row.id] = _summaries(
                o for o in answered if o.object_id == row.object_id and o.locale == row.locale
            )
    return outcomes


def _accept_live(
    context: TenantContext, source: Any, row: TranslationReviewItem
) -> tuple[WriteOutcome, ...]:
    texts = {
        key: (str(value[0]), Provenance.from_dict(dict(value[1])))
        for key, value in row.texts.items()
    }
    if not texts:
        return ()
    answered: tuple[WriteOutcome, ...] = source.write(
        context=context,
        batch=WriteBatch(
            source_key=row.source_key,
            scope="",
            trigger=Trigger(kind="acceptance", job_ref=None, cause=f"user:{context.actor_id}"),
            protected="overwrite" if row.reason == "overwrites_human" else "propose",
            items=(
                WriteItem(
                    object_id=row.object_id,
                    locale=row.locale,
                    basis=row.basis,  # type: ignore[arg-type]
                    basis_version=row.basis_version,
                    target_version=row.target_version or None,
                    texts=texts,
                    requested="live",
                ),
            ),
            idempotency_key=f"review:accept:{row.id}",
        ),
    )
    if any(outcome.state == "conflict" for outcome in answered):
        # The source moved since: the text no longer fits; order it again.
        raise ReviewChanged
    return answered


def _summaries(outcomes: Any) -> list[dict[str, Any]]:
    return [
        {"state": outcome.state, "reason": outcome.reason, "keys": len(outcome.keys)}
        for outcome in outcomes
    ]


# --- Taking a job back and stopping one --------------------------------------------


def _job(organization: Organization, job_id: UUID, *, lock: bool = False) -> TranslationJob:
    rows = TranslationJob.all_objects.filter(organization=organization, pk=job_id)
    job = (rows.select_for_update() if lock else rows).first()
    if job is None:
        raise NotFound("Nie ma takiego zlecenia.")
    return job


def revert_job(*, job_id: UUID, idempotency_key: str) -> Saved[TranslationJob]:
    """„Cofnij ostatnie zadanie”: every source the job wrote returns to its texts
    from before it, through its own derived publication."""
    context = authorize(TRANSLATION_REQUEST)
    assert_person_required(context, JOB_REVERT)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[TranslationJob]:
        job = _job(organization, job_id, lock=True)
        if job.reverted_at is not None:
            raise field_errors({"job_id": "already_reverted"})
        sources = sorted(
            set(
                TranslationJobItem.all_objects.filter(job=job, state=ItemState.WRITTEN).values_list(
                    "source_key", flat=True
                )
            )
        )
        restored = 0
        for source_key in sources:
            outcomes = translation_source(source_key).revert(
                context=context,
                job_ref=f"translation_job:{job.id}",
                idempotency_key=f"revert:{job.id}:{source_key}",
            )
            restored += len(outcomes)
        job.reverted_at = timezone.now()
        job.save(update_fields=["reverted_at", "updated_at"])
        record_audit(
            organization=organization,
            action="translation.job_reverted",
            actor=_actor(context),
            target_type="translation.job",
            target_id=job.id,
            metadata={"job_id": str(job.id), "sources": sources, "restored": restored},
        )
        return Saved(job, job.id, 0, created=False)

    def replay(_job_id: UUID) -> Saved[TranslationJob]:
        return Saved(_job(organization, _job_id), _job_id, 0, created=False, replayed=True)

    return translation_write(
        context=context,
        action="job.revert",
        target_id=job_id,
        request={},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=replay,
    )


def cancel_job(*, job_id: UUID, idempotency_key: str) -> Saved[TranslationJob]:
    """Stops sending: queued items are cancelled, what was delivered is settled."""
    context = authorize(TRANSLATION_REQUEST)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[TranslationJob]:
        job = _job(organization, job_id, lock=True)
        if job.state in JOB_TERMINAL:
            raise field_errors({"job_id": "job_finished"})
        now = timezone.now()
        TranslationJobItem.all_objects.filter(job=job, state=ItemState.QUEUED).update(
            state=ItemState.CANCELED, error_code="canceled", finished_at=now, delivered={}
        )
        job.error_code = "canceled"
        job.next_attempt_at = now
        job.save(update_fields=["error_code", "next_attempt_at", "updated_at"])
        record_audit(
            organization=organization,
            action="translation.job_canceled",
            actor=_actor(context),
            target_type="translation.job",
            target_id=job.id,
            metadata={"job_id": str(job.id)},
        )
        return Saved(job, job.id, 0, created=False)

    def replay(_job_id: UUID) -> Saved[TranslationJob]:
        return Saved(_job(organization, _job_id), _job_id, 0, created=False, replayed=True)

    saved = translation_write(
        context=context,
        action="job.cancel",
        target_id=job_id,
        request={},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=replay,
    )
    from .worker import finish_parts

    finish_parts(organization.id, job_id)
    saved.value.refresh_from_db()
    return saved
