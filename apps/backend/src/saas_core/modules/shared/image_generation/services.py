"""Requesting an AI image (ADR-059): gates, holds and a durable job, no network call."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    consume_quota,
    operation_cost,
    reserve_credits,
    reserve_quota,
)
from saas_core.modules.shared.media.api import MEDIA_MANAGE, STORAGE_BYTES
from saas_core.modules.shared.sites.api import badge_visible

from .models import ACTIVE, ASPECTS, ImageGenerationJob, JobState
from .permissions import (
    CREDIT_OPERATION,
    IMAGE_GENERATION_ENABLED,
    IMAGE_GENERATION_MONTHLY,
    IMAGE_GENERATION_RUN,
)

#: Left by the reconcile task, which only runs where a worker consumes `ai`.
WORKER_SEEN = "image_generation:worker_seen"
#: Set for an hour when OpenAI says the spend limit is reached or the key is bad.
PROVIDER_BLOCKED = "image_generation:provider_blocked"

PROMPT_MIN, PROMPT_MAX = 3, 1000
ACTIVE_JOBS_MAX = 2
REFUSALS_MAX = 5
REFUSAL_WINDOW = timedelta(hours=24)
#: Headroom held for the generated file until it is stored, so a full storage
#: quota refuses the request before anything is paid for.
STORAGE_HEADROOM_BYTES = 3 * 1024**2

PROMPT_TEMPLATE = (
    "Realistic photograph for a small-business website, natural light, true colours. "
    "Scene (owner's description in Polish): «{scene}». "
    "No text, letters, numbers, signage, labels, logos or watermarks. "
    "No recognizable real or famous person."
)


class ImageGenerationUnavailable(APIException):
    status_code = 503
    default_detail = "Generowanie obrazów jest chwilowo niedostępne."
    default_code = "image_generation_unavailable"


class ImageGenerationConflict(APIException):
    status_code = 409
    default_detail = "Klucz operacji wskazuje inne zlecenie obrazu."
    default_code = "image_generation_conflict"


class ImageGenerationBusy(APIException):
    status_code = 429
    default_detail = "Poczekaj, aż skończą się trwające generowania."
    default_code = "image_generation_busy"


class ImageGenerationRefusalLimit(APIException):
    status_code = 429
    default_detail = "Zbyt wiele opisów zostało odrzuconych. Spróbuj ponownie jutro."
    default_code = "image_generation_refusal_limit"


class PersonRequired(APIException):
    status_code = 403
    default_detail = "Obraz może zlecić tylko osoba, nie integracja."
    default_code = "person_required"


class ImageGenerationJobNotFound(NotFound):
    default_detail = "Zlecenie obrazu nie istnieje."
    default_code = "image_generation_job_not_found"


def build_prompt(user_text: str) -> str:
    """The fixed English wrapper: a request to the model, not a control."""
    return PROMPT_TEMPLATE.format(scene=user_text)


def _available() -> bool:
    try:
        priced = operation_cost(CREDIT_OPERATION) > 0
    except APIException:  # not in the catalogue: unpriced, so unavailable
        priced = False
    return bool(
        settings.IMAGE_GENERATION_OPENAI_API_KEY
        and priced
        and cache.get(WORKER_SEEN)
        and not cache.get(PROVIDER_BLOCKED)
    )


def read_offer() -> dict[str, object]:
    authorize_entitled(IMAGE_GENERATION_RUN, IMAGE_GENERATION_ENABLED)
    try:
        cost = operation_cost(CREDIT_OPERATION)
    except APIException:
        cost = 0
    return {
        "available": _available(),
        "credit_cost": cost,
        "aspects": list(ASPECTS),
        "badge_visible": badge_visible(),
    }


def read_job(*, job_id: UUID) -> ImageGenerationJob:
    context = authorize_entitled(
        IMAGE_GENERATION_RUN, IMAGE_GENERATION_ENABLED, operation=FeatureOperation.READ
    )
    job = ImageGenerationJob.all_objects.filter(
        pk=job_id, organization_id=context.organization_id
    ).first()
    if job is None:
        raise ImageGenerationJobNotFound
    return job


def _canonical_hash(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@transaction.atomic
def request_generation(
    *, prompt: str, aspect: str, idempotency_key: str, expected_cost: int
) -> tuple[ImageGenerationJob, bool]:
    context = authorize_entitled(IMAGE_GENERATION_RUN, IMAGE_GENERATION_ENABLED)
    if not context.has_permission(MEDIA_MANAGE):
        raise PermissionDenied
    if context.principal_kind != "membership":
        raise PersonRequired
    if not _available():
        raise ImageGenerationUnavailable
    text = prompt.strip()
    key = idempotency_key.strip()
    if not PROMPT_MIN <= len(text) <= PROMPT_MAX:
        raise ValidationError({
            "prompt": [f"Opis musi mieć od {PROMPT_MIN} do {PROMPT_MAX} znaków."]
        })
    if aspect not in ASPECTS:
        raise ValidationError({"aspect": ["Nieobsługiwane proporcje obrazu."]})
    if not 8 <= len(key) <= 120:
        raise ValidationError({"Idempotency-Key": ["Klucz musi mieć od 8 do 120 znaków."]})
    prompt_sha256 = hashlib.sha256(text.encode()).hexdigest()
    request_hash = _canonical_hash({
        "prompt_sha256": prompt_sha256,
        "aspect": aspect,
        "expected_cost": expected_cost,
    })

    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    jobs = ImageGenerationJob.all_objects.filter(organization_id=context.organization_id)
    existing = jobs.filter(created_by_id=context.actor_id, idempotency_key=key).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ImageGenerationConflict
        return existing, False
    now = timezone.now()
    refusals = jobs.filter(state=JobState.REFUSED, finished_at__gte=now - REFUSAL_WINDOW)
    if refusals.count() >= REFUSALS_MAX:
        raise ImageGenerationRefusalLimit
    if jobs.filter(state__in=ACTIVE).count() >= ACTIVE_JOBS_MAX:
        raise ImageGenerationBusy

    width, height = ASPECTS[aspect]
    job = ImageGenerationJob(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        membership_id=context.membership_id,
        idempotency_key=key,
        request_hash=request_hash,
        aspect=aspect,
        width=width,
        height=height,
        prompt=text,
        prompt_sha256=prompt_sha256,
    )
    # Every attempt counts, refused and failed ones too: this is the cost bound.
    consume_quota(IMAGE_GENERATION_MONTHLY, amount=1, idempotency_key=f"imagegen:{job.id}")
    reserve_quota(
        STORAGE_BYTES,
        amount=STORAGE_HEADROOM_BYTES,
        idempotency_key=f"imagegen-headroom:{job.id}",
        expires_at=now + timedelta(hours=1),
    )
    reservation = reserve_credits(
        CREDIT_OPERATION, idempotency_key=f"imagegen:{job.id}", expected_cost=expected_cost
    )
    if reservation is None:
        # The operation went inactive under us: never generate for free.
        raise ImageGenerationUnavailable
    job.credit_reservation_key = reservation.idempotency_key
    job.credit_cost = reservation.cost
    job.state = JobState.QUEUED
    job.next_attempt_at = now
    job.model = settings.IMAGE_GENERATION_MODEL
    job.save()
    record_audit(
        organization=organization,
        action="image_generation.requested",
        actor=User.objects.get(pk=context.actor_id),
        target_type="image_generation_job",
        target_id=job.id,
        metadata={
            "job_id": str(job.id),
            "aspect": aspect,
            "size": f"{width}x{height}",
            "model": job.model,
            "prompt_sha256": prompt_sha256,
            "prompt_length": len(text),
            "credits": job.credit_cost,
        },
    )
    organization_id, job_id = str(job.organization_id), str(job.id)

    def enqueue() -> None:
        from .tasks import run_image_generation_job

        run_image_generation_job.delay(organization_id, job_id)

    transaction.on_commit(enqueue, robust=True)
    return job, True
