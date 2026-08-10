from rest_framework import serializers


class StripeWebhookReceiptSerializer(serializers.Serializer):
    received = serializers.BooleanField()
