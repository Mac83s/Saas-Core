from typing import Any

from rest_framework import serializers

from .models import CatalogLayout, ProfileSubjectKind


class ProfileWriteSerializer(serializers.Serializer[dict[str, Any]]):
    display_name = serializers.CharField(max_length=160)
    headline = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bio = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    photo_id = serializers.UUIDField(required=False, allow_null=True)
    membership_id = serializers.UUIDField(required=False, allow_null=True)
    contact_email = serializers.EmailField(allow_blank=True, required=False)
    contact_phone = serializers.CharField(max_length=32, allow_blank=True, required=False)
    contact_address = serializers.CharField(max_length=240, allow_blank=True, required=False)
    links = serializers.ListField(child=serializers.DictField(), required=False)
    languages = serializers.ListField(child=serializers.CharField(), required=False)
    specializations = serializers.ListField(child=serializers.CharField(), required=False)
    # Still pl/en in the API: the profile endpoints move to content languages in
    # plan TL12, together with the OpenAPI floor they then have to meet. The
    # service already checks the language against the company's list.
    locale = serializers.ChoiceField(choices=[("pl", "Polski"), ("en", "English")], required=False)
    city_slug = serializers.CharField(max_length=80, allow_blank=True, required=False)
    category = serializers.CharField(max_length=64, allow_blank=True, required=False)
    layout = serializers.ChoiceField(choices=CatalogLayout.choices, required=False)


class ProfileCreateSerializer(ProfileWriteSerializer):
    subject_kind = serializers.ChoiceField(choices=ProfileSubjectKind.choices)


class ProfileUpdateSerializer(ProfileWriteSerializer):
    display_name = serializers.CharField(max_length=160, required=False)
    #: Optimistic lock. Two people editing the same profile is the ordinary
    #: case in a company, so the second one is told rather than overwritten.
    expected_version = serializers.IntegerField(min_value=1)


class ProfileTranslationSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="The language's version this change was made on; 0 for a language the "
        "card does not have yet. Another version answers 409.",
    )
    headline = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bio = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    link_labels = serializers.DictField(
        child=serializers.CharField(max_length=80, allow_blank=True),
        required=False,
        help_text="Link labels by the unit key of the link (`link/<12 hex>`, see `units`); "
        "an empty label removes the translation.",
    )
    allow_headline_fallback = serializers.BooleanField(required=False)
    allow_bio_fallback = serializers.BooleanField(required=False)


class ProfileTranslationUnitSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="`headline`, `bio` or `link/<12 hex>`.")
    source_text = serializers.CharField(help_text="The text in the card's own language.")
    text = serializers.CharField(allow_blank=True, help_text="The translation; empty: none.")
    status = serializers.ChoiceField(
        choices=["fresh", "stale", "missing", "blocked", "copied", "unverified"],
        help_text="Against the current source text (translation-sources.md §4).",
    )
    origin = serializers.CharField(
        allow_blank=True, help_text="Who wrote it: human, ai, integration…; empty: nobody."
    )


class ProfileTranslationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    link_labels = serializers.DictField(child=serializers.CharField())
    allow_headline_fallback = serializers.BooleanField()
    allow_bio_fallback = serializers.BooleanField()
    version = serializers.IntegerField(help_text="0 for a language the card does not have yet.")
    units = ProfileTranslationUnitSerializer(many=True)


class ProfileTranslationListSerializer(serializers.Serializer[dict[str, Any]]):
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    languages = ProfileTranslationSummarySerializer(
        many=True, help_text="Every other language of the company, translated or not."
    )


class ProfileSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    subject_kind = serializers.CharField()
    display_name = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    photo_id = serializers.UUIDField(allow_null=True)
    membership_id = serializers.UUIDField(allow_null=True)
    contact_email = serializers.CharField()
    contact_phone = serializers.CharField()
    contact_address = serializers.CharField()
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())
    locale = serializers.CharField()
    city_slug = serializers.CharField()
    category = serializers.CharField()
    layout = serializers.CharField()
    version = serializers.IntegerField()


