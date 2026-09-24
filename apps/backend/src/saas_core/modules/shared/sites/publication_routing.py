from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization, OrganizationStatus
from saas_core.modules.shared.media.api import ai_generated_asset_ids

from .ai_badge import badge_visible
from .domains import InvalidHostname, normalize_hostname
from .localization import collection_index_path
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    Domain,
    DomainStatus,
    Publication,
    Site,
)


def tenant_is_servable(organization_id: Any) -> bool:
    """Whether the tenant a hostname resolved to may still be served.

    The organization registry carries row-level security (ADR-041), so this is
    a read inside the tenant rather than a join the renderer makes from outside
    one — the hostname is what names the tenant, and it names it before
    anything else is read.

    Deliberately not the pre-tenant door: the public renderer is the platform's
    most exposed surface, and letting it hold a connection that reads past
    policies would give one injection there the reach over every tenant's
    memberships and invitations that ADR-041 exists to take away.
    """
    with transaction.atomic():
        set_local_organization_id(organization_id)
        return Organization.objects.filter(
            pk=organization_id, status=OrganizationStatus.ACTIVE
        ).exists()


DEFAULT_PUBLIC_DESIGN_TOKENS = {
    "schemaVersion": 1,
    "palette": "neutral",
    "typography": "sans",
    "radius": "medium",
    "spacing": "comfortable",
}


class PublicSiteNotFound(NotFound):
    default_detail = "Opublikowana strona nie istnieje dla tego hosta i ścieżki."
    default_code = "public_site_not_found"


@dataclass(frozen=True, slots=True)
class PublicPage:
    hostname: str
    canonical_hostname: str
    requested_path: str
    canonical_path: str
    locale: str
    publication: Publication
    page: dict[str, Any]

    @property
    def redirect_url(self) -> str | None:
        # Compared the same way the page was matched. A raw `==` treats
        # "/start" and "/start/" as different addresses and redirects the
        # visitor to the page they already asked for, forever.
        already_canonical = _comparable_path(self.requested_path) == _comparable_path(
            self.canonical_path
        )
        # `/` is the public alias for the selected home page. Serve it on the
        # canonical hostname and keep the page's real path in canonical_url;
        # this also lets local deployments use a non-standard proxy port
        # without constructing a redirect that silently drops that port.
        root_alias = _comparable_path(self.requested_path) == "/"
        if self.hostname == self.canonical_hostname and (already_canonical or root_alias):
            return None
        return f"{settings.PUBLIC_SITE_SCHEME}://{self.canonical_hostname}{self.canonical_path}"


def resolve_public_page(*, host: str, path: str) -> PublicPage:
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    normalized_path = _normalize_path(path)
    # A published entry is reachable even when the site itself has no
    # publication yet: entries publish independently, so requiring a site
    # snapshot would make the blog depend on something unrelated to it.
    domain = (
        Domain.all_objects.select_related("site__current_publication")
        .filter(hostname=hostname, status=DomainStatus.VERIFIED)
        .first()
    )
    if domain is None or not tenant_is_servable(domain.organization_id):
        raise PublicSiteNotFound
    canonical = Domain.all_objects.filter(
        site_id=domain.site_id,
        status=DomainStatus.VERIFIED,
        is_canonical=True,
    ).first()
    if canonical is None:
        raise PublicSiteNotFound
    publication: Any = domain.site.current_publication
    try:
        if publication is None:
            raise PublicSiteNotFound
        page, locale_document = _find_page(publication.snapshot, normalized_path)
    except PublicSiteNotFound:
        # Not a page, so it may be a collection entry, or the collection's own
        # index. Entries publish on their own (ADR-035 §1) and are therefore
        # absent from the site snapshot; the entry's own publication then stands
        # in for the site's.
        try:
            page, locale_document, publication = _find_entry(
                organization_id=domain.organization_id,
                site_id=domain.site_id,
                requested_path=normalized_path,
            )
        except PublicSiteNotFound:
            try:
                page, locale_document, publication = _find_collection_index(
                    organization_id=domain.organization_id,
                    site_id=domain.site_id,
                    requested_path=normalized_path,
                )
            except PublicSiteNotFound:
                try:
                    # A subject's own archive, which is a projection like the
                    # index rather than a page anybody edits.
                    page, locale_document, publication = _find_tag_archive(
                        organization_id=domain.organization_id,
                        site_id=domain.site_id,
                        requested_path=normalized_path,
                    )
                except PublicSiteNotFound:
                    pass
                else:
                    return _resolved(
                        canonical=canonical,
                        hostname=hostname,
                        locale_document=locale_document,
                        page=page,
                        path=normalized_path,
                        publication=publication,
                    )
                # Nothing answers here any more, but something used to. A
                # visitor following an old link, and a search engine holding an
                # old address, both deserve better than a 404.
                target = _redirect_target(
                    publication=domain.site.current_publication,
                    requested_path=normalized_path,
                )
                if target is None:
                    raise
                raise PublicSiteMoved(
                    f"{settings.PUBLIC_SITE_SCHEME}://{canonical.hostname}{target}"
                ) from None
    return _resolved(
        canonical=canonical,
        hostname=hostname,
        locale_document=locale_document,
        page=page,
        path=normalized_path,
        publication=publication,
    )


