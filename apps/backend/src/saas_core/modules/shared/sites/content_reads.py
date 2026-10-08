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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpResponse
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import platform_workspace_id
from saas_core.modules.shared.media.api import shown_image_facts
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState

from .ai_badge import badge_visible
from .localization import section_segment
from .machine_text import machine_text
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    ContentTag,
    Site,
)
from .public_media import media_response
from .publication_routing import (
    TAG_INDEX_THRESHOLD,
    TAG_SEGMENT,
    parse_moment,
    serving_locales,
)
from .seo_graph import page_graph

#: The one taxonomy of today: the site's tags, flat and shared by its types.
#: Categories join as further taxonomies of a type (ADR-079 pkt 2, 9).
TAG_TAXONOMY = "tag"

#: How many entries a list answers with at most; the product asks for fewer.
MAX_PAGE_SIZE = 100

_CANONICAL_URL_MAX = 2048


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


def _listed(workspace: _Workspace) -> list[_Listed]:
    """Every entry a list may show, newest first: published, asking to be
    indexed, in a language the workspace reads. Bodies stay in the database —
    a list of a few hundred guides is not a few megabytes of blocks."""
    snapshot = "current_publication__snapshot__"
    rows = (
        _published(workspace)
        .filter(Q(**{f"{snapshot}noindex": False}) | Q(**{f"{snapshot}noindex__isnull": True}))
        .values_list(
            "id",
            "collection_id",
            "translation_group",
            "published_at",
            "current_publication__created_at",
            f"{snapshot}locale",
            f"{snapshot}slug",
            f"{snapshot}title",
            f"{snapshot}excerpt",
            f"{snapshot}author_name",
            f"{snapshot}tags",
            f"{snapshot}changed_at",
        )
    )
    found = [
        _Listed(
            entry_id=entry_id,
            collection_id=collection_id,
            group=group,
            locale=str(locale),
            slug=str(slug),
            title=str(title),
            excerpt=str(excerpt or ""),
            author_name=str(author_name or ""),
            tags=_tags_of(tags),
            published_at=published_at,
            # When the text changed, which publishing it again does not move.
            changed_at=parse_moment(changed_at) or created_at,
        )
        for (
            entry_id,
            collection_id,
            group,
            published_at,
            created_at,
            locale,
            slug,
            title,
            excerpt,
            author_name,
            tags,
            changed_at,
        ) in rows
        if str(locale) in workspace.available
    ]
    # A missing timestamp sorts last, as in the router's own list.
    found.sort(key=lambda item: (item.published_at is not None, item.published_at), reverse=True)
    return found


def _type(workspace: _Workspace, key: str, listed: list[_Listed]) -> ContentCollection:
    """The type `key`, which exists for the read once an entry of it is on a
    list — an empty type and no type at all answer the same."""
    collection = next((found for found in _types(workspace).values() if found.key == key), None)
    if collection is None or not any(item.collection_id == collection.id for item in listed):
        raise ContentNotFound
    return collection


def _names(workspace: _Workspace, locale: str) -> dict[str, str]:
    """The accepted names of types and tags in `locale`, by site-text key
    (`collection/<id>`, `tag/<id>`). Read straight from the accepted
    translations (ADR-079 pkt 33): on a company's site they go out with the
    site's publication, and nobody publishes the workspace's site. The caller
    asks only for what a published entry carries."""
    if locale == workspace.default_locale:
        return {}
    from .site_texts import shown_texts, site_text_units, translation_rows

    # Tags and site texts force row-level security: the tenant goes first.
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        return shown_texts(
            site_text_units(workspace.site, None), translation_rows(workspace.site, locale)
        )


def _tag_ids(workspace: _Workspace, slugs: Iterable[str]) -> dict[str, str]:
    wanted = sorted(set(slugs))
    if not wanted:
        return {}
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        return {
            str(slug): str(tag_id)
            for slug, tag_id in ContentTag.all_objects.filter(
                organization_id=workspace.organization_id,
                site_id=workspace.site.id,
                slug__in=wanted,
            ).values_list("slug", "id")
        }


