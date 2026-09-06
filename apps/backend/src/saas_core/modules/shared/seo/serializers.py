from typing import Any, cast

from rest_framework import serializers

from .models import AuditOrder


class AuditRequestSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(min_length=8, max_length=120)
    max_pages = serializers.IntegerField(min_value=1, required=False)
    expected_credit_cost = serializers.IntegerField(min_value=0, required=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({
                "non_field_errors": ["Unknown audit request fields."]
            })
        return cast(dict[str, Any], super().to_internal_value(data))


class AuditOrderSerializer(serializers.ModelSerializer[AuditOrder]):
    site_id = serializers.UUIDField(source="binding.site_id")

    class Meta:
        model = AuditOrder
        fields = [
            "id",
            "site_id",
            "state",
            "requested_options",
            "effective_options",
            "credit_cost",
            "credit_state",
            "report_snapshot",
            "report_hash",
            "error_code",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = fields


class CallbackResultSerializer(serializers.Serializer[dict[str, Any]]):
    accepted = serializers.BooleanField()


class CallbackEnvelopeSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=["module_run.finished"])
    run = serializers.JSONField(
        help_text="SSA module identity, terminal status and source binding; signed raw bytes."
    )


class AuditListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class AuditListSerializer(serializers.Serializer[dict[str, Any]]):
    items = AuditOrderSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class AuditOfferSerializer(serializers.Serializer[dict[str, Any]]):
    credit_cost = serializers.IntegerField(min_value=0)
    max_pages = serializers.IntegerField(min_value=1)
