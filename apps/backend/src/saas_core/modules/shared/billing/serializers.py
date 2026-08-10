from typing import Any

from rest_framework import serializers


class StripeWebhookReceiptSerializer(serializers.Serializer[dict[str, Any]]):
    received = serializers.BooleanField()


class CheckoutCreateSerializer(serializers.Serializer[dict[str, Any]]):
    plan = serializers.SlugField(max_length=64)


class BillingSessionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.CharField()
    url = serializers.URLField()
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
