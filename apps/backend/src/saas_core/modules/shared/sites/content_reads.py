"""What a product's own pages read of the platform's published content
(ADR-079 pkt 29–33).

A platform writes its own content — a guide, a blog — in its workspace's
panel, with the editor, the translations and the publication a customer has.
Its public pages are the product's coded views on the platform's host
(ADR-080), never the builder's renderer, so they ask here what is published.

Three rules hold for every line below:

- **One workspace, named by nobody.** The read takes no host, site or tenant:
  the platform's host is no site's domain. The workspace is found by a
  constant question at the pre-tenant door (`platform_workspace_id`) — the one
  public read that uses it — and everything after is read inside that tenant.
- **Six of the tables read here carry no row-level security** (`publicTables`
  of this module: the renderer reads them before a tenant is set). So every
  query names the workspace and its site itself, on every table it joins; the
  tables that do force it — tags, site texts, media, the organization — are
  read after `SET LOCAL`.
- **Only what is published.** An entry is its current publication's snapshot,
  never the row a draft edits. A type, a term, a count, a name and a picture
  exist for the read only where a published entry carries them — for lists,
  counts and names one that asks to be indexed. Anything else — a draft, a
  withdrawn entry, a switched-off type, another company's entry — answers
  like nothing at all.

Address parts, never paths: the product composes its addresses from its own
table (`docs/architecture/product-content-read.md`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.organizations.context import (
    only_tenant_context_of,
    set_local_organization_id,
    tenant_setting_kept,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import platform_workspace_id
from saas_core.modules.core.organizations.public_sources import served_media_ids
from saas_core.modules.shared.media.api import shown_image_facts
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState

from .ai_badge import badge_visible
from .localization import section_segment
from .machine_text import machine_text
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    Site,
)
from .public_media import media_response
from .publication_routing import (
    TAG_INDEX_THRESHOLD,
    parse_moment,
    serving_locales,
)
from .seo_graph import page_graph
from .term_addresses import (
    CATEGORY_TAXONOMY_KEY,
    TAG_SEGMENT,
    Taxonomy,
    Term,
    Vocabulary,
    site_vocabulary,
    taxonomy_segment,
    term_names,
    term_slug,
)

#: The one taxonomy of today: the site's tags, flat and shared by its types.
#: Categories join as further taxonomies of a type (ADR-079 pkt 2, 9).
TAG_TAXONOMY = "tag"
#: A type's own categories: a tree, read beside the tags (ADR-079 pkt 9).
CATEGORY_TAXONOMY = CATEGORY_TAXONOMY_KEY

#: How many entries a list answers with at most; the product asks for fewer.
MAX_PAGE_SIZE = 100

_CANONICAL_URL_MAX = 2048
#: What closes a quote, a tag or an escape wherever the address is printed.
_CANONICAL_URL_REFUSED = frozenset("<>\"\\'`")


class ContentNotFound(NotFound):
    default_detail = "Nie ma takiej opublikowanej treści."
    default_code = "content_not_found"


@dataclass(frozen=True, slots=True)
class _Workspace:
    """The platform's workspace as this read sees it."""

    organization_id: UUID
    site: Site
    #: The languages read: the workspace's own, and its site's language.
    available: frozenset[str]

    @property
    def default_locale(self) -> str:
        return str(self.site.default_locale)


@dataclass(frozen=True, slots=True)
class _Listed:
    """A published entry as a list, a count and the sitemap know it — its
    snapshot's facts without its body."""

    entry_id: UUID
    collection_id: UUID
    group: UUID
    locale: str
    slug: str
    title: str
    excerpt: str
    author_name: str
    tags: tuple[tuple[str, str], ...]
    #: The categories its publication files it under, as (id, published name).
    categories: tuple[tuple[str, str], ...]
    published_at: datetime | None
    changed_at: datetime


def _workspace() -> _Workspace:
    organization_id = platform_workspace_id()
    if organization_id is None:
        raise ContentNotFound
    # The organization's row forces row-level security: read as that tenant.
    locales = serving_locales(organization_id, publisher=True)
    if locales is None:
        raise ContentNotFound
    # The workspace has one site (`sites.max = 1`, ADR-077 pkt 2). None, or
    # more than one, and nothing says which is meant: nothing is read.
    sites = list(Site.all_objects.filter(organization_id=organization_id).order_by("id")[:2])
    if len(sites) != 1:
        raise ContentNotFound
    site = sites[0]
    return _Workspace(
        organization_id=organization_id,
        site=site,
        available=locales | {str(site.default_locale)},
    )


def _published(workspace: _Workspace) -> QuerySet[ContentEntry]:
    """The workspace's published entries of its switched-on types — what the
    public router of a company's site lists (`published_entries`), with the
    workspace named on each of the three tables the query joins."""
    return ContentEntry.all_objects.filter(
        organization_id=workspace.organization_id,
        site_id=workspace.site.id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
        current_publication__organization_id=workspace.organization_id,
        collection__organization_id=workspace.organization_id,
        collection__site_id=workspace.site.id,
        # A switched-off type answers nothing (ADR-079 pkt 23).
        collection__archived_at__isnull=True,
    )


def _types(workspace: _Workspace) -> dict[UUID, ContentCollection]:
    return {
        collection.id: collection
        for collection in ContentCollection.all_objects.filter(
            organization_id=workspace.organization_id,
            site_id=workspace.site.id,
            archived_at__isnull=True,
        ).order_by("key")
    }


