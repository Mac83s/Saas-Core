from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class RegistrationSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, min_length=12, max_length=128)
    locale = serializers.ChoiceField(choices=["pl", "en"], default="pl")

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value


class VerificationRequestSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)


class VerificationConfirmSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(
        write_only=True,
        min_length=64,
        max_length=160,
        trim_whitespace=True,
    )


class GenericMessageSerializer(serializers.Serializer[dict[str, Any]]):
    detail = serializers.CharField()


class VerificationResultSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.ChoiceField(choices=["verified"])


class CsrfTokenSerializer(serializers.Serializer[dict[str, Any]]):
    csrf_token = serializers.CharField()


class ProblemDetailsSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    code = serializers.CharField()
    detail = serializers.JSONField()
    correlation_id = serializers.CharField(allow_null=True)


class LoginSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128)


class UserSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    status = serializers.CharField()
    locale = serializers.CharField()
    timezone = serializers.CharField()


class SessionSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    device_label = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    current = serializers.BooleanField()
