from __future__ import annotations

from typing import Any

from rest_framework import serializers


class PreferenceSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.ChoiceField(choices=("pl", "en"))
    marketing_enabled = serializers.BooleanField()


class TemplatePreviewSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(max_length=100)
    version = serializers.IntegerField(min_value=1)
    locale = serializers.ChoiceField(choices=("pl", "en"))
    context = serializers.DictField()  # type: ignore[assignment]


class ApiKeyCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    scopes = serializers.ListField(child=serializers.CharField(max_length=80), min_length=1)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class WebhookCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    url = serializers.URLField(max_length=2048)
    events = serializers.ListField(child=serializers.CharField(max_length=120), min_length=1)


class SupportRetrySerializer(serializers.Serializer[dict[str, Any]]):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class DataExportCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=("notification_deliveries", "webhook_deliveries"))


class ProviderStatusSerializer(serializers.Serializer[dict[str, Any]]):
    event_id = serializers.CharField(max_length=160)
    provider_message_id = serializers.CharField(max_length=160)
    status = serializers.ChoiceField(choices=("delivered", "bounced", "complained"))


class TemplateItemSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    version = serializers.IntegerField()
    category = serializers.CharField()
    locales = serializers.ListField(child=serializers.CharField())
    context_fields = serializers.ListField(child=serializers.CharField())


class TemplateCatalogSerializer(serializers.Serializer[dict[str, Any]]):
    items = TemplateItemSerializer(many=True)


class TemplatePreviewResultSerializer(serializers.Serializer[dict[str, Any]]):
    subject = serializers.CharField()
    html_body = serializers.CharField()


class ApiKeySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    prefix = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())
    revoked_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    secret = serializers.CharField(required=False)


class ApiKeyListSerializer(serializers.Serializer[dict[str, Any]]):
    items = ApiKeySerializer(many=True)


class WebhookSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    url = serializers.URLField()
    events = serializers.ListField(child=serializers.CharField())
    active = serializers.BooleanField()
    secret_hint = serializers.CharField()
    created_at = serializers.DateTimeField()
    secret = serializers.CharField(required=False)


class WebhookListSerializer(serializers.Serializer[dict[str, Any]]):
    items = WebhookSerializer(many=True)


class SupportHealthSerializer(serializers.Serializer[dict[str, Any]]):
    queued_messages = serializers.IntegerField()
    dead_messages = serializers.IntegerField()
    active_suppressions = serializers.IntegerField()
    queued_webhooks = serializers.IntegerField()
    dead_webhooks = serializers.IntegerField()


class MessageStatusSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    status = serializers.CharField()


class DataExportSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    download_token = serializers.CharField(allow_null=True)


class AppNotificationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    payload = serializers.JSONField()
    severity = serializers.ChoiceField(choices=["info", "warning", "critical"])
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)


class AppNotificationInboxSerializer(serializers.Serializer[dict[str, Any]]):
    unread = serializers.IntegerField()
    items = AppNotificationSerializer(many=True)


class AppNotificationReadSerializer(serializers.Serializer[dict[str, Any]]):
    ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
