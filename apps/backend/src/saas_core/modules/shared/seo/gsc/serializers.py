from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers


class StrictSerializer(serializers.Serializer[dict[str, Any]]):
    def to_internal_value(self, data):  # type: ignore[no-untyped-def]
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown request fields."]})
        return super().to_internal_value(data)


class GscSiteInput(StrictSerializer):
    site_id = serializers.UUIDField()


class GscAuthorizeInput(GscSiteInput):
    locale = serializers.ChoiceField(choices=["pl", "en"], default="pl")
    connection_id = serializers.UUIDField(allow_null=True)


class GscDisconnectInput(GscSiteInput):
    connection_id = serializers.UUIDField(allow_null=True)
    confirm_workspace_disconnect = serializers.BooleanField()

    def validate_confirm_workspace_disconnect(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError("Confirm disconnect for the whole organization.")
        return value


class GscGrantInput(GscSiteInput):
    property_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField()
    idempotency_key = serializers.RegexField(r"^[A-Za-z0-9_-]{8,64}$")

    def validate_expires_at(self, value):  # type: ignore[no-untyped-def]
        if not timezone.now() < value <= timezone.now() + timedelta(days=366):
            raise serializers.ValidationError("Expiry must be within the next 366 days.")
        return value


class GscSyncInput(StrictSerializer):
    client_reference = serializers.UUIDField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, data):  # type: ignore[no-untyped-def]
        if (
            not data["start_date"] <= data["end_date"] <= timezone.now().date()
            or (data["end_date"] - data["start_date"]).days > 366
        ):
            raise serializers.ValidationError("Choose a past date range of at most 366 days.")
        return data


class GscMetricsQuery(serializers.Serializer[dict[str, Any]]):
    sync_run_id = serializers.UUIDField()
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=25)


class GscGrantListQuery(GscSiteInput):
    cursor = serializers.UUIDField(required=False)


class GscProperty(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_url = serializers.CharField()
    permission_level = serializers.CharField()


class GscProperties(serializers.Serializer[dict[str, Any]]):
    connected = serializers.BooleanField()
    connection_id = serializers.UUIDField(allow_null=True)
    properties = GscProperty(many=True)


class GscAuthorization(serializers.Serializer[dict[str, Any]]):
    authorization_url = serializers.URLField()
    expires_at = serializers.DateTimeField()


class GscSync(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField(allow_null=True)
    client_reference = serializers.UUIDField()
    status = serializers.CharField()
    rows_received = serializers.IntegerField(min_value=0)
    is_truncated = serializers.BooleanField()


class GscGrant(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    property_id = serializers.UUIDField(allow_null=True)
    site_url = serializers.CharField(allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    connected = serializers.BooleanField()
    latest_sync = GscSync(allow_null=True)


class GscGrantSummary(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    property_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    outcome_known = serializers.BooleanField()


class GscGrantList(serializers.Serializer[dict[str, Any]]):
    items = GscGrantSummary(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class GscMetric(serializers.Serializer[dict[str, Any]]):
    dataset = serializers.CharField()
    date = serializers.DateField()
    query = serializers.CharField(allow_blank=True)
    page = serializers.CharField(allow_blank=True)
    country = serializers.CharField(allow_blank=True)
    device = serializers.CharField(allow_blank=True)
    search_appearance = serializers.CharField(allow_blank=True)
    clicks = serializers.IntegerField()
    impressions = serializers.IntegerField()
    ctr = serializers.FloatField()
    position = serializers.FloatField()


class GscMetrics(serializers.Serializer[dict[str, Any]]):
    count = serializers.IntegerField()
    next_page = serializers.IntegerField(allow_null=True)
    results = GscMetric(many=True)


class GscDisconnected(serializers.Serializer[dict[str, Any]]):
    disconnected = serializers.BooleanField()


class GscConnection(serializers.Serializer[dict[str, Any]]):
    connected = serializers.BooleanField()
    connection_id = serializers.UUIDField(allow_null=True)


class GscSyncReceipt(GscSyncInput):
    remote_id = serializers.UUIDField(allow_null=True)


class GscSyncHistory(serializers.Serializer[dict[str, Any]]):
    items = GscSyncReceipt(many=True)
