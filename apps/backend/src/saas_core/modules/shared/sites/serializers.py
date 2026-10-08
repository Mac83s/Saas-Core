from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.locales import ContentLocaleField

from .models import ContentSchemaType, PublicationReason


class CursorQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class SiteCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
    )
    default_locale = ContentLocaleField(default=settings.SITES_DEFAULT_LOCALE)
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
    default_locale = ContentLocaleField()


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
    lang = serializers.CharField(
        required=False,
        help_text="The language of `title` when it is not the page's: a collection "
        "name not yet translated (TL14).",
    )


class PublicSocialImageSerializer(serializers.Serializer[dict[str, Any]]):
    url = serializers.URLField()
    alt = serializers.CharField(allow_blank=True, help_text="In the page's language.")


class PublicMachineTextSerializer(serializers.Serializer[dict[str, Any]]):
    source_type = serializers.CharField(
        help_text="IPTC digital source type of the text: a trained model's, or a person's "
        "and a model's together."
    )
    reviewed = serializers.BooleanField(
        help_text="A person accepted this version, or published it themselves."
    )
    notice = serializers.BooleanField(
        help_text="Show the visitor a notice that a machine translated this version: the "
        "operator's switch is on and nobody has accepted the version yet."
    )


class PublicSocialSerializer(serializers.Serializer[dict[str, Any]]):
    site_name = serializers.CharField(allow_blank=True)
    locale = serializers.CharField(help_text="`og:locale` of the page's language, e.g. `de_DE`.")
    alternate_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="`og:locale:alternate`: the page's other public language versions.",
    )
    image = PublicSocialImageSerializer(
        allow_null=True, help_text="The page's first published picture, or null."
    )


class PublicFeedLinksSerializer(serializers.Serializer[dict[str, Any]]):
    rss = serializers.URLField(help_text="RSS 2.0 of the articles in the page's language.")
    atom = serializers.URLField(help_text="Atom of the articles in the page's language.")


class PublicLanguageLinkSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    name = serializers.CharField(help_text="The language's name in itself, e.g. Deutsch.")
    path = serializers.CharField(
        help_text="This page's version in the language, else the language's home page."
    )
    current = serializers.BooleanField(help_text="The language the page is in.")


class PublicSiteNotFoundSerializer(ProblemDetailsSerializer):
    locale = serializers.CharField(
        required=False, help_text="The language a known site says it in (TL14)."
    )
    home_path = serializers.CharField(
        required=False, help_text="That language's home page on the site."
    )


