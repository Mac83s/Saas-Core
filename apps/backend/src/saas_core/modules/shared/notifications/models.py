from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class MessageCategory(models.TextChoices):
    REQUIRED = "required", "Wymagana"
    MARKETING = "marketing", "Marketingowa"


class DeliveryStatus(models.TextChoices):
    QUEUED = "queued", "Oczekuje"
    PROCESSING = "processing", "Przetwarzana"
    SENT = "sent", "Wysłana"
    DELIVERED = "delivered", "Dostarczona"
    BOUNCED = "bounced", "Odrzucona"
    COMPLAINED = "complained", "Zgłoszona"
    SUPPRESSED = "suppressed", "Wstrzymana"
    DEAD_LETTER = "dead_letter", "Dead letter"


class ExportStatus(models.TextChoices):
    QUEUED = "queued", "Oczekuje"
    PROCESSING = "processing", "Przetwarzany"
    READY = "ready", "Gotowy"
    EXPIRED = "expired", "Wygasł"
    DEAD_LETTER = "dead_letter", "Dead letter"


class NotificationMessage(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    recipient_email = models.EmailField(max_length=254)
    recipient_hash = models.CharField(max_length=64)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notification_messages",
    )
    template_key = models.CharField(max_length=100)
    template_version = models.PositiveIntegerField(default=1)
    locale = models.CharField(max_length=10, choices=(("pl", "Polski"), ("en", "English")))
    category = models.CharField(max_length=16, choices=MessageCategory)
    context = models.JSONField(default=dict)
    #: `<prefix>:<id>` of a file resolved at delivery (attachments.py); "" = none.
    attachment_ref = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=DeliveryStatus, default=DeliveryStatus.QUEUED)
    provider_message_id = models.CharField(max_length=160, blank=True)
    idempotency_key = models.CharField(max_length=160)
    correlation_id = models.UUIDField()
    causation_id = models.CharField(max_length=160)
    signed_tenant_context = models.TextField()
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    retention_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="notifications_message_org_idem_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(template_version__gte=1, max_attempts__gte=1),
                name="notifications_message_limits_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "next_attempt_at"],
                name="notifications_message_due_idx",
            ),
            models.Index(fields=["provider_message_id"], name="notifications_provider_id_idx"),
        ]


class NotificationAttempt(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    message = models.ForeignKey(
        NotificationMessage, on_delete=models.PROTECT, related_name="attempts"
    )
    number = models.PositiveIntegerField()
    outcome = models.CharField(max_length=32)
    provider_request_id = models.CharField(max_length=160, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message", "number"], name="notifications_attempt_no_uq"
            )
        ]


class ProviderMessageRoute(models.Model):
    """Global, PII-free routing index used before a tenant context can be activated."""

    provider_message_id = models.CharField(max_length=160, primary_key=True)
    organization_id = models.UUIDField()
    message_id = models.UUIDField(unique=True)
    tenant_context_ciphertext = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.provider_message_id


class ProviderEventInbox(models.Model):
    """Verified provider events; the raw provider payload is deliberately not retained."""

    event_id = models.CharField(max_length=160, primary_key=True)
    route = models.ForeignKey(ProviderMessageRoute, on_delete=models.PROTECT)
    status = models.CharField(max_length=20)
    payload_digest = models.CharField(max_length=64)
    provider_occurred_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.event_id


class PendingTaskRoute(models.Model):
    """PII-free broker recovery index, separate from tenant-owned payloads."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=32)
    object_key = models.CharField(max_length=160)
    tenant_context_ciphertext = models.TextField()
    next_dispatch_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "object_key"], name="notifications_pending_route_uq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.object_key}"


class ApiKeyCredentialRoute(models.Model):
    """PII-free credential lookup used before tenant selection."""

    prefix = models.CharField(max_length=20, primary_key=True)
    api_key_id = models.UUIDField(unique=True)
    organization_id = models.UUIDField()
    secret_hash = models.CharField(max_length=256)
    scopes = models.JSONField(default=list)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.prefix


class EmailSuppression(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    recipient_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=24)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cleared_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "recipient_hash"],
                condition=models.Q(active=True),
                name="notifications_suppression_active_uq",
            )
        ]


class NotificationPreference(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    locale = models.CharField(max_length=10, choices=(("pl", "Polski"), ("en", "English")))
    marketing_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="notifications_pref_org_user_uq"
            )
        ]


class ApiKey(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=20, unique=True)
    secret_hash = models.CharField(max_length=256)
    scopes = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    rotated_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()


class WebhookEndpoint(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=100)
    url = models.URLField(max_length=2048)
    signing_secret_ciphertext = models.TextField()
    secret_hint = models.CharField(max_length=8)
    events = models.JSONField(default=list)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()


class WebhookDelivery(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.PROTECT, related_name="deliveries"
    )
    event_id = models.UUIDField()
    event_type = models.CharField(max_length=120)
    event_version = models.PositiveIntegerField(default=1)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=DeliveryStatus, default=DeliveryStatus.QUEUED)
    signed_tenant_context = models.TextField()
    correlation_id = models.UUIDField()
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=8)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "event_id"], name="notifications_webhook_event_uq"
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "next_attempt_at"],
                name="notifications_webhook_due_idx",
            )
        ]


class WebhookAttempt(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    delivery = models.ForeignKey(WebhookDelivery, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveIntegerField()
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_digest = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "number"], name="notifications_webhook_attempt_uq"
            )
        ]


class DataExport(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=ExportStatus, default=ExportStatus.QUEUED)
    filters = models.JSONField(default=dict)
    content = models.TextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=160)
    signed_tenant_context = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "created_by", "idempotency_key"],
                name="notifications_export_org_actor_idem_uq",
            )
        ]


class NotificationSeverity(models.TextChoices):
    INFO = "info", "Informacja"
    WARNING = "warning", "Ostrzeżenie"
    CRITICAL = "critical", "Pilne"


class AppNotification(TenantScopedModel):
    """A message waiting inside the product, for the person who can act on it.

    E-mail leaves the building and may never arrive: it lands in spam, the
    address belongs to an accountant, the person changed jobs. This is the copy
    that stays where the work happens, and it is what turns a `BillingNotice`
    from a row nobody reads into something a customer sees.

    The text is not stored. The row carries a `kind` and the facts (`payload`),
    and the panel renders the sentence in the reader's own language — so a
    translation fix does not need a data migration, and one message cannot be
    Polish for one member and English for another.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_notifications",
    )
    kind = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    severity = models.CharField(
        max_length=16,
        choices=NotificationSeverity,
        default=NotificationSeverity.INFO,
    )
    # What produced this, so the same event delivered twice does not appear
    # twice: the sender passes a stable key rather than trusting a timestamp.
    idempotency_key = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user", "idempotency_key"],
                name="notifications_app_org_user_idem_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "user", "read_at"],
                name="notif_app_org_user_read_idx",
            )
        ]
