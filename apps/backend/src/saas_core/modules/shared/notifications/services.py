from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID, uuid7

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext, require_tenant_context
from saas_core.modules.core.organizations.events import DomainEvent
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.observability import correlation_id

from .models import (
    ApiKey,
    ApiKeyCredentialRoute,
    AppNotification,
    DataExport,
    DeliveryStatus,
    EmailSuppression,
    ExportStatus,
    NotificationMessage,
    NotificationPreference,
    PendingTaskRoute,
    ProviderEventInbox,
    ProviderMessageRoute,
    WebhookDelivery,
    WebhookEndpoint,
)
from .security import (
    canonical_json,
    decrypt_secret,
    encrypt_secret,
    recipient_digest,
    validate_webhook_url,
)
from .templates import TEMPLATES, render_template

NOTIFICATIONS_PREFERENCES = "notifications.preferences"
NOTIFICATIONS_MANAGE = "notifications.manage"
NOTIFICATIONS_SUPPORT = "notifications.support"
INTEGRATIONS_MANAGE = "integrations.manage"
ALLOWED_API_SCOPES = frozenset({
    "notifications:read",
    "notifications:write",
    "webhooks:manage",
    # Content scopes for SeoContentRank (ADR-035). Split by what they let the
    # holder do, so a key issued for analysis cannot publish.
    "content:read",
    "content:draft",
    "content:publish",
})
#: What may travel to a subscriber, per event type. Deliberately the one
#: place that decides both: the fields a delivery carries and, below, the
#: types an operator may subscribe to at all. They were separate lists, and
#: an event added to one but not the other reaches nobody while looking
#: entirely wired up.
EVENT_PAYLOAD_ALLOWLISTS: dict[str, set[str]] = {
    "sites.site.published": {"site_id", "publication_id", "sequence", "snapshot_hash"},
    # A rollback carries the publication it restored, which is the whole
    # reason a subscriber cares: it says which state the site went back to.
    "sites.site.rolled_back": {
        "site_id",
        "publication_id",
        "sequence",
        "snapshot_hash",
        "source_publication_id",
    },
    "sites.entry.published": {
        "entry_id",
        "collection_id",
        "publication_id",
        "sequence",
        "snapshot_hash",
        "path",
        "locale",
    },
    # Identifiers and versions only. The text of a draft is the customer's
    # unpublished work and does not travel to a subscriber.
    "sites.page.draft_saved": {
        "resource_type",
        "resource_id",
        "version",
        "credential_id",
    },
    "sites.entry.draft_saved": {
        "resource_type",
        "resource_id",
        "version",
        "credential_id",
    },
    "sites.automation_grant.revoked": {"grant_id", "credential_id", "mode"},
    "notifications.message.status": {"message_id", "status"},
}

ALLOWED_WEBHOOK_EVENTS = frozenset(EVENT_PAYLOAD_ALLOWLISTS)
EXPORT_TOKEN_SALT = "saas-core.notifications.export.v1"


class MfaRequired(PermissionDenied):
    default_detail = "Ta operacja supportowa wymaga potwierdzonego MFA."
    default_code = "mfa_required"


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    api_key: ApiKey
    secret: str


def upsert_preferences(*, locale: str, marketing_enabled: bool) -> NotificationPreference:
    context = authorize_entitled(NOTIFICATIONS_PREFERENCES, "notifications.enabled")
    if locale not in {"pl", "en"}:
        raise ValidationError("Nieobsługiwane locale.")
    preference, _ = NotificationPreference.all_objects.update_or_create(
        organization_id=context.organization_id,
        user_id=context.actor_id,
        defaults={"locale": locale, "marketing_enabled": marketing_enabled},
    )
    return preference


def get_preferences() -> NotificationPreference:
    context = authorize_entitled(NOTIFICATIONS_PREFERENCES, "notifications.enabled")
    preference, _ = NotificationPreference.all_objects.get_or_create(
        organization_id=context.organization_id,
        user_id=context.actor_id,
        defaults={"locale": "pl", "marketing_enabled": False},
    )
    return preference


