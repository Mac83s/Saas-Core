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
    subdomain_label = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=80,
        trim_whitespace=True,
    )


class SubdomainAvailabilityQuerySerializer(serializers.Serializer[dict[str, Any]]):
    # DRF fields are collected by the serializer metaclass; `label` intentionally
    # shadows the descriptive Field.label attribute because it is the API key.
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=80, trim_whitespace=True
    )


class SubdomainAvailabilitySerializer(serializers.Serializer[dict[str, Any]]):
    requested_label = serializers.CharField()
    normalized_label = serializers.CharField()
    hostname = serializers.CharField()
    available = serializers.BooleanField()
    reason = serializers.ChoiceField(
        choices=["available", "invalid", "reserved", "taken", "quarantined"]
    )
    suggestion = serializers.CharField()


class SiteOnboardingSaveSerializer(serializers.Serializer[dict[str, Any]]):
    version = serializers.IntegerField(min_value=0)
    step = serializers.ChoiceField(choices=["address", "details", "review"])
    name = serializers.CharField(max_length=160, trim_whitespace=True, allow_blank=True)
    subdomain_label = serializers.CharField(
        max_length=80,
        trim_whitespace=True,
        allow_blank=True,
    )
    default_locale = serializers.ChoiceField(choices=settings.SITES_SUPPORTED_LOCALES)


class SiteOnboardingSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField(allow_null=True)
    version = serializers.IntegerField()
    step = serializers.CharField()
    name = serializers.CharField()
    subdomain_label = serializers.CharField()
    default_locale = serializers.CharField()
    platform_domain = serializers.CharField()
    hostname = serializers.CharField()
    site_id = serializers.UUIDField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class SiteSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    purpose = serializers.CharField()
    default_locale = serializers.CharField()
    current_publication_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class DomainCreateSerializer(serializers.Serializer[dict[str, Any]]):
    hostname = serializers.CharField(max_length=253, trim_whitespace=False)


class PlatformDomainChangeSerializer(serializers.Serializer[dict[str, Any]]):
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=80, trim_whitespace=True
    )


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


class PublicNavigationLinkSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    parent_page_id = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    path = serializers.CharField()


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
    navigation = PublicNavigationLinkSerializer(many=True)
    breadcrumbs = serializers.ListField(child=serializers.DictField())
    pagination = serializers.DictField(allow_null=True)
    article = serializers.DictField(allow_null=True)


class NavigationItemSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    parent_page_id = serializers.UUIDField(allow_null=True, required=False)
    visible = serializers.BooleanField(default=True)


class SiteNavigationSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    version = serializers.IntegerField()
    items = NavigationItemSerializer(many=True)


class SiteNavigationSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    # A menu with no entries is a legitimate state — it means "no menu" — so an
    # empty list is accepted rather than rejected as a mistake.
    items = NavigationItemSerializer(many=True, allow_empty=True)


class ContentCollectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    key = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField()
    base_path = serializers.CharField()
    automation_policy = serializers.CharField()
    show_in_navigation = serializers.BooleanField()


class ContentCollectionCreateSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=["blog", "news", "guide"], default="blog")
    base_path = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)


class CollectionNavigationSerializer(serializers.Serializer[dict[str, Any]]):
    show_in_navigation = serializers.BooleanField()


class AutomationPolicySerializer(serializers.Serializer[dict[str, Any]]):
    automation_policy = serializers.ChoiceField(
        choices=["manual", "proposed", "automated"]
    )


class ContentTagSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField()
    name = serializers.CharField()


class ContentEntrySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    collection_id = serializers.UUIDField()
    slug = serializers.CharField()
    locale = serializers.CharField()
    title = serializers.CharField()
    excerpt = serializers.CharField(allow_blank=True)
    author_name = serializers.CharField(allow_blank=True)
    state = serializers.CharField()
    version = serializers.IntegerField()
    published_at = serializers.DateTimeField(allow_null=True)
    publication_id = serializers.UUIDField(allow_null=True)
    noindex = serializers.BooleanField()
    draft_author = serializers.CharField(allow_null=True)
    translation_group = serializers.UUIDField()
    schedule_state = serializers.CharField()
    scheduled_publish_at = serializers.DateTimeField(allow_null=True)
    schedule_error = serializers.CharField(allow_blank=True)
    tags = ContentTagSerializer(many=True)


class ContentEntryListSerializer(serializers.Serializer[dict[str, Any]]):
    items = ContentEntrySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class ContentEntryTranslationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=140)
    locale = serializers.ChoiceField(choices=["pl", "en"])
    title = serializers.CharField(max_length=200, trim_whitespace=True)


class ContentEntryCreateSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=140)
    locale = serializers.ChoiceField(choices=["pl", "en"])
    title = serializers.CharField(max_length=200, trim_whitespace=True)


