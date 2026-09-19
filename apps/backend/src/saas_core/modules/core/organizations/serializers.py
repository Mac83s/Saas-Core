from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers


class OrganizationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    slug = serializers.CharField(
        max_length=80,
        validators=[RegexValidator(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")],
    )
    workspace_kind = serializers.ChoiceField(
        choices=["personal", "business"],
        default="business",
    )
    default_locale = serializers.ChoiceField(choices=["pl", "en"], default="pl")
    timezone = serializers.CharField(max_length=64, default="Europe/Warsaw")
    currency = serializers.RegexField(r"^[A-Z]{3}$", default="PLN")
    #: A key of a type the product lets people create themselves (ADR-050).
    #: Optional only where the product has exactly one such type.
    organization_type = serializers.CharField(max_length=40, required=False)

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise serializers.ValidationError("Nieznana strefa czasowa.") from error
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        offered = [
            key
            for key, organization_type in settings.ORGANIZATION_TYPES.items()
            if organization_type.self_signup
        ]
        chosen = attrs.get("organization_type")
        if chosen is None and len(offered) == 1:
            attrs["organization_type"] = offered[0]
        elif chosen not in offered:
            raise serializers.ValidationError(
                {"organization_type": "Wybierz typ organizacji spośród dostępnych."}
            )
        return attrs


class OrganizationUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=160, trim_whitespace=True, required=False)
    default_locale = serializers.ChoiceField(choices=["pl", "en"], required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise serializers.ValidationError("Nieznana strefa czasowa.") from error
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if set(attrs) == {"version"}:
            raise serializers.ValidationError("Podaj co najmniej jedno pole do zmiany.")
        return attrs


class ActiveOrganizationSerializer(serializers.Serializer[dict[str, Any]]):
    organization_id = serializers.UUIDField()


class OrganizationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    workspace_kind = serializers.CharField()
    organization_type = serializers.CharField()
    status = serializers.CharField()
    default_locale = serializers.CharField()
    timezone = serializers.CharField()
    currency = serializers.CharField()
    version = serializers.IntegerField()
    membership_status = serializers.CharField()
    role = serializers.CharField()
    active = serializers.BooleanField()


class ActiveOrganizationResultSerializer(serializers.Serializer[dict[str, Any]]):
    organization = OrganizationSummarySerializer()


class OrganizationArchivedSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.ChoiceField(choices=["archived"])


class InvitationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    role = serializers.SlugField(max_length=64)


class InvitationAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(write_only=True, min_length=64, max_length=160)


class InvitationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()


class MembershipSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.CharField()
    joined_at = serializers.DateTimeField()


class MembershipUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    role = serializers.SlugField(max_length=64, required=False)
    status = serializers.ChoiceField(
        choices=["active", "suspended", "revoked"],
        required=False,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs:
            raise serializers.ValidationError("Podaj rolę albo status do zmiany.")
        return attrs


class OwnershipTransferSerializer(serializers.Serializer[dict[str, Any]]):
    membership_id = serializers.UUIDField()


class LifecycleResultSerializer(serializers.Serializer[dict[str, Any]]):
    status = serializers.CharField()