@transaction.atomic
def queue_email(
    *,
    recipient_email: str,
    template_key: str,
    template_version: int,
    locale: str,
    template_context: dict[str, Any],
    idempotency_key: str,
    causation_id: str,
    recipient_user: User | None = None,
) -> tuple[NotificationMessage, bool]:
    tenant = require_tenant_context()
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValidationError("Nieprawidłowy klucz idempotencji.")
    template = TEMPLATES.get((template_key, template_version))
    if template is None:
        raise ValidationError("Nieznany szablon wiadomości.")
    render_template(
        key=template_key, version=template_version, locale=locale, context=template_context
    )
    existing = NotificationMessage.all_objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing, False
    now = timezone.now()
    message_id = uuid7()
    message = NotificationMessage.all_objects.create(
        id=message_id,
        organization_id=tenant.organization_id,
        recipient_email=recipient_email.strip().lower(),
        recipient_hash=recipient_digest(recipient_email),
        recipient_user=recipient_user,
        template_key=template_key,
        template_version=template_version,
        locale=locale,
        category=template.category,
        context=template_context,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id.get() or uuid7(),
        causation_id=causation_id,
        signed_tenant_context=issue_tenant_task_contract(causation_id=f"email:{message_id}"),
        next_attempt_at=now,
        retention_expires_at=now + timedelta(days=settings.NOTIFICATIONS_RETENTION_DAYS),
    )
    PendingTaskRoute.objects.create(
        kind="email",
        object_key=str(message.id),
        tenant_context_ciphertext=encrypt_secret(message.signed_tenant_context),
        next_dispatch_at=now,
    )
    PendingTaskRoute.objects.create(
        kind="email_cleanup",
        object_key=str(message.id),
        tenant_context_ciphertext=encrypt_secret(message.signed_tenant_context),
        next_dispatch_at=message.retention_expires_at,
    )
    from .tasks import deliver_email_task

    transaction.on_commit(
        lambda: deliver_email_task.delay(str(message.id), message.signed_tenant_context)
    )
    return message, True


def list_app_notifications(*, limit: int = 20) -> tuple[list[AppNotification], int]:
    """This member's messages in this organization, newest first.

    No permission gate: a notification was addressed to a person when it was
    created, so reading one's own inbox needs nothing further. What the tenant
    context decides is which organization's inbox that is — the same account in
    another company sees another list.
    """
    tenant = require_tenant_context()
    mine = AppNotification.all_objects.filter(
        organization_id=tenant.organization_id, user_id=tenant.actor_id
    )
    return list(mine[:limit]), mine.filter(read_at__isnull=True).count()


def mark_app_notifications_read(*, ids: list[UUID] | None = None) -> int:
    """Marks the given messages read, or all of them when none are named."""
    tenant = require_tenant_context()
    unread = AppNotification.all_objects.filter(
        organization_id=tenant.organization_id,
        user_id=tenant.actor_id,
        read_at__isnull=True,
    )
    if ids:
        unread = unread.filter(id__in=ids)
    unread.update(read_at=timezone.now())
    return AppNotification.all_objects.filter(
        organization_id=tenant.organization_id,
        user_id=tenant.actor_id,
        read_at__isnull=True,
    ).count()


def preview_email(
    *, key: str, version: int, locale: str, context: dict[str, Any]
) -> dict[str, str]:
    authorize_entitled(NOTIFICATIONS_MANAGE, "notifications.enabled")
    subject, body = render_template(key=key, version=version, locale=locale, context=context)
    return {"subject": subject, "html_body": body}


@transaction.atomic
def issue_api_key(*, name: str, scopes: list[str], expires_at: Any = None) -> IssuedApiKey:
    context = authorize(INTEGRATIONS_MANAGE)
    normalized = sorted(set(scopes))
    if not normalized or not set(normalized) <= ALLOWED_API_SCOPES:
        raise ValidationError("Nieprawidłowe scope klucza API.")
    raw = "sc_live_" + secrets.token_urlsafe(32)
    prefix = raw[:18]
    api_key = ApiKey.all_objects.create(
        organization_id=context.organization_id,
        name=name.strip(),
        prefix=prefix,
        secret_hash=make_password(raw),
        scopes=normalized,
        created_by_id=context.actor_id,
        expires_at=expires_at,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=prefix,
        api_key_id=api_key.id,
        organization_id=context.organization_id,
        secret_hash=api_key.secret_hash,
        scopes=normalized,
        expires_at=expires_at,
    )
    _audit(action="integration.api_key.created", target=api_key, metadata={"scopes": normalized})
    return IssuedApiKey(api_key=api_key, secret=raw)


