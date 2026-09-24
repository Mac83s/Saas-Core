from __future__ import annotations

import hashlib
import json
import math
import secrets
import unicodedata
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    current_tenant_context,
    require_tenant_context,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    QuotaExceeded,
    adjust_quota_reservation,
    authorize_entitled,
    commit_quota,
    extend_quota_reservation,
    release_committed_quota,
    release_quota,
    reserve_quota,
)

from .images import AI_GENERATED_XMP, UnsafeImageError, process_image
from .models import (
    AiOrigin,
    MediaAsset,
    MediaAssetState,
    MediaReference,
    MediaReferenceOwner,
)
from .permissions import (
    MEDIA_MANAGE,
    MEDIA_READ,
    MEDIA_TEMPLATE_IMPORT,
    STORAGE_BYTES,
    STORAGE_ENABLED,
)
from .scanner import (
    MalwareScanner,
    MalwareScannerUnavailable,
    MalwareVerdict,
    get_malware_scanner,
)
from .storage import (
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    ObjectTooLargeError,
    SignedUpload,
    get_object_storage,
)

MEDIA_UPLOAD_INITIATED = "media.asset.upload_initiated"
MEDIA_UPLOAD_COMPLETED = "media.asset.upload_completed"
MEDIA_ASSET_READY = "media.asset.ready"
MEDIA_ASSET_REJECTED = "media.asset.rejected"
MEDIA_ASSET_TOMBSTONED = "media.asset.tombstoned"
MEDIA_ASSET_CLEANED = "media.asset.cleaned"

ALLOWED_MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MediaIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inne żądanie albo wygasły upload."
    default_code = "media_idempotency_conflict"


class UnsupportedMediaType(APIException):
    status_code = 400
    default_detail = "Dozwolone są wyłącznie obrazy JPEG, PNG i WebP."
    default_code = "unsupported_media_type"


class MediaUploadTooLarge(APIException):
    status_code = 400
    default_detail = "Plik przekracza maksymalny rozmiar uploadu."
    default_code = "media_upload_too_large"


class MediaFilenameInvalid(APIException):
    status_code = 400
    default_detail = "Nazwa pliku jest nieprawidłowa."
    default_code = "media_filename_invalid"


class MediaAssetNotFound(NotFound):
    default_detail = "Asset nie istnieje."
    default_code = "media_asset_not_found"


class MediaUploadMissing(APIException):
    status_code = 409
    default_detail = "Obiekt uploadu nie jest jeszcze dostępny."
    default_code = "media_upload_missing"


class MediaUploadExpired(APIException):
    status_code = 409
    default_detail = "Upload wygasł. Rozpocznij nowy upload."
    default_code = "media_upload_expired"


class MediaUploadMetadataMismatch(APIException):
    status_code = 409
    default_detail = "Rozmiar albo typ obiektu nie zgadza się z rozpoczętym uploadem."
    default_code = "media_upload_metadata_mismatch"


class MediaScannerUnavailable(APIException):
    """The scanner did not answer in time (a loaded host): nothing was stored,
    and the same request can simply be sent again."""

    status_code = 503
    default_detail = "Skaner plików jest chwilowo zajęty. Spróbuj ponownie za chwilę."
    default_code = "media_scanner_unavailable"


class ApprovedMediaMaterializationFailed(APIException):
    status_code = 409
    default_detail = "Zatwierdzone medium szablonu nie mogło zostać przygotowane."
    default_code = "approved_media_materialization_failed"


@dataclass(frozen=True, slots=True)
class MediaUploadIntent:
    asset: MediaAsset
    upload: SignedUpload
    created: bool


@dataclass(frozen=True, slots=True)
class MediaDeletion:
    asset: MediaAsset
    created: bool


@dataclass(frozen=True, slots=True)
class ApprovedMediaMaterialization:
    asset: MediaAsset
    created: bool


def list_media_assets(*, cursor: UUID | None, limit: int) -> tuple[list[MediaAsset], UUID | None]:
    context = authorize_entitled(
        MEDIA_READ,
        STORAGE_ENABLED,
        operation=FeatureOperation.READ,
    )
    queryset = MediaAsset.all_objects.filter(
        organization_id=context.organization_id,
        deleted_at__isnull=True,
    ).order_by("id")
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


