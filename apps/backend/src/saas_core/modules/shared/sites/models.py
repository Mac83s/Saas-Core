from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


def canonical_json_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


class Site(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80)
    default_locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
        default="pl",
    )
    current_publication = models.ForeignKey(
        "Publication",
        on_delete=models.PROTECT,
        related_name="current_for_sites",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_sites",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "slug", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="sites_site_org_slug_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="sites_site_org_actor_idem_uq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "id"], name="sites_site_org_id_idx"),
            models.Index(
                fields=["organization", "current_publication"],
                name="sites_site_org_pub_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.slug}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)


class Page(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="pages")
    name = models.CharField(max_length=160)
    key = models.SlugField(max_length=80)
    version = models.PositiveBigIntegerField(default=0)
    current_draft = models.ForeignKey(
        "PageVersion",
        on_delete=models.PROTECT,
        related_name="current_for_pages",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_pages",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "key"],
                name="sites_page_org_site_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "created_by", "idempotency_key"],
                name="sites_page_org_site_actor_idem_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "id"],
                name="sites_page_org_site_idx",
            ),
            models.Index(
                fields=["organization", "current_draft"],
                name="sites_page_org_draft_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:{self.key}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Strona należy do innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.key = self.key.strip().lower()
        super().save(*args, **kwargs)


class PageVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    page = models.ForeignKey(Page, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveBigIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_page_versions",
    )
    idempotency_key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "page_id", "number")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "page", "number"],
                name="sites_version_org_page_number_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "page", "created_by", "idempotency_key"],
                name="sites_version_org_page_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1),
                name="sites_version_number_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "page", "created_at"],
                name="sites_version_org_page_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.page_id}:v{self.number}"

    def clean(self) -> None:
        super().clean()
        if self.page_id and self.page.organization_id != self.organization_id:
            raise ValidationError({"page": "Wersja należy do strony innej organizacji."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Wersja strony jest niemutowalna.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Wersja strony jest niemutowalna.")


class PageBlock(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    page_version = models.ForeignKey(
        PageVersion,
        on_delete=models.PROTECT,
        related_name="blocks",
    )
    position = models.PositiveIntegerField()
    block_type = models.CharField(max_length=120)
    schema_version = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "page_version_id", "position")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "page_version", "position"],
                name="sites_block_org_version_position_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="sites_block_schema_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    block_type__regex=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
                ),
                name="sites_block_type_format_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "page_version", "position"],
                name="sites_block_org_version_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.page_version_id}:{self.position}:{self.block_type}"

    def clean(self) -> None:
        super().clean()
        if (
            self.page_version_id
            and self.page_version.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"page_version": "Blok należy do wersji innej organizacji."}
            )
        if not isinstance(self.data, dict):
            raise ValidationError({"data": "Dane bloku muszą być obiektem JSON."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Blok wersji strony jest niemutowalny.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Blok wersji strony jest niemutowalny.")


class Publication(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="publications")
    sequence = models.PositiveBigIntegerField()
    snapshot_schema_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict)
    snapshot_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_site_publications",
    )
    source_publication = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="rollbacks",
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "site_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "site", "sequence"],
                name="sites_publication_org_site_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "site", "created_by", "idempotency_key"],
                name="sites_publication_org_site_actor_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="sites_publication_sequence_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(snapshot_schema_version__gte=1),
                name="sites_publication_schema_positive_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "site", "created_at"],
                name="sites_publication_org_site_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.site_id}:p{self.sequence}"

    def clean(self) -> None:
        super().clean()
        if self.site_id and self.site.organization_id != self.organization_id:
            raise ValidationError({"site": "Publikacja należy do innej organizacji."})
        if not isinstance(self.snapshot, dict):
            raise ValidationError({"snapshot": "Snapshot musi być obiektem JSON."})
        expected_hash = canonical_json_hash(self.snapshot)
        if self.snapshot_hash and self.snapshot_hash != expected_hash:
            raise ValidationError({"snapshot_hash": "Hash nie odpowiada snapshotowi."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Publikacja jest niemutowalna.")
        self.snapshot_hash = canonical_json_hash(self.snapshot)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Publikacja jest niemutowalna.")
