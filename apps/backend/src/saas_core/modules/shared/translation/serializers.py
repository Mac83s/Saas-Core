from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.serializers import SettingOptionSerializer

from .glossary import FORMS_MAX, TERM_MAX_LENGTH
from .models import GlossaryRule, TranslationGlossaryTerm
from .settings_spec import AUTO_MONTHLY_LIMIT, COMPANY_SETTINGS, MODE


class SettingValueSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.JSONField(
        allow_null=True, help_text="The company's own value; null when it inherits."
    )
    effective = serializers.JSONField(help_text="What applies now, after defaults and locks.")
    source = serializers.CharField(  # type: ignore[assignment]
        help_text="code, product, organization, operator or platform."
    )
    locked = serializers.BooleanField(help_text="The operator or the deployment decides it now.")
    lock_reason = serializers.CharField(allow_null=True)
    operator_reason = serializers.CharField(
        allow_null=True, help_text="The operator's reason, shown to the company."
    )


class AutomationStateSerializer(serializers.Serializer[dict[str, Any]]):
    consent_membership_id = serializers.UUIDField(
        allow_null=True, help_text="The person whose consent the automation acts on."
    )
    consent_at = serializers.DateTimeField(allow_null=True)


class TranslationSettingsSerializer(serializers.Serializer[dict[str, Any]]):
    group = serializers.CharField()
    version = serializers.IntegerField(help_text="Send it back as `expected_version`.")
    values = serializers.DictField(
        child=SettingValueSerializer(),
        help_text="By setting key: translation.settings.mode, .auto_changes, .auto_monthly_limit.",
    )
    automation = AutomationStateSerializer()
    processing_acknowledged = serializers.BooleanField(
        help_text="The company confirmed that content goes to OpenRouter and model providers "
        "outside the EEA."
    )
    processing_ack_at = serializers.DateTimeField(allow_null=True)


class TranslationSettingsPreviewSerializer(TranslationSettingsSerializer):
    changes = serializers.DictField(help_text="What would change, as the history keeps it.")


class TranslationSettingsUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    mode = serializers.ChoiceField(
        choices=MODE.variants,
        required=False,
        allow_null=True,
        help_text="automatic or review; null leaves it as it is.",
    )
    auto_changes = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Translate changes automatically. Turning it on is your consent: the "
        "automation will act as you.",
    )
    auto_monthly_limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=AUTO_MONTHLY_LIMIT.minimum or 0,
        max_value=AUTO_MONTHLY_LIMIT.maximum or 0,
        help_text="Credits a month translations without a click may spend; 0 turns it off.",
    )
    processing_acknowledged = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Confirm once that content goes to OpenRouter and model providers outside "
        "the EEA. Only true is accepted.",
    )
    reset = serializers.ListField(
        child=serializers.ChoiceField(choices=[d.key for d in COMPANY_SETTINGS]),
        required=False,
        allow_null=True,
        help_text="Keys to take back to the inherited value.",
    )
    expected_version = serializers.IntegerField(
        min_value=0, help_text="The settings version this change was made on."
    )

    def changes(self) -> dict[str, Any]:
        data = self.validated_data
        names = {
            "mode": "translation.settings.mode",
            "auto_changes": "translation.settings.auto_changes",
            "auto_monthly_limit": "translation.settings.auto_monthly_limit",
            "processing_acknowledged": "translation.settings.processing_acknowledged",
        }
        return {key: data[name] for name, key in names.items() if data.get(name) is not None}


class OfferAutomationSerializer(AutomationStateSerializer):
    enabled = serializers.BooleanField()
    monthly_limit = serializers.IntegerField()


class OfferBillingSerializer(serializers.Serializer[dict[str, Any]]):
    mode = serializers.CharField(
        help_text="credits, or platform_budget for the platform workspace."
    )
    operation_key = serializers.CharField()
    unit_characters = serializers.IntegerField(
        help_text="Visible source characters in one unit, per target language."
    )
    credits_per_unit = serializers.IntegerField(
        allow_null=True, help_text="Null while the price is not set (operation_unpriced)."
    )


class TranslationOfferSerializer(serializers.Serializer[dict[str, Any]]):
    available = serializers.BooleanField()
    reasons = serializers.ListField(
        child=serializers.CharField(),
        help_text="Why not: processor_not_listed, model_not_selected, operation_unpriced, "
        "worker_unavailable, disabled, suspended, processing_ack_required.",
    )
    mode = SettingValueSerializer()
    automation = OfferAutomationSerializer()
    billing = OfferBillingSerializer()
    settings = SettingOptionSerializer(many=True)
    glossary_limit = serializers.IntegerField()


class GlossaryTermSerializer(serializers.ModelSerializer[TranslationGlossaryTerm]):
    class Meta:
        model = TranslationGlossaryTerm
        fields = [
            "id",
            "term",
            "rule",
            "source_locale",
            "target_locale",
            "translation",
            "forms",
            "version",
            "created_at",
            "updated_at",
        ]


class GlossaryTermPreviewSerializer(GlossaryTermSerializer):
    changes = serializers.DictField(read_only=True)

    class Meta(GlossaryTermSerializer.Meta):
        fields = [*GlossaryTermSerializer.Meta.fields, "changes"]


class GlossaryTermInputSerializer(serializers.Serializer[dict[str, Any]]):
    term = serializers.CharField(max_length=TERM_MAX_LENGTH, help_text="As written in the source.")
    rule = serializers.ChoiceField(
        choices=GlossaryRule.choices,
        help_text="keep: unchanged everywhere; name: a person's name, transliterated into "
        "Cyrillic; translate_as: your translation.",
    )
    source_locale = serializers.CharField(max_length=10)
    target_locale = serializers.CharField(
        max_length=10, required=False, allow_blank=True, help_text="Empty: every language."
    )
    translation = serializers.CharField(
        max_length=TERM_MAX_LENGTH, required=False, allow_blank=True, help_text="translate_as only."
    )
    forms = serializers.ListField(
        child=serializers.CharField(max_length=TERM_MAX_LENGTH),
        required=False,
        max_length=FORMS_MAX,
        help_text="Inflected forms in the source language, at most 10.",
    )


class GlossaryTermUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    term = serializers.CharField(max_length=TERM_MAX_LENGTH, required=False, allow_null=True)
    rule = serializers.ChoiceField(choices=GlossaryRule.choices, required=False, allow_null=True)
    source_locale = serializers.CharField(max_length=10, required=False, allow_null=True)
    target_locale = serializers.CharField(
        max_length=10, required=False, allow_blank=True, allow_null=True
    )
    translation = serializers.CharField(
        max_length=TERM_MAX_LENGTH, required=False, allow_blank=True, allow_null=True
    )
    forms = serializers.ListField(
        child=serializers.CharField(max_length=TERM_MAX_LENGTH),
        required=False,
        allow_null=True,
        max_length=FORMS_MAX,
    )
    expected_version = serializers.IntegerField(min_value=1)


class GlossaryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.CharField(required=False, help_text="From the previous page.")
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, default=50)


class GlossaryPageSerializer(serializers.Serializer[dict[str, Any]]):
    items = GlossaryTermSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class GlossaryDeleteQuerySerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=1)