def _resolved(
    *,
    canonical: Any,
    hostname: str,
    locale_document: dict[str, Any],
    page: dict[str, Any],
    path: str,
    publication: Any,
) -> PublicPage:
    return PublicPage(
        hostname=hostname,
        canonical_hostname=canonical.hostname,
        requested_path=path,
        canonical_path=str(locale_document["canonical_path"]),
        locale=str(locale_document["locale"]),
        publication=publication,
        page={**page, "selected_locale": locale_document},
    )


def public_page_payload(page: PublicPage) -> dict[str, Any]:
    selected_locale = page.page["selected_locale"]
    publication_snapshot = page.publication.snapshot
    canonical_origin = f"{settings.PUBLIC_SITE_SCHEME}://{page.canonical_hostname}"
    hreflang = {
        locale: f"{canonical_origin}{path}"
        for locale, path in page.page.get("hreflang", {}).items()
    }
    return {
        "publication_id": str(page.publication.id),
        "snapshot_hash": page.publication.snapshot_hash,
        "locale": page.locale,
        "canonical_url": f"{canonical_origin}{page.canonical_path}",
        "hreflang": hreflang,
        "x_default": f"{canonical_origin}{page.page['x_default']}",
        "title": selected_locale["title"],
        "description": selected_locale["description"],
        "social_title": selected_locale["social_title"],
        "social_description": selected_locale["social_description"],
        # An entry's snapshot carries no theme of its own; it inherits the
        # site's, and falls back to the default when the site has never been
        # published.
        "design_tokens": publication_snapshot.get(
            "design_tokens", DEFAULT_PUBLIC_DESIGN_TOKENS
        ),
        "appearance": publication_snapshot.get("appearance"),
        # Only site pages carry one; entries, indexes and archives inherit.
        "page_presentation": page.page.get("page_presentation"),
        "blocks": page.page["blocks"],
        "navigation": _navigation_links(publication_snapshot, page.locale),
        # Derived from the menu, never stored: a stored trail is wrong the
        # moment somebody reorders the tree, and the whole point of the
        # hierarchy is that reordering is cheap.
        "breadcrumbs": _breadcrumbs(
            publication_snapshot,
            locale=page.locale,
            page_id=str(page.page.get("page_id", "")),
            title=selected_locale["title"],
            path=page.canonical_path,
        ),
        # Present only where they mean something: an index has pages, an
        # article has an author and dates, a plain page has neither.
        "pagination": _absolute_pagination(page.page.get("pagination"), canonical_origin),
        "article": page.page.get("article"),
        "ai_media_ids": _ai_media_ids(page),
    }


def _ai_media_ids(page: PublicPage) -> list[str]:
    """AI images on the page, read at render time (ADR-059 pkt 7).

    Provenance is not in the snapshot, so publications made before an asset
    was marked get the badge too. The operator switch hides the list; the XMP
    inside the files stays either way.
    """
    if not badge_visible():
        return []
    # media_mediaasset forces RLS: the tenant the host named goes first.
    with transaction.atomic():
        set_local_organization_id(page.publication.organization_id)
        return sorted(
            ai_generated_asset_ids(
                organization_id=page.publication.organization_id,
                asset_ids=page.page.get("media_asset_ids", []),
            )
        )