class PublicImageSizeSerializer(serializers.Serializer[dict[str, Any]]):
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)


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
    appearance = serializers.DictField(allow_null=True, required=False)
    appearance_lang = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        help_text="Appearance texts still in another language than the page, by path "
        "(`header.tagline`, `footer.text`, `footer.links.<i>.label`) → that language, so the "
        "page marks them with `lang` (ADR-070 pkt 15).",
    )
    page_presentation = serializers.DictField(allow_null=True, required=False)
    blocks = serializers.ListField(child=serializers.DictField())
    live = serializers.DictField(
        child=serializers.DictField(),
        help_text="What the blocks that show the company's live records show now, by "
        "the block's position in `blocks` („0”, „3”): the stay offers of `core.stay_units`, "
        "`core.stay_search` and `core.stay_calendar` — the form's address, the offers and "
        "what a guest chooses of each — a unit's card (`core.stay_unit`), and for "
        "`core.stay_map` the `place`: the unit's town and its centre, or — `exact` — the "
        "unit's own point once its company shows it. A block without an entry draws nothing.",
    )
    navigation = PublicNavigationLinkSerializer(many=True)
    feeds = PublicFeedLinksSerializer()
    describedby = serializers.URLField(
        required=False,
        help_text="The site's llms.txt in the page's language (`rel=describedby`, TL19).",
    )
    machine_text = PublicMachineTextSerializer(
        required=False,
        allow_null=True,
        help_text="Set on a language version with text an AI model wrote; null for a "
        "person's text (ADR-071 pkt 17).",
    )
    structured_data = serializers.DictField(
        required=False,
        help_text="One schema.org JSON-LD graph for the page (TL18): WebSite, the company "
        "as `#organization` (the same node and facts in every language), WebPage, "
        "BreadcrumbList, and BlogPosting or FAQPage where the page is one. The company's "
        "texts inside are untrusted: print the graph only inside a JSON-LD script element, "
        "escaped.",
    )
    social = PublicSocialSerializer()
    breadcrumbs = serializers.ListField(child=serializers.DictField())
    show_breadcrumbs = serializers.BooleanField(
        required=False,
        help_text="The page draws its trail (`breadcrumbs`) for the visitor: a record's own "
        "page — a unit's `/stay/…`, a document's `/documents/…` — which no menu leads to; "
        "the trail starts at the company's name and the home page. False or absent: the "
        "trail is in the structured data alone.",
    )
    pagination = serializers.DictField(allow_null=True)
    article = serializers.DictField(allow_null=True)
    # AI images on this page; empty when the operator switched the badge off.
    ai_media_ids = serializers.ListField(child=serializers.UUIDField())
    image_sizes = serializers.DictField(
        child=PublicImageSizeSerializer(),
        required=False,
        help_text="The stored size of the pictures the page shows, by media asset id — those "
        "of its publication and those its live blocks show now. Print it as the image's "
        "`width` and `height`, whichever copy is loaded: the proportions are the same. An "
        "asset whose size is unknown is left out.",
    )
    noindex = serializers.BooleanField(
        help_text="The page asks search engines not to index it (robots noindex,follow)."
    )
    language_links = PublicLanguageLinkSerializer(
        many=True,
        help_text="Where to read the page in each language the site is live in; empty "
        "while there is only one.",
    )


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


SECTION_PATH_HELP = (
    "Lowercase Latin letters, digits and single hyphens, at most 80 characters; not a "
    "two-letter word (a language's prefix), a platform path or a record source's section."
)


def _locale_paths_field(**kwargs: Any) -> serializers.DictField:
    return serializers.DictField(
        child=serializers.RegexField(
            r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80, allow_blank=True
        ),
        help_text="The section's name in the addresses of other languages, by two-letter "
        'language code: `{"de": "ratgeber"}` gives `/de/ratgeber/`. A language left out, or '
        "given an empty name, follows `base_path`. The site's own language is never a key. "
        + SECTION_PATH_HELP,
        **kwargs,
    )


class ContentCollectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    key = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField()
    base_path = serializers.CharField(
        help_text="The section's name in the addresses of the site's own language: `blog` "
        "gives `/blog/` and `/blog/<entry>/`."
    )
    locale_paths = serializers.DictField(
        child=serializers.CharField(),
        help_text="The section's name in other languages' addresses, by language code; a "
        "language not named here follows `base_path`.",
    )
    paths = serializers.DictField(
        child=serializers.CharField(),
        help_text="Where the section's index answers in each of the site's languages, as a "
        'path on the site: `{"pl": "/poradnik/", "de": "/de/ratgeber/"}`. An article answers '
        "at that path followed by its slug.",
    )
    automation_policy = serializers.CharField()
    show_in_navigation = serializers.BooleanField()
    schema_type = serializers.ChoiceField(
        choices=ContentSchemaType.choices,
        help_text="What an entry of this content type is to a search engine: the schema.org "
        "type of its node in the page's structured data. `WebPage` — the page alone, with no "
        "article node.",
    )
    in_site_feed = serializers.BooleanField(
        help_text="Whether the type's entries are in the site's RSS and Atom feeds."
    )
    archived = serializers.BooleanField(
        help_text="True for a content type that is switched off: nothing of it answers a "
        "visitor and its entries are neither edited nor published; its addresses stay taken "
        "and return when it is switched on."
    )
    archived_at = serializers.DateTimeField(
        allow_null=True, help_text="When the type was switched off; null while it is on."
    )


class ContentCollectionCreateSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=["blog", "news", "guide"], default="blog")
    base_path = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
        help_text="The section's name in the addresses of the site's own language. "
        + SECTION_PATH_HELP,
    )
    locale_paths = _locale_paths_field(required=False)
    schema_type = serializers.ChoiceField(
        choices=ContentSchemaType.choices,
        default=ContentSchemaType.BLOG_POSTING.value,
        help_text="What the type's entries are to a search engine (see the type's "
        "`schema_type`). Default: `BlogPosting`.",
    )
    in_site_feed = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Whether the type's entries are in the site's feeds. Left out: yes for an "
        "article-like type, no for `WebPage`.",
    )


class ContentTypesLimitSerializer(serializers.Serializer[dict[str, Any]]):
    allowed = serializers.BooleanField(
        help_text="Whether the site may have one more content type switched on now."
    )
    code = serializers.CharField(
        allow_blank=True,
        help_text="Why not: `content_types_not_offered` (the platform offers no further "
        "types), `quota_exceeded` (the plan's limit is used up) or `plan_access_denied` (the "
        "subscription does not allow adding now). Empty when allowed.",
    )
    message = serializers.CharField(
        allow_blank=True, help_text="The same in words, in Polish. Empty when allowed."
    )
    offered = serializers.BooleanField(
        help_text="Whether the platform offers content types beyond a site's first at all."
    )
    additional_max = serializers.IntegerField(
        allow_null=True,
        min_value=0,
        help_text="Switched-on types beyond the first the plan allows on one site; null — the "
        "plan sets no limit, or it was not asked (nothing to add beside).",
    )
    additional_used = serializers.IntegerField(
        min_value=0, help_text="Switched-on types beyond the first the site has."
    )


class ContentSchemaTypeOptionSerializer(serializers.Serializer[dict[str, Any]]):
    schema_type = serializers.ChoiceField(
        choices=ContentSchemaType.choices, help_text="The value a type's `schema_type` takes."
    )
    title = serializers.DictField(
        child=serializers.CharField(), help_text="The choice's name, by panel language."
    )
    hint = serializers.DictField(
        child=serializers.CharField(), help_text="What it is for, by panel language."
    )
    in_site_feed = serializers.BooleanField(
        help_text="Whether a new type of this kind joins the site's feeds unless told otherwise."
    )


class ContentTypeRowSerializer(serializers.Serializer[dict[str, Any]]):
    collection = ContentCollectionSerializer()
    entries = serializers.IntegerField(
        min_value=0, help_text="The type's entries in every language, drafts included."
    )
    published = serializers.IntegerField(
        min_value=0, help_text="Those of them a visitor can open while the type is on."
    )
    locales = serializers.ListField(
        child=ContentLocaleField(),
        help_text="The languages the type has entries in, in the company's order.",
    )


class ContentTypesSerializer(serializers.Serializer[dict[str, Any]]):
    types = ContentTypeRowSerializer(
        many=True,
        help_text="The site's content types, the first made first; switched-off ones included.",
    )
    limit = ContentTypesLimitSerializer(
        help_text="The platform's and the plan's word on making one more type."
    )
    schema_types = ContentSchemaTypeOptionSerializer(
        many=True, help_text="What a type's `schema_type` may be, in the order to offer them."
    )


class ContentTypeUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(
        max_length=160,
        trim_whitespace=True,
        required=False,
        help_text="The type's name: the heading of its list on the site and its name in the "
        "panel. 2–160 characters.",
    )
    schema_type = serializers.ChoiceField(
        choices=ContentSchemaType.choices,
        required=False,
        help_text="What the type's entries are to a search engine.",
    )
    in_site_feed = serializers.BooleanField(
        required=False, help_text="Whether the type's entries are in the site's feeds."
    )


class ContentTypeUpdateResultSerializer(serializers.Serializer[dict[str, Any]]):
    collection = ContentCollectionSerializer(
        help_text="The type as saved — or, in a preview, as it would be."
    )
    changed = serializers.BooleanField(
        help_text="False when the values sent are the ones the type already has."
    )


