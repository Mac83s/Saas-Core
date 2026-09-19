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


class MfaChallengeSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.ChoiceField(choices=["mfa_required"])


class MfaCodeSerializer(serializers.Serializer[dict[str, Any]]):
    code = serializers.CharField(write_only=True, min_length=6, max_length=32)

    def validate_code(self, value: str) -> str:
        return value.strip()


class TotpSetupSerializer(serializers.Serializer[dict[str, Any]]):
    secret = serializers.CharField()
    provisioning_uri = serializers.CharField()


class TotpConfirmResultSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.ChoiceField(choices=["mfa_enabled"])
    recovery_codes = serializers.ListField(child=serializers.CharField())


class UserSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    status = serializers.CharField()
    locale = serializers.CharField()
    timezone = serializers.CharField()


class UserUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """What a person may change about themselves from the panel."""

    first_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)


class SessionSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    device_label = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    current = serializers.BooleanField()


class PasswordResetRequestSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(write_only=True, min_length=64, max_length=160)
    password = serializers.CharField(write_only=True, min_length=12, max_length=128)

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value


class PasswordResetResultSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.ChoiceField(choices=["password_updated"])