def _tags_of(value: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(tag["slug"]), str(tag.get("name") or tag["slug"]))
        for tag in (value if isinstance(value, list) else [])
        if isinstance(tag, dict) and tag.get("slug")
    )


def _categories_of(value: Any) -> tuple[tuple[str, str], ...]:
    """The categories a snapshot names (`terms` with a taxonomy); a snapshot
    older than the field names none."""
    return tuple(
        (str(term["id"]), str(term.get("name") or ""))
        for term in (value if isinstance(value, list) else [])
        if isinstance(term, dict) and term.get("id") and term.get("taxonomy")
    )


#: What a list, a count and the sitemap know of a published entry, as one
#: statement: the snapshot is unpacked once per row (`jsonb_to_record`) and
#: the type and the language come from the entry's own columns, which are
#: never rewritten after the entry is made and which a publication copies
#: (`snapshot["locale"]`). Written as the ORM would write `_published`: the
#: three tables carry no row-level security, so each one names the workspace
#: (and the site where it has one) itself. A hidden entry is one whose snapshot
#: says `noindex` is anything but false: a snapshot older than the field has no
#: such key and is listed, a JSON null is not (`jsonb_to_record` reads both as
#: SQL null, so the key's presence is asked where that is the case).
_LISTED_FROM = """
FROM "sites_contententry" e
INNER JOIN "sites_contententrypublication" p ON p."id" = e."current_publication_id"
INNER JOIN "sites_contentcollection" c ON c."id" = e."collection_id"
CROSS JOIN LATERAL jsonb_to_record(p."snapshot") AS s(
    "slug" text, "title" text, "excerpt" text, "author_name" text,
    "tags" jsonb, "terms" jsonb, "changed_at" text, "noindex" jsonb
)
WHERE e."organization_id" = %s AND e."site_id" = %s
  AND e."state" = %s
  AND p."organization_id" = %s
  AND c."organization_id" = %s AND c."site_id" = %s
  AND c."archived_at" IS NULL
  AND e."locale" = ANY(%s)
  AND (
    s."noindex" = 'false'::jsonb
    OR (s."noindex" IS NULL AND NOT p."snapshot" ? 'noindex')
  )
"""
_LISTED_SELECT = """
SELECT e."id", e."collection_id", e."translation_group", e."locale", e."published_at",
       p."created_at", s."slug", s."title", s."excerpt", s."author_name",
       s."tags", s."terms", s."changed_at"
"""
#: The order the ORM gave the same rows (`ContentEntry.Meta.ordering`): ties of
#: the newest-first sort below keep it.
_LISTED_ORDER = """
ORDER BY e."organization_id", e."collection_id", e."published_at" DESC, e."id"
"""


def _listed_query(
    workspace: _Workspace, *, collection_id: UUID | None, locale: str | None
) -> tuple[str, list[Any]] | None:
    """The conditions of `_LISTED_FROM` with their values, or none when the
    language asked for is one the workspace does not read."""
    if locale is not None and locale not in workspace.available:
        return None
    organization_id, site_id = workspace.organization_id, workspace.site.id
    sql = _LISTED_FROM
    params: list[Any] = [
        organization_id,
        site_id,
        ContentEntryState.PUBLISHED.value,
        organization_id,
        organization_id,
        site_id,
        [locale] if locale is not None else sorted(workspace.available),
    ]
    if collection_id is not None:
        sql += '  AND e."collection_id" = %s\n'
        params.append(collection_id)
    return sql, params


def _json_of(value: Any) -> Any:
    # The driver hands a jsonb column over as text (the ORM decodes its own).
    return json.loads(value) if isinstance(value, str) else value


def _listed(
    workspace: _Workspace, *, collection_id: UUID | None = None, locale: str | None = None
) -> list[_Listed]:
    """Every entry a list may show, newest first: published, asking to be
    indexed, in a language the workspace reads — of one type and one language
    when asked for them. Bodies stay in the database — a list of a few hundred
    guides is not a few megabytes of blocks."""
    where = _listed_query(workspace, collection_id=collection_id, locale=locale)
    if where is None:
        return []
    sql, params = where
    with connection.cursor() as cursor:
        cursor.execute(_LISTED_SELECT + sql + _LISTED_ORDER, params)
        rows = cursor.fetchall()
    found = [
        _Listed(
            entry_id=entry_id,
            collection_id=collection,
            group=group,
            locale=str(locale_code),
            slug=str(slug),
            title=str(title),
            excerpt=str(excerpt or ""),
            author_name=str(author_name or ""),
            tags=_tags_of(_json_of(tags)),
            categories=_categories_of(_json_of(terms)),
            published_at=published_at,
            # When the text changed, which publishing it again does not move.
            changed_at=parse_moment(changed_at) or created_at,
        )
        for (
            entry_id,
            collection,
            group,
            locale_code,
            published_at,
            created_at,
            slug,
            title,
            excerpt,
            author_name,
            tags,
            terms,
            changed_at,
        ) in rows
    ]
    # A missing timestamp sorts last, as in the router's own list.
    found.sort(key=lambda item: (item.published_at is not None, item.published_at), reverse=True)
    return found


