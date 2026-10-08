"""What a visitor gets of categories and tags: their archives, an entry's
category links, and the one answer to an address that used to be right
(ADR-079 pkt 10, 13, 19; „Uzupełnienie CT2").

Everything a visitor learns here comes from entries' current publications:
which entries an archive lists, how many, and whether a term exists for a
visitor at all. A term no published entry carries has no archive, no link and
no name here. The tree and the names of terms that do are read as they are —
moving or renaming a category shows at once, like renaming a section.

`sites_contenttag` and `sites_contenttaxonomy` force row-level security; every
read of them goes through `site_vocabulary`, as the tenant the host named.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from django.conf import settings

from .localization import collection_index_path, section_segment
from .models import ContentCollection, ContentEntry, ContentEntryState
from .publication_routing import (
    INDEX_EMPTY_TEXT,
    TAG_INDEX_THRESHOLD,
    TAG_INDEX_TITLE,
    PublicSiteMoved,
    PublicSiteNotFound,
    _comparable_path,
    _find_index,
    _index_item,
    _IndexPublication,
    _pagination,
    _section_address,
    _site_texts,
    _split_index_page,
    _ui_text,
    entries_by_locale,
    index_page_path,
    published_entries,
    published_entry_path,
    tag_archive_path,
)
from .term_addresses import (
    TAG_SEGMENT,
    Taxonomy,
    Term,
    Vocabulary,
    pagination_segments,
    site_vocabulary,
    taxonomy_segment,
    term_archive_path,
    term_names,
    term_slug,
)

#: The title of a category's archive in the reader's language; English for
#: one not listed, like the rest of the site's own texts.
CATEGORY_INDEX_TITLE = {
    "pl": "Kategoria: {name}",
    "en": "Category: {name}",
    "de": "Kategorie: {name}",
    "es": "Categoría: {name}",
    "ru": "Категория: {name}",
}


def _carries(item: dict[str, Any], term: Term, ids: frozenset[str]) -> bool:
    """Whether a published entry is in a term's archive: a tag by its key,
    as snapshots always named it; a category by its id or that of a category
    under it now."""
    if term.taxonomy_id is None:
        return any(tag.get("slug") == term.slug for tag in item["tags"])
    return any(str(found.get("id")) in ids for found in item["terms"])


def _unknown_tag(slug: str) -> Term:
    """A subject some snapshot names that has no row: listed by its key and
    named as the snapshot names it, the way archives were read before terms."""
    return Term(
        id="",
        slug=slug,
        name="",
        taxonomy_id=None,
        parent_id=None,
        position=0,
        locale_slugs={},
        former_slugs=(),
    )


def find_term_archive(
    *,
    organization_id: Any,
    site: Any,
    requested_path: str,
    available: frozenset[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Every published entry of a content type under one tag or one category
    (with the categories under it), at one address per language.

    A projection like the type's index, and for the same reason: a page
    somebody maintains by hand is wrong from the first entry they forget to
    add to it. Answers only at the term's own address in the language of the
    type's index — any other spelling is for `moved_address`. A term nothing
    published carries is a 404 rather than an empty page: nothing links to
    it, and a visitor is told of nothing unpublished.
    """
    # The page suffix comes off first, so an archive paginates exactly like
    # the index rather than growing into one enormous page again.
    without_page, requested_page = _split_index_page(requested_path)
    parts = [part for part in _comparable_path(without_page).split("/") if part]
    if len(parts) < 3:
        raise PublicSiteNotFound
    segment, slug = parts[-2], parts[-1]
    collection, locale = _find_index(
        organization_id=organization_id,
        site=site,
        wanted=_comparable_path("/" + "/".join(parts[:-2]) + "/"),
        available=available,
    )
    default_locale = str(site.default_locale)
    vocabulary = site_vocabulary(organization_id=organization_id, site_id=site.id)
    taxonomy: Taxonomy | None = None
    if segment != TAG_SEGMENT:
        taxonomy = vocabulary.categories_of(collection.id)
        if taxonomy is None or segment != taxonomy_segment(
            taxonomy, default_locale=default_locale, locale=locale
        ):
            raise PublicSiteNotFound
    terms = vocabulary.of(taxonomy)
    term = next(
        (
            found
            for found in terms
            if term_slug(found, default_locale=default_locale, locale=locale) == slug
        ),
        None,
    )
    if term is None:
        if taxonomy is not None or any(slug in term_names(found) for found in terms):
            # Another spelling of a term's address, or no term's at all.
            raise PublicSiteNotFound
        term = _unknown_tag(slug)
    under = vocabulary.with_descendants(term) if taxonomy is not None else frozenset()
    grouped = {
        code: carrying
        for code, items in entries_by_locale(
            published_entries(
                organization_id=organization_id,
                site_id=site.id,
                available=available,
                collection_id=collection.id,
            ),
            str(collection.id),
        ).items()
        if (carrying := [item for item in items if _carries(item, term, under)])
    }
    entries = grouped.get(locale, [])
    if not entries:
        raise PublicSiteNotFound
    page_size = settings.SITES_ENTRY_INDEX_PAGE_SIZE
    total_pages = max(1, -(-len(entries) // page_size))
    if requested_page > total_pages:
        raise PublicSiteNotFound
    window = entries[(requested_page - 1) * page_size : requested_page * page_size]

    texts = _site_texts(site, locale, available)

    def named(found: Term) -> str:
        return str(texts.get(f"tag/{found.id}") or found.name) if found.id else ""

    name = named(term) or next(
        (
            str(tag.get("name") or slug)
            for item in entries
            for tag in item["tags"]
            if tag.get("slug") == slug
        ),
        slug,
    )

    def archive_of(found: Term, code: str) -> str:
        if not found.id:
            return tag_archive_path(
                index_path=collection_index_path(
                    collection, default_locale=default_locale, locale=code
                ),
                slug=slug,
            )
        return term_archive_path(
            collection, taxonomy, found, default_locale=default_locale, locale=code
        )

    archive_path = archive_of(term, locale)
    path = (
        archive_path
        if requested_page == 1
        else index_page_path(archive_path, locale, requested_page)
    )
    hreflang = (
        {code: archive_of(term, code) for code in sorted(grouped)}
        if requested_page == 1
        else {locale: path}
    )
    title = _ui_text(TAG_INDEX_TITLE if taxonomy is None else CATEGORY_INDEX_TITLE, locale).format(
        name=name
    )
    locale_document: dict[str, Any] = {
        "locale": locale,
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
            "main": True,
            "empty_text": _ui_text(INDEX_EMPTY_TEXT, locale),
            "items": [_index_item(item) for item in window],
        },
    }
    page: dict[str, Any] = {
        "page_id": str(collection.id),
        "key": (
            f"{collection.key}-tag-{slug}"
            if taxonomy is None
            else f"{collection.key}-category-{term.slug}"
        ),
        "blocks": [block],
        "media_asset_ids": [],
        "locales": [locale_document],
        "hreflang": hreflang,
        # One x-default for the cluster, as for an article: the site's
        # language where the subject has articles, else the same first one.
        "x_default": hreflang.get(default_locale) or hreflang[min(hreflang)],
        # A subject with one or two articles is a thin duplicate of the
        # index, not a topic page; below the threshold the archive still
        # serves readers but asks not to be indexed.
        "noindex": len(entries) < TAG_INDEX_THRESHOLD,
        "pagination": _pagination(archive_path, locale, requested_page, total_pages),
    }
    if taxonomy is not None:
        # The address is flat wherever the category hangs (ADR-079 pkt 3):
        # the trail is where a reader sees what it lies under.
        page["trail"] = [
            {
                "title": str(texts.get(f"collection/{collection.id}") or collection.name),
                "path": collection_index_path(
                    collection, default_locale=default_locale, locale=locale
                ),
            },
            *(
                {"title": named(above), "path": archive_of(above, locale)}
                for above in vocabulary.trail(term)[:-1]
            ),
            {"title": name, "path": path},
        ]
    return page, locale_document, _IndexPublication(collection=collection, entries=window)


def archive_locations(
    *,
    collection: ContentCollection,
    grouped: dict[str, list[dict[str, Any]]],
    languages: list[str],
    vocabulary: Vocabulary,
    default_locale: str,
) -> Iterator[tuple[dict[str, str], dict[str, list[dict[str, Any]]]]]:
    """A content type's archives worth indexing, for the sitemap: per term,
    the address in each language where it has enough entries, and the
    entries. Tags by key, then categories by key — below the threshold an
    archive serves readers but asks not to be indexed, so listing it, or
    naming it as another's version, would contradict the page itself."""
    firsts = {
        locale: collection_index_path(collection, default_locale=default_locale, locale=locale)
        for locale in languages
    }
    tags = {term.slug: term for term in vocabulary.of(None)}
    topics: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for locale in languages:
        for item in grouped.get(locale, []):
            for tag in item["tags"]:
                slug = str(tag.get("slug", ""))
                if slug:
                    topics.setdefault(slug, {}).setdefault(locale, []).append(item)
    for slug, by_locale in sorted(topics.items()):
        tag_term = tags.get(slug)
        yield (
            {
                locale: (
                    term_archive_path(
                        collection, None, tag_term, default_locale=default_locale, locale=locale
                    )
                    if tag_term is not None
                    else tag_archive_path(index_path=firsts[locale], slug=slug)
                )
                for locale, items in by_locale.items()
                if len(items) >= TAG_INDEX_THRESHOLD
            },
            by_locale,
        )
    taxonomy = vocabulary.categories_of(collection.id)
    if taxonomy is None:
        return
    for term in sorted(vocabulary.of(taxonomy), key=lambda found: found.slug):
        under = vocabulary.with_descendants(term)
        filed = {
            locale: carrying
            for locale in languages
            if (
                carrying := [
                    item for item in grouped.get(locale, []) if _carries(item, term, under)
                ]
            )
        }
        yield (
            {
                locale: term_archive_path(
                    collection, taxonomy, term, default_locale=default_locale, locale=locale
                )
                for locale, items in filed.items()
                if len(items) >= TAG_INDEX_THRESHOLD
            },
            filed,
        )


def entry_categories(
    *,
    organization_id: Any,
    site_id: Any,
    collection_id: Any,
    carried: list[dict[str, Any]],
    texts: dict[str, str],
    default_locale: str,
    locale: str,
) -> list[dict[str, str]]:
    """The categories a published entry is in, as links to their archives in
    the reader's language — from the entry's publication (`carried`: its
    snapshot's terms), named and addressed as the categories are now. A
    category removed since is not there."""
    wanted = [str(item.get("id")) for item in carried if item.get("taxonomy")]
    if not wanted:
        return []
    collection = ContentCollection.all_objects.filter(
        organization_id=organization_id, pk=collection_id, archived_at__isnull=True
    ).first()
    if collection is None:
        return []
    vocabulary = site_vocabulary(organization_id=organization_id, site_id=site_id)
    taxonomy = vocabulary.categories_of(collection.id)
    if taxonomy is None:
        return []
    terms = {term.id: term for term in vocabulary.of(taxonomy)}
    return [
        {
            "name": str(texts.get(f"tag/{term.id}") or term.name),
            "path": term_archive_path(
                collection, taxonomy, term, default_locale=default_locale, locale=locale
            ),
        }
        for term in (terms.get(term_id) for term_id in wanted)
        if term is not None
    ]


# -- the one 308 ---------------------------------------------------------------


def moved_address(
    *,
    organization_id: Any,
    site: Any,
    requested_path: str,
    available: frozenset[str] | None,
) -> str | None:
    """Where an address that no longer answers leads now, in one step
    (ADR-079 pkt 13): every part of it is read as what it is today.

    The address is taken apart — language, the content type's name, then
    nothing (its index), an entry's slug, or a taxonomy's segment and a
    term — and each part is replaced by today's: a former name of the type,
    a former segment of the taxonomy, a slug the entry had, a term's key,
    its address in another language or a former one. The parts are put back
    together under the type's name of today and the result is returned if it
    differs from what was asked and something answers there. So
    `/old-type/old-word/old-term/` is one hop, and a part that was never
    anybody's leads nowhere.

    A name the site's own language used to have counts for every language,
    because a language without a name of its own follows that one. Nothing
    leads into a switched-off type.
    """
    default_locale = str(site.default_locale)
    wanted = _comparable_path(requested_path)

    def answer(path: str) -> str | None:
        try:
            found = _section_address(
                organization_id=organization_id, site=site, path=path, available=available
            )
        except PublicSiteMoved as moved:
            # The language is switched off: straight to where its own
            # address leads, never through it.
            return moved.location
        except PublicSiteNotFound:
            return None
        return found

    # An article's own stored address — where it went out, in whatever shape
    # addresses had then — leads to where it answers now.
    for entry in ContentEntry.all_objects.select_related(
        "current_publication", "collection"
    ).filter(
        organization_id=organization_id,
        site_id=site.id,
        state=ContentEntryState.PUBLISHED,
        current_publication__snapshot__path__in=[wanted, f"{wanted}/"],
        collection__archived_at__isnull=True,
    ):
        assert entry.current_publication is not None
        target = answer(
            published_entry_path(entry, entry.current_publication.snapshot, default_locale)
        )
        if target is not None:
            return target

    parts = wanted.strip("/").split("/")
    locale = default_locale
    if len(parts) > 1 and len(parts[0]) == 2 and parts[0] != default_locale:
        locale, parts = parts[0], parts[1:]
    section, rest = parts[0], parts[1:]
    if not section:
        return None
    page: list[str] = []
    if len(rest) >= 2 and rest[-2] in pagination_segments() and rest[-1].isdigit():
        rest, page = rest[:-2], rest[-2:]
    if len(rest) > 2:
        return None
    vocabulary: Vocabulary | None = None
    for collection in ContentCollection.all_objects.filter(
        organization_id=organization_id, site_id=site.id, archived_at__isnull=True
    ):
        former_name = any(
            isinstance(item, dict)
            and item.get("path") == section
            and item.get("locale") in (locale, default_locale)
            for item in collection.former_paths or []
        )
        if not former_name and section != section_segment(
            collection, default_locale=default_locale, locale=locale
        ):
            continue
        today: list[str]
        if not rest:
            today = []
        elif len(rest) == 1:
            today = [_entry_slug(collection, locale, rest[0])]
        else:
            if vocabulary is None:
                vocabulary = site_vocabulary(organization_id=organization_id, site_id=site.id)
            found = _term_parts(
                vocabulary,
                collection,
                rest[0],
                rest[1],
                default_locale=default_locale,
                locale=locale,
            )
            if found is None:
                continue
            today = list(found)
        target = collection_index_path(
            collection, default_locale=default_locale, locale=locale
        ) + "".join(f"{part}/" for part in (*today, *page))
        if _comparable_path(target) == wanted:
            # Every part is today's already: it is not an old address, it is
            # one that answers nothing.
            continue
        canonical = answer(target)
        if canonical is not None:
            return canonical
    return None


def _entry_slug(collection: ContentCollection, locale: str, slug: str) -> str:
    """The slug the entry that once answered at `slug` is published under."""
    entry = (
        ContentEntry.all_objects.select_related("current_publication")
        .filter(
            organization_id=collection.organization_id,
            collection_id=collection.id,
            locale=locale,
            state=ContentEntryState.PUBLISHED,
            current_publication__isnull=False,
            former_slugs__contains=[slug],
        )
        .first()
    )
    if entry is None or entry.current_publication is None:
        return slug
    return str(entry.current_publication.snapshot.get("slug") or entry.slug)


def _term_parts(
    vocabulary: Vocabulary,
    collection: ContentCollection,
    segment: str,
    slug: str,
    *,
    default_locale: str,
    locale: str,
) -> tuple[str, str] | None:
    """Today's segment and address, in `locale`, of the archive a segment
    and a term's name once meant under a content type; None when the segment
    was never a taxonomy's there or the name never a term's."""
    taxonomy: Taxonomy | None
    if segment == TAG_SEGMENT:
        taxonomy = None
    else:
        taxonomy = vocabulary.categories_of(collection.id)
        if taxonomy is None:
            return None
        current = taxonomy_segment(taxonomy, default_locale=default_locale, locale=locale)
        former = any(
            item.get("segment") == segment and item.get("locale") in (locale, default_locale)
            for item in taxonomy.former_segments
        )
        if segment != current and not former:
            return None
    # One namespace per taxonomy: at most one term has this name.
    term = next((found for found in vocabulary.of(taxonomy) if slug in term_names(found)), None)
    if term is None:
        return None
    return (
        taxonomy_segment(taxonomy, default_locale=default_locale, locale=locale),
        term_slug(term, default_locale=default_locale, locale=locale),
    )


__all__ = [
    "CATEGORY_INDEX_TITLE",
    "archive_locations",
    "entry_categories",
    "find_term_archive",
    "moved_address",
]
