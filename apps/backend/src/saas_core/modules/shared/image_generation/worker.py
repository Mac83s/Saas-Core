"""Run one durable image job; an unknown provider result is never paid for twice.

The shape is seo/worker.py (ADR-045): the claim is its own committed block with a
lease token, the provider call runs outside any transaction, and every outcome
is written in a new block that checks the lease. Credits settle under the
job's persisted context, not a member who may since have left.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from uuid import UUID, uuid4

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
)
from saas_core.modules.shared.billing.api import (
    authorize_entitled,
    commit_credits,
    release_credits,
    release_quota,
)
from saas_core.modules.shared.media.api import (
    MEDIA_MANAGE,
    MalwareScannerUnavailable,
    process_media_asset,
    stage_generated_media_asset,
)

from . import provider as image_provider
from .models import TERMINAL, ImageGenerationJob, JobState
from .permissions import IMAGE_GENERATION_ENABLED, IMAGE_GENERATION_RUN
from .services import PROVIDER_BLOCKED, build_prompt

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=5)
QUEUED_TTL = timedelta(minutes=30)
PROVIDER_BLOCK_SECONDS = 3600

Provider = Callable[..., image_provider.GeneratedImage]


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(600, 30 * 2**attempts))


def _headroom_key(job: ImageGenerationJob) -> str:
    return f"imagegen-headroom:{job.id}"


def _settlement_context(job: ImageGenerationJob) -> TenantContext:
    # The persisted prior authorization, not a new request impersonating a
    # member who may since have left. It settles this job's holds only.
    return TenantContext(
        organization_id=job.organization_id,
        membership_id=job.membership_id,
        actor_id=job.created_by_id,
        role_key="image_generation_job",
        permissions=frozenset(),
        principal_kind="image_generation_job",
    )


def _membership_context(job: ImageGenerationJob) -> TenantContext | None:
    membership = (
        Membership.objects.select_related("role", "user", "organization")
        .filter(
            pk=job.membership_id,
            organization_id=job.organization_id,
            user_id=job.created_by_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
            organization__status=OrganizationStatus.ACTIVE,
        )
        .first()
    )
    return context_from_membership(membership) if membership is not None else None


def _still_authorized(job: ImageGenerationJob) -> bool:
    context = _membership_context(job)
    if context is None or not context.has_permission(MEDIA_MANAGE):
        return False
    with activate_tenant_context(context):
        try:
            authorize_entitled(IMAGE_GENERATION_RUN, IMAGE_GENERATION_ENABLED)
        except APIException:
            return False
    return True


def _locked(organization_id: UUID, job_id: UUID) -> ImageGenerationJob | None:
    return (
        ImageGenerationJob.all_objects.select_for_update(of=("self",))
        .filter(pk=job_id, organization_id=organization_id)
        .first()
    )


def _leased(organization_id: UUID, job: ImageGenerationJob) -> ImageGenerationJob | None:
    """The job again, locked, only while this run still holds its lease."""
    current = _locked(organization_id, job.id)
    if current is None or current.lease_token != job.lease_token or current.state in TERMINAL:
        return None
    return current


def _finish(job: ImageGenerationJob, state: str, error_code: str = "") -> None:
    with activate_tenant_context(_settlement_context(job)):
        if job.credit_reservation_key:
            if state == JobState.SUCCEEDED:
                commit_credits(job.credit_reservation_key)
            else:
                release_credits(job.credit_reservation_key)
        with suppress(ObjectDoesNotExist):  # a no-op once released
            release_quota(_headroom_key(job))
        job.state = state
        job.error_code = error_code
        if state != JobState.REFUSED:
            # A refused prompt stays 30 days as abuse evidence (reconcile clears it).
            job.prompt = ""
        job.finished_at = timezone.now()
        job.lease_token = None
        job.lease_until = None
        job.save()
        record_audit(
            organization=Organization.objects.get(pk=job.organization_id),
            action=f"image_generation.{state}",
            actor=None,
            target_type="image_generation_job",
            target_id=job.id,
            metadata={
                "job_id": str(job.id),
                "aspect": job.aspect,
                "model": job.model,
                "prompt_sha256": job.prompt_sha256,
                "cost_usd_micros": job.cost_usd_micros,
                "credits": job.credit_cost,
                "error_code": error_code,
                "provider_request_id": job.provider_request_id,
            },
        )


@transaction.atomic
def _claim(organization_id: UUID, job_id: UUID) -> ImageGenerationJob | None:
    set_local_organization_id(organization_id)
    now = timezone.now()
    job = _locked(organization_id, job_id)
    if (
        job is None
        or job.state in TERMINAL
        or job.next_attempt_at > now
        or (job.lease_until is not None and job.lease_until > now)
    ):
        return None
    if job.state == JobState.RUNNING:
        # The lease ran out mid-call: the image may have been paid for, so it
        # is never sent again (ADR-046).
        _finish(job, JobState.FAILED, "provider_result_unknown")
        return None
    if job.state == JobState.QUEUED and now - job.created_at > QUEUED_TTL:
        _finish(job, JobState.FAILED, "expired")
        return None
    if job.state == JobState.QUEUED and not _still_authorized(job):
        _finish(job, JobState.FAILED, "request_authorization_revoked")
        return None
    job.lease_token = uuid4()
    job.lease_until = now + LEASE
    job.attempts += 1
    if job.state == JobState.QUEUED:
        job.state = JobState.RUNNING
    job.save(update_fields=["lease_token", "lease_until", "attempts", "state", "updated_at"])
    return job


def run_job(organization_id: UUID, job_id: UUID, *, provider: Provider | None = None) -> None:
    job = _claim(organization_id, job_id)
    if job is None:
        return
    if job.state == JobState.RUNNING:
        request = image_provider.ImageRequest(
            prompt=build_prompt(job.prompt),
            width=job.width,
            height=job.height,
            # The adapter sends it to OpenAI only as a SHA-256.
            end_user=f"{job.organization_id}:{job.created_by_id}",
        )
        try:
            image = (provider or image_provider.generate)(request, model=job.model)
        except image_provider.ProviderError as error:
            _record_provider_error(organization_id, job, error)
            return
        if not _store(organization_id, job, image):
            return
    _ingest(organization_id, job)


def _record_provider_error(
    organization_id: UUID, job: ImageGenerationJob, error: image_provider.ProviderError
) -> None:
    with transaction.atomic():
        set_local_organization_id(organization_id)
        current = _leased(organization_id, job)
        if current is None:
            return
        if error.kind == "refused":
            _finish(current, JobState.REFUSED, error.code)
        elif error.kind == "retryable":
            if current.attempts >= MAX_ATTEMPTS:
                _finish(current, JobState.FAILED, "provider_unavailable")
                return
            # Back to the queue; the reconcile beat sends it again (no Celery
            # autoretry: the lease would make the retry a no-op).
            current.state = JobState.QUEUED
            current.error_code = error.code
            current.lease_token = None
            current.lease_until = None
            current.next_attempt_at = timezone.now() + _backoff(current.attempts)
            current.save()
        elif error.kind in {"quota", "config"}:
            code = (
                "provider_quota_exhausted" if error.kind == "quota" else "provider_not_configured"
            )
            _finish(current, JobState.FAILED, code)
            cache.set(PROVIDER_BLOCKED, 1, PROVIDER_BLOCK_SECONDS)
        elif error.kind == "unknown":
            _finish(current, JobState.FAILED, "provider_result_unknown")
        else:
            _finish(current, JobState.FAILED, error.code)


def _store(
    organization_id: UUID, job: ImageGenerationJob, image: image_provider.GeneratedImage
) -> bool:
    with transaction.atomic():
        set_local_organization_id(organization_id)
        current = _leased(organization_id, job)
        if current is None:
            return False
        current.cost_usd_micros = image.cost_usd_micros
        current.provider_request_id = image.provider_request_id[:120]
        context = _membership_context(current)
        try:
            if context is None:
                raise APIException
            with activate_tenant_context(context):
                release_quota(_headroom_key(current))
                asset = stage_generated_media_asset(
                    source_key=f"imagegen:{current.id}",
                    filename=f"ai-{current.id}.jpg",
                    content_type="image/jpeg",
                    content=image.content,
                )
        except APIException:
            # The member left or storage is full: the provider cost is ours.
            _finish(current, JobState.FAILED, "ingest_refused")
            return False
        current.media_asset_id = asset.id
        current.state = JobState.INGESTING
        current.save()
    return True


def _ingest(organization_id: UUID, job: ImageGenerationJob) -> None:
    """The single processing path of the stored image: scan, XMP, variants."""
    try:
        with transaction.atomic():
            set_local_organization_id(organization_id)
            current = _leased(organization_id, job)
            if current is None or current.media_asset_id is None:
                return
            # The purchase was authorized when it was made; finishing it does
            # not depend on the member still being here (as SEO settles).
            with activate_tenant_context(_settlement_context(current)):
                asset = process_media_asset(asset_id=current.media_asset_id)
            if asset is not None and asset.state == "ready":
                _finish(current, JobState.SUCCEEDED)
            elif asset is not None and asset.state == "rejected":
                _finish(current, JobState.FAILED, asset.rejection_code or "ingest_rejected")
            else:
                _finish(current, JobState.FAILED, "ingest_refused")
    except MalwareScannerUnavailable:
        with transaction.atomic():
            set_local_organization_id(organization_id)
            current = _leased(organization_id, job)
            if current is None:
                return
            current.lease_token = None
            current.lease_until = None
            current.next_attempt_at = timezone.now() + _backoff(current.attempts)
            current.save()


@transaction.atomic
def expire_ingest(organization_id: UUID, job_id: UUID) -> None:
    """An image that could not be scanned for a day is given up, uncharged."""
    set_local_organization_id(organization_id)
    job = _locked(organization_id, job_id)
    now = timezone.now()
    if (
        job is None
        or job.state != JobState.INGESTING
        or (job.lease_until is not None and job.lease_until > now)
    ):
        return
    _finish(job, JobState.FAILED, "ingest_timeout")
