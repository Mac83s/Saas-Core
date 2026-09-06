from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class GscWorkspaceState(TenantScopedModel):
    """Conservative erasure fence: unknown remote outcomes remain cleanup-required."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    source_id = models.UUIDField()
    cleanup_required = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_id"], name="seo_gsc_workspace_uq"
            )
        ]


class GscOAuthAttempt(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    binding = models.ForeignKey("seo.SourceSiteBinding", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    session_id = models.UUIDField()
    session_hash = models.CharField(max_length=64)
    state_hash = models.CharField(max_length=64, unique=True)
    locale = models.CharField(max_length=2, default="pl")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()


class GscGrantIntent(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    binding = models.ForeignKey("seo.SourceSiteBinding", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    property_id = models.UUIDField()
    expires_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    remote_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="seo_gsc_grant_key_uq"
            )
        ]


class GscSyncIntent(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    grant = models.ForeignKey(GscGrantIntent, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    client_reference = models.UUIDField()
    start_date = models.DateField()
    end_date = models.DateField()
    remote_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "client_reference"], name="seo_gsc_sync_ref_uq"
            )
        ]
