from __future__ import annotations

import logging
import math
from uuid import UUID

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    tenant_task_context,
)

from .scanner import MalwareScannerUnavailable
from .services import (
    cleanup_media_source_object,
    cleanup_tombstoned_media_asset,
    process_media_asset,
)
from .storage import ObjectStorageError

logger = logging.getLogger("saas_core.security")


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(MalwareScannerUnavailable, ObjectStorageError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_media_asset_task(
    asset_id: str,
    signed_tenant_context: str,
) -> None:
    try:
        parsed_asset_id = UUID(asset_id)
    except (TypeError, ValueError):
        logger.warning(
            "media_asset_task_identifier_rejected",
            extra={"security_event": "media.asset_task_identifier_rejected"},
        )
        return
    try:
        with tenant_task_context(
            signed_tenant_context,
            expected_causation_id=f"media-upload:{parsed_asset_id}",
        ):
            asset = process_media_asset(asset_id=parsed_asset_id)
            if asset is not None and asset.source_object_key:

                def enqueue_cleanup() -> None:
                    cleanup_media_source_object_task.delay(asset_id, signed_tenant_context)

                transaction.on_commit(enqueue_cleanup, robust=True)
    except InvalidTenantTaskContext:
        logger.warning(
            "media_asset_task_context_rejected",
            extra={"security_event": "media.asset_task_context_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(ObjectStorageError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def cleanup_media_source_object_task(
    asset_id: str,
    signed_tenant_context: str,
) -> None:
    try:
        parsed_asset_id = UUID(asset_id)
    except (TypeError, ValueError):
        return
    try:
        with tenant_task_context(
            signed_tenant_context,
            expected_causation_id=f"media-upload:{parsed_asset_id}",
        ):
            cleanup_media_source_object(asset_id=parsed_asset_id)
    except InvalidTenantTaskContext:
        logger.warning(
            "media_cleanup_task_context_rejected",
            extra={"security_event": "media.cleanup_task_context_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(ObjectStorageError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 8},
)
def cleanup_tombstoned_media_asset_task(
    asset_id: str,
    signed_tenant_context: str,
) -> None:
    try:
        parsed_asset_id = UUID(asset_id)
    except (TypeError, ValueError):
        logger.warning(
            "media_delete_task_identifier_rejected",
            extra={"security_event": "media.delete_task_identifier_rejected"},
        )
        return
    try:
        with tenant_task_context(
            signed_tenant_context,
            expected_causation_id=f"media-delete:{parsed_asset_id}",
        ):
            asset = cleanup_tombstoned_media_asset(asset_id=parsed_asset_id)
            if (
                asset is not None
                and asset.deleted_at is not None
                and asset.cleanup_completed_at is None
                and asset.upload_expires_at > timezone.now()
            ):
                cleanup_tombstoned_media_asset_task.apply_async(
                    args=[asset_id, signed_tenant_context],
                    countdown=max(
                        1,
                        math.ceil((asset.upload_expires_at - timezone.now()).total_seconds()),
                    ),
                )
    except InvalidTenantTaskContext:
        logger.warning(
            "media_delete_task_context_rejected",
            extra={"security_event": "media.delete_task_context_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(ObjectStorageError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def purge_erased_objects() -> int:
    """Delete the storage objects an erased tenant left behind (ADR-042).

    PostgreSQL cannot roll back object storage, so erasure deletes rows first
    and writes the object keys onto the receipt. Until this has emptied that
    list, the erasure is not finished — which is why the receipt says so rather
    than pretending the work is done.

    It lives in `media` because Core may not import Shared: erasure writes down
    what has to go, this is what knows how.
    """
    from saas_core.modules.core.organizations.models import (  # noqa: PLC0415
        ErasureReceipt,
    )

    from .storage import get_object_storage  # noqa: PLC0415

    storage = get_object_storage()
    deleted = 0
    for receipt in ErasureReceipt.objects.filter(objects_completed_at__isnull=True):
        remaining: list[str] = []
        for object_key in list(receipt.pending_object_keys):
            try:
                storage.delete(object_key=object_key)
            except ObjectStorageError:
                # Keep it on the list. A file that outlives its row is exactly
                # what this sweep exists to notice, so it must not be dropped.
                remaining.append(object_key)
                continue
            deleted += 1
        receipt.deleted_object_count += len(receipt.pending_object_keys) - len(remaining)
        receipt.pending_object_keys = remaining
        if not remaining:
            receipt.objects_completed_at = timezone.now()
        receipt.save(
            update_fields=[
                "pending_object_keys",
                "deleted_object_count",
                "objects_completed_at",
            ]
        )
    return deleted
