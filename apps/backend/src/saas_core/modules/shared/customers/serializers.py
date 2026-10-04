from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.locales import ContentLocaleField

from .documents import DOCUMENT_TEXT_MAX
from .models import DocumentKind


class CustomerDocumentDraftSerializer(serializers.Serializer[dict[str, Any]]):
    text = serializers.CharField(help_text="The draft's text, plain paragraphs.")
    locale = serializers.CharField(help_text="The content language the draft is written in.")
    origin_ref = serializers.CharField(
        allow_blank=True,
        help_text="The assistant's run that wrote the draft; empty when a person did.",
    )


class CustomerDocumentTextSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField(help_text="The text row a consent points at.")
    locale = serializers.CharField(help_text="The row's content language.")
    text = serializers.CharField(help_text="Exactly what customers read.")
    text_hash = serializers.CharField(help_text="sha256 of `text`.")
    accepted_at = serializers.DateTimeField(help_text="When a person added the row.")
    accepted_by = serializers.CharField(allow_blank=True, help_text="Who added it, by name.")
    stale = serializers.BooleanField(
        required=False,
        help_text="A translation accepted against another source text than the version's "
        "own language reads now: the source was corrected since. Adding the same text "
        "again confirms it against the corrected source; otherwise the same text is 400 "
        "`text_unchanged`.",
    )


class CustomerDocumentVersionSerializer(serializers.Serializer[dict[str, Any]]):
    number = serializers.IntegerField(help_text="The version's number, from 1.")
    source_locale = serializers.CharField(help_text="The language it was approved in.")
    effective_from = serializers.DateField(
        help_text="The first day customers get it, in the company's time zone."
    )
    approved_at = serializers.DateTimeField()
    approved_by = serializers.CharField(allow_blank=True, help_text="Who approved it, by name.")
    locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The languages the version has a text in. A customer who reads another "
        "one gets no document.",
    )
    texts = CustomerDocumentTextSerializer(
        many=True, required=False, help_text="The current text per language; on a detail read."
    )


class CustomerDocumentTranslationSerializer(serializers.Serializer[dict[str, Any]]):
    object_id = serializers.UUIDField(
        help_text="What a translation order names, with the source `customers.document`."
    )
    version = serializers.IntegerField(
        help_text="The version a machine translation is made for: the one that takes "
        "force last — the version in force, or the one approved for a later day."
    )
    waiting = serializers.ListField(
        child=serializers.CharField(),
        help_text="Languages whose machine translation waits in the translation review "
        "for a person to accept it; a text is added only then.",
    )


class CustomerDocumentSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    version = serializers.IntegerField(
        help_text="Send it back as `expected_version` with every write; 0 before the first."
    )
    draft = CustomerDocumentDraftSerializer(
        allow_null=True, help_text="What somebody is still writing; binds nobody."
    )
    in_force = CustomerDocumentVersionSerializer(
        allow_null=True, help_text="The version customers get today."
    )
    upcoming = CustomerDocumentVersionSerializer(
        allow_null=True, help_text="A version approved for a later day."
    )
    public_url = serializers.CharField(
        allow_null=True, help_text="The document's public page; null before the first version."
    )
    versions = CustomerDocumentVersionSerializer(
        many=True, required=False, help_text="Every version, newest first; on a detail read."
    )
    translation = CustomerDocumentTranslationSerializer(
        required=False,
        allow_null=True,
        help_text="What ordering a machine translation of the document needs; on a detail "
        "read, null before the first version.",
    )


class CustomerDocumentOptionsSerializer(serializers.Serializer[dict[str, Any]]):
    kinds = serializers.ListField(child=serializers.ChoiceField(choices=DocumentKind.choices))
    locales = serializers.ListField(
        child=serializers.CharField(), help_text="The company's content languages."
    )
    default_locale = serializers.CharField(help_text="The language a new draft starts in.")
    text_max = serializers.IntegerField(help_text="The longest text, in characters.")


class CustomerDocumentListSerializer(serializers.Serializer[dict[str, Any]]):
    documents = CustomerDocumentSerializer(many=True)
    options = CustomerDocumentOptionsSerializer()


class CustomerDocumentDetailSerializer(serializers.Serializer[dict[str, Any]]):
    document = CustomerDocumentSerializer()
    options = CustomerDocumentOptionsSerializer()


class CustomerDocumentDraftInputSerializer(serializers.Serializer[dict[str, Any]]):
    text = serializers.CharField(
        allow_blank=True,
        max_length=DOCUMENT_TEXT_MAX,
        trim_whitespace=False,
        help_text="Plain text: paragraphs separated by an empty line. Empty clears the draft.",
    )
    locale = ContentLocaleField(help_text="The content language of the draft, e.g. pl.")
    expected_version = serializers.IntegerField(
        min_value=0, help_text="The document's `version` as last read; another answers 409."
    )


class CustomerDocumentApproveInputSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(
        min_value=0, help_text="The document's `version` as last read; another answers 409."
    )
    effective_from = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="The first day the version is in force, in the company's time zone; "
        "today when left out, never a past day.",
    )


class CustomerDocumentApprovalEffectSerializer(serializers.Serializer[dict[str, Any]]):
    number = serializers.IntegerField(help_text="The number the new version gets.")
    effective_from = serializers.DateField(
        help_text="The day the version takes force: the one asked for, else the earliest "
        "one possible — today, or the day a version already approved takes force."
    )
    not_before = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="The day a version already approved takes force, when that is later "
        "than today: a new version cannot take force before it (400 "
        "`before_latest_version`). Null when today is the earliest day.",
    )
    source_locale = serializers.CharField()
    locales_without_text = serializers.ListField(
        child=serializers.CharField(),
        help_text="The company's other languages: the new version has no text in them "
        "until a person adds one, and customers who read them get no document.",
    )


class CustomerDocumentApprovalSerializer(serializers.Serializer[dict[str, Any]]):
    effect = CustomerDocumentApprovalEffectSerializer()
    document = CustomerDocumentSerializer()


class CustomerDocumentTextInputSerializer(serializers.Serializer[dict[str, Any]]):
    number = serializers.IntegerField(min_value=1, help_text="The version the text belongs to.")
    locale = ContentLocaleField(help_text="The content language of the text, e.g. en.")
    text = serializers.CharField(
        max_length=DOCUMENT_TEXT_MAX,
        trim_whitespace=False,
        help_text="Plain text: paragraphs separated by an empty line.",
    )
    expected_version = serializers.IntegerField(
        min_value=0, help_text="The document's `version` as last read; another answers 409."
    )


class PublicCustomerDocumentSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    organization_name = serializers.CharField(help_text="The company whose document it is.")
    version = serializers.IntegerField()
    effective_from = serializers.DateField()
    locale = serializers.CharField(help_text="The language of `text`.")
    locales = serializers.ListField(
        child=serializers.CharField(), help_text="The languages this version can be read in."
    )
    text = serializers.CharField()
    text_hash = serializers.CharField(help_text="sha256 of `text`.")
