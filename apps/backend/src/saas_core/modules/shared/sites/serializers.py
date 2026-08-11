from __future__ import annotations

from typing import Any

from rest_framework import serializers


class CursorQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class SiteCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )
    default_locale = serializers.ChoiceField(choices=["pl", "en"], default="pl")


class SiteSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    default_locale = serializers.CharField()
    current_publication_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SiteListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    key = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )


class PageSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    name = serializers.CharField()
    key = serializers.CharField()
    version = serializers.IntegerField()
    current_draft_id = serializers.UUIDField(allow_null=True)
    current_draft_hash = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PageListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PageSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageBlockInputSerializer(serializers.Serializer[dict[str, Any]]):
    block_type = serializers.RegexField(
        r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=120,
    )
    schema_version = serializers.IntegerField(min_value=1)
    data = serializers.JSONField()  # type: ignore[assignment]

    def validate_data(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Dane bloku muszą być obiektem JSON.")
        return value


class DraftSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    blocks = PageBlockInputSerializer(many=True, allow_empty=True)

    def validate_blocks(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 200:
            raise serializers.ValidationError("Draft może zawierać maksymalnie 200 bloków.")
        return value


class PageBlockSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    position = serializers.IntegerField()
    block_type = serializers.CharField()
    schema_version = serializers.IntegerField()
    data = serializers.JSONField()  # type: ignore[assignment]


class PageDraftSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    version = serializers.IntegerField()
    draft_id = serializers.UUIDField(allow_null=True)
    content_hash = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    blocks = PageBlockSerializer(many=True)
