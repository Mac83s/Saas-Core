"""Requesting an AI image (ADR-059): every gate before a job exists, and no network call."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.shared.billing.models import (
    CreditOperation,
    CreditReservation,
    EntitlementSnapshot,
    QuotaReservation,
    QuotaUsage,
)
from saas_core.modules.shared.image_generation import services
from saas_core.modules.shared.image_generation.models import ImageGenerationJob, JobState
from saas_core.modules.shared.image_generation.services import (
    PROVIDER_BLOCKED,
    WORKER_SEEN,
    PersonRequired,
    request_generation,
)
from test_media_api import media_client
from test_sites_api import csrf_value

pytestmark = pytest.mark.django_db

PROMPT = "Pusta sala zabiegowa w jasnym świetle poranka"


@pytest.fixture(autouse=True)
def available(settings: Any, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    cache.clear()
    settings.IMAGE_GENERATION_OPENAI_API_KEY = "synthetic-test-key"
    cache.set(WORKER_SEEN, 1, 300)
    enqueued: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.image_generation.tasks.run_image_generation_job.delay",
        lambda *args: enqueued.append(args),
    )
    return enqueued


def generation_client(
    slug: str, *, attempts: int = 50, storage: int = 10 * 1024**2, credits: int = 100
) -> tuple[APIClient, Organization]:
    client, organization, _ = media_client(slug=slug, storage_limit=storage)
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    snapshot.features["image_generation.enabled"] = True
    snapshot.quotas["image_generation.monthly"] = attempts
    snapshot.quotas["credits.monthly"] = credits
    snapshot.sources["image_generation.monthly"] = {"kind": "plan"}
    snapshot.sources["credits.monthly"] = {"kind": "plan"}
    snapshot.save()
    return client, organization


def post(
    client: APIClient, *, key: str = "imagegen-key-001", prompt: str = PROMPT, **body: Any
) -> Any:
    return client.post(
        "/api/v1/image-generation/jobs/",
        {"prompt": prompt, "aspect": "3:2", "expected_cost": 2, **body},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_offer_reports_price_aspects_and_availability() -> None:
    client, _ = generation_client("imagegen-offer")
    response = client.get("/api/v1/image-generation/offer/")
    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "credit_cost": 2,
        "aspects": ["16:9", "4:3", "3:2"],
    }
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("missing", ["key", "operation", "heartbeat", "blocked"])
def test_offer_is_unavailable_fail_closed(settings: Any, missing: str) -> None:
    client, _ = generation_client(f"imagegen-off-{missing}")
    if missing == "key":
        settings.IMAGE_GENERATION_OPENAI_API_KEY = ""
    elif missing == "operation":
        CreditOperation.objects.filter(key="image_generation.generate").update(is_active=False)
    elif missing == "heartbeat":
        cache.delete(WORKER_SEEN)
    else:
        cache.set(PROVIDER_BLOCKED, 1, 3600)
    response = client.get("/api/v1/image-generation/offer/")
    assert response.status_code == 200
    assert response.json()["available"] is False
    created = post(client)
    assert created.status_code == 503
    assert created.json()["code"] == "image_generation_unavailable"
    assert not ImageGenerationJob.all_objects.exists()


@pytest.mark.parametrize("refusal", ["entitlement", "permission"])
def test_offer_and_request_need_entitlement_and_permission(refusal: str) -> None:
    client, organization = generation_client(f"imagegen-403-{refusal}")
    if refusal == "entitlement":
        snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
        snapshot.features["image_generation.enabled"] = False
        snapshot.save()
    else:
        Membership.objects.filter(organization=organization).update(
            role=Role.objects.get(key="staff", organization=None, organization_type="")
        )
    assert client.get("/api/v1/image-generation/offer/").status_code == 403
    assert post(client).status_code == 403
    assert not ImageGenerationJob.all_objects.exists()
    assert not CreditReservation.all_objects.exists()


def test_request_queues_a_job_with_every_hold_and_no_prompt_in_the_audit(
    available: list[tuple[str, str]], django_capture_on_commit_callbacks: Any
) -> None:
    client, organization = generation_client("imagegen-create")
    with django_capture_on_commit_callbacks(execute=True):
        response = post(client)
    assert response.status_code == 202, response.content
    body = response.json()
    assert "prompt" not in body
    assert (body["state"], body["aspect"], body["width"], body["height"]) == (
        "queued",
        "3:2",
        1536,
        1024,
    )
    assert response["Cache-Control"] == "private, no-store"
    job = ImageGenerationJob.all_objects.get(pk=body["id"])
    assert job.prompt == PROMPT and job.credit_cost == 2
    assert job.model == "gpt-image-2.5-flare-2026-09-08"
    assert available == [(str(organization.id), str(job.id))]

    credits = CreditReservation.all_objects.get()
    assert (credits.cost, credits.state, credits.expires_at) == (2, "reserved", None)
    attempts = QuotaUsage.all_objects.get(quota_definition__key="image_generation.monthly")
    assert (attempts.used, attempts.reserved) == (1, 0)
    headroom = QuotaReservation.all_objects.get(idempotency_key=f"imagegen-headroom:{job.id}")
    assert (headroom.amount, headroom.state) == (3 * 1024**2, "reserved")

    entry = OrganizationAuditEntry.objects.get(action="image_generation.requested")
    assert entry.metadata["prompt_sha256"] == job.prompt_sha256
    assert entry.metadata["prompt_length"] == len(PROMPT)
    assert PROMPT not in str(entry.metadata)


def test_same_key_replays_and_other_body_conflicts(
    available: list[tuple[str, str]], django_capture_on_commit_callbacks: Any
) -> None:
    client, _ = generation_client("imagegen-replay")
    with django_capture_on_commit_callbacks(execute=True):
        first = post(client)
        again = post(client)
    assert (first.status_code, again.status_code) == (202, 200)
    assert again.json()["id"] == first.json()["id"]
    assert len(available) == 1
    conflict = post(client, prompt="Inny opis zupełnie innej sceny")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "image_generation_conflict"
    assert ImageGenerationJob.all_objects.count() == 1
    assert CreditReservation.all_objects.count() == 1


@pytest.mark.parametrize("principal_kind", ["service", "integration"])
def test_only_a_person_generates(principal_kind: str) -> None:
    _, organization = generation_client(f"imagegen-key-{principal_kind}")
    membership = Membership.objects.get(organization=organization)
    context = TenantContext(
        organization_id=organization.id,
        membership_id=membership.id,
        actor_id=membership.user_id,
        role_key="owner",
        permissions=frozenset({"image_generation.run", "media.manage"}),
        principal_kind=principal_kind,
    )
    with activate_tenant_context(context), pytest.raises(PersonRequired):
        request_generation(
            prompt=PROMPT, aspect="3:2", idempotency_key="automation-1", expected_cost=2
        )
    assert not ImageGenerationJob.all_objects.exists()


def test_third_active_job_is_refused() -> None:
    client, _ = generation_client("imagegen-busy")
    assert post(client, key="imagegen-busy-1").status_code == 202
    assert post(client, key="imagegen-busy-2").status_code == 202
    response = post(client, key="imagegen-busy-3")
    assert response.status_code == 429
    assert response.json()["code"] == "image_generation_busy"


def test_five_refusals_in_a_day_block_the_organization() -> None:
    client, _ = generation_client("imagegen-refusals")
    assert post(client, key="imagegen-seed-0").status_code == 202
    seed = ImageGenerationJob.all_objects.get()
    ImageGenerationJob.all_objects.filter(pk=seed.pk).update(
        state=JobState.REFUSED, finished_at=timezone.now()
    )
    for index in range(1, 5):
        ImageGenerationJob.all_objects.create(
            organization_id=seed.organization_id,
            created_by_id=seed.created_by_id,
            membership_id=seed.membership_id,
            idempotency_key=f"imagegen-seed-{index}",
            request_hash="x" * 64,
            state=JobState.REFUSED,
            aspect="3:2",
            width=1536,
            height=1024,
            model="m",
            prompt_sha256="0" * 64,
            next_attempt_at=timezone.now(),
            finished_at=timezone.now() - timedelta(hours=index),
        )
    response = post(client, key="imagegen-after-refusals")
    assert response.status_code == 429
    assert response.json()["code"] == "image_generation_refusal_limit"


def test_exhausted_attempt_quota_is_409() -> None:
    client, _ = generation_client("imagegen-attempts", attempts=1)
    assert post(client, key="imagegen-attempt-1").status_code == 202
    ImageGenerationJob.all_objects.update(state=JobState.FAILED, finished_at=timezone.now())
    response = post(client, key="imagegen-attempt-2")
    assert response.status_code == 409
    assert response.json()["code"] == "quota_exceeded"


def test_full_storage_refuses_before_any_credit_is_held() -> None:
    client, _ = generation_client("imagegen-storage", storage=1024**2)
    response = post(client)
    assert response.status_code == 409
    assert response.json()["code"] == "quota_exceeded"
    assert not CreditReservation.all_objects.exists()
    assert not ImageGenerationJob.all_objects.exists()


def test_credits_exhausted_and_price_changed() -> None:
    client, _ = generation_client("imagegen-credits", credits=1)
    exhausted = post(client)
    assert exhausted.status_code == 402
    assert exhausted.json()["code"] == "credits_exhausted"
    changed = post(client, key="imagegen-price", expected_cost=1)
    assert changed.status_code == 409
    assert changed.json()["code"] == "credit_price_changed"
    assert not ImageGenerationJob.all_objects.exists()


def test_invalid_prompt_aspect_and_key_are_400() -> None:
    client, _ = generation_client("imagegen-invalid")
    assert post(client, prompt="  ab  ").status_code == 400
    assert post(client, aspect="1:1").status_code == 400
    assert post(client, key="short").status_code == 400
    assert not ImageGenerationJob.all_objects.exists()


def test_job_is_read_only_inside_its_organization() -> None:
    client, _ = generation_client("imagegen-read")
    job_id = post(client).json()["id"]
    response = client.get(f"/api/v1/image-generation/jobs/{job_id}/")
    assert response.status_code == 200
    assert "prompt" not in response.json()
    assert PROMPT not in response.content.decode()
    other, _ = generation_client("imagegen-other")
    assert other.get(f"/api/v1/image-generation/jobs/{job_id}/").status_code == 404
    assert other.get(f"/api/v1/image-generation/jobs/{uuid7()}/").status_code == 404


def test_prompt_wrapper_keeps_the_customer_text_inside_the_rules() -> None:
    wrapped = services.build_prompt(PROMPT)
    assert PROMPT in wrapped
    assert "No recognizable real or famous person" in wrapped
