from typing import Any

from rest_framework import serializers

from .language_versions import OVERVIEW_KINDS, OVERVIEW_STATES
from .localized_bodies import (
    DATA_PUBLIC,
    DATA_PUBLIC_PERSONAL,
    UNIT_ADDRESS,
    UNIT_INLINE,
    UNIT_NAME,
    UNIT_TEXT,
)


class LocaleBodyUnitSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(
        help_text="Block position and JSON path, e.g. `2/items/0/question`. Stable for one "
        "source version."
    )
    kind = serializers.ChoiceField(
        choices=[UNIT_TEXT, UNIT_INLINE, UNIT_NAME, UNIT_ADDRESS],
        help_text="`inline` carries its marks as tokens ⟦n⟧…⟦/n⟧ that must stay; `name` and "
        "`address` are copied into every language unless overridden.",
    )
    source_text = serializers.CharField(help_text="The text in the source language.")
    text = serializers.CharField(
        allow_null=True, help_text="This language's text; null where nothing was written."
    )
    origin = serializers.CharField(
        allow_null=True,
        help_text="Who wrote it: human, ai, integration, template, import, or copy (the source "
        "text standing in, still untranslated).",
    )
    translated = serializers.BooleanField()
    suggestion = serializers.CharField(
        allow_null=True,
        help_text="A person's text for this unit's earlier source wording, kept when the "
        "source changed; for review, never published as the translation.",
    )
    data_class = serializers.ChoiceField(choices=[DATA_PUBLIC, DATA_PUBLIC_PERSONAL])
    placeholder = serializers.BooleanField(
        help_text="The source holds an owner's [Uzupełnij: …] slot; the language version "
        "waits until the owner fills the source."
    )
    max_length = serializers.IntegerField(allow_null=True)
    required_text = serializers.BooleanField(help_text="The unit may not be left empty.")


class LocaleBodySerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    locale = serializers.CharField()
    source_version_id = serializers.UUIDField(
        help_text="The source version this language follows; send it back when saving."
    )
    source_version = serializers.IntegerField(help_text="Its number in the page's history.")
    outdated = serializers.BooleanField(
        help_text="The source has a newer version than the one this language follows."
    )
    body_version = serializers.IntegerField(
        help_text="This language's own lock; send it back as `expected_body_version`."
    )
    version = serializers.IntegerField(
        allow_null=True, help_text="Number of the current body version; null before the first."
    )
    untranslated = serializers.IntegerField(help_text="Units still without a translation.")
    units = LocaleBodyUnitSerializer(many=True)


class LocaleBodySaveSerializer(serializers.Serializer[dict[str, Any]]):
    source_version_id = serializers.UUIDField()
    expected_body_version = serializers.IntegerField(min_value=0)
    units = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=12000),
        allow_empty=False,
        help_text="Unit key → text. Units not named keep what they have. Inline units keep "
        "their tokens.",
    )


class LocaleBodyCopySerializer(serializers.Serializer[dict[str, Any]]):
    source_version_id = serializers.UUIDField()
    expected_body_version = serializers.IntegerField(min_value=0)


class LocaleBodyRestoreSerializer(serializers.Serializer[dict[str, Any]]):
    expected_body_version = serializers.IntegerField(min_value=0)


class LocaleBodyVersionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    number = serializers.IntegerField()
    source_version_id = serializers.UUIDField()
    source_version = serializers.IntegerField()
    origin = serializers.CharField(help_text="save, copy, restore, or a translation job.")
    origin_ref = serializers.CharField()
    created_at = serializers.DateTimeField()


class LocaleBodyVersionListSerializer(serializers.Serializer[dict[str, Any]]):
    items = LocaleBodyVersionSerializer(many=True)


class LocaleBodyVersionPreviewSerializer(serializers.Serializer[dict[str, Any]]):
    version = LocaleBodyVersionSerializer()
    blocks = serializers.ListField(
        child=serializers.DictField(), help_text="The blocks a visitor would get."
    )


class LocaleBodyRebaseSerializer(serializers.Serializer[dict[str, Any]]):
    expected_body_version = serializers.IntegerField(min_value=0)


class TranslationOverviewQuerySerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=OVERVIEW_KINDS, default="page")
    locale = serializers.RegexField(r"^[a-z]{2}$", required=False)
    state = serializers.ChoiceField(choices=OVERVIEW_STATES, required=False)
    cursor = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class TranslationOverviewCellSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    state = serializers.ChoiceField(choices=OVERVIEW_STATES)
    untranslated = serializers.IntegerField(allow_null=True)
    metadata_complete = serializers.BooleanField(
        allow_null=True, help_text="Own address, title and description (pages only)."
    )


class TranslationOverviewRowSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=OVERVIEW_KINDS)
    id = serializers.UUIDField(help_text="The page, or the article's translation group.")
    title = serializers.CharField()
    cells = TranslationOverviewCellSerializer(many=True)


class TranslationOverviewSerializer(serializers.Serializer[dict[str, Any]]):
    locales = serializers.ListField(child=serializers.CharField())
    items = TranslationOverviewRowSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)