def _has_listed(workspace: _Workspace, collection_id: UUID) -> bool:
    """Whether the type has an entry on a list in any language, which is what
    its existence for the read comes down to — asked only where the entries
    read are none. Stops at the first."""
    where = _listed_query(workspace, collection_id=collection_id, locale=None)
    assert where is not None
    sql, params = where
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1" + sql + " LIMIT 1", params)
        return cursor.fetchone() is not None


def _type(workspace: _Workspace, key: str) -> ContentCollection:
    """The switched-on type `key`. It exists for the read once an entry of it
    is on a list — an empty type and no type at all answer the same — which
    the caller sees in the entries it reads of it."""
    collection = next((found for found in _types(workspace).values() if found.key == key), None)
    if collection is None:
        raise ContentNotFound
    return collection


def _names(
    workspace: _Workspace, locale: str, vocabulary: Vocabulary | None = None
) -> dict[str, str]:
    """The accepted names of types and tags in `locale`, by site-text key
    (`collection/<id>`, `tag/<id>`). Read straight from the accepted
    translations (ADR-079 pkt 33): on a company's site they go out with the
    site's publication, and nobody publishes the workspace's site.

    The terms are the vocabulary the answer already read — a name is found
    per key and by that term's own text, so the units the answer never asks
    for cost nothing and no second scan of the snapshots decides which terms
    to offer (`published_terms`). Without one, the names are the types' alone.
    The caller asks only for what a published entry carries: a name is read
    where a list, a count or an entry's own terms name its term."""
    if locale == workspace.default_locale:
        return {}
    from .site_texts import shown_texts, site_text_units, translation_rows

    # Site texts force row-level security: the tenant goes first.
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        return shown_texts(
            site_text_units(
                workspace.site, None, terms=vocabulary.terms if vocabulary is not None else ()
            ),
            translation_rows(workspace.site, locale),
        )


def _vocabulary(workspace: _Workspace) -> Vocabulary:
    """The workspace's tags and categories as they are now — their addresses
    per language, the tree, the identifiers accepted names are kept under.
    One read per answer, as that tenant: both tables force row-level
    security (`site_vocabulary`). What exists for the read is still decided
    by what published entries carry; this only names and addresses it."""
    return site_vocabulary(organization_id=workspace.organization_id, site_id=workspace.site.id)