class ContentTypeSwitchSerializer(serializers.Serializer[dict[str, Any]]):
    collection = ContentCollectionSerializer(
        help_text="The type as saved — in a preview, as it is now."
    )
    changed = serializers.BooleanField(
        help_text="False when the type already is what was asked for."
    )
    published = serializers.IntegerField(
        min_value=0,
        help_text="Entries visitors can open today that stop answering (switching off), or "
        "that answer again (switching on).",
    )
    scheduled = serializers.IntegerField(
        min_value=0,
        help_text="Publications planned for later that switching off calls off.",
    )
    paths = serializers.DictField(
        child=serializers.CharField(),
        help_text="Where the type's list answers per language: the addresses that, with "
        "everything under them, stop answering or answer again.",
    )
    restorable = serializers.BooleanField(
        help_text="Whether the type could be switched on again right after, on the plan as "
        "it is. A switched-off type does not count to the limit; switching it on needs room."
    )
    restore_problem = serializers.CharField(
        allow_blank=True, help_text="Why it could not, in Polish; empty when `restorable`."
    )
    restore_problem_code = serializers.CharField(
        allow_blank=True,
        help_text="The same as a code: `quota_exceeded`, `plan_access_denied` or "
        "`content_types_not_offered`; empty when `restorable`.",
    )


class CollectionPathsSerializer(serializers.Serializer[dict[str, Any]]):
    """The whole set of a section's names, sent each time."""

    base_path = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
        help_text="The section's name in the addresses of the site's own language. "
        + SECTION_PATH_HELP,
    )
    locale_paths = _locale_paths_field(default=dict)
    reason = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Why the address moves. Required when the change moves an address "
        "visitors can open today (`moved` of the preview is not empty); kept in the history.",
    )


class CollectionMovedPathSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text="The language whose address moves.")
    from_path = serializers.CharField(
        help_text="The index address that stops being the section's; it and everything "
        "under it answers one 308."
    )
    to_path = serializers.CharField(help_text="Where it leads from then on.")


class CollectionPathsResultSerializer(serializers.Serializer[dict[str, Any]]):
    collection = ContentCollectionSerializer(
        help_text="The section with the names as saved — or, in a preview, as they would be."
    )
    moved = CollectionMovedPathSerializer(
        many=True,
        help_text="The index addresses visitors can open today that the change moves. Empty: "
        "nothing public moves and no reason is needed.",
    )
    changed = serializers.BooleanField(
        help_text="False when the names sent are the ones the section already has."
    )


class CollectionNavigationSerializer(serializers.Serializer[dict[str, Any]]):
    show_in_navigation = serializers.BooleanField()


class AutomationPolicySerializer(serializers.Serializer[dict[str, Any]]):
    automation_policy = serializers.ChoiceField(choices=["manual", "proposed", "automated"])


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
    translation_of = serializers.UUIDField(
        allow_null=True,
        help_text="The entry a translation job translated this one from; null for a person's.",
    )
    pending_reason = serializers.CharField(
        allow_blank=True,
        help_text="Why a translation of this entry waits for a person; empty when none waits.",
    )


class ContentEntryMetadataSerializer(serializers.Serializer[dict[str, Any]]):
    """Each field is optional: one left out keeps its value."""

    title = serializers.CharField(
        max_length=200, required=False, help_text="The article's title; never empty."
    )
    excerpt = serializers.CharField(
        max_length=400,
        required=False,
        allow_blank=True,
        help_text="The summary under the title in the index and in search results.",
    )
    author_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True, help_text="Who wrote it, as printed."
    )
    noindex = serializers.BooleanField(
        required=False,
        help_text="The article asks search engines not to index it (robots noindex,follow).",
    )


class ContentEntryListSerializer(serializers.Serializer[dict[str, Any]]):
    items = ContentEntrySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class ContentEntryTranslationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=140)
    locale = ContentLocaleField()
    title = serializers.CharField(max_length=200, trim_whitespace=True)


class ContentEntryCreateSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=140)
    locale = ContentLocaleField()
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
    names = serializers.ListField(child=serializers.CharField(max_length=120), max_length=10)


