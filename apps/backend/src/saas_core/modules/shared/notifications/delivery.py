from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .attachments import Attachment, resolve_attachment
from .metrics import DELIVERY_RESULTS, PROVIDER_STATUSES
from .models import (
    DeliveryStatus,
    EmailSuppression,
    NotificationAttempt,
    NotificationMessage,
    NotificationPreference,
    ProviderEventInbox,
    ProviderMessageRoute,
    WebhookAttempt,
    WebhookDelivery,
)
from .providers import EmailProvider, ProviderMessage, get_email_provider
from .security import (
    canonical_json,
    decrypt_secret,
    encrypt_secret,
    sign_webhook,
    validate_webhook_url,
)
from .templates import render_template


class DeliveryDeferred(RuntimeError):
    def __init__(self, countdown: int) -> None:
        self.countdown = countdown
        super().__init__("Dostawa wymaga ponowienia.")


class WebhookTransport(Protocol):
    def post(self, *, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]: ...


class UrlLibWebhookTransport:
    def post(self, *, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[no-untyped-def]
                return None

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, response.read(4096)
        except urllib.error.HTTPError as error:
            return error.code, error.read(4096)


def deliver_email(
    message_id: UUID, *, provider: EmailProvider | None = None
) -> NotificationMessage:
    provider = provider or get_email_provider()
    with transaction.atomic():
        message = NotificationMessage.all_objects.select_for_update().get(pk=message_id)
        if message.status in {
            DeliveryStatus.SENT,
            DeliveryStatus.DELIVERED,
            DeliveryStatus.BOUNCED,
            DeliveryStatus.COMPLAINED,
            DeliveryStatus.SUPPRESSED,
        }:
            return message
        suppressed = EmailSuppression.all_objects.filter(
            recipient_hash=message.recipient_hash, active=True
        ).exists()
        marketing_disabled = (
            message.category == "marketing"
            and message.recipient_user_id is not None
            and NotificationPreference.all_objects.filter(
                user_id=message.recipient_user_id,
                marketing_enabled=False,
            ).exists()
        )
        if suppressed or marketing_disabled:
            message.status = DeliveryStatus.SUPPRESSED
            message.last_error_code = "suppression" if suppressed else "marketing_opt_out"
            message.save(update_fields=["status", "last_error_code", "updated_at"])
            DELIVERY_RESULTS.labels(channel="email", outcome="suppressed").inc()
            return message
        message.attempt_count += 1
        attempt_number = message.attempt_count
        message.status = DeliveryStatus.PROCESSING
        message.save(update_fields=["attempt_count", "status", "updated_at"])
        subject, html_body = render_template(
            key=message.template_key,
            version=message.template_version,
            locale=message.locale,
            context=message.context,
        )
        # Resolved in the tenant context the message was queued in, inside the
        # same transaction that read the message.
        attachments: list[Attachment] | None = []
        if message.attachment_ref:
            try:
                attachments = [resolve_attachment(message.attachment_ref)]
            except Exception:  # noqa: BLE001 - any failure: the file is not there to send
                attachments = None
    if attachments is None:
        return _mark_email_failed(message_id, attempt_number, "attachment_unavailable")
    try:
        result = provider.send(
            recipient=message.recipient_email,
            subject=subject,
            html_body=html_body,
            idempotency_key=message.idempotency_key,
            attachments=attachments,
        )
    except Exception:
        accepted = provider.status_for_idempotency_key(message.idempotency_key)
        if accepted is not None:
            return _mark_email_sent(message_id, attempt_number, accepted)
        return _mark_email_failed(message_id, attempt_number, "provider_unavailable")
    return _mark_email_sent(message_id, attempt_number, result)


@transaction.atomic
def _mark_email_sent(
    message_id: UUID, attempt_number: int, result: ProviderMessage
) -> NotificationMessage:
    message = NotificationMessage.all_objects.select_for_update().get(pk=message_id)
    message.status = DeliveryStatus.SENT
    message.provider_message_id = result.id
    message.sent_at = timezone.now()
    message.next_attempt_at = None
    message.last_error_code = ""
    message.save(
        update_fields=[
            "status",
            "provider_message_id",
            "sent_at",
            "next_attempt_at",
            "last_error_code",
            "updated_at",
        ]
    )
    NotificationAttempt.all_objects.get_or_create(
        message=message,
        number=attempt_number,
        defaults={
            "organization_id": message.organization_id,
            "outcome": "accepted",
            "provider_request_id": result.id,
        },
    )
    ProviderMessageRoute.objects.update_or_create(
        provider_message_id=result.id,
        defaults={
            "organization_id": message.organization_id,
            "message_id": message.id,
            "tenant_context_ciphertext": encrypt_secret(message.signed_tenant_context),
        },
    )
    DELIVERY_RESULTS.labels(channel="email", outcome="accepted").inc()
    return message


def _mark_email_failed(
    message_id: UUID, attempt_number: int, error_code: str
) -> NotificationMessage:
    """Records the failed attempt, then defers the retry.

    The deferral is raised after the transaction commits: raised inside it, it
    would roll back the very attempt and error code it is reporting.
    """
    message, delay = _record_email_failure(message_id, attempt_number, error_code)
    if delay is None:
        return message
    raise DeliveryDeferred(delay)


@transaction.atomic
def _record_email_failure(
    message_id: UUID, attempt_number: int, error_code: str
) -> tuple[NotificationMessage, int | None]:
    message = NotificationMessage.all_objects.select_for_update().get(pk=message_id)
    NotificationAttempt.all_objects.get_or_create(
        message=message,
        number=attempt_number,
        defaults={
            "organization_id": message.organization_id,
            "outcome": "failed",
            "error_code": error_code,
        },
    )
    message.last_error_code = error_code
    if message.attempt_count >= message.max_attempts:
        message.status = DeliveryStatus.DEAD_LETTER
        message.next_attempt_at = None
        message.save(update_fields=["status", "next_attempt_at", "last_error_code", "updated_at"])
        DELIVERY_RESULTS.labels(channel="email", outcome="dead_letter").inc()
        return message, None
    delay = min(3600, 2**message.attempt_count * 30)
    message.status = DeliveryStatus.QUEUED
    message.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    message.save(update_fields=["status", "next_attempt_at", "last_error_code", "updated_at"])
    DELIVERY_RESULTS.labels(channel="email", outcome="retry").inc()
    return message, delay


@transaction.atomic
def process_provider_status(event_id: str) -> NotificationMessage:
    inbox = ProviderEventInbox.objects.select_for_update().select_related("route").get(pk=event_id)
    message = NotificationMessage.all_objects.select_for_update().get(pk=inbox.route.message_id)
    if inbox.processed_at is not None:
        return message
    rank: dict[str, int] = {
        DeliveryStatus.SENT: 1,
        DeliveryStatus.DELIVERED: 2,
        DeliveryStatus.BOUNCED: 3,
        DeliveryStatus.COMPLAINED: 4,
    }
    if rank.get(inbox.status, 0) >= rank.get(message.status, 0):
        message.status = inbox.status
        message.save(update_fields=["status", "updated_at"])
    PROVIDER_STATUSES.labels(status=inbox.status).inc()
    if inbox.status in {DeliveryStatus.BOUNCED, DeliveryStatus.COMPLAINED}:
        EmailSuppression.all_objects.get_or_create(
            organization_id=message.organization_id,
            recipient_hash=message.recipient_hash,
            active=True,
            defaults={"reason": inbox.status},
        )
    inbox.processed_at = timezone.now()
    inbox.save(update_fields=["processed_at"])
    return message


def deliver_webhook(
    delivery_id: UUID, *, transport: WebhookTransport | None = None
) -> WebhookDelivery:
    transport = transport or UrlLibWebhookTransport()
    with transaction.atomic():
        delivery = (
            WebhookDelivery.all_objects.select_for_update()
            .select_related("endpoint")
            .get(pk=delivery_id)
        )
        if delivery.status == DeliveryStatus.DELIVERED:
            return delivery
        delivery.attempt_count += 1
        attempt_number = delivery.attempt_count
        delivery.status = DeliveryStatus.PROCESSING
        delivery.save(update_fields=["attempt_count", "status", "updated_at"])
        envelope = {
            "id": str(delivery.event_id),
            "type": delivery.event_type,
            "version": delivery.event_version,
            "organization_id": str(delivery.organization_id),
            "data": delivery.payload,
        }
        body = canonical_json(envelope)
        timestamp = int(timezone.now().timestamp())
        url = validate_webhook_url(delivery.endpoint.url)
        headers = {
            "Content-Type": "application/json",
            "X-Saas-Delivery": str(delivery.id),
            "X-Saas-Timestamp": str(timestamp),
            "X-Saas-Signature": sign_webhook(
                secret=decrypt_secret(delivery.endpoint.signing_secret_ciphertext),
                timestamp=timestamp,
                body=body,
            ),
        }
    try:
        response_status, response_body = transport.post(url=url, body=body, headers=headers)
    except Exception:
        return _mark_webhook_failed(delivery_id, attempt_number, "transport_error")
    digest = hashlib.sha256(response_body[:4096]).hexdigest()
    if 200 <= response_status < 300:
        with transaction.atomic():
            delivery = WebhookDelivery.all_objects.select_for_update().get(pk=delivery_id)
            delivery.status = DeliveryStatus.DELIVERED
            delivery.delivered_at = timezone.now()
            delivery.next_attempt_at = None
            delivery.last_error_code = ""
            delivery.save(
                update_fields=[
                    "status",
                    "delivered_at",
                    "next_attempt_at",
                    "last_error_code",
                    "updated_at",
                ]
            )
            WebhookAttempt.all_objects.get_or_create(
                delivery=delivery,
                number=attempt_number,
                defaults={
                    "organization_id": delivery.organization_id,
                    "response_status": response_status,
                    "response_digest": digest,
                },
            )
            DELIVERY_RESULTS.labels(channel="webhook", outcome="delivered").inc()
            return delivery
    return _mark_webhook_failed(
        delivery_id, attempt_number, f"http_{response_status}", response_status, digest
    )


@transaction.atomic
def _mark_webhook_failed(
    delivery_id: UUID,
    attempt_number: int,
    error_code: str,
    response_status: int | None = None,
    response_digest: str = "",
) -> WebhookDelivery:
    delivery = WebhookDelivery.all_objects.select_for_update().get(pk=delivery_id)
    WebhookAttempt.all_objects.get_or_create(
        delivery=delivery,
        number=attempt_number,
        defaults={
            "organization_id": delivery.organization_id,
            "response_status": response_status,
            "response_digest": response_digest,
            "error_code": error_code,
        },
    )
    delivery.last_error_code = error_code
    if delivery.attempt_count >= delivery.max_attempts:
        delivery.status = DeliveryStatus.DEAD_LETTER
        delivery.next_attempt_at = None
        delivery.save(update_fields=["status", "next_attempt_at", "last_error_code", "updated_at"])
        DELIVERY_RESULTS.labels(channel="webhook", outcome="dead_letter").inc()
        return delivery
    delay = min(7200, 2**delivery.attempt_count * 30)
    delivery.status = DeliveryStatus.QUEUED
    delivery.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    delivery.save(update_fields=["status", "next_attempt_at", "last_error_code", "updated_at"])
    DELIVERY_RESULTS.labels(channel="webhook", outcome="retry").inc()
    raise DeliveryDeferred(delay)
