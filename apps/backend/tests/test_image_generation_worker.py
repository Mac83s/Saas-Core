"""The image job worker (ADR-059): one paid call, one processing path, one charge.

The provider is a fake callable; storage and the scanner are in memory. Nothing
here reaches OpenAI.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.shared.billing.models import CreditLedgerEntry, CreditReservation
from saas_core.modules.shared.image_generation.models import ImageGenerationJob, JobState
from saas_core.modules.shared.image_generation.provider import (
    GeneratedImage,
    ImageRequest,
    ProviderError,
)
from saas_core.modules.shared.image_generation.services import PROVIDER_BLOCKED, WORKER_SEEN
from saas_core.modules.shared.image_generation.tasks import reconcile_image_generation_jobs
from saas_core.modules.shared.image_generation.worker import run_job
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState
from saas_core.modules.shared.media.scanner import MalwareVerdict
from test_image_generation_api import PROMPT, generation_client, post
from test_media_api import MemoryStorage, UnavailableScanner, VerdictScanner, encoded_image

pytestmark = pytest.mark.django_db

JPEG = encoded_image("JPEG", size=(300, 200))


class FakeProvider:
    def __init__(self, *outcomes: GeneratedImage | ProviderError) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[ImageRequest] = []
        #: Transaction depth of the test itself; the worker must add none.
        self.baseline = len(connection.atomic_blocks)
        self.during_call: Any = None

    def __call__(self, request: ImageRequest, *, model: str) -> GeneratedImage:
        assert len(connection.atomic_blocks) == self.baseline, "provider called in a transaction"
        self.requests.append(request)
        if self.during_call is not None:
            self.during_call()
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


def image() -> GeneratedImage:
    return GeneratedImage(
        content=JPEG,
        model="gpt-image-2.5-flare-2026-09-08",
        cost_usd_micros=41_000,
        provider_request_id="req_synthetic",
    )


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    storage = MemoryStorage()
    state: dict[str, Any] = {"storage": storage, "scanner": VerdictScanner(MalwareVerdict.CLEAN)}
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: state["scanner"]
    )
    return state


@pytest.fixture
def job(settings: Any, monkeypatch: pytest.MonkeyPatch) -> ImageGenerationJob:
    cache.clear()
    settings.IMAGE_GENERATION_OPENAI_API_KEY = "synthetic-test-key"
    cache.set(WORKER_SEEN, 1, 300)
    monkeypatch.setattr(
        "saas_core.modules.shared.image_generation.tasks.run_image_generation_job.delay",
        lambda *args: None,
    )
    client, _ = generation_client(f"imagegen-worker-{uuid4().hex[:8]}")
    response = post(client)
    assert response.status_code == 202, response.content
    return ImageGenerationJob.all_objects.get(pk=response.json()["id"])


def run(job: ImageGenerationJob, provider: FakeProvider) -> ImageGenerationJob:
    run_job(job.organization_id, job.id, provider=provider)
    job.refresh_from_db()
    return job


def due(job: ImageGenerationJob) -> None:
    ImageGenerationJob.all_objects.filter(pk=job.pk).update(
        next_attempt_at=timezone.now() - timedelta(seconds=1)
    )


def credits(job: ImageGenerationJob) -> str:
    return CreditReservation.all_objects.get(idempotency_key=job.credit_reservation_key).state


def test_success_stores_marks_and_charges_once(job: ImageGenerationJob, media: Any) -> None:
    provider = FakeProvider(image())
    job = run(job, provider)
    assert (job.state, job.error_code, job.prompt) == (JobState.SUCCEEDED, "", "")
    assert job.cost_usd_micros == 41_000 and job.provider_request_id == "req_synthetic"
    assert len(provider.requests) == 1
    assert PROMPT in provider.requests[0].prompt
    assert (provider.requests[0].width, provider.requests[0].height) == (1536, 1024)

    asset = MediaAsset.all_objects.get(pk=job.media_asset_id)
    assert (asset.state, asset.ai_origin) == (MediaAssetState.READY, "generated")
    assert b"trainedAlgorithmicMedia" in media["storage"].objects[asset.object_key][0]
    # The provider original stays as private evidence.
    assert asset.source_object_key in media["storage"].objects
    assert credits(job) == "committed"
    consumed = CreditLedgerEntry.all_objects.filter(
        reservation__idempotency_key=job.credit_reservation_key
    )
    assert consumed.count() == 1

    due(job)
    job = run(job, provider)
    assert len(provider.requests) == 1
    assert consumed.count() == 1


def test_refusal_releases_credits_keeps_the_prompt_and_is_never_retried(
    job: ImageGenerationJob, media: Any
) -> None:
    provider = FakeProvider(ProviderError("moderation_blocked", "refused"))
    job = run(job, provider)
    assert (job.state, job.error_code, job.prompt) == (
        JobState.REFUSED,
        "moderation_blocked",
        PROMPT,
    )
    assert credits(job) == "released"
    due(job)
    run(job, provider)
    assert len(provider.requests) == 1


def test_retryable_error_requeues_with_backoff_then_gives_up(
    job: ImageGenerationJob, media: Any
) -> None:
    provider = FakeProvider(ProviderError("openai_http_503", "retryable"))
    job = run(job, provider)
    assert job.state == JobState.QUEUED and job.lease_token is None
    assert job.next_attempt_at > timezone.now()
    for _ in range(2):
        due(job)
        job = run(job, provider)
    assert (job.state, job.error_code) == (JobState.FAILED, "provider_unavailable")
    assert len(provider.requests) == 3
    assert credits(job) == "released" and job.prompt == ""


def test_exhausted_spend_limit_blocks_the_offer(job: ImageGenerationJob, media: Any) -> None:
    job = run(job, FakeProvider(ProviderError("insufficient_quota", "quota")))
    assert (job.state, job.error_code) == (JobState.FAILED, "provider_quota_exhausted")
    assert cache.get(PROVIDER_BLOCKED)
    assert credits(job) == "released"


def test_unknown_result_is_never_sent_again(job: ImageGenerationJob, media: Any) -> None:
    provider = FakeProvider(ProviderError("openai_result_unknown", "unknown"))
    job = run(job, provider)
    assert (job.state, job.error_code) == (JobState.FAILED, "provider_result_unknown")
    due(job)
    run(job, provider)
    assert len(provider.requests) == 1


def test_expired_lease_while_running_is_an_unknown_result(
    job: ImageGenerationJob, media: Any
) -> None:
    ImageGenerationJob.all_objects.filter(pk=job.pk).update(
        state=JobState.RUNNING,
        lease_token=uuid4(),
        lease_until=timezone.now() - timedelta(seconds=1),
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )
    provider = FakeProvider(image())
    job = run(job, provider)
    assert (job.state, job.error_code) == (JobState.FAILED, "provider_result_unknown")
    assert provider.requests == []
    assert credits(job) == "released"


def test_unavailable_scanner_keeps_ingesting_without_calling_the_provider_again(
    job: ImageGenerationJob, media: Any
) -> None:
    media["scanner"] = UnavailableScanner()
    provider = FakeProvider(image())
    job = run(job, provider)
    assert job.state == JobState.INGESTING and job.lease_token is None
    assert job.next_attempt_at > timezone.now()
    assert MediaAsset.all_objects.get(pk=job.media_asset_id).state == MediaAssetState.UPLOADED
    assert credits(job) == "reserved"

    media["scanner"] = VerdictScanner(MalwareVerdict.CLEAN)
    due(job)
    job = run(job, provider)
    assert job.state == JobState.SUCCEEDED
    assert len(provider.requests) == 1
    assert credits(job) == "committed"
    assert (
        CreditLedgerEntry.all_objects.filter(
            reservation__idempotency_key=job.credit_reservation_key
        ).count()
        == 1
    )


def test_revoked_membership_before_the_claim_releases_everything(
    job: ImageGenerationJob, media: Any
) -> None:
    Membership.objects.filter(pk=job.membership_id).update(status=MembershipStatus.SUSPENDED)
    provider = FakeProvider(image())
    job = run(job, provider)
    assert (job.state, job.error_code) == (JobState.FAILED, "request_authorization_revoked")
    assert provider.requests == []
    assert credits(job) == "released"


def test_a_late_result_after_losing_the_lease_is_discarded(
    job: ImageGenerationJob, media: Any
) -> None:
    provider = FakeProvider(image())
    provider.during_call = lambda: ImageGenerationJob.all_objects.filter(pk=job.pk).update(
        lease_token=uuid4()
    )
    job = run(job, provider)
    assert job.state == JobState.RUNNING and job.media_asset_id is None
    assert not MediaAsset.all_objects.filter(organization_id=job.organization_id).exists()
    assert credits(job) == "reserved"


def test_reconcile_heartbeat_dispatch_timeout_and_prompt_purge(
    job: ImageGenerationJob, media: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.image_generation.tasks.run_image_generation_job.delay",
        lambda *args: dispatched.append(args),
    )
    template = {
        field: getattr(job, field)
        for field in ("organization_id", "created_by_id", "membership_id", "aspect", "width")
    }

    def extra(key: str, **fields: Any) -> ImageGenerationJob:
        return ImageGenerationJob.all_objects.create(
            **template,
            height=1024,
            idempotency_key=key,
            request_hash="0" * 64,
            model="m",
            prompt_sha256="0" * 64,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
            **fields,
        )

    stale = extra("imagegen-stale", state=JobState.INGESTING)
    ImageGenerationJob.all_objects.filter(pk=stale.pk).update(
        created_at=timezone.now() - timedelta(hours=25)
    )
    refused = extra(
        "imagegen-refused-old",
        state=JobState.REFUSED,
        prompt="stary opis",
        finished_at=timezone.now() - timedelta(days=31),
    )
    leased = extra(
        "imagegen-leased",
        state=JobState.RUNNING,
        lease_token=uuid4(),
        lease_until=timezone.now() + timedelta(minutes=5),
    )
    due(job)
    cache.delete(WORKER_SEEN)

    assert reconcile_image_generation_jobs() == 1
    assert cache.get(WORKER_SEEN)
    assert dispatched == [(str(job.organization_id), str(job.id))]
    stale.refresh_from_db()
    assert (stale.state, stale.error_code) == (JobState.FAILED, "ingest_timeout")
    refused.refresh_from_db()
    assert refused.prompt == ""
    leased.refresh_from_db()
    assert leased.state == JobState.RUNNING


def test_erasure_removes_the_jobs_and_lists_every_object_including_the_original(
    job: ImageGenerationJob, media: Any
) -> None:
    from django.contrib.auth import get_user_model

    from saas_core.modules.core.organizations.erasure import erase_organization
    from saas_core.modules.core.organizations.models import Organization

    job = run(job, FakeProvider(image()))
    asset = MediaAsset.all_objects.get(pk=job.media_asset_id)
    expected = {
        asset.object_key,
        asset.source_object_key,
        *(variant["object_key"] for variant in asset.variants.values()),
    }
    operator = get_user_model().objects.create_user(
        email=f"operator-{uuid4()}@example.test", password="Erasure-2026!"
    )
    receipt = erase_organization(
        organization=Organization.objects.get(pk=job.organization_id),
        requested_by=operator,
        reason="Test usunięcia zleceń obrazów.",
    )
    assert not ImageGenerationJob.all_objects.filter(organization_id=job.organization_id).exists()
    assert expected <= set(receipt.pending_object_keys)