@transaction.atomic
def rotate_api_key(*, key_id: UUID) -> IssuedApiKey:
    context = authorize(INTEGRATIONS_MANAGE)
    previous = (
        ApiKey.all_objects.select_for_update().filter(pk=key_id, revoked_at__isnull=True).first()
    )
    if previous is None:
        raise NotFound("Klucz API nie istnieje albo został wycofany.")
    now = timezone.now()
    previous.revoked_at = now
    previous.save(update_fields=["revoked_at"])
    ApiKeyCredentialRoute.objects.filter(api_key_id=previous.id).update(revoked_at=now)
    raw = "sc_live_" + secrets.token_urlsafe(32)
    created = ApiKey.all_objects.create(
        organization_id=context.organization_id,
        name=previous.name,
        prefix=raw[:18],
        secret_hash=make_password(raw),
        scopes=previous.scopes,
        created_by_id=context.actor_id,
        rotated_from=previous,
        expires_at=previous.expires_at,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=created.prefix,
        api_key_id=created.id,
        organization_id=context.organization_id,
        secret_hash=created.secret_hash,
        scopes=created.scopes,
        expires_at=created.expires_at,
    )
    _audit(
        action="integration.api_key.rotated",
        target=created,
        metadata={"rotated_from": str(previous.id)},
    )
    return IssuedApiKey(created, raw)


@transaction.atomic
def revoke_api_key(*, key_id: UUID) -> ApiKey:
    authorize(INTEGRATIONS_MANAGE)
    api_key = ApiKey.all_objects.select_for_update().filter(pk=key_id).first()
    if api_key is None:
        raise NotFound("Klucz API nie istnieje.")
    if api_key.revoked_at is None:
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["revoked_at"])
        ApiKeyCredentialRoute.objects.filter(api_key_id=api_key.id).update(
            revoked_at=api_key.revoked_at
        )
        _audit(action="integration.api_key.revoked", target=api_key)
    return api_key


def authenticate_api_key(raw: str, *, required_scope: str) -> ApiKeyCredentialRoute | None:
    if not raw.startswith("sc_live_"):
        return None
    key = ApiKeyCredentialRoute.objects.filter(prefix=raw[:18], revoked_at__isnull=True).first()
    if key is None or required_scope not in key.scopes or not check_password(raw, key.secret_hash):
        return None
    if key.expires_at is not None and key.expires_at <= timezone.now():
        return None
    return key


@transaction.atomic
def create_webhook_endpoint(
    *, name: str, url: str, events: list[str]
) -> tuple[WebhookEndpoint, str]:
    context = authorize(INTEGRATIONS_MANAGE)
    normalized_events = sorted(set(events))
    if not normalized_events or not set(normalized_events) <= ALLOWED_WEBHOOK_EVENTS:
        raise ValidationError("Nieprawidłowe typy zdarzeń webhooka.")
    validated_url = validate_webhook_url(url)
    secret = "whsec_" + secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint.all_objects.create(
        organization_id=context.organization_id,
        name=name.strip(),
        url=validated_url,
        signing_secret_ciphertext=encrypt_secret(secret),
        secret_hint=secret[-8:],
        events=normalized_events,
        created_by_id=context.actor_id,
    )
    _audit(
        action="integration.webhook.created",
        target=endpoint,
        metadata={"events": normalized_events},
    )
    return endpoint, secret


