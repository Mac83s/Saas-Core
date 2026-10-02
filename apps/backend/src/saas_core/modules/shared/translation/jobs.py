"""Quotes and orders (ADR-069 pkt 18, 19, 23, 25–27).

A quote writes nothing: it reads every (object, language) through the source,
counts what `sendable_units` would send, says what waits for a person and
why, and seals it all in a digest. An order repeats the quote and proceeds
only on the same digest and the same price, so what the person agreed to is
what runs; then it creates the job, its parts and items, holds the first
part's credits and hands the job to the worker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from saas_core.content_protocol.policy import Trigger
from saas_core.content_protocol.registry import translation_source
from saas_core.content_protocol.sources import ContentContext, SourceRead
from saas_core.content_protocol.units import Selection, sendable_units
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import is_platform_workspace
from saas_core.modules.shared.billing.api import CreditPriceChanged, reserve_credits
from saas_core.modules.shared.billing.models import CreditOperation

from .engine_policy import ENGINE_POLICY
from .models import (
    ITEM_ACTIVE,
    JobState,
    TranslationJob,
    TranslationJobItem,
    TranslationJobPart,
)
from .permissions import CREDIT_OPERATION, TRANSLATION_REQUEST
from .quotes import Quote, QuoteLine, billed_units, build_quote, quote_line
from .services import Saved, field_errors, translation_offer, translation_write

#: Pairs one quote may name.
MAX_TARGETS = 1_000
#: A part's deadline, from its start (ADR-069 pkt 20).
PART_DEADLINE = timedelta(hours=72)
#: Waiting for the port's pool moves the deadline at most this far.
PART_DEADLINE_MAX = timedelta(days=7)

EXCLUDED_IN_PROGRESS = "in_progress"


class TranslationQuoteChanged(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Wycena się zmieniła. Sprawdź nową i potwierdź ją."
    default_code = "translation_quote_changed"

    def __init__(self, quote: Quote) -> None:
        super().__init__()
        self.quote = quote


class TranslationUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Tłumaczenie nie jest teraz dostępne."
    default_code = "translation_unavailable"

    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__()
        self.reasons = list(reasons)


class NothingToTranslate(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Nie ma nic do przetłumaczenia."
    default_code = "translation_nothing_to_translate"


@dataclass(frozen=True, slots=True)
class TargetRequest:
    source_key: str
    object_id: UUID
    locale: str
    # "working" translates the draft open in the editor; automation never does.
    basis: str = "published"


@dataclass(frozen=True, slots=True)
class QuoteResult:
    quote: Quote
    available: bool
    reasons: tuple[str, ...]


def _sendable() -> frozenset[str]:
    return frozenset(settings.MODEL_PORT_SENDABLE_DATA_CLASSES) & {"public", "public_personal"}


def _validate_targets(organization: Organization, targets: Sequence[TargetRequest]) -> None:
    errors: dict[str, str] = {}
    if not targets:
        errors["targets"] = "required"
    if len(targets) > MAX_TARGETS:
        errors["targets"] = "too_many"
    enabled = set(organization.public_locales or ())
    seen: set[tuple[str, UUID, str]] = set()
    for index, target in enumerate(targets):
        try:
            source = translation_source(target.source_key)
        except LookupError:
            errors[f"targets.{index}.source_key"] = "unknown_source"
            continue
        if target.basis not in source.bases:
            errors[f"targets.{index}.basis"] = "invalid_choice"
        if target.locale not in enabled:
            errors[f"targets.{index}.locale"] = "locale_not_enabled"
        pair = (target.source_key, target.object_id, target.locale)
        if pair in seen:
            errors[f"targets.{index}"] = "duplicate"
        seen.add(pair)
    if errors:
        raise field_errors(errors)


def _read(context: ContentContext, target: TargetRequest) -> SourceRead:
    source = translation_source(target.source_key)
    try:
        source.authorize(context=context, action="translate", object_ids=[target.object_id])
        return source.read(
            context=context,
            object_id=target.object_id,
            locale=target.locale,
            basis=target.basis,  # type: ignore[arg-type]
        )
    except (LookupError, NotFound) as error:
        raise NotFound("Nie ma takiego obiektu.") from error


def _price() -> int | None:
    operation = CreditOperation.objects.filter(key=CREDIT_OPERATION).first()
    return operation.cost if operation is not None and operation.is_active else None


def _cause(context: TenantContext) -> str:
    if context.acting_trigger:
        return context.acting_trigger
    if context.principal_kind == "api_key" and context.credential_id:
        return f"api_key:{context.credential_id}"
    return f"user:{context.actor_id}"


def build_job_quote(
    context: TenantContext,
    organization: Organization,
    targets: Sequence[TargetRequest],
    *,
    protected: str,
    include_unverified: bool,
) -> tuple[Quote, list[tuple[TargetRequest, Selection]]]:
    policy = ENGINE_POLICY.policy(organization_id=organization.id)
    trigger = Trigger(kind="click", job_ref=None, cause=_cause(context))
    busy = set(
        TranslationJobItem.all_objects.filter(
            organization=organization, state__in=list(ITEM_ACTIVE)
        ).values_list("source_key", "object_id", "locale")
    )
    lines: list[QuoteLine] = []
    selections: list[tuple[TargetRequest, Selection]] = []
    for target in targets:
        read = _read(context, target)
        excluded = None
        if (target.source_key, target.object_id, target.locale) in busy:
            excluded = EXCLUDED_IN_PROGRESS
        if excluded or read.excluded:
            selection = Selection(units=(), proposals=frozenset(), skipped={})
        else:
            selection = sendable_units(
                read.units,
                read.targets,
                sendable=_sendable(),
                protected=protected,  # type: ignore[arg-type]
                include_unverified=include_unverified,
            )
        lines.append(
            quote_line(
                source_key=target.source_key,
                read=read,
                selection=selection,
                policy=policy,
                trigger=trigger,
                excluded=excluded,
            )
        )
        selections.append((target, selection))
    platform = is_platform_workspace(organization)
    price = _price()
    quote = build_quote(
        lines,
        operation_key=CREDIT_OPERATION,
        unit_cost=0 if platform else (price or 0),
        mode=policy.mode,
        protected=protected,  # type: ignore[arg-type]
        include_unverified=include_unverified,
    )
    return quote, selections


def _availability() -> tuple[str, ...]:
    return tuple(translation_offer()["reasons"])


def quote_translation(
    *,
    targets: Sequence[TargetRequest],
    protected: str = "propose",
    include_unverified: bool = False,
) -> QuoteResult:
    """Nothing is saved; the same request against the same content gives the
    same digest."""
    context = authorize(TRANSLATION_REQUEST)
    organization = Organization.objects.get(pk=context.organization_id)
    _validate_targets(organization, targets)
    quote, _ = build_job_quote(
        context, organization, targets, protected=protected, include_unverified=include_unverified
    )
    reasons = _availability()
    return QuoteResult(quote=quote, available=not reasons, reasons=reasons)


def order_translation(
    *,
    targets: Sequence[TargetRequest],
    digest: str,
    expected_credits: int,
    protected: str = "propose",
    include_unverified: bool = False,
    idempotency_key: str,
) -> Saved[TranslationJob]:
    """Orders the quote with this digest at this price, as the person sending it."""
    context = authorize(TRANSLATION_REQUEST)
    if context.principal_kind != "membership":
        # A job runs as a person's membership (ADR-069 pkt 13).
        raise PermissionDenied("Tłumaczenie zleca osoba.")
    organization = Organization.objects.get(pk=context.organization_id)
    _validate_targets(organization, targets)
    request = {
        "targets": [
            {
                "source_key": t.source_key,
                "object_id": str(t.object_id),
                "locale": t.locale,
                "basis": t.basis,
            }
            for t in targets
        ],
        "digest": digest,
        "expected_credits": expected_credits,
        "protected": protected,
        "include_unverified": include_unverified,
    }

    def write() -> Saved[TranslationJob]:
        reasons = _availability()
        if reasons:
            raise TranslationUnavailable(reasons)
        quote, _ = build_job_quote(
            context,
            organization,
            targets,
            protected=protected,
            include_unverified=include_unverified,
        )
        if quote.digest != digest:
            raise TranslationQuoteChanged(quote)
        if quote.credits != expected_credits:
            raise CreditPriceChanged
        if quote.units == 0:
            raise NothingToTranslate
        job = _create_job(context, organization, quote, protected, include_unverified)
        return Saved(job, job.id, 1, created=True)

    def replay(job_id: UUID) -> Saved[TranslationJob]:
        job = TranslationJob.all_objects.get(pk=job_id, organization=organization)
        return Saved(job, job.id, 1, created=True, replayed=True)

    saved = translation_write(
        context=context,
        action="job.create",
        target_id=None,
        request=request,
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=replay,
    )
    if not saved.replayed:
        from .tasks import enqueue_job

        job_id, organization_id = saved.item_id, organization.id
        transaction.on_commit(lambda: enqueue_job(organization_id, job_id), robust=True)
    return saved


def _create_job(
    context: TenantContext,
    organization: Organization,
    quote: Quote,
    protected: str,
    include_unverified: bool,
) -> TranslationJob:
    now = timezone.now()
    platform = is_platform_workspace(organization)
    job = TranslationJob.all_objects.create(
        organization=organization,
        membership_id=context.membership_id,
        created_by_id=context.actor_id,
        trigger="click",
        cause=_cause(context),
        billing="platform_budget" if platform else "credits",
        protected=protected,
        include_unverified=include_unverified,
        quote_digest=quote.digest,
        operation_key=quote.operation_key,
        unit_cost=None if platform else quote.unit_cost,
        units=quote.units,
        credits=quote.credits,
        next_attempt_at=now,
    )
    position = 0
    for index, line_indexes in enumerate(quote.parts):
        characters = sum(quote.lines[i].characters for i in line_indexes)
        part = TranslationJobPart.all_objects.create(
            organization=organization, job=job, index=index, units=billed_units(characters)
        )
        for line_index in line_indexes:
            line = quote.lines[line_index]
            TranslationJobItem.all_objects.create(
                organization=organization,
                job=job,
                part=part,
                position=position,
                source_key=line.source_key,
                object_id=line.object_id,
                locale=line.locale,
                basis=line.basis,
                scope="",
                quoted_characters=line.characters,
            )
            position += 1
    first = job.parts.order_by("index").first()
    if first is not None:
        start_part(job, first)
    record_audit(
        organization=organization,
        action="translation.job_created",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="translation.job",
        target_id=job.id,
        metadata={
            "job_id": str(job.id),
            "pairs": position,
            "characters": quote.characters,
            "units": quote.units,
            "credits": quote.credits,
            "digest": quote.digest,
            "billing": job.billing,
        },
    )
    return job


def start_part(job: TranslationJob, part: TranslationJobPart) -> None:
    """Holds the part's credits and starts its deadline. The hold lasts as long
    as the longest wait could; settling releases what was not delivered."""
    now = timezone.now()
    if job.billing == "credits" and part.units and not part.reservation_key:
        key = f"translation:{job.id}:{part.index}"
        reservation = reserve_credits(
            CREDIT_OPERATION,
            idempotency_key=key,
            quantity=part.units,
            expected_cost=part.units * (job.unit_cost or 0),
            expires_at=now + PART_DEADLINE_MAX + timedelta(hours=1),
        )
        if reservation is None:
            # The price went away under us: never translate for free.
            raise TranslationUnavailable(("operation_unpriced",))
        part.reservation_key = reservation.idempotency_key
    part.started_at = now
    part.deadline_at = now + PART_DEADLINE
    part.state = "running"
    part.save()
    if job.state == JobState.QUEUED:
        job.state = JobState.RUNNING
        job.started_at = now
        job.save(update_fields=["state", "started_at", "updated_at"])


def quote_payload(result: QuoteResult | Quote, reasons: Sequence[str] = ()) -> dict[str, Any]:
    quote = result.quote if isinstance(result, QuoteResult) else result
    if isinstance(result, QuoteResult):
        reasons = result.reasons
    return {
        "digest": quote.digest,
        "available": not reasons,
        "reasons": list(reasons),
        "characters": quote.characters,
        "units": quote.units,
        "unit_cost": quote.unit_cost,
        "credits": quote.credits,
        "mode": quote.mode,
        "protected": quote.protected,
        "include_unverified": quote.include_unverified,
        "parts": [list(part) for part in quote.parts],
        "waiting": quote.waiting,
        "lines": [
            {
                "source_key": line.source_key,
                "object_id": line.object_id,
                "locale": line.locale,
                "basis": line.basis,
                "characters": line.characters,
                "proposals": len(line.proposals),
                "proposal_characters": line.proposal_characters,
                "skipped": dict(line.skipped),
                "outcome": line.outcome,
                "reason": line.reason,
                "excluded": line.excluded,
            }
            for line in quote.lines
        ],
    }


def job_payload(job: TranslationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "state": job.state,
        "trigger": job.trigger,
        "billing": job.billing,
        "units": job.units,
        "credits": job.credits,
        "error_code": job.error_code,
        "next_attempt_at": job.next_attempt_at,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "reverted_at": job.reverted_at,
        "parts": list(
            job.parts.order_by("index").values(
                "index",
                "units",
                "state",
                "deadline_at",
                "delivered_characters",
                "settled_units",
                "settled_credits",
            )
        ),
        "items": list(
            job.items.order_by("position").values(
                "id",
                "source_key",
                "object_id",
                "locale",
                "state",
                "quoted_characters",
                "delivered_characters",
                "outcomes",
                "error_code",
            )
        ),
    }


def list_jobs(*, cursor: str | None, limit: int) -> tuple[list[TranslationJob], str | None]:
    context = authorize(TRANSLATION_REQUEST)
    jobs = TranslationJob.all_objects.filter(organization_id=context.organization_id).order_by(
        "-created_at", "-id"
    )
    start = int(cursor) if cursor and cursor.isdigit() else 0
    page = list(jobs[start : start + limit + 1])
    return page[:limit], (str(start + limit) if len(page) > limit else None)


def get_job(job_id: UUID) -> TranslationJob:
    context = authorize(TRANSLATION_REQUEST)
    job = TranslationJob.all_objects.filter(
        organization_id=context.organization_id, pk=job_id
    ).first()
    if job is None:
        raise NotFound("Nie ma takiego zlecenia.")
    return job
