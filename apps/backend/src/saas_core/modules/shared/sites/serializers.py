from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers


class CursorQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class SiteCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )
    default_locale = serializers.ChoiceField(
        choices=settings.SITES_SUPPORTED_LOCALES,
        default=settings.SITES_DEFAULT_LOCALE,
    )


class SiteSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    default_locale = serializers.CharField()
    current_publication_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class DomainCreateSerializer(serializers.Serializer[dict[str, Any]]):
    hostname = serializers.CharField(max_length=253, trim_whitespace=False)


class DomainActionSerializer(serializers.Serializer[dict[str, Any]]):
    action = serializers.ChoiceField(
        choices=["disable", "enable", "release", "set_canonical", "verify"]
    )


class SiteDomainSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    hostname = serializers.CharField()
    kind = serializers.CharField()
    status = serializers.CharField()
    tls_status = serializers.CharField()
    is_canonical = serializers.BooleanField()
    verification_name = serializers.CharField()
    verification_token = serializers.CharField()
    dns_cname_target = serializers.CharField()
    dns_expected_ipv4 = serializers.ListField(child=serializers.IPAddressField(protocol="IPv4"))
    dns_expected_ipv6 = serializers.ListField(child=serializers.IPAddressField(protocol="IPv6"))
    dns_error_code = serializers.CharField()
    last_checked_at = serializers.DateTimeField(allow_null=True)
    last_verified_at = serializers.DateTimeField(allow_null=True)
    next_check_at = serializers.DateTimeField(allow_null=True)
    tls_last_requested_at = serializers.DateTimeField(allow_null=True)
    released_at = serializers.DateTimeField(allow_null=True)
    quarantine_until = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class SiteDomainListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteDomainSerializer(many=True)


class PublicSitePageSerializer(serializers.Serializer[dict[str, Any]]):
    publication_id = serializers.UUIDField()
    snapshot_hash = serializers.CharField()
    locale = serializers.CharField()
    canonical_url = serializers.URLField()
    hreflang = serializers.DictField(child=serializers.URLField())
    x_default = serializers.URLField()
    title = serializers.CharField()
    description = serializers.CharField()
    social_title = serializers.CharField()
    social_description = serializers.CharField()
    design_tokens = serializers.DictField()
    blocks = serializers.ListField(child=serializers.DictField())


class SiteListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    key = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )


class PageSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    name = serializers.CharField()
    key = serializers.CharField()
    version = serializers.IntegerField()
    current_draft_id = serializers.UUIDField(allow_null=True)
    current_draft_hash = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PageListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PageSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageBlockInputSerializer(serializers.Serializer[dict[str, Any]]):
    block_type = serializers.RegexField(
        r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=120,
    )
    schema_version = serializers.IntegerField(min_value=1)
    data = serializers.JSONField()  # type: ignore[assignment]

    def validate_data(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Dane bloku muszą być obiektem JSON.")
        return value


class DraftSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    blocks = PageBlockInputSerializer(many=True, allow_empty=True)
    media_asset_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        default=list,
        max_length=100,
    )

    def validate_blocks(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 200:
            raise serializers.ValidationError("Draft może zawierać maksymalnie 200 bloków.")
        return value

    def validate_media_asset_ids(self, value: list[Any]) -> list[Any]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Lista mediów nie może zawierać duplikatów.")
        return value


class PageBlockSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    position = serializers.IntegerField()
    block_type = serializers.CharField()
    schema_version = serializers.IntegerField()
    data = serializers.JSONField()  # type: ignore[assignment]


class PageDraftSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    version = serializers.IntegerField()
    draft_id = serializers.UUIDField(allow_null=True)
    content_hash = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    blocks = PageBlockSerializer(many=True)
    media_asset_ids = serializers.ListField(child=serializers.UUIDField())


class PageTranslationSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )
    title = serializers.CharField(
        max_length=160,
        allow_blank=True,
        required=False,
        default="",
        trim_whitespace=True,
    )
    description = serializers.CharField(
        max_length=320,
        allow_blank=True,
        required=False,
        default="",
        trim_whitespace=True,
    )
    social_title = serializers.CharField(
        max_length=160,
        allow_blank=True,
        required=False,
        default="",
        trim_whitespace=True,
    )
    social_description = serializers.CharField(
        max_length=320,
        allow_blank=True,
        required=False,
        default="",
        trim_whitespace=True,
    )
    allow_title_fallback = serializers.BooleanField(default=False)
    allow_description_fallback = serializers.BooleanField(default=False)
    allow_social_title_fallback = serializers.BooleanField(default=False)
    allow_social_description_fallback = serializers.BooleanField(default=False)


class PageTranslationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    page_id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    locale = serializers.CharField()
    slug = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    social_title = serializers.CharField(allow_blank=True)
    social_description = serializers.CharField(allow_blank=True)
    allow_title_fallback = serializers.BooleanField()
    allow_description_fallback = serializers.BooleanField()
    allow_social_title_fallback = serializers.BooleanField()
    allow_social_description_fallback = serializers.BooleanField()
    version = serializers.IntegerField()
    slug_locked = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PageTranslationListSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    default_locale = serializers.CharField()
    supported_locales = serializers.ListField(child=serializers.CharField())
    items = PageTranslationSerializer(many=True)


class LocaleLocalizationSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    translation_id = serializers.UUIDField(allow_null=True)
    version = serializers.IntegerField(allow_null=True)
    slug = serializers.CharField(allow_null=True)
    path = serializers.CharField(allow_null=True)
    canonical_path = serializers.CharField(allow_null=True)
    title = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    social_title = serializers.CharField(allow_null=True)
    social_description = serializers.CharField(allow_null=True)
    fallback_fields = serializers.ListField(child=serializers.CharField())
    missing_fields = serializers.ListField(child=serializers.CharField())
    complete = serializers.BooleanField()
    slug_locked = serializers.BooleanField()


class PageLocalizationSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    page_key = serializers.CharField()
    page_name = serializers.CharField()
    locales = LocaleLocalizationSerializer(many=True)
    hreflang = serializers.DictField(child=serializers.CharField())
    x_default = serializers.CharField(allow_null=True)


class SiteLocalizationReportSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    default_locale = serializers.CharField()
    supported_locales = serializers.ListField(child=serializers.CharField())
    ready_to_publish = serializers.BooleanField()
    pages = PageLocalizationSerializer(many=True)


class SitePublishSerializer(serializers.Serializer[dict[str, Any]]):
    pass


class SiteRollbackSerializer(serializers.Serializer[dict[str, Any]]):
    pass


class PublicationAuthorSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()


class SitePublicationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    snapshot_schema_version = serializers.IntegerField()
    snapshot_hash = serializers.CharField()
    source_publication_id = serializers.UUIDField(allow_null=True)
    created_by = PublicationAuthorSerializer()
    created_at = serializers.DateTimeField()


class SitePublicationListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SitePublicationSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)