def _absolute_pagination(
    pagination: dict[str, Any] | None, origin: str
) -> dict[str, Any] | None:
    if pagination is None:
        return None
    return {
        **pagination,
        "previous_url": (
            f"{origin}{pagination['previous_path']}"
            if pagination["previous_path"]
            else None
        ),
        "next_url": (
            f"{origin}{pagination['next_path']}" if pagination["next_path"] else None
        ),
    }


def _navigation_links(snapshot: dict[str, Any], locale: str) -> list[dict[str, Any]]:
    """Menu entries resolved for one locale, in publication order.

    The visible text is the page's own translated title, so it cannot drift
    from the page. An entry whose page has no translation in this locale is skipped:
    linking to it would send the visitor to an address that does not exist in
    the language they are reading."""
    pages_by_id = {
        str(raw_page.get("page_id")): raw_page
        for raw_page in snapshot.get("pages", [])
        if isinstance(raw_page, dict)
    }
    links: list[dict[str, Any]] = []
    for entry in snapshot.get("navigation", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("collection_id") is not None:
            # A collection has one name in one language, so there is nothing to
            # resolve per locale and nothing that can be missing.
            links.append({
                "page_id": str(entry["collection_id"]),
                "parent_page_id": None,
                "title": str(entry.get("title", "")),
                "path": str(entry.get("path", "")),
            })
            continue
        raw_page = pages_by_id.get(str(entry.get("page_id")))
        if raw_page is None:
            continue
        localized = next(
            (
                candidate
                for candidate in raw_page.get("locales", [])
                if isinstance(candidate, dict) and candidate.get("locale") == locale
            ),
            None,
        )
        if localized is None:
            continue
        links.append({
            "page_id": str(entry.get("page_id")),
            "parent_page_id": entry.get("parent_page_id"),
            "title": localized["title"],
            "path": localized["path"],
        })
    return links


def _find_entry(
    *,
    organization_id: Any,
    site_id: Any,
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Resolves a published blog entry and shapes it like a page.

    Returning the page shape keeps one payload builder and one renderer for both
    surfaces — the reader should not be able to tell that an article is stored
    differently from a page.
    """
    wanted = _comparable_path(requested_path)
    entries = ContentEntry.all_objects.select_related("current_publication").filter(
        organization_id=organization_id,
        site_id=site_id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    )
    for entry in entries:
        publication = entry.current_publication
        if publication is None:
            continue
        snapshot = publication.snapshot
        if _comparable_path(str(snapshot.get("path", ""))) != wanted:
            continue
        locale_document = {
            "locale": snapshot["locale"],
            "translation_id": None,
            "version": snapshot.get("version", 1),
            "slug": snapshot["slug"],
            "path": snapshot["path"],
            "canonical_path": snapshot["path"],
            "title": snapshot["title"],
            "description": snapshot.get("excerpt", ""),
            "social_title": snapshot["title"],
            "social_description": snapshot.get("excerpt", ""),
            "fallback_fields": [],
        }
        siblings = _published_translations(
            organization_id=organization_id, entry=entry
        )
        return (
            {
                "page_id": snapshot["entry_id"],
                "key": snapshot["slug"],
                "blocks": snapshot["blocks"],
                "media_asset_ids": snapshot.get("media_asset_ids", []),
                "locales": [locale_document],
                # Only languages that are actually published: advertising a
                # translation still in draft points a search engine at a 404.
                "hreflang": siblings,
                "x_default": siblings.get(snapshot["locale"], snapshot["path"]),
                "noindex": bool(snapshot.get("noindex", False)),
                # What a reader and a search engine both want to know about an
                # article and never about a page: who wrote it and when.
                "article": {
                    "author_name": str(snapshot.get("author_name", "")),
                    "published_at": (
                        entry.published_at.isoformat()
                        if entry.published_at is not None
                        else None
                    ),
                    "updated_at": publication.created_at.isoformat(),
                    "tags": [
                        tag
                        for tag in snapshot.get("tags", [])
                        if isinstance(tag, dict) and tag.get("slug")
                    ],
                },
            },
            locale_document,
            publication,
        )
    raise PublicSiteNotFound


def published_entries(*, organization_id: Any, site_id: Any) -> list[dict[str, Any]]:
    """Every published entry of a site, newest first, as plain snapshot data.

    The feed, the sitemap and the blog index are the same projection read three
    ways (ADR-035 section 7), so they read it from one place rather than each
    growing its own idea of what is published.
    """
    rows = ContentEntry.all_objects.select_related("current_publication").filter(
        organization_id=organization_id,
        site_id=site_id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    )
    items: list[dict[str, Any]] = []
    for entry in rows:
        publication = entry.current_publication
        if publication is None:
            continue
        snapshot = publication.snapshot
        if bool(snapshot.get("noindex", False)):
            continue
        items.append({
            "collection_id": str(entry.collection_id),
            "translation_group": str(entry.translation_group),
            "title": str(snapshot["title"]),
            "path": str(snapshot["path"]),
            "locale": str(snapshot["locale"]),
            "excerpt": str(snapshot.get("excerpt", "")),
            "author_name": str(snapshot.get("author_name", "")),
            "tags": [
                tag
                for tag in snapshot.get("tags", [])
                if isinstance(tag, dict) and tag.get("slug")
            ],
            "published_at": entry.published_at,
            # When the article last changed, which is when its current
            # publication was created — not when the row was last touched, as
            # any edit to a draft would move that without changing what a
            # reader sees.
            "updated_at": publication.created_at,
        })
    # A missing timestamp sorts last rather than crashing the comparison: an
    # entry published before the column existed is still published.
    items.sort(
        key=lambda item: (item["published_at"] is not None, item["published_at"]),
        reverse=True,
    )
    return items


def one_per_article(
    entries: list[dict[str, Any]], preferred_locale: str
) -> list[dict[str, Any]]:
    """Collapses an article's language versions to the one worth listing.

    Listing both would show the reader the same article twice under two
    titles. The site's own language wins; a translation-only article still
    appears, because something published should never be invisible.
    """
    chosen: dict[str, dict[str, Any]] = {}
    for item in entries:
        group = item["translation_group"]
        current = chosen.get(group)
        if current is None or (
            current["locale"] != preferred_locale
            and item["locale"] == preferred_locale
        ):
            chosen[group] = item
    return [item for item in entries if chosen.get(item["translation_group"]) is item]


INDEX_EMPTY_TEXT = {
    "pl": "Nie ma jeszcze zadnego wpisu.",
    "en": "No entries yet.",
}


@dataclass(frozen=True, slots=True)
class _IndexPublication:
    """Stands in for a `Publication` on a page nobody published.

    The index has no snapshot of its own — it is recomputed on every request —
    but the payload builder and the renderer both expect a publication to name
    and to hash. The hash is derived from what the index actually shows, so a
    cache keyed on it still invalidates when an article appears.
    """

    collection: ContentCollection
    entries: list[dict[str, Any]]

    @property
    def id(self) -> Any:
        return self.collection.id

    @property
    def snapshot(self) -> dict[str, Any]:
        return {}

    @property
    def snapshot_hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(str(self.collection.id).encode())
        for item in self.entries:
            digest.update(item["path"].encode())
            digest.update(item["title"].encode())
        return digest.hexdigest()


def _find_collection_index(
    *,
    organization_id: Any,
    site_id: Any,
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """The blog's own address, built from what is published rather than edited.

    ADR-035 section 7 calls the index a reproducible projection: nobody
    maintains a page listing the articles, because such a page is wrong the
    moment an article is published and nobody remembers to update it.
    """
    wanted, requested_page = _split_index_page(requested_path)
    site_locale = (
        Site.all_objects.filter(pk=site_id, organization_id=organization_id)
        .values_list("default_locale", flat=True)
        .first()
        or settings.LANGUAGE_CODE.split("-")[0]
    )
    collection = next(
        (
            candidate
            for candidate in ContentCollection.all_objects.filter(
                organization_id=organization_id, site_id=site_id
            )
            if _comparable_path(
                collection_index_path(
                    default_locale=site_locale,
                    locale=site_locale,
                    base_path=candidate.base_path,
                )
            )
            == wanted
        ),
        None,
    )
    if collection is None:
        raise PublicSiteNotFound
    entries = one_per_article(
        [
            item
            for item in published_entries(
                organization_id=organization_id, site_id=site_id
            )
            if item["collection_id"] == str(collection.id)
        ],
        site_locale,
    )
    # An index with nothing on it is still the blog's address. Answering 404
    # would break the link in the menu until the first article lands.
    locale = site_locale
    first_path = collection_index_path(
        default_locale=site_locale, locale=locale, base_path=collection.base_path
    )
    page_size = settings.SITES_ENTRY_INDEX_PAGE_SIZE
    total_pages = max(1, -(-len(entries) // page_size))
    # A page past the end is not an empty page, it is a wrong address. Answering
    # 200 there would put an unbounded number of thin duplicates in the index.
    if requested_page > total_pages:
        raise PublicSiteNotFound
    window = entries[(requested_page - 1) * page_size : requested_page * page_size]
    path = first_path if requested_page == 1 else index_page_path(
        first_path, locale, requested_page
    )
    locale_document: dict[str, Any] = {
        "locale": locale,
        "translation_id": None,
        "version": 1,
        "slug": collection.base_path,
        "path": path,
        "canonical_path": path,
        "title": collection.name,
        "description": "",
        "social_title": collection.name,
        "social_description": "",
        "fallback_fields": [],
    }
    block = {
        "block_type": "core.entry_list",
        "schema_version": 1,
        "data": {
            "title": collection.name,
            "empty_text": INDEX_EMPTY_TEXT.get(locale, INDEX_EMPTY_TEXT["pl"]),
            "items": [_index_item(item) for item in window],
        },
    }
    return (
        {
            "page_id": str(collection.id),
            "key": collection.key,
            "blocks": [block],
            "media_asset_ids": [],
            "locales": [locale_document],
            "hreflang": {locale: path},
            "x_default": path,
            "noindex": False,
            # Each page is canonical to itself. Pointing every page at the
            # first would tell a search engine that page four does not exist,
            # and the articles reachable only from it would go with it.
            "pagination": {
                "page": requested_page,
                "pages": total_pages,
                "previous_path": (
                    None
                    if requested_page == 1
                    else (
                        first_path
                        if requested_page == 2
                        else index_page_path(first_path, locale, requested_page - 1)
                    )
                ),
                "next_path": (
                    None
                    if requested_page >= total_pages
                    else index_page_path(first_path, locale, requested_page + 1)
                ),
            },
        },
        locale_document,
        _IndexPublication(collection=collection, entries=window),
    )


#: One segment for every site, in both languages, because a tag address has to
#: survive being read aloud and retyped.
TAG_SEGMENT = "tag"

TAG_INDEX_TITLE = {"pl": "Wpisy oznaczone: {name}", "en": "Entries tagged: {name}"}

#: Below this many articles a subject archive is a thin duplicate of the
#: index rather than a topic page worth indexing on its own.
TAG_INDEX_THRESHOLD = 3


def tag_archive_path(*, index_path: str, slug: str) -> str:
    return f"{index_path}{TAG_SEGMENT}/{slug}/"


def _split_tag_archive(requested_path: str) -> tuple[str, str] | None:
    """Separates `/blog/tag/porady/` into the index address and the tag."""
    normalized = _comparable_path(requested_path)
    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 3 and parts[-2] == TAG_SEGMENT:
        return _comparable_path("/" + "/".join(parts[:-2]) + "/"), parts[-1]
    return None


#: The segment that carries the page number, in the reader's language. A Polish
#: blog emitting `/blog/page/2/` reads as a leak of the machinery.
INDEX_PAGE_SEGMENT = {"pl": "strona", "en": "page"}


def index_page_path(first_path: str, locale: str, page: int) -> str:
    segment = INDEX_PAGE_SEGMENT.get(locale, INDEX_PAGE_SEGMENT["pl"])
    return f"{first_path}{segment}/{page}/"


def _split_index_page(requested_path: str) -> tuple[str, int]:
    """Separates `/blog/strona/3/` into the index address and the page number.

    Both spellings are accepted whatever the site's language: a link written by
    hand in the other one should still land somewhere sensible.
    """
    normalized = _comparable_path(requested_path)
    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 3 and parts[-2] in set(INDEX_PAGE_SEGMENT.values()):
        try:
            page = int(parts[-1])
        except ValueError:
            return normalized, 1
        if page < 1:
            return normalized, 1
        # Comparable, like every other path in this module: the caller
        # matches it against a collection address, and "/blog" and "/blog/"
        # must not be two different answers.
        return _comparable_path("/" + "/".join(parts[:-2]) + "/"), page
    return normalized, 1


def _find_tag_archive(
    *,
    organization_id: Any,
    site_id: Any,
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Every published article on one subject, at one address.

    A projection like the collection index, and for the same reason: a page
    somebody maintains by hand is wrong from the first article they forget to
    add to it. An empty tag is a 404 rather than an empty page — unlike the
    blog's own address, nothing links to a subject nobody has written about.
    """
    # The page suffix comes off first, so an archive paginates exactly like the
    # collection index rather than growing into one enormous page again.
    without_page, requested_page = _split_index_page(requested_path)
    split = _split_tag_archive(without_page)
    if split is None:
        raise PublicSiteNotFound
    index_path, slug = split
    site_locale = (
        Site.all_objects.filter(pk=site_id, organization_id=organization_id)
        .values_list("default_locale", flat=True)
        .first()
        or settings.LANGUAGE_CODE.split("-")[0]
    )
    collection = next(
        (
            candidate
            for candidate in ContentCollection.all_objects.filter(
                organization_id=organization_id, site_id=site_id
            )
            if _comparable_path(
                collection_index_path(
                    default_locale=site_locale,
                    locale=site_locale,
                    base_path=candidate.base_path,
                )
            )
            == index_path
        ),
        None,
    )
    if collection is None:
        raise PublicSiteNotFound

    entries = one_per_article(
        [
            item
            for item in published_entries(
                organization_id=organization_id, site_id=site_id
            )
            if item["collection_id"] == str(collection.id)
            and any(tag.get("slug") == slug for tag in item["tags"])
        ],
        site_locale,
    )
    if not entries:
        raise PublicSiteNotFound
    page_size = settings.SITES_ENTRY_INDEX_PAGE_SIZE
    total_pages = max(1, -(-len(entries) // page_size))
    if requested_page > total_pages:
        raise PublicSiteNotFound
    window = entries[(requested_page - 1) * page_size : requested_page * page_size]

    name = next(
        (
            str(tag.get("name") or slug)
            for item in entries
            for tag in item["tags"]
            if tag.get("slug") == slug
        ),
        slug,
    )
    first_path = collection_index_path(
        default_locale=site_locale, locale=site_locale, base_path=collection.base_path
    )
    archive_path = tag_archive_path(index_path=first_path, slug=slug)
    path = (
        archive_path
        if requested_page == 1
        else index_page_path(archive_path, site_locale, requested_page)
    )
    title = TAG_INDEX_TITLE.get(site_locale, TAG_INDEX_TITLE["pl"]).format(name=name)
    locale_document: dict[str, Any] = {
        "locale": site_locale,
        "translation_id": None,
        "version": 1,
        "slug": slug,
        "path": path,
        "canonical_path": path,
        "title": title,
        "description": "",
        "social_title": title,
        "social_description": "",
        "fallback_fields": [],
    }
    block = {
        "block_type": "core.entry_list",
        "schema_version": 1,
        "data": {
            "title": title,
            "empty_text": INDEX_EMPTY_TEXT.get(site_locale, INDEX_EMPTY_TEXT["pl"]),
            "items": [_index_item(item) for item in window],
        },
    }
    return (
        {
            "page_id": str(collection.id),
            "key": f"{collection.key}-tag-{slug}",
            "blocks": [block],
            "media_asset_ids": [],
            "locales": [locale_document],
            "hreflang": {site_locale: path},
            "x_default": path,
            # A subject with one or two articles is a thin duplicate of the
            # index, not a topic page; below the threshold the archive still
            # serves readers but asks not to be indexed.
            "noindex": len(entries) < TAG_INDEX_THRESHOLD,
            "pagination": {
                "page": requested_page,
                "pages": total_pages,
                "previous_path": (
                    None
                    if requested_page == 1
                    else (
                        archive_path
                        if requested_page == 2
                        else index_page_path(
                            archive_path, site_locale, requested_page - 1
                        )
                    )
                ),
                "next_path": (
                    None
                    if requested_page >= total_pages
                    else index_page_path(archive_path, site_locale, requested_page + 1)
                ),
            },
        },
        locale_document,
        _IndexPublication(collection=collection, entries=window),
    )


def _index_item(item: dict[str, Any]) -> dict[str, Any]:
    listed: dict[str, Any] = {"title": item["title"], "path": item["path"]}
    if item["excerpt"]:
        listed["excerpt"] = item["excerpt"]
    if item["published_at"] is not None:
        listed["published_at"] = item["published_at"].isoformat()
    return listed


def _breadcrumbs(
    snapshot: dict[str, Any],
    *,
    locale: str,
    page_id: str,
    title: str,
    path: str,
) -> list[dict[str, Any]]:
    """The trail from the top of the menu down to this page.

    An article is not in the menu at all, and a page nobody put there is not
    either; both get a trail of just themselves rather than a broken one.
    """
    links = {link["page_id"]: link for link in _navigation_links(snapshot, locale)}
    here = links.get(page_id)
    if here is None:
        return [{"title": title, "path": path}]
    trail: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: dict[str, Any] | None = here
    while current is not None and current["page_id"] not in seen:
        seen.add(current["page_id"])
        trail.append({"title": current["title"], "path": current["path"]})
        parent_id = current.get("parent_page_id")
        current = links.get(str(parent_id)) if parent_id else None
    trail.reverse()
    return trail


class PublicSiteMoved(Exception):
    """The address moved. Carries where to, so the view can answer 308."""

    def __init__(self, location: str) -> None:
        super().__init__(location)
        self.location = location


def _redirect_target(*, publication: Any, requested_path: str) -> str | None:
    if publication is None:
        return None
    wanted = _comparable_path(requested_path)
    for entry in publication.snapshot.get("redirects", []):
        if not isinstance(entry, dict):
            continue
        if _comparable_path(str(entry.get("from_path", ""))) == wanted:
            return str(entry.get("to_path", "")) or None
    return None


def _published_translations(*, organization_id: Any, entry: ContentEntry) -> dict[str, str]:
    """Address per language for one article, published versions only.

    Each language is its own entry (they are different texts, written and
    published at different times), so the group is what makes them one article
    to a search engine.
    """
    addresses: dict[str, str] = {}
    for sibling in ContentEntry.all_objects.select_related("current_publication").filter(
        organization_id=organization_id,
        translation_group=entry.translation_group,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    ):
        publication = sibling.current_publication
        if publication is None:
            continue
        addresses[str(publication.snapshot["locale"])] = str(publication.snapshot["path"])
    return addresses


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError({"path": ["Ścieżka musi zaczynać się od /. "]})
    if "\\" in value or "\x00" in value or "?" in value or "#" in value or "//" in value:
        raise ValidationError({"path": ["Ścieżka zawiera niedozwolone znaki."]})
    if len(value) > 2048:
        raise ValidationError({"path": ["Ścieżka jest za długa."]})
    return value


def _comparable_path(value: str) -> str:
    """One spelling for `/start`, `/start/` and `//start//`, so a visitor's URL
    and the snapshot's stored path compare equal whichever way either ends."""
    return value.rstrip("/") or "/"


def _find_page(
    snapshot: dict[str, Any],
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wanted = _comparable_path(requested_path)
    pages = snapshot.get("pages", [])
    for raw_page in pages:
        if not isinstance(raw_page, dict):
            continue
        for raw_locale in raw_page.get("locales", []):
            if not isinstance(raw_locale, dict):
                continue
            # The snapshot stores trailing-slash paths ("/start/"), so the
            # stored value needs the same treatment as the request. Comparing a
            # trimmed request against an untrimmed candidate never matched, and
            # every page except the home page answered 404.
            if _comparable_path(str(raw_locale.get("path", ""))) == wanted:
                return raw_page, raw_locale
    if wanted == "/":
        return _home_page(snapshot, pages)
    raise PublicSiteNotFound


def _home_page(
    snapshot: dict[str, Any],
    pages: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    valid_pages = [page for page in pages if isinstance(page, dict)]
    page = next(
        (item for item in valid_pages if item.get("page_type") == "homepage"),
        valid_pages[0] if valid_pages else None,
    )
    if page is None:
        raise PublicSiteNotFound

    locales = [item for item in page.get("locales", []) if isinstance(item, dict)]
    default_locale = snapshot.get("default_locale")
    locale = next(
        (item for item in locales if item.get("locale") == default_locale),
        locales[0] if locales else None,
    )
    if locale is None or not locale.get("canonical_path"):
        raise PublicSiteNotFound
    return page, locale
