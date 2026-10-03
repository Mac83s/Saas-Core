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


class LocaleBodyMarkSerializer(serializers.Serializer[dict[str, Any]]):
    bold = serializers.BooleanField(required=False)
    italic = serializers.BooleanField(required=False)
    href = serializers.CharField(required=False)
    rel = serializers.CharField(required=False)


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
    marks = LocaleBodyMarkSerializer(
        many=True,
        help_text="For an `inline` unit, what each token marks in the source: `⟦n⟧` is entry "
        "n-1. A translation keeps every token and may move it, never change it.",
    )


class LocaleBodyPendingSerializer(serializers.Serializer[dict[str, Any]]):
    version_id = serializers.UUIDField()
    number = serializers.IntegerField()
    reason = serializers.CharField(
        allow_blank=True,
        help_text="Why it waits: the translation engine's review reason (e.g. `review_mode`, "
        "`legal_document`, `overwrites_human`, `qa_flagged`).",
    )


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
    version_id = serializers.UUIDField(
        allow_null=True, help_text="The current body version, for its read-only preview."
    )
    pending = LocaleBodyPendingSerializer(
        allow_null=True,
        help_text="A translation waiting for a person's decision (accept or reject), or null.",
    )
    withdrawn = serializers.BooleanField(
        help_text="A person took this language version off the site; it stays off until "
        "somebody publishes it again."
    )
    untranslated = serializers.IntegerField(help_text="Units still without a translation.")
    block_types = serializers.ListField(
        child=serializers.CharField(),
        help_text="The source's sections in order; a unit key starts with the position.",
    )
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


SKIP_REASONS = [
    "metadata_incomplete",
    "untranslated_units",
    "source_placeholder",
    "locale_home_missing",
    "source_unpublished",
    "source_outdated",
    "media_unavailable",
]


class LanguageDecisionSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    locale = serializers.CharField()
    published = serializers.BooleanField(help_text="Whether the version went out.")
    publication_id = serializers.UUIDField(
        allow_null=True, help_text="The derived publication made by this decision."
    )
    skipped = serializers.ChoiceField(
        choices=SKIP_REASONS,
        allow_null=True,
        help_text="Why the version did not go out (ADR-070 pkt 6).",
    )


class LocaleAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    expected_body_version = serializers.IntegerField(min_value=0)


class LocaleBatchItemSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    locale = serializers.RegexField(r"^[a-z]{2}$")
    expected_body_version = serializers.IntegerField(min_value=0)


class LocaleBatchAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    items = serializers.ListField(
        child=LocaleBatchItemSerializer(), allow_empty=False, max_length=100
    )
    digest = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="The digest the preview returned; required for more than one item.",
    )

    def validate_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len({(item["page_id"], item["locale"]) for item in items}) != len(items):
            raise serializers.ValidationError(
                "Każda wersja językowa może być na liście tylko raz.", code="duplicate"
            )
        return items


class LocaleBatchResultSerializer(serializers.Serializer[dict[str, Any]]):
    items = LanguageDecisionSerializer(many=True)
    digest = serializers.CharField(
        allow_null=True, help_text="Present on a preview: send it back to accept this list."
    )


SITE_TEXT_ROLES = ["tagline", "footer", "footer_link", "collection", "tag"]
SITE_TEXT_STATES = ["fresh", "stale", "unverified", "missing"]


class SiteTextItemSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(
        help_text="Where the text stands: `header/tagline`, `footer/text`, "
        "`footer/link/<address hash>`, `collection/<id>` or `tag/<id>` — not its position, "
        "so a reordered footer keeps its keys."
    )
    role = serializers.ChoiceField(choices=SITE_TEXT_ROLES)
    source_text = serializers.CharField(help_text="The text in the site's language.")
    text = serializers.CharField(
        allow_blank=True, help_text="This language's translation; empty where there is none."
    )
    origin = serializers.CharField(
        allow_blank=True, help_text="Who wrote the translation: human, ai, integration or copy."
    )
    state = serializers.ChoiceField(
        choices=SITE_TEXT_STATES,
        help_text="`stale`: translated from an earlier wording of this text; visitors read "
        "the source text instead, unless a person or an integration wrote the translation.",
    )
    pending_text = serializers.CharField(
        allow_blank=True, help_text="A translation waiting for a person's decision."
    )
    pending_reason = serializers.CharField(allow_blank=True)


class SiteTextsSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    locale = serializers.CharField()
    version = serializers.CharField(
        help_text="Send it back with a save; another save in between answers 409 "
        "`site_texts_version_conflict`."
    )
    items = SiteTextItemSerializer(many=True)


class SiteTextsSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.CharField(max_length=32)
    texts = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=True, max_length=300),
        allow_empty=False,
        help_text="Translations by key; an empty one removes the translation, so visitors "
        "read the source text again.",
    )


class SiteTextsPublicationSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    locale = serializers.CharField()
    publication_id = serializers.UUIDField(
        help_text="The publication visitors now read; the current one when nothing changed."
    )