@transaction.atomic
def queue_webhooks(
    *, event_id: UUID, event_type: str, version: int, payload: dict[str, Any]
) -> int:
    context = require_tenant_context()
    allowed_payload = _allowlisted_event_payload(event_type, payload)
    endpoints = list(WebhookEndpoint.all_objects.filter(active=True, events__contains=[event_type]))
    count = 0
    for endpoint in endpoints:
        delivery, created = WebhookDelivery.all_objects.get_or_create(
            endpoint=endpoint,
            event_id=event_id,
            defaults={
                "organization_id": context.organization_id,
                "event_type": event_type,
                "event_version": version,
                "payload": allowed_payload,
                "signed_tenant_context": issue_tenant_task_contract(
                    causation_id=f"webhook:{event_id}"
                ),
                "correlation_id": correlation_id.get() or uuid7(),
                "next_attempt_at": timezone.now(),
            },
        )
        if created:
            PendingTaskRoute.objects.create(
                kind="webhook",
                object_key=str(delivery.id),
                tenant_context_ciphertext=encrypt_secret(delivery.signed_tenant_context),
                next_dispatch_at=timezone.now(),
            )
            from .tasks import deliver_webhook_task

            transaction.on_commit(
                partial(
                    deliver_webhook_task.delay,
                    str(delivery.id),
                    delivery.signed_tenant_context,
                )
            )
            count += 1
    return count


def consume_domain_event(event: DomainEvent) -> None:
    queue_webhooks(
        event_id=event.id,
        event_type=event.event_type,
        version=event.version,
        payload=event.payload,
    )


def ingest_provider_status(
    *, event_id: str, provider_message_id: str, status: str, payload_digest: str
) -> tuple[ProviderEventInbox, bool]:
    if status not in {DeliveryStatus.DELIVERED, DeliveryStatus.BOUNCED, DeliveryStatus.COMPLAINED}:
        raise ValidationError("Nieobsługiwany status providera.")
    try:
        route = ProviderMessageRoute.objects.get(provider_message_id=provider_message_id)
    except ProviderMessageRoute.DoesNotExist as error:
        raise NotFound("Nieznany identyfikator wiadomości providera.") from error
    inbox, created = ProviderEventInbox.objects.get_or_create(
        event_id=event_id,
        defaults={"route": route, "status": status, "payload_digest": payload_digest},
    )
    if created:
        PendingTaskRoute.objects.create(
            kind="provider_status",
            object_key=event_id,
            tenant_context_ciphertext=route.tenant_context_ciphertext,
            next_dispatch_at=timezone.now(),
        )
        from .tasks import process_provider_status_task

        transaction.on_commit(
            lambda: process_provider_status_task.delay(
                event_id, decrypt_secret(route.tenant_context_ciphertext)
            )
        )
    return inbox, created


@transaction.atomic
def support_retry_message(*, message_id: UUID, reason: str) -> NotificationMessage:
    _authorize_support(reason)
    message = NotificationMessage.all_objects.select_for_update().filter(pk=message_id).first()
    if message is None:
        raise NotFound("Wiadomość nie istnieje.")
    if message.status != DeliveryStatus.DEAD_LETTER:
        raise Conflict("Tylko dead-letter może zostać ponowiony.")
    message.status = DeliveryStatus.QUEUED
    message.attempt_count = 0
    message.last_error_code = ""
    message.next_attempt_at = timezone.now()
    message.signed_tenant_context = issue_tenant_task_contract(causation_id=f"email:{message.id}")
    message.save(
        update_fields=[
            "status",
            "attempt_count",
            "last_error_code",
            "next_attempt_at",
            "signed_tenant_context",
            "updated_at",
        ]
    )
    PendingTaskRoute.objects.update_or_create(
        kind="email",
        object_key=str(message.id),
        defaults={
            "tenant_context_ciphertext": encrypt_secret(message.signed_tenant_context),
            "next_dispatch_at": timezone.now(),
            "completed_at": None,
        },
    )
    _audit(
        action="support.notification.retried", target=message, metadata={"reason": reason.strip()}
    )
    from .tasks import deliver_email_task

    transaction.on_commit(
        lambda: deliver_email_task.delay(str(message.id), message.signed_tenant_context)
    )
    return message


