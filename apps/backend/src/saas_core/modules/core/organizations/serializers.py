from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers

from .command_registry import RISKS
from .context import ACTING_VIA
from .options import (
    DEFAULT_CURRENCY,
    SETTING_STRATEGIES,
    SETTING_TYPES,
    SETTING_UNITS,
    currency_codes,
)


def _offered_currency(value: str) -> str:
    offered = currency_codes()
    if value not in offered:
        raise serializers.ValidationError(
            f"Wybierz walutę z listy: {', '.join(offered)}.", code="currency_not_offered"
        )
    return value


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
    currency = serializers.RegexField(r"^[A-Z]{3}$", default=DEFAULT_CURRENCY)
    #: A key of a type the product lets people create themselves (ADR-050).
    #: Optional only where the product has exactly one such type.
    organization_type = serializers.CharField(max_length=40, required=False)

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise serializers.ValidationError("Nieznana strefa czasowa.") from error
        return value

    def validate_currency(self, value: str) -> str:
        return _offered_currency(value)

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

    def validate_currency(self, value: str) -> str:
        return _offered_currency(value)

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
    #: What this membership may do here. Roles differ per organization type
    #: (ADR-050), so a screen hides what the person cannot use by permission,
    #: never by the role's name. The API still checks every call.
    permissions = serializers.ListField(child=serializers.CharField())
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
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role = serializers.CharField()
    status = serializers.CharField()
    joined_at = serializers.DateTimeField()
    #: When a former member lost access or left; null for a current one.
    revoked_at = serializers.DateTimeField(allow_null=True)
    #: Whether the person signs in with two-factor verification (35a) — shown
    #: to who manages the team or the company's settings; null for others.
    mfa_enabled = serializers.BooleanField(allow_null=True, required=False)


class MembershipListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    #: Former members too, each with their last membership (management only).
    include_former = serializers.BooleanField(default=False)


class SeatUsageSerializer(serializers.Serializer[dict[str, Any]]):
    """Accounts that log in against the plan's limit (owner's answer 5)."""

    used = serializers.IntegerField()
    #: Null: the plan names no limit.
    limit = serializers.IntegerField(allow_null=True)


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


class RoleSummarySerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    name = serializers.CharField()
    scope = serializers.ChoiceField(choices=["system", "organization"])
    permissions = serializers.ListField(child=serializers.CharField())
    limited = serializers.BooleanField()
    version = serializers.IntegerField()


class RoleCatalogSerializer(serializers.Serializer[dict[str, Any]]):
    roles = RoleSummarySerializer(many=True)
    grantable_permissions = serializers.ListField(child=serializers.CharField())


class RoleCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    permissions = serializers.ListField(child=serializers.CharField(max_length=120))


class RoleUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=80, trim_whitespace=True, required=False)
    permissions = serializers.ListField(child=serializers.CharField(max_length=120), required=False)


class HistoryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=25)
    action = serializers.CharField(max_length=64, required=False, default="")
    #: A settings group (ADR-078 pkt 7): its changes, whichever field.
    group = serializers.CharField(
        max_length=120,
        required=False,
        default="",
        help_text="A settings group, e.g. booking.reminders.",
    )
    #: One setting: the changes of its group that touched it.
    key = serializers.CharField(
        max_length=120,
        required=False,
        default="",
        help_text="One setting, e.g. booking.reminders.lead_hours.",
    )


class HistoryActorSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField()
    email = serializers.EmailField()


class HistoryActingSerializer(serializers.Serializer[dict[str, Any]]):
    via = serializers.ChoiceField(choices=sorted(ACTING_VIA))
    ref = serializers.CharField(help_text="conversation:<uuid> or translation_job:<uuid>")
    trigger = serializers.CharField(allow_null=True)


class HistoryTargetSerializer(serializers.Serializer[dict[str, Any]]):
    label = serializers.CharField(  # type: ignore[assignment]
        help_text="What the object is called, e.g. a farm's name."
    )
    href = serializers.CharField(
        allow_blank=True, help_text="The panel address that shows it; empty when none does."
    )
    at = serializers.DateTimeField(
        allow_null=True, help_text="The object's own time, e.g. a visit's start."
    )


class HistoryEntrySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField()
    action = serializers.CharField()
    actor = HistoryActorSerializer(allow_null=True)
    channel = serializers.ChoiceField(choices=["panel", "api_key", "system"], allow_null=True)
    #: The membership acted for `actor` through the assistant or a translation
    #: job (ADR-076 §6); null when the person acted directly.
    acting = HistoryActingSerializer(allow_null=True)
    target_type = serializers.CharField(allow_blank=True)
    target_id = serializers.UUIDField(allow_null=True)
    #: The object by name, where its module names it and it still exists.
    target = HistoryTargetSerializer(allow_null=True)
    changes = serializers.DictField(child=serializers.JSONField())
    changed_fields = serializers.ListField(child=serializers.CharField())
    details = serializers.DictField(child=serializers.JSONField())


class HistoryPageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    actions = serializers.ListField(child=serializers.CharField())
    items = HistoryEntrySerializer(many=True)


class LocalizedTextSerializer(serializers.Serializer[dict[str, Any]]):
    pl = serializers.CharField()
    en = serializers.CharField()


class SettingValueOptionSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.CharField()
    label = LocalizedTextSerializer()  # type: ignore[assignment]


class SettingOptionSerializer(serializers.Serializer[dict[str, Any]]):
    """One setting a company may choose, with what it may choose; the shape of
    an entry of the settings registry's schema (ADR-078 pkt 11)."""

    key = serializers.CharField(help_text="Stable key, e.g. organization.currency.")
    type = serializers.ChoiceField(choices=SETTING_TYPES)
    minimum = serializers.IntegerField(allow_null=True)
    maximum = serializers.IntegerField(allow_null=True)
    unit = serializers.ChoiceField(choices=SETTING_UNITS, allow_null=True)
    values = SettingValueOptionSerializer(many=True, allow_null=True)
    default = serializers.JSONField(help_text="The value a new company starts with.")
    label = LocalizedTextSerializer()  # type: ignore[assignment]
    help = LocalizedTextSerializer(allow_null=True)
    description = serializers.CharField(help_text="What the setting does, in English.")
    scopes = serializers.ListField(child=serializers.CharField())
    depends_on = serializers.CharField(allow_null=True)
    strategy = serializers.ChoiceField(
        choices=SETTING_STRATEGIES,
        help_text="restrict: the value in force may be stricter than the company's — the "
        "module applies its ceilings (operator, deployment) on top.",
    )
    max_length = serializers.IntegerField(
        allow_null=True, required=False, help_text="The longest a text may be."
    )


class SettingOptionsSerializer(serializers.Serializer[dict[str, Any]]):
    keys = SettingOptionSerializer(many=True)


class CommandEffectSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.CharField()
    resource = serializers.CharField()
    resource_id = serializers.CharField(allow_blank=True)
    summary = LocalizedTextSerializer()


class CommandConsentCallSerializer(serializers.Serializer[dict[str, Any]]):
    step_id = serializers.UUIDField()
    command = serializers.CharField(help_text="name@version")
    title = LocalizedTextSerializer()
    summary = LocalizedTextSerializer()
    risk = serializers.ChoiceField(choices=list(RISKS))
    effects = CommandEffectSerializer(many=True)
    quote = serializers.JSONField(allow_null=True)
    person_gates = serializers.ListField(child=serializers.CharField())


class CommandConsentSerializer(serializers.Serializer[dict[str, Any]]):
    """What the person is asked to agree to, exactly as the server previewed it."""

    digest = serializers.CharField()
    risk = serializers.ChoiceField(choices=list(RISKS))
    step_up_required = serializers.BooleanField()
    expires_at = serializers.DateTimeField()
    calls = CommandConsentCallSerializer(many=True)


class CommandConsentGrantSerializer(serializers.Serializer[dict[str, Any]]):
    consent_token = serializers.CharField()
    expires_at = serializers.DateTimeField()
