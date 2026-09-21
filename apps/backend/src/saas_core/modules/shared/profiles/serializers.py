from typing import Any

from rest_framework import serializers

from .models import LOCALE_CHOICES, CatalogLayout, ProfileSubjectKind


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
    locale = serializers.ChoiceField(choices=LOCALE_CHOICES, required=False)
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
    headline = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bio = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    allow_headline_fallback = serializers.BooleanField(required=False)
    allow_bio_fallback = serializers.BooleanField(required=False)


class ProfileTranslationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    allow_headline_fallback = serializers.BooleanField()
    allow_bio_fallback = serializers.BooleanField()
    version = serializers.IntegerField()


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


class CatalogPageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    items = CatalogItemSerializer(many=True)


class CatalogProfileSerializer(CatalogItemSerializer):
    layout = serializers.CharField()
    voivodeship = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
    contact_phone = serializers.CharField(allow_blank=True)
    contact_address = serializers.CharField(allow_blank=True)
    links = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.CharField())
    specializations = serializers.ListField(child=serializers.CharField())
    locale = serializers.CharField()


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