class ContentEntryDraftSerializer(serializers.Serializer[dict[str, Any]]):
    entry_id = serializers.UUIDField()
    version = serializers.IntegerField()
    blocks = serializers.ListField(child=serializers.DictField())
    media_asset_ids = serializers.ListField(child=serializers.UUIDField())


class ContentEntryDraftSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    media_asset_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=50
    )
    blocks = serializers.ListField(child=serializers.DictField())


class ContentEntryPublicationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    entry_id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    snapshot_hash = serializers.CharField()


class SiteListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    key = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )


class EntryTagsSaveSerializer(serializers.Serializer[dict[str, Any]]):
    # Names, not slugs: the operator types what a reader will see and the
    # address is derived, so the two cannot drift apart.
    names = serializers.ListField(
        child=serializers.CharField(max_length=120), max_length=10
    )


class EntryScheduleSerializer(serializers.Serializer[dict[str, Any]]):
    publish_at = serializers.DateTimeField()


class EntryScheduleStateSerializer(serializers.Serializer[dict[str, Any]]):
    entry_id = serializers.UUIDField()
    schedule_state = serializers.CharField()
    scheduled_publish_at = serializers.DateTimeField(allow_null=True)
    schedule_error = serializers.CharField(allow_blank=True)


class PageUrlChangeSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.ChoiceField(choices=["pl", "en"])
    slug = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    # Required, and stored: six months later the audit is the only thing that
    # explains why a ranking address moved.
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class SiteRedirectSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    locale = serializers.CharField()
    from_path = serializers.CharField()
    to_path = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)


class PageTypeSerializer(serializers.Serializer[dict[str, Any]]):
    page_type = serializers.ChoiceField(
        choices=[
            "homepage",
            "landing",
            "service",
            "about",
            "contact",
            "legal",
            "article_index",
            "article",
        ]
    )


class SitePurposeSerializer(serializers.Serializer[dict[str, Any]]):
    purpose = serializers.ChoiceField(
        choices=["customer", "platform_marketing", "platform_blog"]
    )


class ChangeSetProposalSerializer(serializers.Serializer[dict[str, Any]]):
    """The envelope is checked against the frozen JSON Schema, not here.

    A DRF serializer mirroring it would be a second description of the same
    contract, and the two would drift the first time one was edited alone.
    """

    change_set = serializers.DictField()


class ChangeSetApplySerializer(serializers.Serializer[dict[str, Any]]):
    change_set = serializers.DictField()
    approval_digest = serializers.CharField(required=False, allow_blank=False)


class ChangeSetDiffSerializer(serializers.Serializer[dict[str, Any]]):
    resource_id = serializers.UUIDField()
    base_version = serializers.IntegerField()
    commands = serializers.ListField(child=serializers.CharField())
    blocks_before = serializers.ListField(child=serializers.DictField())
    blocks_after = serializers.ListField(child=serializers.DictField())
    translation_fields = serializers.DictField()
    publish_at = serializers.CharField(allow_null=True)
    approval_digest = serializers.CharField()
    digest_expires_at = serializers.DateTimeField()


class ChangeSetResultSerializer(serializers.Serializer[dict[str, Any]]):
    resource_id = serializers.UUIDField()
    base_version = serializers.IntegerField()
    applied_commands = serializers.ListField(child=serializers.CharField())
    approval_digest = serializers.CharField()
    published = serializers.BooleanField()


class ContentInventorySerializer(serializers.Serializer[dict[str, Any]]):
    """Everything the caller may act on, as of one moment."""

    contract_version = serializers.IntegerField()
    minimum_contract_version = serializers.IntegerField()
    observed_at = serializers.DateTimeField()
    sites = serializers.ListField(child=serializers.DictField())


class ContentCapabilitiesSerializer(serializers.Serializer[dict[str, Any]]):
    """Shape and limits, never unpublished content."""

    contract_version = serializers.IntegerField()
    minimum_contract_version = serializers.IntegerField()
    locales = serializers.DictField()
    block_schemas = serializers.ListField(child=serializers.DictField())
    content_types = serializers.DictField()
    quotas = serializers.ListField(child=serializers.DictField())
    sites = serializers.ListField(child=serializers.DictField())


class PageSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    name = serializers.CharField()
    key = serializers.CharField()
    version = serializers.IntegerField()
    current_draft_id = serializers.UUIDField(allow_null=True)
    current_draft_hash = serializers.CharField(allow_null=True)
    page_type = serializers.CharField()
    automation_policy = serializers.CharField()
    # "person" or "automation": who wrote the draft that is waiting. Without it
    # a proposal is indistinguishable from the operator's own unsaved work.
    draft_author = serializers.CharField(allow_null=True)
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


class PageTemplateImportSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    template_id = serializers.RegexField(
        r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
        max_length=120,
    )
    template_version = serializers.IntegerField(min_value=1)


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
