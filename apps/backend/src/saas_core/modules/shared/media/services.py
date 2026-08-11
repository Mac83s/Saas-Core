from __future__ import annotations

import hashlib
import json
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    reserve_quota,
)

from .models import MediaAsset, MediaAssetState
from .permissions import MEDIA_MANAGE, MEDIA_READ, STORAGE_BYTES, STORAGE_ENABLED
from .storage import ObjectNotFoundError, ObjectStorage, SignedUpload, get_object_storage

MEDIA_UPLOAD_INITIATED = "media.asset.upload_initiated"
MEDIA_UPLOAD_COMPLETED = "media.asset.upload_completed"

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


@dataclass(frozen=True, slots=True)
class MediaUploadIntent:
    asset: MediaAsset
    upload: SignedUpload
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


def complete_media_upload(
    *,
    asset_id: UUID,
    storage: ObjectStorage | None = None,
) -> MediaAsset:
    context = authorize_entitled(MEDIA_MANAGE, STORAGE_ENABLED)
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
        actor = User.objects.get(pk=context.actor_id)
        record_audit(
            organization=locked.organization,
            action=MEDIA_UPLOAD_COMPLETED,
            actor=actor,
            target_type="media_asset",
            target_id=locked.id,
            metadata={"actual_size": metadata.content_length},
        )
        return locked


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