class MediaPreviewUnavailable(APIException):
    status_code = 503
    default_detail = "Podgląd medium jest chwilowo niedostępny."
    default_code = "media_preview_unavailable"


def read_media_preview(*, asset_id: UUID, storage: ObjectStorage | None = None) -> bytes:
    context = authorize_entitled(MEDIA_READ, STORAGE_ENABLED, operation=FeatureOperation.READ)
    asset = MediaAsset.all_objects.filter(
        id=asset_id,
        organization_id=context.organization_id,
        deleted_at__isnull=True,
        state=MediaAssetState.READY,
    ).first()
    if asset is None:
        raise MediaAssetNotFound()
    # Only our processed WebP is readable, never an uploaded original or an
    # arbitrary object key supplied in JSON metadata.
    preview = asset.variants.get("preview")
    object_key = _variant_object_key(asset, "preview")
    if (
        not isinstance(preview, dict)
        or preview.get("object_key") != object_key
        or preview.get("content_type") != "image/webp"
    ):
        raise MediaAssetNotFound()
    try:
        return (storage or get_object_storage()).read(
            object_key=object_key,
            max_bytes=10 * 1024**2,
        )
    except ObjectNotFoundError as error:
        raise MediaAssetNotFound() from error
    except (ObjectStorageError, ObjectTooLargeError) as error:
        raise MediaPreviewUnavailable() from error