@dataclass(frozen=True, slots=True)
class _Naming:
    """How one answer names terms: in one language, of one type."""

    workspace: _Workspace
    vocabulary: Vocabulary
    locale: str
    #: Accepted names in `locale`, by site-text key.
    names: Mapping[str, str]
    #: The type's category taxonomy, when it has one.
    taxonomy: Taxonomy | None

    @property
    def tags(self) -> dict[str, Term]:
        return {term.slug: term for term in self.vocabulary.of(None)}

    def slug(self, term: Term) -> str:
        """The term's part of an address in the language read."""
        return term_slug(term, default_locale=self.workspace.default_locale, locale=self.locale)

    def tag(self, key: str, published: str) -> dict[str, Any]:
        """A tag by the key snapshots name it by: under its address in the
        language read, and its accepted name there, else as published."""
        row = self.tags.get(key)
        return {
            "taxonomy": TAG_TAXONOMY,
            "slug": self.slug(row) if row is not None else key,
            "name": (self.names.get(f"tag/{row.id}") if row is not None else None) or published,
        }

    def category(self, term: Term, published: str = "") -> dict[str, Any]:
        return {
            "taxonomy": CATEGORY_TAXONOMY,
            "slug": self.slug(term),
            "name": self.names.get(f"tag/{term.id}") or published or term.name,
        }

    def categories(self) -> dict[str, Term]:
        """The type's categories that still exist, by id."""
        if self.taxonomy is None:
            return {}
        return {term.id: term for term in self.vocabulary.of(self.taxonomy)}

    def terms(
        self, tags: Iterable[tuple[str, str]], categories: Iterable[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """An entry's terms as the read names them: its tags by key, then its
        categories in the tree's order. A category removed since is not there."""
        mine = self.categories()
        carried = dict(categories)
        return [
            *(self.tag(key, name) for key, name in sorted(dict(tags).items())),
            *(
                self.category(term, carried[term.id])
                for term in (self.vocabulary.tree(self.taxonomy) if self.taxonomy else ())
                if term.id in carried and term.id in mine
            ),
        ]


def _naming(
    workspace: _Workspace, collection: ContentCollection, locale: str, vocabulary: Vocabulary
) -> _Naming:
    return _Naming(
        workspace=workspace,
        vocabulary=vocabulary,
        locale=locale,
        names=_names(workspace, locale, vocabulary),
        taxonomy=vocabulary.categories_of(collection.id),
    )


def _under(naming: _Naming, term: Term) -> frozenset[str]:
    """A category and every category under it now: its list shows theirs."""
    return naming.vocabulary.with_descendants(term)


def _in_category(item: _Listed, ids: frozenset[str]) -> bool:
    return any(term_id in ids for term_id, _name in item.categories)


def _first_picture(blocks: Any, published: set[str]) -> dict[str, str] | None:
    """The first picture the body shows — what a list's card and a shared
    link show of the entry."""

    def first(value: Any) -> dict[str, str] | None:
        if isinstance(value, dict):
            asset_id = value.get("asset_id")
            if isinstance(asset_id, str) and asset_id in published:
                return {"asset_id": asset_id, "alt": str(value.get("alt") or "")}
            values: Any = value.values()
        elif isinstance(value, list):
            values = value
        else:
            return None
        return next((found for item in values if (found := first(item)) is not None), None)

    return first(blocks)


def _cover(blocks: Any, published: set[str]) -> dict[str, str] | None:
    """The picture the body opens with: the first thing of its first block,
    when that block is text and the thing is a picture in it. An import puts
    a post's cover there, and a page that draws it above the title asks the
    body to leave it out (`SiteEntryBody`, `withoutCover`). A picture
    further down, or one that belongs to another kind of block (a hero's),
    is no cover."""
    first = blocks[0] if isinstance(blocks, list) and blocks else None
    if not isinstance(first, dict) or first.get("block_type") != "core.rich_text":
        return None
    content = (first.get("data") or {}).get("content")
    node = content[0] if isinstance(content, list) and content else None
    image = node.get("image") if isinstance(node, dict) and node.get("type") == "figure" else None
    if not isinstance(image, dict):
        return None
    asset_id = image.get("asset_id")
    if not isinstance(asset_id, str) or asset_id not in published:
        return None
    return {"asset_id": asset_id, "alt": str(image.get("alt") or "")}


def _pictures(
    workspace: _Workspace, entry_ids: list[UUID]
) -> dict[UUID, dict[str, dict[str, str] | None]]:
    """The first picture of each of a page's entries, and the one its body
    opens with: the only part of a list that needs the bodies, read for that
    page's entries alone."""
    return {
        entry_id: {
            "image": _first_picture(blocks, {str(asset_id) for asset_id in media or []}),
            "cover": _cover(blocks, {str(asset_id) for asset_id in media or []}),
        }
        for entry_id, blocks, media in _published(workspace)
        .filter(pk__in=entry_ids)
        .values_list(
            "id",
            "current_publication__snapshot__blocks",
            "current_publication__snapshot__media_asset_ids",
        )
    }


def _item(
    item: _Listed, naming: _Naming, pictures: Mapping[str, dict[str, str] | None]
) -> dict[str, Any]:
    return {
        "locale": item.locale,
        "slug": item.slug,
        "title": item.title,
        "excerpt": item.excerpt,
        "author_name": item.author_name,
        "published_at": item.published_at,
        "updated_at": item.changed_at,
        "image": pictures.get("image"),
        "cover": pictures.get("cover"),
        "terms": naming.terms(item.tags, item.categories),
    }


def _languages(default_locale: str, found: Iterable[str]) -> list[str]:
    """The site's language first, the rest in order."""
    codes = set(found)
    return [code for code in [default_locale, *sorted(codes - {default_locale})] if code in codes]


# -- types ---------------------------------------------------------------------


def read_types() -> list[dict[str, Any]]:
    """The platform's content types that have something published, each with
    its name and the name of its section per language it has an entry in."""
    workspace = _workspace()
    listed = _listed(workspace)
    answer: list[dict[str, Any]] = []
    names: dict[str, dict[str, str]] = {}
    for collection in _types(workspace).values():
        languages = _languages(
            workspace.default_locale,
            (item.locale for item in listed if item.collection_id == collection.id),
        )
        if not languages:
            continue
        for locale in languages:
            if locale not in names:
                names[locale] = _names(workspace, locale)
        answer.append({
            "key": collection.key,
            "schema_type": str(collection.schema_type),
            "languages": languages,
            "names": {
                locale: names[locale].get(f"collection/{collection.id}") or collection.name
                for locale in languages
            },
            "segments": {
                locale: section_segment(
                    collection, default_locale=workspace.default_locale, locale=locale
                )
                for locale in languages
            },
        })
    return answer


def read_terms(*, type_key: str, locale: str) -> dict[str, Any]:
    """The terms of a type in one language, with how many entries each has
    there. From published entries that ask to be indexed and from nothing
    else (ADR-079 pkt 30): a term only a draft or a hidden entry carries is
    not here, under any name, and counts for nothing."""
    workspace = _workspace()
    collection = _type(workspace, type_key)
    entries = _listed(workspace, collection_id=collection.id, locale=locale)
    if not entries and (
        # The type has no list in this language; or, in the site's own, none
        # in any (an empty type answers like no type).
        locale != workspace.default_locale
        or not _has_listed(workspace, collection.id)
    ):
        raise ContentNotFound
    counts: dict[str, int] = {}
    published: dict[str, str] = {}
    for item in entries:
        for slug, name in item.tags:
            counts[slug] = counts.get(slug, 0) + 1
            # Newest first: the name the latest publication gave the tag.
            published.setdefault(slug, name)
    naming = _naming(workspace, collection, locale, _vocabulary(workspace))
    taxonomies: list[dict[str, Any]] = [
        {
            "key": TAG_TAXONOMY,
            "hierarchical": False,
            "segment": TAG_SEGMENT,
            "terms": [
                {
                    **naming.tag(key, name),
                    "count": counts[key],
                    "indexable": counts[key] >= TAG_INDEX_THRESHOLD,
                    # Tags are flat; a category names the one above it.
                    "parent_slug": None,
                }
                for key, name in sorted(published.items())
            ],
        }
    ]
    categories = _category_terms(naming, entries)
    if categories:
        assert naming.taxonomy is not None
        taxonomies.append({
            "key": CATEGORY_TAXONOMY,
            "hierarchical": True,
            "segment": taxonomy_segment(
                naming.taxonomy, default_locale=workspace.default_locale, locale=locale
            ),
            "terms": categories,
        })
    return {"type": collection.key, "locale": locale, "taxonomies": taxonomies}


def _category_terms(naming: _Naming, entries: list[_Listed]) -> list[dict[str, Any]]:
    """A type's categories that have a list in the language read, in the
    tree's order: each with how many listed entries it shows — its own and
    those of the categories under it — and the one above it. A category no
    listed entry is under is not here; one above a listed one always is."""
    if naming.taxonomy is None:
        return []
    mine = naming.categories()
    found: list[dict[str, Any]] = []
    for term in naming.vocabulary.tree(naming.taxonomy):
        ids = _under(naming, term)
        count = sum(1 for item in entries if _in_category(item, ids))
        if not count:
            continue
        above = mine.get(term.parent_id) if term.parent_id else None
        published = next(
            (name for item in entries for term_id, name in item.categories if term_id == term.id),
            "",
        )
        found.append({
            **naming.category(term, published),
            "count": count,
            "indexable": count >= TAG_INDEX_THRESHOLD,
            "parent_slug": naming.slug(above) if above is not None else None,
        })
    return found


# -- lists ---------------------------------------------------------------------


def read_entries(
    *,
    type_key: str,
    locale: str,
    page: int = 1,
    page_size: int | None = None,
    taxonomy: str = "",
    term: str = "",
) -> dict[str, Any]:
    """A page of a type's published entries in one language, newest first —
    all of them, or those under one term. A type's list in the site's own
    language answers even when every entry is in another one; a term's list
    answers only where the term has an entry."""
    size = page_size or settings.SITES_ENTRY_INDEX_PAGE_SIZE
    if page < 1 or not 1 <= size <= MAX_PAGE_SIZE:
        raise ContentNotFound
    if bool(taxonomy) != bool(term) or taxonomy not in ("", TAG_TAXONOMY, CATEGORY_TAXONOMY):
        raise ContentNotFound
    workspace = _workspace()
    collection = _type(workspace, type_key)
    # All of the type's languages: its languages, the name of a term, where a
    # term moved to — each is answered from the other languages' entries too.
    of_type = _listed(workspace, collection_id=collection.id)
    if not of_type:
        # A type with nothing listed is no type for the read.
        raise ContentNotFound
    naming = _naming(workspace, collection, locale, _vocabulary(workspace))
    asked = _asked_term(naming, of_type, taxonomy, term) if term else None
    if asked is not None:
        of_type = [item for item in of_type if asked.lists(item)]
    entries = [item for item in of_type if item.locale == locale]
    if not entries and (term or locale != workspace.default_locale):
        raise ContentNotFound
    if asked is not None and asked.term["slug"] != term:
        # Asked by an address the term used to have, by its key, or by its
        # address in another language: where its list answers in this one.
        return {
            "list": None,
            "moved": {
                "type": collection.key,
                "locale": locale,
                "taxonomy": taxonomy,
                "term": asked.term["slug"],
            },
        }
    # Where this list answers: a term's wherever it has an entry, a type's
    # also in the site's own language, as on a company's site.
    languages = _languages(
        workspace.default_locale,
        [*(item.locale for item in of_type), *([] if term else [workspace.default_locale])],
    )
    pages = max(1, -(-len(entries) // size))
    # A page past the end is a wrong address, not an empty page.
    if page > pages:
        raise ContentNotFound
    window = entries[(page - 1) * size : page * size]
    pictures = _pictures(workspace, [item.entry_id for item in window])
    return {
        "moved": None,
        "list": {
            "type": collection.key,
            "locale": locale,
            "name": naming.names.get(f"collection/{collection.id}") or collection.name,
            "term": (
                {**asked.term, "versions": asked.versions(workspace.default_locale, languages)}
                if asked is not None
                else None
            ),
            "items": [_item(item, naming, pictures.get(item.entry_id) or {}) for item in window],
            "page": page,
            "pages": pages,
            "total": len(entries),
            "languages": languages,
            # The day a reader sees on a card is the day it was at the
            # publisher's, as on the entry's own page.
            "timezone": _timezone(workspace),
            # A term's list with one or two entries is a thin copy of the type's
            # own list: it answers readers and asks not to be indexed. The rule
            # is the core's; the product only applies it.
            "indexable": not term or len(entries) >= TAG_INDEX_THRESHOLD,
        },
    }


def _timezone(workspace: _Workspace) -> str:
    # The organization's row forces row-level security: the tenant first.
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        zone = (
            Organization.objects.filter(pk=workspace.organization_id)
            .values_list("timezone", flat=True)
            .first()
        )
    return str(zone or "UTC")


@dataclass(frozen=True, slots=True)
class _Asked:
    """The term a list was asked for: how the read names it now, and which
    listed entries are on its list."""

    term: dict[str, Any]
    #: A tag's key, as snapshots name it; empty for a category.
    key: str
    #: A category's id and those of the categories under it.
    ids: frozenset[str]
    #: The term's row; none for a tag that only snapshots still name.
    row: Term | None

    def lists(self, item: _Listed) -> bool:
        if self.key:
            return any(key == self.key for key, _name in item.tags)
        return _in_category(item, self.ids)

    def versions(self, default_locale: str, languages: Iterable[str]) -> list[dict[str, str]]:
        """The term's list in each language it answers in, as (language,
        slug) — this one too, the site's own first, like an entry's
        `versions`: a language switch and `hreflang` need no further read.
        A tag without a row answers under its key everywhere."""
        return [
            {
                "locale": code,
                "slug": (
                    term_slug(self.row, default_locale=default_locale, locale=code)
                    if self.row is not None
                    else self.key
                ),
            }
            for code in languages
        ]


def _asked_term(naming: _Naming, of_type: list[_Listed], taxonomy: str, asked: str) -> _Asked:
    """The term `asked` names in a taxonomy of this type: by its address in
    the language read, or — the answer is then „moved" — by anything else
    that leads to it: its key, its address in another language, an address it
    used to have (one namespace per taxonomy, ADR-079 pkt 6). Nothing else
    names a term."""
    if taxonomy == CATEGORY_TAXONOMY:
        rows = list(naming.categories().values())
    else:
        rows = list(naming.tags.values())
    found = next((row for row in rows if naming.slug(row) == asked), None) or next(
        (row for row in rows if asked in term_names(row)), None
    )
    if taxonomy == CATEGORY_TAXONOMY:
        if found is None:
            raise ContentNotFound
        published = next(
            (name for item in of_type for term_id, name in item.categories if term_id == found.id),
            "",
        )
        return _Asked(naming.category(found, published), "", _under(naming, found), found)
    key = found.slug if found is not None else asked
    name = next((name for item in of_type for slug, name in item.tags if slug == key), None)
    if name is None:
        # No listed entry of the type carries it.
        raise ContentNotFound
    return _Asked(naming.tag(key, name), key, frozenset(), naming.tags.get(key))


# -- an entry ------------------------------------------------------------------


def _versions(workspace: _Workspace, group: UUID) -> list[dict[str, str]]:
    """The entry's published versions as (language, slug), its own included:
    each language is its own entry, and the group makes them one work."""
    found = {
        str(locale): str(slug)
        for locale, slug in _published(workspace)
        .filter(translation_group=group)
        .values_list("current_publication__snapshot__locale", "current_publication__snapshot__slug")
        if str(locale) in workspace.available
    }
    return [
        {"locale": locale, "slug": found[locale]}
        for locale in _languages(workspace.default_locale, found)
    ]


def _canonical_url(value: str) -> str:
    """The address the product gives the entry, as its structured data will
    name it: a plain http(s) address on the platform's own host — where a
    product's pages stand (ADR-080) — and nobody else's. Composed into
    identifiers only — never fetched, stored or answered with a redirect —
    and still a value an anonymous caller chooses, so nothing that could
    close a quote or a tag is let into it."""
    refused = ValidationError({
        "canonical_url": [
            ErrorDetail(
                "Adres kanoniczny to pełny adres http(s) na hoście platformy, "
                "bez zapytania i fragmentu.",
                code="canonical_url_invalid",
            )
        ]
    })
    if len(value) > _CANONICAL_URL_MAX or any(
        ord(char) <= 32 or char in _CANONICAL_URL_REFUSED for char in value
    ):
        raise refused
    try:
        parts = urlsplit(value)
        hostname, _port = parts.hostname, parts.port
    except ValueError as error:
        # An address no parser reads — an unclosed `[`, a port that is no
        # number — is a wrong value, not a failure of ours.
        raise refused from error
    if (
        parts.scheme not in ("http", "https")
        or (hostname or "").rstrip(".") != settings.SITES_PLATFORM_DOMAIN
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise refused
    return value


def _entry_node(
    *,
    canonical_url: str,
    locale: str,
    snapshot: Mapping[str, Any],
    article: dict[str, Any],
    picture: dict[str, str] | None,
    machine: dict[str, Any] | None,
    schema_type: str,
) -> list[dict[str, Any]]:
    """The entry's own nodes of the structured data — its page (a page of
    questions where the body asks some) and, unless its type is a plain page,
    the article — built by the function a company's site builds its graph
    with (`page_graph`), from the address the product gives. The site around
    them — WebSite, Organization — is the product's to state, under the
    identifiers these nodes point at (`<origin>/#website`,
    `<origin>/#organization`)."""
    parts = urlsplit(canonical_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    graph = page_graph(
        origin=origin,
        site_name="",
        locale=locale,
        canonical_url=canonical_url,
        title=str(snapshot["title"]),
        description=str(snapshot.get("excerpt") or ""),
        breadcrumbs=[],
        blocks=list(snapshot["blocks"]),
        article=article,
        image=(
            {"url": f"{origin}/media/{picture['asset_id']}", "alt": picture["alt"]}
            if picture
            else None
        ),
        facts=None,
        machine_source_type=machine["source_type"] if machine else None,
        article_type=schema_type,
    )["@graph"]
    own = {f"{canonical_url}#webpage", f"{canonical_url}#article"}
    return [node for node in graph if node.get("@id") in own]


def read_entry(
    *, type_key: str, locale: str, slug: str, canonical_url: str | None = None
) -> dict[str, Any]:
    """A published entry by type, language and slug — or where it answers
    now (`moved`), in address parts."""
    address = _canonical_url(canonical_url) if canonical_url else None
    workspace = _workspace()
    entry = (
        _published(workspace)
        .select_related("current_publication", "collection")
        .filter(
            collection__key=type_key,
            # The entry's own columns, which a publication copies: the
            # router finds an entry by its slug column as well.
            locale=locale,
            slug=slug,
        )
        .first()
    )
    if entry is None or entry.current_publication is None:
        # Not an entry's address today; one it had leads to today's (ADR-079
        # pkt 16) — the same rule as the public router's `moved_address`: a
        # live address was asked first, so a former slug never shadows it.
        former = (
            _published(workspace)
            .select_related("current_publication")
            .filter(
                collection__key=type_key,
                locale=locale,
                former_slugs__contains=[slug],
            )
            .order_by("id")
            .first()
        )
        if former is None or former.current_publication is None:
            raise ContentNotFound
        if locale not in workspace.available:
            # Straight to where the switched-off language leads — one hop.
            versions = _versions(workspace, former.translation_group)
            if not versions:
                raise ContentNotFound
            return {"entry": None, "moved": {"type": type_key, **versions[0]}}
        return {
            "entry": None,
            "moved": {
                "type": type_key,
                "locale": locale,
                "slug": str(former.current_publication.snapshot["slug"]),
            },
        }
    publication = entry.current_publication
    snapshot = publication.snapshot
    versions = _versions(workspace, entry.translation_group)
    if locale not in workspace.available:
        # A language the workspace switched off: the entry in the site's own
        # language, where it has one, else in the first it has (ADR-071 pkt 9).
        if not versions:
            raise ContentNotFound
        return {
            "entry": None,
            "moved": {"type": entry.collection.key, **versions[0]},
        }
    noindex = bool(snapshot.get("noindex", False))
    tags = _tags_of(snapshot.get("tags"))
    categories = _categories_of(snapshot.get("terms"))
    naming = _naming(workspace, entry.collection, locale, _vocabulary(workspace))
    if noindex and (tags or categories):
        # A hidden entry is on no list, so a term only it carries has no list
        # either (pkt 30): it names the terms other entries make readable.
        others = _listed(workspace, collection_id=entry.collection_id, locale=locale)
        readable = {slug for item in others for slug, _name in item.tags}
        tags = tuple(tag for tag in tags if tag[0] in readable)
        mine = naming.categories()
        categories = tuple(
            (term_id, name)
            for term_id, name in categories
            if term_id in mine
            and any(_in_category(item, _under(naming, mine[term_id])) for item in others)
        )
    media = [str(asset_id) for asset_id in snapshot.get("media_asset_ids") or []]
    blocks = snapshot["blocks"]
    picture = _first_picture(blocks, set(media))
    facts: dict[str, Any] = {}
    timezone = "UTC"
    # Media and the organization force row-level security: the tenant first.
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        if media:
            facts = shown_image_facts(organization_id=workspace.organization_id, asset_ids=media)
        timezone = str(
            Organization.objects.filter(pk=workspace.organization_id)
            .values_list("timezone", flat=True)
            .first()
            or "UTC"
        )
    machine = machine_text(snapshot.get("origin"))
    terms = naming.terms(tags, categories)
    updated_at = str(snapshot.get("changed_at") or publication.created_at.isoformat())
    published_at = entry.published_at.isoformat() if entry.published_at is not None else None
    schema_type = str(entry.collection.schema_type)
    return {
        "moved": None,
        "entry": {
            "type": entry.collection.key,
            "locale": locale,
            "slug": str(snapshot["slug"]),
            "title": str(snapshot["title"]),
            "excerpt": str(snapshot.get("excerpt") or ""),
            "author_name": str(snapshot.get("author_name") or ""),
            "published_at": published_at,
            "updated_at": updated_at,
            # The day a reader sees is the day it was in the publisher's zone.
            "timezone": timezone,
            "blocks": blocks,
            "image": picture,
            "cover": _cover(blocks, set(media)),
            "image_sizes": {
                asset_id: {"width": fact.width, "height": fact.height}
                for asset_id, fact in facts.items()
                if fact.width and fact.height
            },
            # Empty when the operator hid the badge, as on a company's site.
            "ai_media_ids": (
                sorted(asset_id for asset_id, fact in facts.items() if fact.ai)
                if badge_visible()
                else []
            ),
            "terms": terms,
            "versions": versions,
            "noindex": noindex,
            "machine_text": machine,
            "schema_type": schema_type,
            "structured_data": (
                _entry_node(
                    canonical_url=address,
                    locale=locale,
                    snapshot=snapshot,
                    article={
                        "title": str(snapshot["title"]),
                        "author_name": str(snapshot.get("author_name") or ""),
                        "published_at": published_at,
                        "updated_at": updated_at,
                        # Keywords are the tags; a category is not one.
                        "tags": [
                            {"name": term["name"]}
                            for term in terms
                            if term["taxonomy"] == TAG_TAXONOMY
                        ],
                    },
                    picture=picture,
                    machine=machine,
                    schema_type=schema_type,
                )
                if address
                else None
            ),
        },
    }


# -- the sitemap ---------------------------------------------------------------


def read_sitemap() -> dict[str, Any]:
    """Everything of the platform's content a sitemap lists, as address
    parts: entries by translation group, each type's list per language, and
    the lists of terms worth indexing. The product writes the addresses."""
    workspace = _workspace()
    listed = _listed(workspace)
    types = _types(workspace)
    entries: dict[UUID, dict[str, Any]] = {}
    lists: dict[UUID, dict[str, datetime]] = {}
    tagged: dict[tuple[UUID, str], dict[str, list[_Listed]]] = {}
    for item in listed:
        collection = types.get(item.collection_id)
        if collection is None:
            continue
        group = entries.setdefault(item.group, {"type": collection.key, "versions": {}})
        group["versions"][item.locale] = {
            "locale": item.locale,
            "slug": item.slug,
            "updated_at": item.changed_at,
        }
        newest = lists.setdefault(item.collection_id, {})
        newest[item.locale] = max(newest.get(item.locale, item.changed_at), item.changed_at)
        for slug, _name in item.tags:
            tagged.setdefault((item.collection_id, slug), {}).setdefault(item.locale, []).append(
                item
            )
    default = workspace.default_locale
    vocabulary = _vocabulary(workspace)
    tags = {term.slug: term for term in vocabulary.of(None)}

    def address(term: Term | None, key: str, locale: str) -> str:
        return term_slug(term, default_locale=default, locale=locale) if term else key

    def worth(by_locale: dict[str, list[_Listed]]) -> list[str]:
        # Below the threshold a term's list asks not to be indexed.
        return [
            locale for locale, items in by_locale.items() if len(items) >= TAG_INDEX_THRESHOLD
        ]

    terms: list[dict[str, Any]] = [
        {
            "type": types[collection_id].key,
            "taxonomy": TAG_TAXONOMY,
            "versions": [
                {
                    "locale": locale,
                    "slug": address(tags.get(key), key, locale),
                    "updated_at": max(item.changed_at for item in by_locale[locale]),
                }
                for locale in _languages(default, indexable)
            ],
        }
        for (collection_id, key), by_locale in sorted(
            tagged.items(), key=lambda found: (types[found[0][0]].key, found[0][1])
        )
        if (indexable := worth(by_locale))
    ]
    # A type's categories: each with the entries of those under it.
    for collection in sorted(types.values(), key=lambda found: found.key):
        taxonomy = vocabulary.categories_of(collection.id)
        if taxonomy is None:
            continue
        of_type = [item for item in listed if item.collection_id == collection.id]
        for term in vocabulary.tree(taxonomy):
            ids = vocabulary.with_descendants(term)
            filed: dict[str, list[_Listed]] = {}
            for item in of_type:
                if _in_category(item, ids):
                    filed.setdefault(item.locale, []).append(item)
            indexable = worth(filed)
            if indexable:
                terms.append({
                    "type": collection.key,
                    "taxonomy": CATEGORY_TAXONOMY,
                    "versions": [
                        {
                            "locale": locale,
                            "slug": address(term, term.slug, locale),
                            "updated_at": max(item.changed_at for item in filed[locale]),
                        }
                        for locale in _languages(default, indexable)
                    ],
                })
    return {
        "entries": [
            {
                "type": group["type"],
                "versions": [
                    group["versions"][locale] for locale in _languages(default, group["versions"])
                ],
            }
            for group in entries.values()
        ],
        "lists": [
            {
                "type": types[collection_id].key,
                "versions": [
                    {"locale": locale, "updated_at": newest[locale]}
                    for locale in _languages(default, newest)
                ],
            }
            for collection_id, newest in lists.items()
        ],
        "terms": terms,
    }


# -- pictures ------------------------------------------------------------------


def serve_content_media(*, asset_id: UUID, variant: str = "") -> HttpResponse:
    """A picture the platform's host may show: at `/media/…` there, where the
    block renderers and a product's own pages look for pictures.

    Two rules, as on a company's site (`public_media`):

    - what a published entry of the workspace shows — the original or one of
      the pipeline's WebP copies. Only what an entry's current publication
      names: never a picture of the workspace's builder pages, which no host
      shows (pkt 29), nor one of a draft, a withdrawn entry, a switched-off
      type or an entry in a language the workspace switched off — a picture
      answers where its entry does;
    - what a live record of the workspace shows a visitor, on the word of the
      module that owns it (the registry of public sources, `served_media`) —
      a breed's picture on a product's own page (ADR-080, „Uzupełnienie
      PR1c"). One of our copies, never the original.

    The same answer whether the asset is somebody else's, nobody's, or the
    workspace's own that neither rule names."""
    # The read sets the workspace's tenant, and a signed-in visitor's browser
    # sends the panel's session along with a picture's address: whatever
    # tenant the request had set is put back, and the visitor's own company
    # is not who a source is asked as (as `in_platform_workspace` does).
    with tenant_setting_kept():
        workspace = _workspace()
        with only_tenant_context_of(workspace.organization_id), transaction.atomic():
            # A source reads its own tables, and they force row-level
            # security as media does: asked before the tenant is set, the
            # application's role sees no row there and every such picture
            # would answer 404.
            set_local_organization_id(workspace.organization_id)
            if not (
                # A copy asks the sources first: a list page's dozens of
                # thumbnails are then answered by one small read each, and
                # never wait for the search of every published snapshot.
                (variant and asset_id in served_media_ids(workspace.organization_id))
                or _published(workspace)
                .filter(
                    current_publication__snapshot__locale__in=sorted(workspace.available),
                    current_publication__snapshot__media_asset_ids__contains=[str(asset_id)],
                )
                .exists()
            ):
                raise ContentNotFound
            asset = MediaAsset.all_objects.filter(
                pk=asset_id,
                organization_id=workspace.organization_id,
                state=MediaAssetState.READY,
            ).first()
    return media_response(asset, variant)