class CatalogStateSerializer(serializers.Serializer[dict[str, Any]]):
    """Whether this company is in the public catalogue, and under which address."""

    published = serializers.BooleanField()
    city_slug = serializers.CharField(allow_blank=True)
    slug = serializers.CharField(allow_blank=True)
    path = serializers.CharField(allow_blank=True)
    site_url = serializers.CharField(allow_blank=True, allow_null=True)
    published_at = serializers.DateTimeField(allow_null=True)


class OrganizationProfileSerializer(serializers.Serializer[dict[str, Any]]):
    profile = ProfileSummarySerializer()
    catalog = CatalogStateSerializer()


class CatalogItemSerializer(serializers.Serializer[dict[str, Any]]):
    """One row of the public listing (ADR-053 §5).

    `url` is always usable: the catalogue page when the company has no reachable
    site, that site's address when it has one. `is_external` says which, so the
    client can mark a link that leaves the platform without parsing the address.
    """

    slug = serializers.CharField()
    city_slug = serializers.CharField()
    city = serializers.CharField()
    category = serializers.CharField()
    display_name = serializers.CharField()
    headline = serializers.CharField(allow_blank=True)
    photo_id = serializers.CharField(allow_null=True)
    url = serializers.CharField()
    is_external = serializers.BooleanField()
    #: Kilometres from the searched point, town centre to town centre; null
    #: when the search had no point.
    distance_km = serializers.FloatField(allow_null=True)
    locale = serializers.CharField(
        help_text="The language of the card's texts in this answer: the asked one where the "
        "card is whole in it, the card's own otherwise."
    )
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    translated_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The company's languages the card has a complete translation in, in the "
        "company's order (TL20).",
    )


class CatalogPageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    items = CatalogItemSerializer(many=True)
    #: Entries that fit the words by meaning without containing them (ADR-064):
    #: "Podobne" when `items` is empty, "Może też" below them otherwise.
    similar = CatalogItemSerializer(many=True)
    locale_has_entries = serializers.BooleanField(
        allow_null=True,
        help_text="With `locale`: whether any card of the catalogue is whole in that language. "
        "A listing in a language nobody speaks yet is not indexed. Null without `locale`.",
    )


class CatalogSitemapEntrySerializer(serializers.Serializer[dict[str, Any]]):
    city_slug = serializers.CharField()
    slug = serializers.CharField()
    source_locale = serializers.CharField(help_text="The language the card is written in.")
    translated_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The languages the card has a complete translation in.",
    )
    updated_at = serializers.DateTimeField()


class CatalogSitemapPageSerializer(serializers.Serializer[dict[str, Any]]):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    items = CatalogSitemapEntrySerializer(many=True)


class CatalogProfileSerializer(CatalogItemSerializer):
    fallback = serializers.ListField(
        child=serializers.CharField(),
        help_text="Units shown in the card's own language. Empty since TL20: the card comes "
        "whole in the asked language or whole in its own.",
    )
    layout = serializers.CharField()
    voivodeship = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
    contact_phone = serializers.CharField(allow_blank=True)
    contact_address = serializers.CharField(allow_blank=True)
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())


class CatalogCitySerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField()
    name = serializers.CharField()
    voivodeship = serializers.CharField()


class CatalogCategorySerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    # `labels`, not `label`: DRF's Field already owns `label` as the human name
    # of a field, so a serializer attribute of that name collides with it.
    labels = serializers.DictField(child=serializers.CharField())


class CatalogDictionarySerializer(serializers.Serializer[dict[str, Any]]):
    cities = CatalogCitySerializer(many=True)
    categories = CatalogCategorySerializer(many=True)
    locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="Languages at least one card is whole in (its own or a complete "
        "translation): a catalogue page in any other language is not indexed (TL20).",
    )
