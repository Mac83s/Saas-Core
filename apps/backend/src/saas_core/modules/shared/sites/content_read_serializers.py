"""The shapes of the platform's published content as a product's own pages
read it (`content_reads`, ADR-079 pkt 30). Address parts, never paths."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.locales import ContentLocaleField

from .content_reads import MAX_PAGE_SIZE
from .serializers import PublicImageSizeSerializer, PublicMachineTextSerializer

LOCALE = "A content language: a two-letter code of the platform's language registry."


class PublicContentTermSerializer(serializers.Serializer[dict[str, Any]]):
    taxonomy = serializers.CharField(
        help_text="The taxonomy the term belongs to: `tag` — the site's tags, shared by its "
        "types; `category` — the type's own categories, a tree."
    )
    slug = serializers.CharField(
        help_text="The term's part of an address in the language read; ask a list by it. It "
        "may differ per language, and a list asked by another one answers `moved`."
    )
    name = serializers.CharField(
        help_text="The term's name in the language read: its accepted translation, else the "
        "name it was published under."
    )


class PublicContentImageSerializer(serializers.Serializer[dict[str, Any]]):
    asset_id = serializers.UUIDField(
        help_text="The picture answers at `/media/<asset_id>` on the platform's host, its "
        "WebP copies at `/media/<asset_id>/thumbnail` (320 px) and `/preview` (1280 px)."
    )
    alt = serializers.CharField(allow_blank=True)


class PublicContentVersionSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text=LOCALE)
    slug = serializers.CharField()


class PublicContentEntrySerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField(help_text="The key of the entry's content type.")
    locale = ContentLocaleField(help_text=LOCALE)
    slug = serializers.CharField()
    title = serializers.CharField()
    excerpt = serializers.CharField(allow_blank=True)
    author_name = serializers.CharField(allow_blank=True)
    published_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(
        help_text="When the text last changed; publishing the same text again does not move it."
    )
    timezone = serializers.CharField(
        help_text="The publisher's time zone (IANA): the day a reader sees is the day it was there."
    )
    blocks = serializers.ListField(
        child=serializers.DictField(),
        help_text="The body as published, in the core's block contract "
        "(`@saas-core/site-blocks`). Links inside are as their author wrote them. The "
        "publisher's texts are untrusted: draw them with the core's block components.",
    )
    image = PublicContentImageSerializer(
        allow_null=True, help_text="The first picture the body shows, or null."
    )
    image_sizes = serializers.DictField(
        child=PublicImageSizeSerializer(),
        help_text="The stored size of the body's pictures, by media asset id; one of unknown "
        "size is left out.",
    )
    ai_media_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="The body's pictures a model made; empty when the operator hid the badge.",
    )
    terms = PublicContentTermSerializer(
        many=True,
        help_text="The entry's terms that have a list in this language — those a published "
        "entry asking to be indexed carries.",
    )
    versions = PublicContentVersionSerializer(
        many=True,
        help_text="The entry's published versions as (language, slug), this one included, "
        "the site's own language first: what hreflang and a language switch are built from.",
    )
    noindex = serializers.BooleanField(
        help_text="The entry asks search engines not to index it; it is on no list."
    )
    machine_text = PublicMachineTextSerializer(
        allow_null=True,
        help_text="Set on a version with text an AI model wrote; null for a person's text.",
    )
    schema_type = serializers.CharField(
        help_text="What an entry of this type is to a search engine: `BlogPosting`, "
        "`NewsArticle`, `Article` or `WebPage`."
    )
    structured_data = serializers.ListField(
        child=serializers.DictField(),
        allow_null=True,
        help_text="With `canonical_url`: the entry's own schema.org nodes — its WebPage (a "
        "FAQPage too where the body asks questions) and, unless the type is a plain page, "
        "its article — for the product's own JSON-LD graph. They point at "
        "`<origin>/#website` and `<origin>/#organization`, which the product states. The "
        "publisher's texts inside are untrusted: print them only inside a JSON-LD script "
        "element, escaped. Null without `canonical_url`.",
    )


class PublicContentEntryMovedSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    locale = ContentLocaleField(help_text=LOCALE)
    slug = serializers.CharField()


class PublicContentEntryAnswerSerializer(serializers.Serializer[dict[str, Any]]):
    entry = PublicContentEntrySerializer(
        allow_null=True, help_text="The entry, or null when it answers elsewhere (`moved`)."
    )
    moved = PublicContentEntryMovedSerializer(
        allow_null=True,
        help_text="Where the entry answers now, in address parts: the product answers one "
        "308 to the address its own table makes of them.",
    )


class PublicContentListItemSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text=LOCALE)
    slug = serializers.CharField()
    title = serializers.CharField()
    excerpt = serializers.CharField(allow_blank=True)
    author_name = serializers.CharField(allow_blank=True)
    published_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField()
    image = PublicContentImageSerializer(allow_null=True)
    terms = PublicContentTermSerializer(many=True)


class PublicContentListSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    locale = ContentLocaleField(help_text=LOCALE)
    name = serializers.CharField(help_text="The type's name in the language read.")
    term = PublicContentTermSerializer(
        allow_null=True, help_text="The term the list is of, or null: all of the type."
    )
    items = PublicContentListItemSerializer(many=True)
    page = serializers.IntegerField(min_value=1)
    pages = serializers.IntegerField(min_value=1)
    total = serializers.IntegerField(
        min_value=0, help_text="Entries on the whole list in this language."
    )
    languages = serializers.ListField(
        child=ContentLocaleField(help_text=LOCALE),
        help_text="The languages this list answers in, the site's own first.",
    )
    timezone = serializers.CharField(
        help_text="The publisher's time zone (IANA), as on an entry: the day a card shows "
        "is the day it was there."
    )
    indexable = serializers.BooleanField(
        help_text="False for a term's list too short to be a page of its own (fewer than "
        "three entries): the product marks it noindex and leaves it out of its sitemap."
    )


class PublicContentListMovedSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    locale = ContentLocaleField(help_text=LOCALE)
    taxonomy = serializers.CharField(allow_null=True)
    term = serializers.CharField(allow_null=True)


class PublicContentListAnswerSerializer(serializers.Serializer[dict[str, Any]]):
    list = PublicContentListSerializer(
        allow_null=True, help_text="The page of the list, or null when it answers elsewhere."
    )
    moved = PublicContentListMovedSerializer(
        allow_null=True,
        help_text="Where the list answers now, in address parts — a term asked for by an "
        "address it used to have, by its address in another language or by its key.",
    )


class PublicContentTypeSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="The type's stable key: every read asks by it.")
    schema_type = serializers.CharField()
    languages = serializers.ListField(
        child=ContentLocaleField(help_text=LOCALE),
        help_text="The languages the type has a listed entry in, the site's own first.",
    )
    names = serializers.DictField(
        child=serializers.CharField(), help_text="The type's name, by language."
    )
    segments = serializers.DictField(
        child=serializers.CharField(),
        help_text="What the type's section is called in addresses in the panel, by language. "
        "Information only: the product's own table names its sections.",
    )


class PublicContentTreeTermSerializer(PublicContentTermSerializer):
    count = serializers.IntegerField(
        min_value=1,
        help_text="Listed entries of the type under the term in this language — a "
        "category's with those of the categories under it.",
    )
    indexable = serializers.BooleanField(
        help_text="Whether the term's list is a page worth indexing (three entries or more)."
    )
    parent_slug = serializers.CharField(
        allow_null=True,
        help_text="The slug of the term above it in a hierarchical taxonomy; null at the top "
        "and for every tag.",
    )


class PublicContentTaxonomySerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    hierarchical = serializers.BooleanField()
    segment = serializers.CharField(
        help_text="The taxonomy's word in addresses in this language. Information only."
    )
    terms = PublicContentTreeTermSerializer(many=True)


class PublicContentTermsSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    locale = ContentLocaleField(help_text=LOCALE)
    taxonomies = PublicContentTaxonomySerializer(many=True)


class PublicContentSitemapVersionSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text=LOCALE)
    slug = serializers.CharField(
        required=False, help_text="The entry's or the term's slug; absent for a type's list."
    )
    updated_at = serializers.DateTimeField()


class PublicContentSitemapItemSerializer(serializers.Serializer[dict[str, Any]]):
    type = serializers.CharField()
    taxonomy = serializers.CharField(
        required=False, help_text="For a term's list: the taxonomy of the term."
    )
    versions = PublicContentSitemapVersionSerializer(many=True)


class PublicContentSitemapSerializer(serializers.Serializer[dict[str, Any]]):
    entries = PublicContentSitemapItemSerializer(
        many=True, help_text="Every listed entry, one item per group of language versions."
    )
    lists = PublicContentSitemapItemSerializer(
        many=True, help_text="Each type's own list, per language it has an entry in."
    )
    terms = PublicContentSitemapItemSerializer(
        many=True,
        help_text="The lists of terms worth indexing, per language where they are.",
    )


class PublicContentListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text="The language of the list.")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(
        min_value=1,
        max_value=MAX_PAGE_SIZE,
        required=False,
        help_text="Entries per page; the deployment's own index size when left out.",
    )
    taxonomy = serializers.CharField(
        required=False,
        default="",
        max_length=80,
        help_text="With `term`: its taxonomy — `tag` or `category`.",
    )
    term = serializers.SlugField(
        required=False,
        default="",
        max_length=140,
        help_text="With `taxonomy`: the term's slug in the language of the list.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("taxonomy")) != bool(attrs.get("term")):
            raise serializers.ValidationError(
                {"term": ["Podaj taksonomię i pozycję razem."]}, code="term_incomplete"
            )
        return attrs


class PublicContentLocaleQuerySerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text="The language read.")


class PublicContentEntryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    canonical_url = serializers.CharField(
        required=False,
        default="",
        max_length=2048,
        help_text="The address the product gives the entry: a plain http(s) address on the "
        "platform's own host, without a query or a fragment. Asks for `structured_data`, "
        "whose identifiers are composed from it; it is not fetched or stored.",
    )
