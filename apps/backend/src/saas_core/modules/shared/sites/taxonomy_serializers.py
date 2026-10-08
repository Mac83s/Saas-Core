"""Shapes of the categories and tags API (ADR-079 pkt 24–26, 36)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.locales import ContentLocaleField

from .term_addresses import KIND_CATEGORIES, KIND_TAGS

TERM_KIND_CHOICES = [
    (KIND_CATEGORIES, "A content type's categories: a tree, its own"),
    (KIND_TAGS, "The site's tags: flat, shared by every content type"),
]
SLUG_HELP = "Lower-case Latin letters, digits and single hyphens."


class TermNameSerializer(serializers.Serializer[dict[str, Any]]):
    text = serializers.CharField(help_text="The name in that language.")
    origin = serializers.CharField(
        allow_blank=True,
        help_text="Who wrote it: `human` or `ai`; empty when not recorded.",
    )
    state = serializers.CharField(
        help_text="`fresh`; `stale` — the name in the site's language changed since; `unverified`."
    )


class TermSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    key = serializers.CharField(
        help_text="The term's fixed key, unique on the site. An address under the key always "
        "leads to the term."
    )
    name = serializers.CharField(help_text="The name in the site's own language.")
    parent_id = serializers.UUIDField(
        allow_null=True, help_text="The category above; null at the top and for a tag."
    )
    position = serializers.IntegerField(help_text="The place among those beside it, from 0.")
    depth = serializers.IntegerField(help_text="1 at the top, up to `max_depth`.")
    names = serializers.DictField(
        child=TermNameSerializer(),
        help_text="The name in the site's other languages, by language code; a language "
        "without one is absent and shows the site's language's name.",
    )
    slugs = serializers.DictField(
        child=serializers.CharField(),
        help_text="The term's address per language of the site.",
    )
    paths = serializers.DictField(
        child=serializers.CharField(),
        help_text="Where its archive under this content type answers, per language.",
    )
    locked = serializers.ListField(
        child=serializers.CharField(),
        help_text="The languages its address is closed in: the name no longer changes it, "
        "only `address` does.",
    )
    entries = serializers.IntegerField(
        help_text="Entries of this content type filed under it, drafts included."
    )
    entries_elsewhere = serializers.IntegerField(
        help_text="A tag: entries of the site's other content types filed under it."
    )
    published = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Entries its archive under this content type lists to visitors now, by "
        "language — a category's with those of the categories under it. Read from "
        "publications; a language absent here has no archive.",
    )
    removable = serializers.BooleanField(
        help_text="Whether nothing carries it: no entry in the panel and no publication."
    )


class TermListSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=TERM_KIND_CHOICES)
    collection_id = serializers.UUIDField()
    taxonomy_id = serializers.UUIDField(
        allow_null=True,
        help_text="Null for tags, and for categories until the type's first one is made.",
    )
    default_locale = ContentLocaleField(help_text="The site's own language.")
    locales = serializers.ListField(
        child=serializers.CharField(), help_text="The site's languages, its own first."
    )
    segments = serializers.DictField(
        child=serializers.CharField(),
        help_text="The word between the type's name and a term in an archive's address, "
        "per language: `tag` everywhere for tags.",
    )
    max_depth = serializers.IntegerField(help_text="How deep categories nest.")
    max_per_entry = serializers.IntegerField(help_text="How many terms of one kind an entry takes.")
    terms = TermSerializer(
        many=True, help_text="In tree order: a category, then those under it, by position."
    )


class TermListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=TERM_KIND_CHOICES, default=KIND_CATEGORIES)


class TermCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=TERM_KIND_CHOICES, default=KIND_CATEGORIES)
    name = serializers.CharField(
        max_length=120,
        trim_whitespace=True,
        help_text="The name in the site's own language; the address is made from it.",
    )
    parent_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="A category of the same content type to put the new one under.",
    )


class TermUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """Each field is optional: one left out keeps its value."""

    name = serializers.CharField(
        max_length=120,
        trim_whitespace=True,
        required=False,
        help_text="The name in the site's own language.",
    )
    parent_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="The category to move it under; null moves it to the top.",
    )
    position = serializers.IntegerField(
        required=False, min_value=0, help_text="The place among those beside it, from 0."
    )


class TermMovedPathSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text="The language whose archive moves.")
    from_path = serializers.CharField(
        help_text="The archive's address that stops being the term's; it answers one 308."
    )
    to_path = serializers.CharField(help_text="Where it leads from then on.")


class TermTakenOverSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField(help_text="The address that redirects today.")
    term_id = serializers.UUIDField(help_text="The term it redirects to.")
    name = serializers.CharField(help_text="That term's name.")


class TermChangeSerializer(serializers.Serializer[dict[str, Any]]):
    term = TermSerializer(help_text="The term as saved — or, in a preview, as it would be.")
    changed = serializers.BooleanField(help_text="False when nothing differs from what is.")
    moved = TermMovedPathSerializer(
        many=True,
        help_text="Archives visitors could open that the change moves. Empty: nothing public "
        "moves and no reason is needed.",
    )
    takes_over = TermTakenOverSerializer(
        many=True,
        help_text="Redirects of other terms that stop, because this term takes the address "
        "they start from.",
    )
    published = serializers.IntegerField(
        help_text="Published entries under the term, whose archives change at once."
    )


class TermNamesSerializer(serializers.Serializer[dict[str, Any]]):
    names = serializers.DictField(
        child=serializers.CharField(max_length=120, allow_blank=True, trim_whitespace=True),
        help_text="The name per language code, for the languages that change; an empty "
        "name removes it.",
    )


class TermAddressSerializer(serializers.Serializer[dict[str, Any]]):
    locale = ContentLocaleField(help_text="The language whose address changes.")
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80, help_text="The new address. " + SLUG_HELP
    )
    reason = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Why the address moves. Required when the change moves an archive "
        "visitors could open (`moved` of the preview is not empty); kept in the history.",
    )
    take_over_former = serializers.BooleanField(
        default=False,
        help_text="Confirms that a redirect of another term may stop (`takes_over` of the "
        "preview): the address only redirects to that term today.",
    )


class TermRemovalSerializer(serializers.Serializer[dict[str, Any]]):
    removable = serializers.BooleanField(help_text="Whether nothing carries the term.")
    removed = serializers.BooleanField(help_text="True once it is gone; false in a preview.")
    drafts = serializers.IntegerField(help_text="Entries filed under it in the panel.")
    published = serializers.IntegerField(help_text="Entries whose current publication carries it.")
    children = serializers.IntegerField(help_text="Categories under it, which move one level up.")


class TaxonomySegmentsSaveSerializer(serializers.Serializer[dict[str, Any]]):
    """The whole set of words, sent each time."""

    segment = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=80,
        help_text="The word in the addresses of the site's own language. " + SLUG_HELP,
    )
    locale_segments = serializers.DictField(
        child=serializers.CharField(max_length=80, allow_blank=True, trim_whitespace=True),
        default=dict,
        help_text="The word per other language code; a language left out, or given an "
        "empty word, follows `segment`.",
    )
    reason = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Why the addresses move. Required when the change moves archives "
        "visitors could open (`moved` of the preview is not empty).",
    )


class TaxonomySegmentsSerializer(serializers.Serializer[dict[str, Any]]):
    segments = serializers.DictField(
        child=serializers.CharField(),
        help_text="The word per language of the site, as saved or as it would be.",
    )
    moved = TermMovedPathSerializer(
        many=True,
        help_text="Per language whose category archives move: the address every archive "
        "starts with, before and after.",
    )
    changed = serializers.BooleanField(help_text="False when the words sent are the ones in use.")


class EntryCategoriesSaveSerializer(serializers.Serializer[dict[str, Any]]):
    term_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=10,
        help_text="The categories of the entry's content type to file it under — the whole "
        "set; an empty list takes it out of every category.",
    )
