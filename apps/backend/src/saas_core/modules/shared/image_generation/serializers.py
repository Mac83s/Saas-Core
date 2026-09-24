from typing import Any, cast

from rest_framework import serializers

from .models import ASPECTS, ImageGenerationJob


class ImageGenerationOfferSerializer(serializers.Serializer[dict[str, Any]]):
    available = serializers.BooleanField()
    credit_cost = serializers.IntegerField(min_value=0)
    aspects = serializers.ListField(child=serializers.ChoiceField(choices=list(ASPECTS)))


class ImageGenerationRequestSerializer(serializers.Serializer[dict[str, Any]]):
    prompt = serializers.CharField(min_length=3, max_length=1000)
    aspect = serializers.ChoiceField(choices=list(ASPECTS))
    expected_cost = serializers.IntegerField(min_value=0)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({
                "non_field_errors": ["Unknown image generation request fields."]
            })
        return cast(dict[str, Any], super().to_internal_value(data))


class ImageGenerationJobSerializer(serializers.ModelSerializer[ImageGenerationJob]):
    """Never the prompt: it is the customer's text and is not echoed back."""

    class Meta:
        model = ImageGenerationJob
        fields = [
            "id",
            "state",
            "aspect",
            "width",
            "height",
            "media_asset_id",
            "error_code",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields
