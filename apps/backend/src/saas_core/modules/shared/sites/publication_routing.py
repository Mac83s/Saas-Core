from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import (
    WORKING_ORGANIZATION_STATUSES,
    Organization,
)
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
    return serving_locales(organization_id) is not None


def serving_locales(organization_id: Any) -> frozenset[str] | None:
    """The company's languages this deployment serves, read together with
    whether it may be served at all (None: it may not). Read on every request:
    a language switched off is off at once (ADR-071 pkt 8)."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        organization = (
            Organization.objects.filter(
                pk=organization_id, status__in=WORKING_ORGANIZATION_STATUSES
            )
            .only("id", "public_locales")
            .first()
        )
    if organization is None:
        return None
    return frozenset(organization_content_locales(organization))


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
    organization_id: Any
    site_id: Any
    hostname: str
    canonical_hostname: str
    requested_path: str
    canonical_path: str
    locale: str
    publication: Publication
    page: dict[str, Any]
    #: The site's languages a visitor may read now: its source language and
    #: the company's (ADR-071 pkt 8). None: every language the snapshot has.
    available: frozenset[str] | None = None

    @property
    def redirect_url(self) -> str | None:
        # Exact, trailing slash included (ADR-071): the page was matched
        # either way, and the other spelling answers one 308 to the canonical
        # one. The renderer passes the visitor's path as typed, so this is
        # not the loop it was while Next stripped the slash first.
        if self.hostname == self.canonical_hostname:
            # Same host: only the path, so the visitor keeps the scheme and the
            # port they came on (a local stack is not on 443).
            return None if self.requested_path == self.canonical_path else self.canonical_path
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
        # The snapshot is read once per process (`visible_snapshot`), not with
        # every request for the site.
        .defer("site__current_publication__snapshot")
        .filter(hostname=hostname, status=DomainStatus.VERIFIED)
        .first()
    )
    locales = serving_locales(domain.organization_id) if domain is not None else None
    if domain is None or locales is None:
        raise PublicSiteNotFound
    available = locales | {domain.site.default_locale}
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
        page, locale_document = find_page(
            visible_snapshot(publication, available), normalized_path
        )
    except PublicSiteNotFound:
        # Not a page, so it may be a collection entry, or the collection's own
        # index. Entries publish on their own (ADR-035 §1) and are therefore
        # absent from the site snapshot; the entry's own publication then stands
        # in for the site's.
        try:
            page, locale_document, publication = _find_entry(
                organization_id=domain.organization_id,
                site_id=domain.site_id,
                default_locale=domain.site.default_locale,
                requested_path=normalized_path,
                available=available,
            )
        except PublicSiteNotFound:
            try:
                page, locale_document, publication = _find_collection_index(
                    organization_id=domain.organization_id,
                    site_id=domain.site_id,
                    requested_path=normalized_path,
                    available=available,
                )
            except PublicSiteNotFound:
                try:
                    # A subject's own archive, which is a projection like the
                    # index rather than a page anybody edits.
                    page, locale_document, publication = _find_tag_archive(
                        organization_id=domain.organization_id,
                        site_id=domain.site_id,
                        requested_path=normalized_path,
                        available=available,
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
                        available=available,
                    )
                # Nothing answers here any more, but something used to. A
                # visitor following an old link, and a search engine holding an
                # old address, both deserve better than a 404.
                found = _redirect_target(
                    publication=domain.site.current_publication,
                    requested_path=normalized_path,
                    available=available,
                )
                if found is None:
                    raise
                target, temporary = found
                raise PublicSiteMoved(
                    target
                    if hostname == canonical.hostname
                    else f"{settings.PUBLIC_SITE_SCHEME}://{canonical.hostname}{target}",
                    temporary=temporary,
                ) from None
    return _resolved(
        canonical=canonical,
        hostname=hostname,
        locale_document=locale_document,
        page=page,
        path=normalized_path,
        publication=publication,
        available=available,
    )


def _resolved(
    *,
    canonical: Any,
    hostname: str,
    locale_document: dict[str, Any],
    page: dict[str, Any],
    path: str,
    publication: Any,
    available: frozenset[str] | None = None,
) -> PublicPage:
    return PublicPage(
        organization_id=canonical.organization_id,
        site_id=canonical.site_id,
        hostname=hostname,
        canonical_hostname=canonical.hostname,
        requested_path=path,
        canonical_path=str(locale_document["canonical_path"]),
        locale=str(locale_document["locale"]),
        publication=publication,
        page={**page, "selected_locale": locale_document},
        available=available,
    )


def public_page_payload(page: PublicPage) -> dict[str, Any]:
    selected_locale = page.page["selected_locale"]
    publication_snapshot = (
        visible_snapshot(page.publication, page.available)
        if isinstance(page.publication, Publication)
        else page.publication.snapshot
    )
    blocks = selected_locale.get("blocks", page.page["blocks"])
    appearance = publication_snapshot.get("appearance")
    if (
        isinstance(page.publication, Publication)
        and page.locale != publication_snapshot.get("default_locale")
    ):
        links = _link_targets(publication_snapshot, page.locale)
        blocks, appearance = localized_links(blocks, links), localized_links(appearance, links)
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
        "appearance": appearance,
        # Only site pages carry one; entries, indexes and archives inherit.
        "page_presentation": page.page.get("page_presentation"),
        # The language's own body (ADR-070); the source language uses the
        # page's blocks.
        "blocks": blocks,
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
        # Pages that ask not to be indexed (thin tag archives, entries marked
        # by their author) say so in the document itself; a sitemap that
        # leaves them out is not enough for a crawler that arrives by link.
        "noindex": bool(page.page.get("noindex", False)),
    }


#: Block and appearance fields that hold a link (`ctaHref`: core.hero v1;
#: `privacy_href`: core.contact_form). `path` of core.entry_list names an
#: entry, which has its own language siblings, so it is not one of them.
LINK_FIELDS = frozenset({"href", "ctaHref", "privacy_href"})


def _link_targets(snapshot: dict[str, Any], locale: str) -> dict[str, str]:
    """Where a link to a page in the source language leads in `locale`: its
    live version there, keyed by the source address without its trailing
    slash. Old addresses of a page (`moved`) lead to the same place."""
    default_locale = snapshot.get("default_locale")
    targets: dict[str, str] = {}
    for page in snapshot.get("pages", []):
        documents = {
            item.get("locale"): item for item in page.get("locales", []) if isinstance(item, dict)
        }
        source, target = documents.get(default_locale), documents.get(locale)
        if source and target and source.get("path") and target.get("path"):
            targets[_comparable_path(str(source["path"]))] = str(target["path"])
    for old, new in snapshot.get("moved", {}).items():
        if _comparable_path(new) in targets:
            targets.setdefault(old, targets[_comparable_path(new)])
    return targets


def localized_links(value: Any, targets: dict[str, str]) -> Any:
    """`value` with every internal link to a page that is live in the reader's
    language pointing at that version (ADR-070 pkt 15). Everything else — the
    query and fragment, `rel` (ADR-061), links to pages without that language
    and to anything off the site — stays as written."""
    if isinstance(value, list):
        return [localized_links(item, targets) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                _localized_href(item, targets)
                if key in LINK_FIELDS and isinstance(item, str)
                else localized_links(item, targets)
            )
            for key, item in value.items()
        }
    return value


def _localized_href(href: str, targets: dict[str, str]) -> str:
    if not href.startswith("/") or href.startswith("//"):
        return href
    cut = min(
        (index for index in (href.find("?"), href.find("#")) if index >= 0), default=len(href)
    )
    target = targets.get(_comparable_path(href[:cut]))
    return href if target is None else target + href[cut:]


def _ai_media_ids(page: PublicPage) -> list[str]:
    """AI images on the page, read at render time (ADR-059 pkt 7).

    Provenance is not in the snapshot, so publications made before an asset
    was marked get the badge too. The operator switch hides the list; the XMP
    inside the files stays either way.
    """
    asset_ids = (
        page.page["selected_locale"].get("media_asset_ids")
        or page.page.get("media_asset_ids")
        or []
    )
    if not asset_ids or not badge_visible():
        return []
    # media_mediaasset forces RLS: the tenant the host named goes first.
    with transaction.atomic():
        set_local_organization_id(page.publication.organization_id)
        return sorted(
            ai_generated_asset_ids(
                organization_id=page.publication.organization_id,
                asset_ids=asset_ids,
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
    default_locale: str,
    requested_path: str,
    available: frozenset[str] | None = None,
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
        siblings = {
            locale: path
            for locale, path in _published_translations(
                organization_id=organization_id, entry=entry
            ).items()
            if available is None or locale in available
        }
        if available is not None and snapshot["locale"] not in available:
            # A language the company switched off: the article in the site's
            # language, when there is one, otherwise nothing (ADR-071 pkt 9).
            target = siblings.get(default_locale) or next(iter(siblings.values()), None)
            if target is None:
                raise PublicSiteNotFound
            raise PublicSiteMoved(target)
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
                # One x-default for the whole cluster: every sibling names the
                # same address — the site's language if that one is published,
                # otherwise the same first one — never each its own.
                "x_default": siblings.get(default_locale) or siblings[min(siblings)],
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


def published_entries(
    *, organization_id: Any, site_id: Any, available: frozenset[str] | None = None
) -> list[dict[str, Any]]:
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
        if available is not None and str(snapshot["locale"]) not in available:
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
    def organization_id(self) -> Any:
        return self.collection.organization_id

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
    available: frozenset[str] | None = None,
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
                organization_id=organization_id, site_id=site_id, available=available
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
    available: frozenset[str] | None = None,
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
                organization_id=organization_id, site_id=site_id, available=available
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
    """The address moved. Carries where to, so the view can answer 308 — or
    307 while a language version is withheld (ADR-070 pkt 10)."""

    def __init__(self, location: str, *, temporary: bool = False) -> None:
        super().__init__(location)
        self.location = location
        self.temporary = temporary


def _redirect_target(
    *, publication: Any, requested_path: str, available: frozenset[str] | None = None
) -> tuple[str, bool] | None:
    """Where an address answers now, and whether only for a while."""
    if publication is None:
        return None
    wanted = _comparable_path(requested_path)
    visible = visible_snapshot(publication, available)
    for entry in visible.get("redirects", []):
        if not isinstance(entry, dict):
            continue
        if _comparable_path(str(entry.get("from_path", ""))) == wanted:
            target = str(entry.get("to_path", ""))
            return (target, False) if target else None
    if wanted in visible["withheld"]:
        return visible["withheld"][wanted], True
    if wanted in visible["moved"]:
        return visible["moved"][wanted], False
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


def find_page(
    snapshot: dict[str, Any],
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wanted = _comparable_path(requested_path)
    for raw_page in snapshot.get("pages", []):
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
    raise PublicSiteNotFound


#: Snapshots are immutable, so what visitors get of one is worked out once per
#: process. Cleared rather than evicted one by one when full: simple, and a
#: worker serves far fewer live publications than this.
_VISIBLE_SNAPSHOTS: dict[Any, dict[str, Any]] = {}
# A site of 50 pages in 5 languages is about 2.3 MB of JSON (measured 02.10),
# so the bound is what one worker may hold, not how many sites exist.
_VISIBLE_SNAPSHOTS_LIMIT = 64


def visible_snapshot(
    publication: Publication, available: frozenset[str] | None = None
) -> dict[str, Any]:
    """A site publication as visitors get it (ADR-071, plan TL2).

    Two reading rules apply to every snapshot, old ones included, without
    rewriting it:

    - the home page answers at `/`, and at `/xx/` in another language; its
      slug address moves there with a 308;
    - a language version with no body of its own is not public. Snapshots
      before per-language bodies (ADR-070) carry one block list per page, so
      their other-language versions served the source text under another
      `lang`; they drop out of routing, hreflang, the menu and the sitemap,
      and their addresses move to the page in the source language.

    `moved` maps each such address, compared without its trailing slash, to
    where it now answers. A language version withheld after its source changed
    a fact (ADR-070 pkt 10) is out of routing, hreflang, the menu and the
    sitemap too, but answers from `withheld` — a 307 until it is refreshed. A
    language whose home page is not live (`live_locales`) is not public.
    """
    # By the languages too: the same publication reads differently once the
    # company switches one off, and at once (ADR-071 pkt 8, 9).
    key = (publication.id, tuple(sorted(available)) if available is not None else None)
    cached = _VISIBLE_SNAPSHOTS.get(key)
    if cached is None:
        if len(_VISIBLE_SNAPSHOTS) >= _VISIBLE_SNAPSHOTS_LIMIT:
            _VISIBLE_SNAPSHOTS.clear()
        cached = _visible(publication.snapshot, available)
        _VISIBLE_SNAPSHOTS[key] = cached
    return cached


def _visible(snapshot: dict[str, Any], available: frozenset[str] | None = None) -> dict[str, Any]:
    default_locale = snapshot.get("default_locale")
    pages = [page for page in snapshot.get("pages", []) if isinstance(page, dict)]
    # The page the root shows: the one marked as home, or the first.
    home = next((page for page in pages if page.get("page_type") == "homepage"), None)
    if home is None and pages:
        home = pages[0]
    live = snapshot.get("live_locales")
    moved: dict[str, str] = {}
    withheld: dict[str, str] = {}
    visible: list[dict[str, Any]] = []
    for page in pages:
        kept: list[dict[str, Any]] = []
        hidden: list[dict[str, Any]] = []
        paused: list[dict[str, Any]] = []
        for raw_locale in page.get("locales", []):
            if not isinstance(raw_locale, dict):
                continue
            locale = str(raw_locale.get("locale", ""))
            if locale != default_locale and (
                "blocks" not in raw_locale
                or (live is not None and locale not in live)
                # Switched off by the company: kept, answering 308 to the
                # source page until switched on again (ADR-071 pkt 9).
                or (available is not None and locale not in available)
            ):
                hidden.append(raw_locale)
                continue
            if locale != default_locale and raw_locale.get("withheld"):
                paused.append(raw_locale)
                continue
            if page is home:
                root = "/" if locale == default_locale else f"/{locale}/"
                old = str(raw_locale.get("path") or root)
                if _comparable_path(old) != _comparable_path(root):
                    moved[_comparable_path(old)] = root
                raw_locale = {**raw_locale, "path": root, "canonical_path": root}
            kept.append(raw_locale)
        source_path = next(
            (str(item["path"]) for item in kept if item.get("locale") == default_locale), None
        )
        if source_path is not None:
            for group, into in ((hidden, moved), (paused, withheld)):
                for raw_locale in group:
                    addresses = [raw_locale.get("path")]
                    if page is home:
                        addresses.append(f"/{raw_locale.get('locale')}/")
                    for address in addresses:
                        if address:
                            into.setdefault(_comparable_path(str(address)), source_path)
        hreflang = {str(item["locale"]): str(item["path"]) for item in kept if item.get("path")}
        visible.append({
            **page,
            "locales": kept,
            "hreflang": hreflang,
            "x_default": hreflang.get(str(default_locale), page.get("x_default")),
        })
    return {**snapshot, "pages": visible, "moved": moved, "withheld": withheld}