@transaction.atomic
def initiate_media_upload(
    *,
    filename: str,
    content_type: str,
    size: int,
    idempotency_key: str,
    storage: ObjectStorage | None = None,
) -> MediaUploadIntent:
    context = authorize_entitled(MEDIA_MANAGE, STORAGE_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_name = _safe_filename(filename)
    normalized_type = content_type.strip().lower()
    extension = ALLOWED_MEDIA_TYPES.get(normalized_type)
    if extension is None:
        raise UnsupportedMediaType
    if size > settings.MEDIA_MAX_UPLOAD_BYTES:
        raise MediaUploadTooLarge

    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    request_hash = _canonical_hash({
        "filename": normalized_name,
        "content_type": normalized_type,
        "size": size,
    })
    existing = MediaAsset.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash or existing.upload_expires_at <= timezone.now():
            raise MediaIdempotencyConflict
        return MediaUploadIntent(
            asset=existing,
            upload=_sign_upload(existing, storage=storage),
            created=False,
        )

    upload_expires_at = timezone.now() + timedelta(seconds=settings.MEDIA_UPLOAD_URL_TTL_SECONDS)
    quota_key = _quota_idempotency_key(
        organization_id=context.organization_id,
        actor_id=context.actor_id,
        idempotency_key=normalized_key,
    )
    reserve_quota(
        STORAGE_BYTES,
        amount=size,
        idempotency_key=quota_key,
        expires_at=upload_expires_at,
    )

    actor = User.objects.get(pk=context.actor_id)
    asset = MediaAsset.all_objects.create(
        organization=organization,
        original_filename=normalized_name,
        object_key=(f"{context.organization_id}/originals/{secrets.token_urlsafe(32)}{extension}"),
        declared_mime=normalized_type,
        expected_size=size,
        quota_reservation_key=quota_key,
        upload_expires_at=upload_expires_at,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=organization,
        action=MEDIA_UPLOAD_INITIATED,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={"content_type": normalized_type, "expected_size": size},
    )
    return MediaUploadIntent(
        asset=asset,
        upload=_sign_upload(asset, storage=storage),
        created=True,
    )


@transaction.atomic
def materialize_approved_media_asset(
    *,
    source_key: str,
    filename: str,
    content_type: str,
    content: bytes,
    ai_origin: str = AiOrigin.NONE,
    storage: ObjectStorage | None = None,
    scanner: MalwareScanner | None = None,
) -> ApprovedMediaMaterialization:
    """Import server-approved template bytes, never a client-supplied upload.

    Callers must resolve the bytes from a checksum-verified template catalogue.
    The narrow template permission grants no upload, completion or deletion API.
    """
    active = current_tenant_context()
    permission = (
        MEDIA_MANAGE
        if active is not None and active.has_permission(MEDIA_MANAGE)
        else MEDIA_TEMPLATE_IMPORT
    )
    context = authorize_entitled(permission, STORAGE_ENABLED)
    object_storage = storage or get_object_storage()
    asset, created = _stage_approved_bytes(
        context=context,
        source_key=source_key,
        filename=filename,
        content_type=content_type,
        content=content,
        ai_origin=ai_origin,
        storage=object_storage,
        enqueue_processing=True,
    )
    if not created:
        if asset.state != MediaAssetState.READY:
            raise MediaIdempotencyConflict
        return ApprovedMediaMaterialization(asset=asset, created=False)
    cleanup_keys = (
        asset.object_key,
        _processed_object_key(asset),
        _variant_object_key(asset, "thumbnail"),
        _variant_object_key(asset, "preview"),
    )
    try:
        processed = process_media_asset(
            asset_id=asset.id,
            storage=object_storage,
            scanner=scanner,
        )
        if processed is None or processed.state != MediaAssetState.READY:
            raise ApprovedMediaMaterializationFailed
    except Exception as error:
        for object_key in cleanup_keys:
            with suppress(ObjectStorageError):
                object_storage.delete(object_key=object_key)
        if isinstance(error, MalwareScannerUnavailable):
            raise MediaScannerUnavailable from error
        raise
    return ApprovedMediaMaterialization(asset=processed, created=True)


@transaction.atomic
def stage_generated_media_asset(
    *,
    source_key: str,
    filename: str,
    content_type: str,
    content: bytes,
    storage: ObjectStorage | None = None,
) -> MediaAsset:
    """Store the provider's bytes as an uploaded AI asset, without processing it.

    The caller (the image-generation worker) runs `process_media_asset` itself in
    a later transaction, so there is one processing path and the Organization
    lock is held only here. The same source key returns the same asset.
    """
    context = authorize_entitled(MEDIA_MANAGE, STORAGE_ENABLED)
    asset, _created = _stage_approved_bytes(
        context=context,
        source_key=source_key,
        filename=filename,
        content_type=content_type,
        content=content,
        ai_origin=AiOrigin.GENERATED,
        storage=storage or get_object_storage(),
        enqueue_processing=False,
    )
    return asset


def _stage_approved_bytes(
    *,
    context: TenantContext,
    source_key: str,
    filename: str,
    content_type: str,
    content: bytes,
    ai_origin: str,
    storage: ObjectStorage,
    enqueue_processing: bool,
) -> tuple[MediaAsset, bool]:
    """Create, store and complete a server-held asset; the caller's transaction."""
    normalized_source_key = _idempotency_key(source_key)
    normalized_name = _safe_filename(filename)
    normalized_type = content_type.strip().lower()
    extension = ALLOWED_MEDIA_TYPES.get(normalized_type)
    if extension is None:
        raise UnsupportedMediaType
    if not content or len(content) > settings.MEDIA_MAX_UPLOAD_BYTES:
        raise MediaUploadTooLarge
    origin = AiOrigin(ai_origin)

    content_sha256 = hashlib.sha256(content).hexdigest()
    request_hash = _canonical_hash({
        "source_key": normalized_source_key,
        "filename": normalized_name,
        "content_type": normalized_type,
        "size": len(content),
        "sha256": content_sha256,
    })
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    asset_id = uuid5(
        NAMESPACE_URL,
        f"saas-core:approved-media:{context.organization_id}:{normalized_source_key}",
    )
    existing = MediaAsset.all_objects.filter(
        pk=asset_id,
        organization_id=context.organization_id,
    ).first()
    if existing is not None:
        # Provenance is compared beside the hash, not inside it, so assets
        # materialized before ai_origin existed still match their re-import.
        if existing.request_hash != request_hash or existing.ai_origin != origin:
            raise MediaIdempotencyConflict
        return existing, False

    quota_identity = f"{context.organization_id}:{normalized_source_key}"
    quota_key = f"approved-media:{hashlib.sha256(quota_identity.encode()).hexdigest()}"
    reserve_quota(
        STORAGE_BYTES,
        amount=len(content),
        idempotency_key=quota_key,
        expires_at=timezone.now()
        + timedelta(seconds=settings.MEDIA_PROCESSING_RESERVATION_TTL_SECONDS),
    )
    actor = User.objects.get(pk=context.actor_id)
    asset = MediaAsset.all_objects.create(
        id=asset_id,
        organization=organization,
        original_filename=normalized_name,
        object_key=f"{context.organization_id}/originals/{asset_id}{extension}",
        declared_mime=normalized_type,
        expected_size=len(content),
        quota_reservation_key=quota_key,
        upload_expires_at=timezone.now()
        + timedelta(seconds=settings.MEDIA_PROCESSING_RESERVATION_TTL_SECONDS),
        created_by=actor,
        idempotency_key=normalized_source_key,
        request_hash=request_hash,
        ai_origin=origin,
    )
    record_audit(
        organization=organization,
        action=MEDIA_UPLOAD_INITIATED,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={
            "approved_source": normalized_source_key,
            "content_type": normalized_type,
            "expected_size": len(content),
        },
    )
    original_key = asset.object_key
    try:
        storage.put(object_key=original_key, content=content, content_type=normalized_type)
        asset = _complete_media_upload(
            context=context,
            asset_id=asset.id,
            storage=storage,
            enqueue_processing=enqueue_processing,
        )
    except Exception:
        # Object storage does not roll back with PostgreSQL.
        with suppress(ObjectStorageError):
            storage.delete(object_key=original_key)
        raise
    return asset, True


def discard_approved_media_asset_objects(
    *,
    asset: MediaAsset,
    storage: ObjectStorage | None = None,
) -> None:
    context = require_tenant_context()
    if asset.organization_id != context.organization_id:
        raise MediaAssetNotFound
    object_storage = storage or get_object_storage()
    for object_key in _stored_object_keys(asset):
        with suppress(ObjectStorageError):
            object_storage.delete(object_key=object_key)


def complete_media_upload(
    *,
    asset_id: UUID,
    storage: ObjectStorage | None = None,
) -> MediaAsset:
    context = authorize_entitled(MEDIA_MANAGE, STORAGE_ENABLED)
    return _complete_media_upload(context=context, asset_id=asset_id, storage=storage)


def _complete_media_upload(
    *,
    context: TenantContext,
    asset_id: UUID,
    storage: ObjectStorage | None,
    enqueue_processing: bool = True,
) -> MediaAsset:
    asset = MediaAsset.all_objects.filter(
        pk=asset_id,
        organization_id=context.organization_id,
        deleted_at__isnull=True,
    ).first()
    if asset is None:
        raise MediaAssetNotFound
    if asset.state != MediaAssetState.PENDING:
        return asset
    if asset.upload_expires_at <= timezone.now():
        raise MediaUploadExpired

    try:
        metadata = (storage or get_object_storage()).head(object_key=asset.object_key)
    except ObjectNotFoundError as error:
        raise MediaUploadMissing from error
    if (
        metadata.content_length != asset.expected_size
        or _base_content_type(metadata.content_type) != asset.declared_mime
    ):
        raise MediaUploadMetadataMismatch

    with transaction.atomic():
        locked = (
            MediaAsset.all_objects.select_for_update()
            .filter(
                pk=asset.id,
                organization_id=context.organization_id,
                deleted_at__isnull=True,
            )
            .first()
        )
        if locked is None:
            raise MediaAssetNotFound
        if locked.state != MediaAssetState.PENDING:
            return locked
        if locked.upload_expires_at <= timezone.now():
            raise MediaUploadExpired
        locked.state = MediaAssetState.UPLOADED
        locked.actual_size = metadata.content_length
        locked.uploaded_at = timezone.now()
        locked.save(update_fields=["state", "actual_size", "uploaded_at", "updated_at"])
        extend_quota_reservation(
            locked.quota_reservation_key,
            expires_at=timezone.now()
            + timedelta(seconds=settings.MEDIA_PROCESSING_RESERVATION_TTL_SECONDS),
        )
        actor = User.objects.get(pk=context.actor_id)
        record_audit(
            organization=locked.organization,
            action=MEDIA_UPLOAD_COMPLETED,
            actor=actor,
            target_type="media_asset",
            target_id=locked.id,
            metadata={"actual_size": metadata.content_length},
        )
        if not enqueue_processing:
            # The caller processes the asset itself; one processing path only.
            return locked
        task_contract = issue_tenant_task_contract(causation_id=f"media-upload:{locked.id}")

        def enqueue() -> None:
            from .tasks import process_media_asset_task

            process_media_asset_task.delay(str(locked.id), task_contract)

        transaction.on_commit(enqueue, robust=True)
        return locked


@transaction.atomic
def tombstone_media_asset(
    *,
    asset_id: UUID,
    idempotency_key: str,
) -> MediaDeletion:
    context = authorize_entitled(MEDIA_MANAGE, STORAGE_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    existing = MediaAsset.all_objects.filter(
        organization_id=context.organization_id,
        deleted_by_id=context.actor_id,
        deletion_idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.id != asset_id:
            raise MediaIdempotencyConflict
        if existing.cleanup_completed_at is None:
            _schedule_tombstone_cleanup(existing)
        return MediaDeletion(existing, False)

    asset = (
        MediaAsset.all_objects.select_for_update()
        .filter(pk=asset_id, organization_id=context.organization_id)
        .first()
    )
    if asset is None:
        raise MediaAssetNotFound
    if asset.deleted_at is not None:
        if asset.cleanup_completed_at is None:
            _schedule_tombstone_cleanup(asset)
        return MediaDeletion(asset, False)

    actor = User.objects.get(pk=context.actor_id)
    asset.deleted_at = timezone.now()
    asset.deleted_by = actor
    asset.deletion_idempotency_key = normalized_key
    asset.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "deletion_idempotency_key",
            "updated_at",
        ]
    )
    publication_reference_count = MediaReference.all_objects.filter(
        organization_id=context.organization_id,
        asset_id=asset.id,
        owner_type=MediaReferenceOwner.PUBLICATION,
    ).count()
    record_audit(
        organization=organization,
        action=MEDIA_ASSET_TOMBSTONED,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={"publication_reference_count": publication_reference_count},
    )
    _schedule_tombstone_cleanup(asset)
    return MediaDeletion(asset, True)


def process_media_asset(
    *,
    asset_id: UUID,
    storage: ObjectStorage | None = None,
    scanner: MalwareScanner | None = None,
) -> MediaAsset | None:
    context = require_tenant_context()
    asset = (
        MediaAsset.all_objects.select_for_update()
        .filter(pk=asset_id, organization_id=context.organization_id)
        .first()
    )
    if asset is None or asset.state in {MediaAssetState.READY, MediaAssetState.REJECTED}:
        return asset
    if asset.state == MediaAssetState.PENDING or asset.deleted_at is not None:
        return asset

    asset.state = MediaAssetState.SCANNING
    asset.save(update_fields=["state", "updated_at"])
    object_storage = storage or get_object_storage()
    malware_scanner = scanner or get_malware_scanner()
    try:
        raw_content = object_storage.read(
            object_key=asset.object_key,
            max_bytes=settings.MEDIA_MAX_UPLOAD_BYTES,
        )
    except (ObjectNotFoundError, ObjectTooLargeError):
        return _reject_media_asset(
            asset,
            code="media_object_invalid",
            storage=object_storage,
            scanned_at=None,
        )
    if len(raw_content) != asset.expected_size or len(raw_content) != asset.actual_size:
        return _reject_media_asset(
            asset,
            code="media_size_mismatch",
            storage=object_storage,
            scanned_at=None,
        )

    checked_at = timezone.now()
    if malware_scanner.scan(raw_content) == MalwareVerdict.INFECTED:
        return _reject_media_asset(
            asset,
            code="media_malware_detected",
            storage=object_storage,
            scanned_at=checked_at,
        )
    try:
        processed = process_image(
            raw_content,
            declared_mime=asset.declared_mime,
            xmp=AI_GENERATED_XMP if asset.ai_origin != AiOrigin.NONE else None,
        )
    except UnsafeImageError:
        return _reject_media_asset(
            asset,
            code="media_image_invalid",
            storage=object_storage,
            scanned_at=checked_at,
        )

    variants: dict[str, dict[str, object]] = {}
    variant_keys: list[str] = []
    variant_size = 0
    for variant in processed.variants:
        object_key = _variant_object_key(asset, variant.kind)
        variant_keys.append(object_key)
        object_storage.put(
            object_key=object_key,
            content=variant.content,
            content_type=variant.content_type,
        )
        variant_size += len(variant.content)
        variants[variant.kind] = {
            "object_key": object_key,
            "content_type": variant.content_type,
            "size": len(variant.content),
            "width": variant.width,
            "height": variant.height,
        }
    processed_object_key = _processed_object_key(asset)
    object_storage.put(
        object_key=processed_object_key,
        content=processed.content,
        content_type=processed.content_type,
    )
    stored_size = len(processed.content) + variant_size
    try:
        adjust_quota_reservation(asset.quota_reservation_key, amount=stored_size)
    except QuotaExceeded:
        return _reject_media_asset(
            asset,
            code="media_quota_exceeded",
            storage=object_storage,
            scanned_at=checked_at,
            extra_object_keys=[*variant_keys, processed_object_key],
        )
    commit_quota(asset.quota_reservation_key)

    asset.state = MediaAssetState.READY
    asset.source_object_key = asset.object_key
    asset.object_key = processed_object_key
    asset.detected_mime = processed.content_type
    asset.stored_size = stored_size
    asset.sha256 = processed.sha256
    asset.width = processed.width
    asset.height = processed.height
    asset.variants = variants
    asset.quota_committed = True
    asset.scanned_at = checked_at
    asset.ready_at = timezone.now()
    asset.rejection_code = ""
    asset.save(
        update_fields=[
            "state",
            "source_object_key",
            "object_key",
            "detected_mime",
            "stored_size",
            "sha256",
            "width",
            "height",
            "variants",
            "quota_committed",
            "scanned_at",
            "ready_at",
            "rejection_code",
            "updated_at",
        ]
    )
    actor = User.objects.get(pk=context.actor_id)
    record_audit(
        organization=asset.organization,
        action=MEDIA_ASSET_READY,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={
            "content_type": processed.content_type,
            "stored_size": stored_size,
            "variant_kinds": sorted(variants),
        },
    )
    return asset


def ai_generated_asset_ids(*, organization_id: UUID, asset_ids: Iterable[str]) -> set[str]:
    """The AI-generated subset of `asset_ids`; the caller has set the tenant."""
    ids = list(asset_ids)
    if not ids:
        return set()
    return {
        str(pk)
        for pk in MediaAsset.all_objects.filter(
            organization_id=organization_id,
            pk__in=ids,
            ai_origin=AiOrigin.GENERATED,
        ).values_list("pk", flat=True)
    }


def cleanup_media_source_object(
    *,
    asset_id: UUID,
    storage: ObjectStorage | None = None,
) -> MediaAsset | None:
    context = require_tenant_context()
    asset = (
        MediaAsset.all_objects.select_for_update()
        .filter(pk=asset_id, organization_id=context.organization_id)
        .first()
    )
    if asset is None or not asset.source_object_key:
        return asset
    (storage or get_object_storage()).delete(object_key=asset.source_object_key)
    asset.source_object_key = ""
    asset.save(update_fields=["source_object_key", "updated_at"])
    return asset


@transaction.atomic
def cleanup_tombstoned_media_asset(
    *,
    asset_id: UUID,
    storage: ObjectStorage | None = None,
) -> MediaAsset | None:
    context = require_tenant_context()
    asset = (
        MediaAsset.all_objects.select_for_update()
        .filter(pk=asset_id, organization_id=context.organization_id)
        .first()
    )
    if (
        asset is None
        or asset.deleted_at is None
        or asset.cleanup_completed_at is not None
        or asset.upload_expires_at > timezone.now()
    ):
        return asset
    if MediaReference.all_objects.filter(
        organization_id=context.organization_id,
        asset_id=asset.id,
        owner_type=MediaReferenceOwner.PUBLICATION,
    ).exists():
        return asset

    object_keys = _stored_object_keys(asset)
    object_storage = storage or get_object_storage()
    for object_key in object_keys:
        object_storage.delete(object_key=object_key)
    if asset.quota_committed:
        release_committed_quota(asset.quota_reservation_key)
        asset.quota_committed = False
    else:
        release_quota(asset.quota_reservation_key)
    asset.cleanup_completed_at = timezone.now()
    asset.source_object_key = ""
    asset.save(
        update_fields=[
            "quota_committed",
            "cleanup_completed_at",
            "source_object_key",
            "updated_at",
        ]
    )
    actor = asset.deleted_by or User.objects.get(pk=context.actor_id)
    record_audit(
        organization=asset.organization,
        action=MEDIA_ASSET_CLEANED,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={
            "object_count": len(object_keys),
            "released_storage_bytes": asset.stored_size or 0,
        },
    )
    return asset


def _reject_media_asset(
    asset: MediaAsset,
    *,
    code: str,
    storage: ObjectStorage,
    scanned_at: datetime | None,
    extra_object_keys: list[str] | None = None,
) -> MediaAsset:
    for object_key in [*(extra_object_keys or []), asset.object_key]:
        storage.delete(object_key=object_key)
    release_quota(asset.quota_reservation_key)
    asset.state = MediaAssetState.REJECTED
    asset.rejection_code = code
    asset.rejected_at = timezone.now()
    if scanned_at is not None:
        asset.scanned_at = scanned_at
    asset.save(
        update_fields=[
            "state",
            "rejection_code",
            "rejected_at",
            "scanned_at",
            "updated_at",
        ]
    )
    context = require_tenant_context()
    actor = User.objects.get(pk=context.actor_id)
    record_audit(
        organization=asset.organization,
        action=MEDIA_ASSET_REJECTED,
        actor=actor,
        target_type="media_asset",
        target_id=asset.id,
        metadata={"reason": code},
    )
    return asset


def _variant_object_key(asset: MediaAsset, kind: str) -> str:
    return f"{asset.organization_id}/variants/{asset.id}/{kind}.webp"


def _processed_object_key(asset: MediaAsset) -> str:
    extension = ALLOWED_MEDIA_TYPES[asset.declared_mime]
    return f"{asset.organization_id}/processed/{asset.id}/original{extension}"


def _stored_object_keys(asset: MediaAsset) -> tuple[str, ...]:
    variant_keys = [
        variant.get("object_key")
        for variant in asset.variants.values()
        if isinstance(variant, dict)
    ]
    return tuple(
        dict.fromkeys(
            object_key
            for object_key in [asset.object_key, asset.source_object_key, *variant_keys]
            if isinstance(object_key, str) and object_key
        )
    )


def _schedule_tombstone_cleanup(asset: MediaAsset) -> None:
    task_contract = issue_tenant_task_contract(causation_id=f"media-delete:{asset.id}")
    countdown = max(
        0,
        math.ceil((asset.upload_expires_at - timezone.now()).total_seconds()),
    )

    def enqueue_cleanup() -> None:
        from .tasks import cleanup_tombstoned_media_asset_task

        cleanup_tombstoned_media_asset_task.apply_async(
            args=[str(asset.id), task_contract],
            countdown=countdown,
        )

    transaction.on_commit(enqueue_cleanup, robust=True)


def _sign_upload(asset: MediaAsset, *, storage: ObjectStorage | None) -> SignedUpload:
    expires_in = max(1, int((asset.upload_expires_at - timezone.now()).total_seconds()))
    return (storage or get_object_storage()).sign_put(
        object_key=asset.object_key,
        content_type=asset.declared_mime,
        expires_in=expires_in,
    )


def _base_content_type(value: str) -> str:
    return value.partition(";")[0].strip().lower()


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise MediaIdempotencyConflict
    return normalized


def _safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\\", "/")
    basename = PurePosixPath(normalized).name.strip()
    basename = "".join(
        character for character in basename if not unicodedata.category(character).startswith("C")
    )
    if not basename or basename in {".", ".."} or len(basename) > 160:
        raise MediaFilenameInvalid
    return basename


def _quota_idempotency_key(*, organization_id: UUID, actor_id: UUID, idempotency_key: str) -> str:
    digest = _canonical_hash({
        "endpoint": "media.upload.initiate",
        "organization_id": str(organization_id),
        "actor_id": str(actor_id),
        "key": idempotency_key,
    })
    return f"media-upload:{digest}"


def _canonical_hash(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