class EntryScheduleSerializer(serializers.Serializer[dict[str, Any]]):
    publish_at = serializers.DateTimeField()


class EntryScheduleStateSerializer(serializers.Serializer[dict[str, Any]]):
    entry_id = serializers.UUIDField()
    schedule_state = serializers.CharField()
    scheduled_publish_at = serializers.DateTimeField(allow_null=True)
    schedule_error = serializers.CharField(allow_blank=True)


class PageUrlChangeSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField()
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
    purpose = serializers.ChoiceField(choices=["customer", "platform_marketing", "platform_blog"])


class ChangeSetProposalSerializer(serializers.Serializer[dict[str, Any]]):
    """The envelope is checked against the frozen JSON Schema, not here.

    A DRF serializer mirroring it would be a second description of the same
    contract, and the two would drift the first time one was edited alone.
    """

    change_set = serializers.DictField()


class ChangeSetApplySerializer(serializers.Serializer[dict[str, Any]]):
    change_set = serializers.DictField()
    approval_digest = serializers.CharField(required=False, allow_blank=False)
    approval_token = serializers.CharField(required=False, allow_blank=False)


class ContentBaseQuerySerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=["site_page", "content_entry"])
    site_id = serializers.UUIDField()
    page_id = serializers.UUIDField(required=False)
    collection_id = serializers.UUIDField(required=False)
    entry_id = serializers.UUIDField(required=False)
    locale = ContentLocaleField()


class ContentBaseStateSerializer(serializers.Serializer[dict[str, Any]]):
    version = serializers.IntegerField()
    snapshot_hash = serializers.CharField()
    observed_at = serializers.DateTimeField()


class ContentBaseSerializer(serializers.Serializer[dict[str, Any]]):
    target = ContentBaseQuerySerializer()
    base = ContentBaseStateSerializer()
    blocks = serializers.ListField(child=serializers.DictField())
    translation_fields = serializers.DictField()
    observed_at = serializers.DateTimeField()


class ChangeSetDiffSerializer(serializers.Serializer[dict[str, Any]]):
    resource_id = serializers.UUIDField()
    base_version = serializers.IntegerField()
    commands = serializers.ListField(child=serializers.CharField())
    blocks_before = serializers.ListField(child=serializers.DictField())
    blocks_after = serializers.ListField(child=serializers.DictField())
    translation_fields = serializers.DictField()
    publish_at = serializers.CharField(allow_null=True)
    approval_digest = serializers.CharField()
    approval_token = serializers.CharField()
    digest_expires_at = serializers.DateTimeField()


class ChangeSetResultSerializer(serializers.Serializer[dict[str, Any]]):
    resource_id = serializers.UUIDField()
    base_version = serializers.IntegerField()
    applied_commands = serializers.ListField(child=serializers.CharField())
    pending_commands = serializers.ListField(child=serializers.CharField())
    proposal_id = serializers.UUIDField()
    approval_digest = serializers.CharField()
    published = serializers.BooleanField()


class OperationStatusSerializer(serializers.Serializer[dict[str, Any]]):
    idempotency_key = serializers.CharField()
    found = serializers.BooleanField()
    resource_type = serializers.ChoiceField(
        choices=[
            "page",
            "page_version",
            "site_publication",
            "content_collection",
            "content_entry",
            "content_entry_version",
            "content_entry_publication",
        ],
        allow_null=True,
    )
    resource_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)


class AutomationConnectionSerializer(serializers.Serializer[dict[str, Any]]):
    grant_id = serializers.UUIDField()
    credential_id = serializers.UUIDField()
    mode = serializers.CharField()
    scope = serializers.DictField()
    expires_at = serializers.DateTimeField(allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)
    active = serializers.BooleanField()
    max_changes_per_day = serializers.IntegerField(allow_null=True)
    max_payload_bytes = serializers.IntegerField(allow_null=True)
    window_start = serializers.TimeField(allow_null=True)
    window_end = serializers.TimeField(allow_null=True)
    last_activity_at = serializers.DateTimeField(allow_null=True)


