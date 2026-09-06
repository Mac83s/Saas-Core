from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel

from .gsc.models import (  # noqa: F401
    GscGrantIntent,
    GscOAuthAttempt,
    GscSyncIntent,
    GscWorkspaceState,
)


class SourceSiteBinding(TenantScopedModel):
    """One site in one configured analytical source; URL never establishes ownership."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey("sites.Site", on_delete=models.PROTECT)
    source_id = models.UUIDField()
    external_project_id = models.CharField(max_length=200)
    name = models.CharField(max_length=200)
    root_url = models.URLField(max_length=2000)
    remote_binding_id = models.UUIDField(null=True, blank=True)
    remote_organization_id = models.UUIDField(null=True, blank=True)
    remote_project_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "source_id"],
                name="seo_binding_org_site_source_uq",
            )
        ]


class AuditOrderState(models.TextChoices):
    QUEUED = "queued", "Queued"
    SUBMITTING = "submitting", "Submitting"
    RUNNING = "running", "Running"
    RECONCILING = "reconciling", "Reconciling"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Partial without charge"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class AuditOrder(TenantScopedModel):
    """Durable work queue, idempotent remote intent and the frozen result of one purchase."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    binding = models.ForeignKey(SourceSiteBinding, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    membership_id = models.UUIDField()
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    requested_options = models.JSONField(default=dict)
    effective_options = models.JSONField(default=dict)
    state = models.CharField(
        max_length=20, choices=AuditOrderState.choices, default=AuditOrderState.QUEUED
    )
    remote_operation_id = models.UUIDField(null=True, blank=True)
    remote_audit_run_id = models.UUIDField(null=True, blank=True)
    remote_job_id = models.UUIDField(null=True, blank=True)
    remote_module_run_id = models.UUIDField(null=True, blank=True)
    credit_operation_key = models.CharField(max_length=120)
    credit_reservation_key = models.CharField(max_length=120, blank=True)
    credit_cost = models.PositiveIntegerField(default=0)
    credit_state = models.CharField(max_length=16, default="free")
    provider_cost_usd = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    report_snapshot = models.JSONField(default=dict)
    report_hash = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="seo_order_org_key_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "next_attempt_at"], name="seo_order_dispatch_idx"
            )
        ]


class AuditCallbackReceipt(TenantScopedModel):
    """Verified routing evidence only, never a copy of provider errors or secrets."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    order = models.ForeignKey(AuditOrder, on_delete=models.PROTECT)
    source_id = models.UUIDField()
    event_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    remote_module_run_id = models.UUIDField()
    remote_audit_run_id = models.UUIDField()
    status = models.CharField(max_length=20)
    received_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_id", "event_id"],
                name="seo_callback_org_source_event_uq",
            )
        ]
