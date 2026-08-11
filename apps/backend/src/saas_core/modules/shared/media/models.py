from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class MediaAssetState(models.TextChoices):
    PENDING = "pending", "Oczekuje na upload"
    UPLOADED = "uploaded", "Przesłany"
    SCANNING = "scanning", "Skanowany"
    READY = "ready", "Gotowy"
    REJECTED = "rejected", "Odrzucony"


class MediaAsset(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    original_filename = models.CharField(max_length=160)
    object_key = models.CharField(max_length=240, unique=True)
    declared_mime = models.CharField(max_length=80)
    detected_mime = models.CharField(max_length=80, blank=True)
    expected_size = models.PositiveBigIntegerField()
    actual_size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    state = models.CharField(
        max_length=16,
        choices=MediaAssetState,
        default=MediaAssetState.PENDING,
    )
    quota_reservation_key = models.CharField(max_length=120, unique=True)
    quota_committed = models.BooleanField(default=False)
    rejection_code = models.CharField(max_length=80, blank=True)
    upload_expires_at = models.DateTimeField()
    uploaded_at = models.DateTimeField(null=True, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_media_assets",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="media_asset_org_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_size__gte=1),
                name="media_asset_expected_size_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_size__isnull=True) | models.Q(actual_size__gte=1),
                name="media_asset_actual_size_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(quota_committed=False) | models.Q(state=MediaAssetState.READY),
                name="media_asset_quota_only_ready_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "created_at"],
                name="media_asset_org_state_idx",
            ),
            models.Index(
                fields=["organization", "id"],
                name="media_asset_org_id_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.id}:{self.state}"

    def clean(self) -> None:
        super().clean()
        if self.quota_committed and self.state != MediaAssetState.READY:
            raise ValidationError({"quota_committed": "Limit można rozliczyć tylko dla ready."})
        if self.state == MediaAssetState.REJECTED and not self.rejection_code:
            raise ValidationError({"rejection_code": "Odrzucony asset wymaga kodu powodu."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.original_filename = self.original_filename.strip()
        super().save(*args, **kwargs)
