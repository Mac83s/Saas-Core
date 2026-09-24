from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class JobState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    INGESTING = "ingesting", "Ingesting"
    SUCCEEDED = "succeeded", "Succeeded"
    REFUSED = "refused", "Refused"
    FAILED = "failed", "Failed"


TERMINAL = frozenset({JobState.SUCCEEDED, JobState.REFUSED, JobState.FAILED})
ACTIVE = frozenset({JobState.QUEUED, JobState.RUNNING, JobState.INGESTING})

#: The customer aspects of this increment (ADR-059): the slots that are not
#: proof. 1:1 and 4:5 arrive with the first slot that needs them.
ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (1536, 864),
    "4:3": (1536, 1152),
    "3:2": (1536, 1024),
}


class ImageGenerationJob(TenantScopedModel):
    """Durable work queue and record of one paid generation (ADR-059, ADR-045 shape)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    membership_id = models.UUIDField()
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=JobState.choices, default=JobState.QUEUED)
    aspect = models.CharField(max_length=8)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    model = models.CharField(max_length=80)
    #: Cleared at a terminal state, except `refused`: kept 30 days as abuse evidence.
    prompt = models.TextField(blank=True)
    prompt_sha256 = models.CharField(max_length=64)
    credit_reservation_key = models.CharField(max_length=120, blank=True)
    credit_cost = models.PositiveIntegerField(default=0)
    media_asset_id = models.UUIDField(null=True, blank=True)
    cost_usd_micros = models.BigIntegerField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=120, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="imagegen_job_org_actor_key_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "next_attempt_at"],
                name="imagegen_job_dispatch_idx",
            )
        ]