def _terms(
    workspace: _Workspace, locale: str, tags: Iterable[tuple[str, str]], names: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Tags as the read names them: by taxonomy and slug, under the name in
    the reader's language where one is accepted, else as published."""
    tags = sorted(dict(tags).items())
    ids = _tag_ids(workspace, (slug for slug, _name in tags)) if names else {}
    return [
        {
            "taxonomy": TAG_TAXONOMY,
            "slug": slug,
            "name": names.get(f"tag/{ids.get(slug)}") or name,
        }
        for slug, name in tags
    ]


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


def _pictures(workspace: _Workspace, entry_ids: list[UUID]) -> dict[UUID, dict[str, str] | None]:
    """The first picture of each of a page's entries: the only part of a list
    that needs the bodies, read for that page's entries alone."""
    return {
        entry_id: _first_picture(blocks, {str(asset_id) for asset_id in media or []})
        for entry_id, blocks, media in _published(workspace)
        .filter(pk__in=entry_ids)
        .values_list(
            "id",
            "current_publication__snapshot__blocks",
            "current_publication__snapshot__media_asset_ids",
        )
    }


def _item(
    workspace: _Workspace,
    item: _Listed,
    names: Mapping[str, str],
    picture: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "locale": item.locale,
        "slug": item.slug,
        "title": item.title,
        "excerpt": item.excerpt,
        "author_name": item.author_name,
        "published_at": item.published_at,
        "updated_at": item.changed_at,
        "image": picture,
        "terms": _terms(workspace, item.locale, item.tags, names),
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
    listed = _listed(workspace)
    collection = _type(workspace, type_key, listed)
    entries = [
        item for item in listed if item.collection_id == collection.id and item.locale == locale
    ]
    if not entries and locale != workspace.default_locale:
        # The type has no list in this language.
        raise ContentNotFound
    counts: dict[str, int] = {}
    published: dict[str, str] = {}
    for item in entries:
        for slug, name in item.tags:
            counts[slug] = counts.get(slug, 0) + 1
            # Newest first: the name the latest publication gave the tag.
            published.setdefault(slug, name)
    names = _names(workspace, locale)
    return {
        "type": collection.key,
        "locale": locale,
        "taxonomies": [
            {
                "key": TAG_TAXONOMY,
                "hierarchical": False,
                "segment": TAG_SEGMENT,
                "terms": [
                    {
                        **term,
                        "count": counts[term["slug"]],
                        "indexable": counts[term["slug"]] >= TAG_INDEX_THRESHOLD,
                        # Tags are flat; a category names the one above it.
                        "parent_slug": None,
                    }
                    for term in _terms(workspace, locale, published.items(), names)
                ],
            }
        ],
    }


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
    if bool(taxonomy) != bool(term) or (taxonomy and taxonomy != TAG_TAXONOMY):
        raise ContentNotFound
    workspace = _workspace()
    listed = _listed(workspace)
    collection = _type(workspace, type_key, listed)
    of_type = [item for item in listed if item.collection_id == collection.id]
    if term:
        of_type = [item for item in of_type if any(slug == term for slug, _name in item.tags)]
    entries = [item for item in of_type if item.locale == locale]
    if not entries and (term or locale != workspace.default_locale):
        raise ContentNotFound
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
    names = _names(workspace, locale)
    pictures = _pictures(workspace, [item.entry_id for item in window])
    named = (
        _terms(
            workspace,
            locale,
            [next((slug, name) for item in entries for slug, name in item.tags if slug == term)],
            names,
        )[0]
        if term
        else None
    )
    return {
        "type": collection.key,
        "locale": locale,
        "name": names.get(f"collection/{collection.id}") or collection.name,
        "term": named,
        "items": [_item(workspace, item, names, pictures.get(item.entry_id)) for item in window],
        "page": page,
        "pages": pages,
        "total": len(entries),
        "languages": languages,
        # A term's list with one or two entries is a thin copy of the type's
        # own list: it answers readers and asks not to be indexed. The rule
        # is the core's; the product only applies it.
        "indexable": not term or len(entries) >= TAG_INDEX_THRESHOLD,
    }


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
    name it. Composed into identifiers only — never fetched, stored or
    answered with a redirect."""

    def refuse(code: str, message: str) -> ValidationError:
        return ValidationError({"canonical_url": [ErrorDetail(message, code=code)]})

    if len(value) > _CANONICAL_URL_MAX or any(ord(char) <= 32 for char in value):
        raise refuse("canonical_url_invalid", "Adres kanoniczny ma nieprawidłowy format.")
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise refuse(
            "canonical_url_invalid",
            "Adres kanoniczny to pełny adres http(s) bez zapytania i fragmentu.",
        )
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
            current_publication__snapshot__locale=locale,
            current_publication__snapshot__slug=slug,
        )
        .first()
    )
    if entry is None or entry.current_publication is None:
        raise ContentNotFound
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
    if noindex and tags:
        # A hidden entry is on no list, so a term only it carries has no list
        # either (pkt 30): it names the terms other entries make readable.
        readable = {
            slug
            for item in _listed(workspace)
            if item.collection_id == entry.collection_id and item.locale == locale
            for slug, _name in item.tags
        }
        tags = tuple(tag for tag in tags if tag[0] in readable)
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
    names = _names(workspace, locale)
    terms = _terms(workspace, locale, tags, names)
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
                        "tags": [{"name": term["name"]} for term in terms],
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
    terms: dict[tuple[UUID, str], dict[str, list[_Listed]]] = {}
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
            terms.setdefault((item.collection_id, slug), {}).setdefault(item.locale, []).append(
                item
            )
    default = workspace.default_locale
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
        "terms": [
            {
                "type": types[collection_id].key,
                "taxonomy": TAG_TAXONOMY,
                "versions": [
                    {
                        "locale": locale,
                        "slug": slug,
                        "updated_at": max(item.changed_at for item in by_locale[locale]),
                    }
                    for locale in _languages(default, indexable)
                ],
            }
            for (collection_id, slug), by_locale in sorted(
                terms.items(), key=lambda found: (types[found[0][0]].key, found[0][1])
            )
            # Below the threshold a term's list asks not to be indexed.
            if (
                indexable := [
                    locale
                    for locale, items in by_locale.items()
                    if len(items) >= TAG_INDEX_THRESHOLD
                ]
            )
        ],
    }


# -- pictures ------------------------------------------------------------------


def serve_content_media(*, asset_id: UUID, variant: str = "") -> HttpResponse:
    """A picture a published entry of the workspace shows: the original or
    one of the pipeline's WebP copies. The platform's host answers it at
    `/media/…`, where the block renderers look for pictures.

    Only what an entry's current publication names — never a picture of the
    workspace's builder pages, which no host shows (pkt 29), nor one of a
    draft, a withdrawn entry or a switched-off type. The same answer whether
    the asset is somebody else's or nobody's."""
    workspace = _workspace()
    if (
        not _published(workspace)
        .filter(current_publication__snapshot__media_asset_ids__contains=[str(asset_id)])
        .exists()
    ):
        raise ContentNotFound
    with transaction.atomic():
        set_local_organization_id(workspace.organization_id)
        asset = MediaAsset.all_objects.filter(
            pk=asset_id,
            organization_id=workspace.organization_id,
            state=MediaAssetState.READY,
        ).first()
    return media_response(asset, variant)
