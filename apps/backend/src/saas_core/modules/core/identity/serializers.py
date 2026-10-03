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


class ProblemFieldErrorSerializer(serializers.Serializer[dict[str, Any]]):
    field = serializers.CharField(
        allow_null=True,
        help_text=(
            "Path of the failing value in the request data (body or query): segments "
            "joined with dots, list positions as numbers (`address.city`, `items.1.name`). "
            "Null when the error concerns the request as a whole."
        ),
    )
    code = serializers.CharField(
        help_text=(
            "Machine-readable reason: a validation code (`required`, `max_length`, "
            "`invalid_choice`), a Django validator's code or a domain code."
        )
    )
    message = serializers.CharField(
        help_text="A sentence for a person, in the server's language; for display only."
    )


class ProblemDetailsSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField(help_text="Always `about:blank`; `code` names the problem.")
    title = serializers.CharField(help_text="A fixed, generic title in the server's language.")
    status = serializers.IntegerField(help_text="The HTTP status of the response.")
    code = serializers.CharField(
        help_text=(
            "Stable machine-readable code of the problem; clients branch on it. Input "
            "validation answers `invalid` unless the operation names a domain code."
        )
    )
    detail = serializers.JSONField(
        help_text=(
            "For display only: a sentence, or for input validation a map of field to "
            "messages. A program reads `code` and `errors` instead."
        )
    )
    correlation_id = serializers.CharField(
        allow_null=True,
        help_text="The request's `X-Correlation-ID`, to quote when reporting the problem.",
    )
    errors = ProblemFieldErrorSerializer(  # type: ignore[assignment]
        many=True,
        required=False,
        help_text=(
            "On 400 and 422 only, never empty: each problem the caller can act on, with "
            "the failing field (or null for the whole request), its code and a message."
        ),
    )


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
    operator_level = serializers.IntegerField(
        required=False,
        help_text="0: not a platform operator; 1: an operator (staff with 2FA); 2: a platform "
        "administrator. The „Platforma” panel is for 1 and 2.",
    )


class UserUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """What a person may change about themselves from the panel."""

    first_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=80, required=False, allow_blank=True)


class SessionsEndedSerializer(serializers.Serializer[dict[str, Any]]):
    ended = serializers.IntegerField(help_text="How many other sessions ended.")


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


class StepUpSerializer(serializers.Serializer[dict[str, Any]]):
    code = serializers.CharField(write_only=True, min_length=6, max_length=32)

    def validate_code(self, value: str) -> str:
        return value.strip()


class StepUpResultSerializer(serializers.Serializer[dict[str, Any]]):
    stepped_up_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