class GrantRevokeSerializer(serializers.Serializer[dict[str, Any]]):
    # Required, and stored: an emergency stop nobody wrote a reason for is one
    # nobody can explain a week later.
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class ContentProposalSerializer(serializers.Serializer[dict[str, Any]]):
    proposal_id = serializers.UUIDField()
    resource_type = serializers.CharField()
    resource_id = serializers.UUIDField()
    locale = serializers.CharField(
        help_text="The language the proposal is about. A page has one line per language."
    )
    version = serializers.IntegerField(
        help_text="The version the proposal produced in that language: the page's draft in "
        "the source language, the language version's own lock in any other."
    )
    credential_id = serializers.UUIDField(allow_null=True)
    summary = serializers.CharField()
    risk = serializers.CharField()
    expected_outcome = serializers.CharField(allow_blank=True)
    sources = serializers.ListField(child=serializers.DictField())
    commands = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    review_state = serializers.CharField()
    target = serializers.DictField()
    metadata_pending = serializers.BooleanField()
    decided_at = serializers.DateTimeField(allow_null=True)


class ContentProposalDetailSerializer(ContentProposalSerializer):
    """The queue row plus the two block lists an operator compares."""

    blocks_before = serializers.ListField(child=serializers.DictField())
    blocks_after = serializers.ListField(child=serializers.DictField())
    metadata_before = serializers.DictField()
    metadata_after = serializers.DictField()
    language_version_waiting = serializers.BooleanField(
        help_text="The proposal's text waits as a version of the page in another language: "
        "accepting it makes it the working version and publishes it where that language of "
        "the page is live."
    )
    page_presentation_before = serializers.DictField(required=False)
    page_presentation_after = serializers.DictField(required=False)
    review_token = serializers.CharField()
    review_expires_at = serializers.DateTimeField()


class ProposalAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    review_token = serializers.CharField(allow_blank=False)


class ProposalAcceptResultSerializer(serializers.Serializer[dict[str, Any]]):
    proposal_id = serializers.UUIDField()
    review_state = serializers.CharField()
    version = serializers.IntegerField()
    published = serializers.BooleanField()


class ProposalDiscardResultSerializer(serializers.Serializer[dict[str, Any]]):
    resource_type = serializers.CharField()
    resource_id = serializers.UUIDField()
    restored_version = serializers.IntegerField()


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
    contract_versions = serializers.ListField(child=serializers.CharField())
    commands = serializers.ListField(child=serializers.CharField())
    grant = serializers.DictField(allow_null=True)
    change_set_commands = serializers.ListField(child=serializers.CharField())
    language_version_commands = serializers.ListField(
        child=serializers.CharField(),
        help_text="The change-set commands accepted for a page in a language other than its "
        "site's source language; a `block.replace` there may change text only.",
    )
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


class PageListItemSerializer(PageSummarySerializer):
    """A page as the panel's list shows it (decision 7): where it answers,
    whether visitors see it and which version, and whether the menu has it."""

    title = serializers.CharField(allow_null=True)
    path = serializers.CharField(allow_null=True)
    published_version = serializers.IntegerField(allow_null=True)
    in_navigation = serializers.BooleanField()
    deleted_at = serializers.DateTimeField(allow_null=True)


class PageListQuerySerializer(CursorQuerySerializer):
    state = serializers.ChoiceField(choices=["live", "deleted"], default="live")


class PageListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PageListItemSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class PageDeleteSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    # Where the page's public addresses lead afterwards; the home page when
    # absent. Ignored for a page visitors never saw.
    redirect_to_page_id = serializers.UUIDField(required=False, allow_null=True)


class PageRedirectSummarySerializer(serializers.Serializer[dict[str, Any]]):
    from_path = serializers.CharField()
    to_path = serializers.CharField()


class PageDeletionSerializer(serializers.Serializer[dict[str, Any]]):
    page = PageListItemSerializer()
    publication_id = serializers.UUIDField(allow_null=True)
    redirects = PageRedirectSummarySerializer(many=True)


