from typing import Any, cast

from rest_framework import serializers

from saas_core.modules.shared.notifications.models import DeliveryStatus


class SiteInquirySubmitSerializer(serializers.Serializer[dict[str, Any]]):
    publication_id = serializers.UUIDField()
    path = serializers.CharField(max_length=500)
    block_position = serializers.IntegerField(min_value=0, max_value=1000)
    name = serializers.CharField(max_length=120)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    message = serializers.CharField(max_length=5000)
    website = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Nieznane pola formularza."]})
        return cast(dict[str, Any], super().to_internal_value(data))

    def validate_path(self, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or any(c in value for c in "?#\\"):
            raise serializers.ValidationError("Nieprawidłowa ścieżka strony.")
        return value

    def validate_website(self, value: str) -> str:
        if value:
            raise serializers.ValidationError("Nieprawidłowe zgłoszenie.")
        return value


class SiteInquiryAcceptedSerializer(serializers.Serializer[dict[str, Any]]):
    accepted = serializers.BooleanField()
    reference = serializers.UUIDField()


class SiteInquirySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    page_path = serializers.CharField()
    name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()
    message = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)
    email_status = serializers.ChoiceField(
        choices=[*DeliveryStatus.choices, ("unavailable", "Niedostępny")]
    )


class SiteInquiryListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteInquirySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class SiteInquiryListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=30)
