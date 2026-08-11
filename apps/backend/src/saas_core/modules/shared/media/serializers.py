from __future__ import annotations

from typing import Any

from rest_framework import serializers


class MediaUploadCreateSerializer(serializers.Serializer[dict[str, Any]]):
    filename = serializers.CharField(max_length=255, trim_whitespace=True)
    content_type = serializers.CharField(max_length=80, trim_whitespace=True)
    size = serializers.IntegerField(min_value=1)


class MediaAssetSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    original_filename = serializers.CharField()
    declared_mime = serializers.CharField()
    expected_size = serializers.IntegerField()
    actual_size = serializers.IntegerField(allow_null=True)
    state = serializers.CharField()
    upload_expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()


class MediaUploadSerializer(serializers.Serializer[dict[str, Any]]):
    asset = MediaAssetSerializer()
    upload_url = serializers.URLField(max_length=4096)
    upload_headers = serializers.DictField(child=serializers.CharField())
