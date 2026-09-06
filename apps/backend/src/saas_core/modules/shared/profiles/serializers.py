from typing import Any

from rest_framework import serializers

from .models import LOCALE_CHOICES, ProfileSubjectKind


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
    version = serializers.IntegerField()
