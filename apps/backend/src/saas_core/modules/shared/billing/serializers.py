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


class TrialActivationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    checkout_session_id = serializers.CharField(min_length=1, max_length=160)


class TrialActivationResultSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    status = serializers.CharField()
    created = serializers.BooleanField()


class CustomerPlanSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.SlugField()
    name = serializers.CharField()
    description = serializers.CharField()
    version = serializers.IntegerField()
    currency = serializers.CharField()
    billing_interval = serializers.CharField()
    unit_amount_minor = serializers.IntegerField()
    trial_days = serializers.IntegerField()
    features = serializers.ListField(child=serializers.CharField())
    quotas = serializers.DictField(child=serializers.IntegerField())
    is_current = serializers.BooleanField()
    checkout_available = serializers.BooleanField()


class CustomerSubscriptionSerializer(serializers.Serializer[dict[str, Any]]):
    state = serializers.CharField()
    access_mode = serializers.CharField(allow_null=True)
    plan_key = serializers.CharField(allow_null=True)
    plan_version = serializers.IntegerField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    trial_end = serializers.DateTimeField(allow_null=True)
    grace_period_end = serializers.DateTimeField(allow_null=True)
    cancel_at_period_end = serializers.BooleanField()


class CustomerBillingOverviewSerializer(serializers.Serializer[dict[str, Any]]):
    can_manage = serializers.BooleanField()
    payment_mode = serializers.ChoiceField(choices=["stripe", "simulated"])
    portal_available = serializers.BooleanField()
    subscription = CustomerSubscriptionSerializer(allow_null=True)
    plans = CustomerPlanSerializer(many=True)


class EntitlementSupportSnapshotSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    version = serializers.IntegerField()
    subscription_state = serializers.CharField()
    access_mode = serializers.CharField()
    plan_key = serializers.CharField(allow_null=True)
    plan_version = serializers.IntegerField(allow_null=True)
    computed_at = serializers.DateTimeField()
    effective_until = serializers.DateTimeField(allow_null=True)


class EntitlementSupportItemSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=["feature", "quota"])
    key = serializers.CharField()
    available = serializers.BooleanField()
    reason = serializers.CharField()
    read_allowed = serializers.BooleanField(allow_null=True)
    read_reason = serializers.CharField(allow_null=True)
    value = serializers.IntegerField(allow_null=True)
    used = serializers.IntegerField(allow_null=True)
    reserved = serializers.IntegerField(allow_null=True)
    period_start = serializers.DateField(allow_null=True)
    period_end = serializers.DateField(allow_null=True)
    evidence = serializers.JSONField(allow_null=True)


class EntitlementSupportReportSerializer(serializers.Serializer[dict[str, Any]]):
    snapshot = EntitlementSupportSnapshotSerializer(allow_null=True)
    items = EntitlementSupportItemSerializer(many=True)