class PageRestoreSerializer(serializers.Serializer[dict[str, Any]]):
    # New addresses per locale, when the old ones were taken meanwhile.
    slugs = serializers.DictField(
        child=serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80),
        required=False,
    )


class PageIncomingLinkSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    name = serializers.CharField()
    links = serializers.IntegerField()


class PageIncomingLinksSerializer(serializers.Serializer[dict[str, Any]]):
    items = PageIncomingLinkSerializer(many=True)


class PageBlockInputSerializer(serializers.Serializer[dict[str, Any]]):
    block_type = serializers.RegexField(
        r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
        max_length=120,
    )
    schema_version = serializers.IntegerField(min_value=1)
    data = serializers.JSONField()  # type: ignore[assignment]
    decoration = serializers.JSONField(required=False, allow_null=True)
    presentation = serializers.JSONField(required=False, allow_null=True)

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
    # Absent keeps the current draft's value; null clears it (see save_draft).
    page_presentation = serializers.JSONField(required=False, allow_null=True)

    def validate_blocks(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 200:
            raise serializers.ValidationError("Draft może zawierać maksymalnie 200 bloków.")
        return value

    def validate_media_asset_ids(self, value: list[Any]) -> list[Any]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Lista mediów nie może zawierać duplikatów.")
        return value


class KeptSectionSerializer(serializers.Serializer[dict[str, Any]]):
    #: Position of the template's section the page's own takes the place of.
    slot = serializers.IntegerField(min_value=0)
    block = PageBlockInputSerializer()


class TemplateSwapSerializer(serializers.Serializer[dict[str, Any]]):
    """F4-C: the page's sections in the template's places, the rest after it.
    Absent, the template replaces every section, as before."""

    kept = KeptSectionSerializer(many=True, required=False)
    appended = PageBlockInputSerializer(many=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if len(attrs.get("kept", ())) + len(attrs.get("appended", ())) > 200:
            raise serializers.ValidationError("Draft może zawierać maksymalnie 200 bloków.")
        return attrs


class PageTemplateImportSerializer(TemplateSwapSerializer):
    locale = ContentLocaleField(required=False)
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
    decoration = serializers.JSONField(required=False, allow_null=True)
    presentation = serializers.JSONField(required=False, allow_null=True)


class PageDraftSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    version = serializers.IntegerField()
    draft_id = serializers.UUIDField(allow_null=True)
    content_hash = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    blocks = PageBlockSerializer(many=True)
    media_asset_ids = serializers.ListField(child=serializers.UUIDField())
    page_presentation = serializers.JSONField(allow_null=True)


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
    state = serializers.ChoiceField(
        choices=[
            "complete",
            "incomplete",
            "published",
            "missing",
            "pending",
            "outdated",
            "untranslated",
        ],
        help_text="The site's language: `complete` or `incomplete` (its metadata). Another "
        "language: `published` (its own version is on the site), `missing`, `pending` (a "
        "translation waits for a person), `outdated` (translates an older source), "
        "`untranslated` (units left) or `complete` (not published yet).",
    )
    blocks_publication = serializers.BooleanField(
        help_text="Only the site's language can hold a publication back (W8)."
    )


class SiteLanguageSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    is_source = serializers.BooleanField(help_text="The site's own language.")
    live = serializers.BooleanField(help_text="Visitors can read the site in it now.")


class PageLocalizationSerializer(serializers.Serializer[dict[str, Any]]):
    page_id = serializers.UUIDField()
    page_key = serializers.CharField()
    page_name = serializers.CharField()
    locales = LocaleLocalizationSerializer(many=True)
    hreflang = serializers.DictField(child=serializers.CharField())
    x_default = serializers.CharField(allow_null=True)
    placeholders = serializers.IntegerField(
        help_text="`[Uzupełnij: …]` slots left in the page's draft (UX-038)."
    )
    template_contact = serializers.BooleanField(
        help_text="The template's sample phone or e-mail is still in a link of the draft."
    )
    missing_pages = serializers.ListField(
        child=serializers.CharField(),
        help_text="Links of the draft to a record's own page that is not there now: a "
        "company document nobody approved yet (`/documents/privacy-policy/`), a unit the "
        "company no longer shows (`/stay/…`). A visitor who follows one gets 404.",
    )


class SiteLocalizationReportSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    default_locale = serializers.CharField()
    supported_locales = serializers.ListField(child=serializers.CharField())
    ready_to_publish = serializers.BooleanField()
    languages = SiteLanguageSerializer(many=True)
    pages = PageLocalizationSerializer(many=True)


class SitePublishSerializer(serializers.Serializer[dict[str, Any]]):
    pass


class SiteRollbackSerializer(serializers.Serializer[dict[str, Any]]):
    pass


class PublicationAuthorSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    #: First and last name; empty when the account has none — show the e-mail then.
    name = serializers.CharField(allow_blank=True)


class PageVersionRestoreSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)


class PageVersionSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    number = serializers.IntegerField()
    # save, template, restore, change_set, proposal_rejected; "" before 2026-09-28.
    origin = serializers.CharField(allow_blank=True)
    # `core.step_guide@1` for a template, the source number for a restore.
    origin_ref = serializers.CharField(allow_blank=True)
    created_by = PublicationAuthorSerializer()
    automation = serializers.BooleanField()
    block_count = serializers.IntegerField()
    current = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class PageVersionListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PageVersionSummarySerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class SiteTemplateContentSerializer(serializers.Serializer[dict[str, Any]]):
    # Up to 20 sections, like a page recipe; the service checks per kind.
    blocks = PageBlockInputSerializer(many=True, allow_empty=False)
    page_presentation = serializers.JSONField(required=False, allow_null=True, default=None)
    media_asset_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, default=list, max_length=100
    )
    source_page_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class SiteTemplateCreateSerializer(SiteTemplateContentSerializer):
    kind = serializers.ChoiceField(choices=("section", "page"))
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )


