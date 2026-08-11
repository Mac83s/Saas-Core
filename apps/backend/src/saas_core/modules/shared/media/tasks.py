from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task
from django.db import transaction

from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    tenant_task_context,
)

from .scanner import MalwareScannerUnavailable
from .services import cleanup_media_source_object, process_media_asset
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
