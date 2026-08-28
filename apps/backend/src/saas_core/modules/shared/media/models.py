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


class MediaReferenceOwner(models.TextChoices):
    PAGE_VERSION = "sites.page_version", "Wersja strony"
    CONTENT_ENTRY_VERSION = "sites.content_entry_version", "Wersja wpisu"
    PUBLICATION = "sites.publication", "Publikacja"


class MediaAsset(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    original_filename = models.CharField(max_length=160)
    object_key = models.CharField(max_length=240, unique=True)
    source_object_key = models.CharField(max_length=240, blank=True)
    declared_mime = models.CharField(max_length=80)
    detected_mime = models.CharField(max_length=80, blank=True)
    expected_size = models.PositiveBigIntegerField()
    actual_size = models.PositiveBigIntegerField(null=True, blank=True)
    stored_size = models.PositiveBigIntegerField(null=True, blank=True)
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
    variants = models.JSONField(default=dict, blank=True)
    rejection_code = models.CharField(max_length=80, blank=True)
    upload_expires_at = models.DateTimeField()
    uploaded_at = models.DateTimeField(null=True, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    cleanup_completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_media_assets",
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deleted_media_assets",
        null=True,
        blank=True,
    )
    deletion_idempotency_key = models.CharField(max_length=120, blank=True)
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
                condition=models.Q(stored_size__isnull=True) | models.Q(stored_size__gte=1),
                name="media_asset_stored_size_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(quota_committed=False)
                | models.Q(state=MediaAssetState.READY, stored_size__isnull=False),
                name="media_asset_quota_only_ready_ck",
            ),
            models.UniqueConstraint(
                fields=["organization", "deleted_by", "deletion_idempotency_key"],
                condition=models.Q(deleted_by__isnull=False)
                & ~models.Q(deletion_idempotency_key=""),
                name="media_asset_org_actor_delete_idem_uq",
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
            models.Index(
                fields=["organization", "deleted_at", "cleanup_completed_at"],
                name="media_asset_cleanup_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.id}:{self.state}"

    def clean(self) -> None:
        super().clean()
        if self.quota_committed and self.state != MediaAssetState.READY:
            raise ValidationError({"quota_committed": "Limit można rozliczyć tylko dla ready."})
        if self.quota_committed and self.stored_size is None:
            raise ValidationError({"stored_size": "Rozliczony asset wymaga rozmiaru storage."})
        if self.state == MediaAssetState.REJECTED and not self.rejection_code:
            raise ValidationError({"rejection_code": "Odrzucony asset wymaga kodu powodu."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.original_filename = self.original_filename.strip()
        super().save(*args, **kwargs)


class MediaReference(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    asset = models.ForeignKey(
        MediaAsset,
        on_delete=models.PROTECT,
        related_name="references",
    )
    owner_type = models.CharField(max_length=80, choices=MediaReferenceOwner)
    owner_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "owner_type", "owner_id", "asset_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "owner_type", "owner_id", "asset"],
                name="media_ref_org_owner_asset_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(owner_type__in=MediaReferenceOwner.values),
                name="media_ref_owner_type_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "owner_type", "owner_id"],
                name="media_ref_org_owner_idx",
            ),
            models.Index(
                fields=["organization", "asset", "owner_type"],
                name="media_ref_org_asset_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.owner_type}:{self.owner_id}:{self.asset_id}"

    def clean(self) -> None:
        super().clean()
        if self.asset_id and self.asset.organization_id != self.organization_id:
            raise ValidationError({"asset": "Referencja wskazuje media innej organizacji."})