class SiteTemplateVersionCreateSerializer(SiteTemplateContentSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class SiteTemplateUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(max_length=500, allow_blank=True, default="")


class SiteTemplateBlockSerializer(serializers.Serializer[dict[str, Any]]):
    block_type = serializers.CharField()
    schema_version = serializers.IntegerField()
    data = serializers.JSONField()  # type: ignore[assignment]
    decoration = serializers.JSONField(required=False, allow_null=True)
    presentation = serializers.JSONField(required=False, allow_null=True)


class SiteTemplateVersionSerializer(serializers.Serializer[dict[str, Any]]):
    number = serializers.IntegerField()
    blocks = SiteTemplateBlockSerializer(many=True)
    page_presentation = serializers.JSONField(allow_null=True)
    media_asset_ids = serializers.ListField(child=serializers.UUIDField())
    created_by = PublicationAuthorSerializer()
    created_at = serializers.DateTimeField()


class SiteTemplateSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=("section", "page"))
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    created_by = PublicationAuthorSerializer()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    # The newest version: what the library draws and inserts.
    version = SiteTemplateVersionSerializer()


class SiteTemplateListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SiteTemplateSerializer(many=True)
    # The plan's limit of active templates; null when the plan sets none.
    limit = serializers.IntegerField(allow_null=True)


class OwnTemplateImportSerializer(TemplateSwapSerializer):
    expected_version = serializers.IntegerField(min_value=0)
    template_id = serializers.UUIDField()
    template_version = serializers.IntegerField(min_value=1)


class SitePublicationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    snapshot_schema_version = serializers.IntegerField()
    snapshot_hash = serializers.CharField()
    source_publication_id = serializers.UUIDField(allow_null=True)
    reason = serializers.ChoiceField(
        choices=PublicationReason.choices,
        allow_blank=True,
        help_text="Why the publication exists; empty for publications from before the field.",
    )
    created_by = PublicationAuthorSerializer()
    created_at = serializers.DateTimeField()


class SitePublicationListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SitePublicationSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)