@transaction.atomic
def support_retry_webhook(*, delivery_id: UUID, reason: str) -> WebhookDelivery:
    _authorize_support(reason)
    delivery = WebhookDelivery.all_objects.select_for_update().filter(pk=delivery_id).first()
    if delivery is None:
        raise NotFound("Dostawa webhooka nie istnieje.")
    if delivery.status != DeliveryStatus.DEAD_LETTER:
        raise Conflict("Tylko dead-letter może zostać ponowiony.")
    delivery.status = DeliveryStatus.QUEUED
    delivery.attempt_count = 0
    delivery.last_error_code = ""
    delivery.next_attempt_at = timezone.now()
    delivery.signed_tenant_context = issue_tenant_task_contract(
        causation_id=f"webhook:{delivery.event_id}"
    )
    delivery.save(
        update_fields=[
            "status",
            "attempt_count",
            "last_error_code",
            "next_attempt_at",
            "signed_tenant_context",
            "updated_at",
        ]
    )
    PendingTaskRoute.objects.update_or_create(
        kind="webhook",
        object_key=str(delivery.id),
        defaults={
            "tenant_context_ciphertext": encrypt_secret(delivery.signed_tenant_context),
            "next_dispatch_at": timezone.now(),
            "completed_at": None,
        },
    )
    _audit(
        action="support.webhook.retried",
        target=delivery,
        metadata={"reason": reason.strip()},
    )
    from .tasks import deliver_webhook_task

    transaction.on_commit(
        lambda: deliver_webhook_task.delay(str(delivery.id), delivery.signed_tenant_context)
    )
    return delivery


def support_health() -> dict[str, int]:
    _authorize_support("health-check")
    return {
        "queued_messages": NotificationMessage.all_objects.filter(
            status=DeliveryStatus.QUEUED
        ).count(),
        "dead_messages": NotificationMessage.all_objects.filter(
            status=DeliveryStatus.DEAD_LETTER
        ).count(),
        "active_suppressions": EmailSuppression.all_objects.filter(active=True).count(),
        "queued_webhooks": WebhookDelivery.all_objects.filter(status=DeliveryStatus.QUEUED).count(),
        "dead_webhooks": WebhookDelivery.all_objects.filter(
            status=DeliveryStatus.DEAD_LETTER
        ).count(),
    }


def issue_export_token(export: DataExport) -> str:
    return signing.dumps(
        {"id": str(export.id), "organization_id": str(export.organization_id)},
        salt=EXPORT_TOKEN_SALT,
    )


