from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from saas_core.modules.core.organizations.tasks import InvalidTenantTaskContext, tenant_task_context

from .billing_notices import deliver_billing_notices
from .delivery import DeliveryDeferred, deliver_email, deliver_webhook, process_provider_status
from .metrics import PENDING_TASKS
from .models import DeliveryStatus, ExportStatus, PendingTaskRoute
from .security import decrypt_secret
from .services import build_data_export, expire_data_export, scrub_notification_message

logger = logging.getLogger("saas_core.security")


@shared_task(bind=True, max_retries=8)  # type: ignore[untyped-decorator]
def deliver_email_task(self: Any, message_id: str, signed_tenant_context: str) -> None:
    try:
        parsed = UUID(message_id)
        with tenant_task_context(signed_tenant_context, expected_causation_id=f"email:{parsed}"):
            message = deliver_email(parsed)
        if message.status != DeliveryStatus.QUEUED:
            _complete_route("email", message_id)
    except DeliveryDeferred as error:
        raise self.retry(countdown=error.countdown) from error
    except (InvalidTenantTaskContext, ValueError):
        logger.warning(
            "notifications_email_task_rejected",
            extra={"security_event": "notifications.email_task_rejected"},
        )


@shared_task(bind=True, max_retries=10)  # type: ignore[untyped-decorator]
def deliver_webhook_task(self: Any, delivery_id: str, signed_tenant_context: str) -> None:
    try:
        parsed = UUID(delivery_id)
        with tenant_task_context(signed_tenant_context, expected_causation_id=None):
            delivery = deliver_webhook(parsed)
        if delivery.status != DeliveryStatus.QUEUED:
            _complete_route("webhook", delivery_id)
    except DeliveryDeferred as error:
        raise self.retry(countdown=error.countdown) from error
    except (InvalidTenantTaskContext, ValueError):
        logger.warning(
            "notifications_webhook_task_rejected",
            extra={"security_event": "notifications.webhook_task_rejected"},
        )


@shared_task  # type: ignore[untyped-decorator]
def process_provider_status_task(event_id: str, signed_tenant_context: str) -> None:
    try:
        with tenant_task_context(signed_tenant_context, expected_causation_id=None):
            process_provider_status(event_id)
        _complete_route("provider_status", event_id)
    except InvalidTenantTaskContext:
        logger.warning(
            "notifications_provider_task_rejected",
            extra={"security_event": "notifications.provider_task_rejected"},
        )


@shared_task  # type: ignore[untyped-decorator]
def build_data_export_task(export_id: str, signed_tenant_context: str) -> None:
    try:
        parsed = UUID(export_id)
        with tenant_task_context(signed_tenant_context, expected_causation_id=f"export:{parsed}"):
            export = build_data_export(parsed)
        if export.status == ExportStatus.READY:
            _complete_route("export", export_id)
    except (InvalidTenantTaskContext, ValueError):
        logger.warning(
            "notifications_export_task_rejected",
            extra={"security_event": "notifications.export_task_rejected"},
        )


@shared_task(name="saas_core.modules.shared.notifications.tasks.recover_pending")  # type: ignore[untyped-decorator]
def recover_pending() -> int:
    now = timezone.now()
    pending_counts = {
        item["kind"]: item["total"]
        for item in PendingTaskRoute.objects.filter(completed_at__isnull=True)
        .values("kind")
        .annotate(total=Count("id"))
    }
    for kind in ("email", "webhook", "provider_status", "export"):
        PENDING_TASKS.labels(kind=kind).set(pending_counts.get(kind, 0))
    with transaction.atomic():
        routes = list(
            PendingTaskRoute.objects.select_for_update(skip_locked=True)
            .filter(completed_at__isnull=True, next_dispatch_at__lte=now)
            .order_by("next_dispatch_at")[:100]
        )
        for route in routes:
            route.next_dispatch_at = now + timedelta(minutes=5)
            route.save(update_fields=["next_dispatch_at"])
    for route in routes:
        signed_context = decrypt_secret(route.tenant_context_ciphertext)
        if route.kind == "email":
            deliver_email_task.delay(route.object_key, signed_context)
        elif route.kind == "webhook":
            deliver_webhook_task.delay(route.object_key, signed_context)
        elif route.kind == "provider_status":
            process_provider_status_task.delay(route.object_key, signed_context)
        elif route.kind == "export":
            build_data_export_task.delay(route.object_key, signed_context)
        elif route.kind == "export_cleanup":
            expire_export_task.delay(route.object_key, signed_context)
        elif route.kind == "email_cleanup":
            scrub_email_task.delay(route.object_key, signed_context)
    return len(routes)


def _complete_route(kind: str, object_key: str) -> None:
    PendingTaskRoute.objects.filter(kind=kind, object_key=object_key).update(
        completed_at=timezone.now()
    )


@shared_task  # type: ignore[untyped-decorator]
def expire_export_task(export_id: str, signed_tenant_context: str) -> None:
    try:
        parsed = UUID(export_id)
        with tenant_task_context(signed_tenant_context, expected_causation_id=f"export:{parsed}"):
            expire_data_export(parsed)
        _complete_route("export_cleanup", export_id)
    except (InvalidTenantTaskContext, ValueError):
        logger.warning(
            "notifications_export_cleanup_rejected",
            extra={"security_event": "notifications.export_cleanup_rejected"},
        )


@shared_task  # type: ignore[untyped-decorator]
def scrub_email_task(message_id: str, signed_tenant_context: str) -> None:
    try:
        parsed = UUID(message_id)
        with tenant_task_context(signed_tenant_context, expected_causation_id=f"email:{parsed}"):
            scrub_notification_message(parsed)
        _complete_route("email_cleanup", message_id)
    except (InvalidTenantTaskContext, ValueError):
        logger.warning(
            "notifications_email_cleanup_rejected",
            extra={"security_event": "notifications.email_cleanup_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.notifications.tasks.deliver_billing_notices"
)
def deliver_billing_notices_task() -> int:
    return deliver_billing_notices()