@transaction.atomic
def create_data_export(*, kind: str, idempotency_key: str) -> tuple[DataExport, bool]:
    context = authorize(INTEGRATIONS_MANAGE)
    if kind not in {"notification_deliveries", "webhook_deliveries"}:
        raise ValidationError("Nieobsługiwany rodzaj eksportu.")
    existing = DataExport.all_objects.filter(
        created_by_id=context.actor_id, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        return existing, False
    export_id = uuid7()
    export = DataExport.all_objects.create(
        id=export_id,
        organization_id=context.organization_id,
        kind=kind,
        idempotency_key=idempotency_key,
        signed_tenant_context=issue_tenant_task_contract(causation_id=f"export:{export_id}"),
        created_by_id=context.actor_id,
        expires_at=timezone.now() + timedelta(hours=settings.NOTIFICATIONS_EXPORT_TTL_HOURS),
    )
    PendingTaskRoute.objects.create(
        kind="export",
        object_key=str(export.id),
        tenant_context_ciphertext=encrypt_secret(export.signed_tenant_context),
        next_dispatch_at=timezone.now(),
    )
    PendingTaskRoute.objects.create(
        kind="export_cleanup",
        object_key=str(export.id),
        tenant_context_ciphertext=encrypt_secret(export.signed_tenant_context),
        next_dispatch_at=export.expires_at,
    )
    from .tasks import build_data_export_task

    transaction.on_commit(
        lambda: build_data_export_task.delay(str(export.id), export.signed_tenant_context)
    )
    return export, True


@transaction.atomic
def build_data_export(export_id: UUID) -> DataExport:
    export = DataExport.all_objects.select_for_update().get(pk=export_id)
    if export.status == ExportStatus.READY:
        return export
    export.status = ExportStatus.PROCESSING
    export.save(update_fields=["status", "updated_at"])
    if export.kind == "notification_deliveries":
        rows: list[dict[str, Any]] = [
            dict(row)
            for row in (
                NotificationMessage.all_objects.order_by("created_at").values(
                    "id",
                    "template_key",
                    "locale",
                    "category",
                    "status",
                    "attempt_count",
                    "created_at",
                )[: settings.NOTIFICATIONS_EXPORT_MAX_ROWS]
            )
        ]
    else:
        rows = [
            dict(row)
            for row in (
                WebhookDelivery.all_objects.order_by("created_at").values(
                    "id",
                    "event_id",
                    "event_type",
                    "event_version",
                    "status",
                    "attempt_count",
                    "created_at",
                )[: settings.NOTIFICATIONS_EXPORT_MAX_ROWS]
            )
        ]
    serializable_rows = [
        {
            key: value.isoformat() if hasattr(value, "isoformat") else str(value)
            for key, value in row.items()
        }
        for row in rows
    ]
    export.content = canonical_json({
        "version": 1,
        "kind": export.kind,
        "rows": serializable_rows,
    }).decode()
    export.row_count = len(rows)
    export.status = ExportStatus.READY
    export.save(update_fields=["content", "row_count", "status", "updated_at"])
    return export


def resolve_data_export(*, export_id: UUID, token: str) -> DataExport:
    authorize(INTEGRATIONS_MANAGE)
    try:
        payload = signing.loads(
            token, salt=EXPORT_TOKEN_SALT, max_age=settings.NOTIFICATIONS_EXPORT_TTL_HOURS * 3600
        )
    except signing.BadSignature as error:
        raise NotFound("Link eksportu jest nieprawidłowy albo wygasł.") from error
    context = require_tenant_context()
    if payload != {"id": str(export_id), "organization_id": str(context.organization_id)}:
        raise NotFound("Eksport nie istnieje.")
    export = DataExport.all_objects.filter(pk=export_id, status=ExportStatus.READY).first()
    if export is None or export.expires_at <= timezone.now():
        raise NotFound("Eksport nie istnieje albo wygasł.")
    return export


@transaction.atomic
def expire_data_export(export_id: UUID) -> DataExport:
    export = DataExport.all_objects.select_for_update().get(pk=export_id)
    if export.expires_at > timezone.now():
        raise Conflict("Eksport jeszcze nie wygasł.")
    export.content = ""
    export.status = ExportStatus.EXPIRED
    export.save(update_fields=["content", "status", "updated_at"])
    return export


@transaction.atomic
def scrub_notification_message(message_id: UUID) -> NotificationMessage:
    message = NotificationMessage.all_objects.select_for_update().get(pk=message_id)
    if message.retention_expires_at > timezone.now():
        raise Conflict("Retencja wiadomości jeszcze nie wygasła.")
    message.recipient_email = f"redacted+{message.recipient_hash[:16]}@invalid.local"
    message.context = {}
    message.signed_tenant_context = ""
    message.save(
        update_fields=["recipient_email", "context", "signed_tenant_context", "updated_at"]
    )
    ProviderMessageRoute.objects.filter(message_id=message.id).delete()
    return message


def _authorize_support(reason: str) -> TenantContext:
    context = authorize(NOTIFICATIONS_SUPPORT)
    if not has_confirmed_mfa(User.objects.get(pk=context.actor_id)):
        raise MfaRequired
    if not reason.strip() or len(reason.strip()) > 500:
        raise ValidationError("Operacja supportowa wymaga powodu.")
    return context


def _audit(*, action: str, target: Any, metadata: dict[str, Any] | None = None) -> None:
    context = require_tenant_context()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        actor=User.objects.get(pk=context.actor_id),
        action=action,
        target_type=target._meta.label_lower,
        target_id=target.id,
        metadata=metadata,
    )


def _allowlisted_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = EVENT_PAYLOAD_ALLOWLISTS.get(event_type)
    if allowed is None:
        raise ValidationError("Typ zdarzenia nie jest publicznym kontraktem webhooka.")
    return {key: payload[key] for key in sorted(allowed) if key in payload}
