"""Where a category's or a tag's archive answers (ADR-079 pkt 5, 6, 11, 12).

The one place a term's address is put together, the way `localization` is for
a section's: the resolver matches against these functions and every surface
that prints an archive's address calls them. Nothing here writes, and nothing
here imports a service — the public router reads it as freely as the panel.

- A **term** is a `ContentTag` row. Its `slug` is its key: fixed, unique on the
  site, what a published snapshot names a tag by. Its address in a language is
  `locale_slugs[language]`, else the site's language's, else the key.
- The **site's tags** are the terms of no taxonomy; their segment is `tag` in
  every language. A content type's **categories** are the terms of its
  taxonomy row, whose segment is a word per language.
- A taxonomy's terms share **one namespace across languages**: a key, an
  address in any language and a former address of one term are never another
  term's. That is what lets any of them lead to the term in one 308.

Both tag tables and the taxonomy table force row-level security, and a
visitor's request has no tenant but the one its host named: `site_vocabulary`
reads them inside that tenant, into plain values, in one place.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from saas_core.content_protocol.transliteration import slug_from_title
from saas_core.modules.core.organizations.context import set_local_organization_id

from .localization import collection_index_path
from .models import (
    EVERY_LOCALE,
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    ContentTag,
    ContentTaxonomy,
)

#: The segment of a tag's archive in every language (the debt of ADR-071 pkt
#: 14 stays: paying it is a taxonomy row for tags and one 308).
TAG_SEGMENT = "tag"

#: The two kinds of vocabulary version 1 shows a company.
KIND_TAGS = "tags"
KIND_CATEGORIES = "categories"

#: The key of a content type's category taxonomy — what the read for a
#: product's pages calls it beside `tag`.
CATEGORY_TAXONOMY_KEY = "category"

#: What a category's archive is called in an address, per language of the
#: reader — written into the taxonomy's row when it is made and changed there
#: like a section's name. A language not listed follows the site's own.
CATEGORY_SEGMENTS: Mapping[str, str] = {
    "pl": "kategoria",
    "en": "category",
    "de": "kategorie",
    "es": "categoria",
    "ru": "kategoriya",
}

#: The taxonomy's own name, in the site's language where the table has it.
CATEGORY_TAXONOMY_NAMES: Mapping[str, str] = {
    "pl": "Kategorie",
    "en": "Categories",
    "de": "Kategorien",
    "es": "Categorías",
    "ru": "Категории",
}

#: How deep a type's categories nest, and how many terms of one taxonomy an
#: entry carries (ADR-079 pkt 4, 9). Named here and read from the API until a
#: company can set them (ADR-078).
CATEGORY_MAX_DEPTH = 3
ENTRY_TERMS_MAX = 10
TERM_SLUG_MAX = 80


def site_tags(*, organization_id: Any, site_id: Any) -> QuerySet[ContentTag]:
    """The site's tags — the terms of no taxonomy. Every read that means
    „tags" goes through here, so a category is never taken for one."""
    return ContentTag.all_objects.filter(
        organization_id=organization_id, site_id=site_id, taxonomy__isnull=True
    )


def term_slug(term: Any, *, default_locale: str, locale: str) -> str:
    """A term's address in a language: its own there, else the one in the
    site's language, else its key. A tag older than addresses per language
    has none of the first two and answers under its key everywhere."""
    slugs = term.locale_slugs or {}
    return str(slugs.get(locale) or slugs.get(default_locale) or term.slug)


def term_names(term: Any) -> frozenset[str]:
    """Everything that leads to the term in its taxonomy: its key, its
    address in each language and its former addresses."""
    return frozenset(
        str(slug)
        for slug in (term.slug, *(term.locale_slugs or {}).values(), *(term.former_slugs or ()))
        if slug
    )


def term_locked(term: Any, locale: str) -> bool:
    """Whether the term's address in a language is closed: it no longer
    follows the name, and changes only by a person's decision."""
    locks = term.slug_locked_at or {}
    return EVERY_LOCALE in locks or locale in locks


def taxonomy_segment(taxonomy: Any | None, *, default_locale: str, locale: str) -> str:
    """The segment of a taxonomy's archives in a language; `None` is the
    site's tags."""
    if taxonomy is None:
        return TAG_SEGMENT
    if locale == default_locale:
        return str(taxonomy.segment)
    return str((taxonomy.locale_segments or {}).get(locale) or taxonomy.segment)


def term_archive_path(
    collection: ContentCollection,
    taxonomy: Any | None,
    term: Any,
    *,
    default_locale: str,
    locale: str,
) -> str:
    """Where a term's archive under a content type answers in a language."""
    index = collection_index_path(collection, default_locale=default_locale, locale=locale)
    segment = taxonomy_segment(taxonomy, default_locale=default_locale, locale=locale)
    return f"{index}{segment}/{term_slug(term, default_locale=default_locale, locale=locale)}/"


def name_slug(name: str) -> str:
    """An address made from a name in any script the registry offers
    (ADR-070 pkt 18): by code, never typed and never by a model."""
    return slug_from_title(name, max_length=TERM_SLUG_MAX)


def pagination_segments() -> frozenset[str]:
    return frozenset(entry.pagination_segment for entry in settings.LOCALE_REGISTRY.values())


# -- the vocabulary as a visitor's request reads it ----------------------------


@dataclass(frozen=True, slots=True)
class Term:
    """A term as plain values: read once inside the tenant, used after."""

    id: str
    slug: str
    name: str
    taxonomy_id: str | None
    parent_id: str | None
    position: int
    locale_slugs: Mapping[str, str]
    former_slugs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Taxonomy:
    id: str
    key: str
    collection_id: str | None
    segment: str
    locale_segments: Mapping[str, str]
    former_segments: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """A site's taxonomies and terms, tags included."""

    taxonomies: tuple[Taxonomy, ...]
    terms: tuple[Term, ...]

    def of(self, taxonomy: Taxonomy | None) -> tuple[Term, ...]:
        """The terms of one taxonomy; `None`: the site's tags."""
        wanted = taxonomy.id if taxonomy is not None else None
        return tuple(term for term in self.terms if term.taxonomy_id == wanted)

    def categories_of(self, collection_id: Any) -> Taxonomy | None:
        return next(
            (item for item in self.taxonomies if item.collection_id == str(collection_id)), None
        )

    def by_id(self) -> dict[str, Term]:
        return {term.id: term for term in self.terms}

    def tree(self, taxonomy: Taxonomy) -> tuple[Term, ...]:
        """A taxonomy's terms, a category before those under it, each level
        in its own order."""
        terms = self.of(taxonomy)
        ids = {term.id for term in terms}
        ordered: list[Term] = []

        def walk(parent: str | None) -> None:
            for term in sorted(
                (
                    found
                    for found in terms
                    if (found.parent_id if found.parent_id in ids else None) == parent
                ),
                key=lambda found: (found.position, found.slug),
            ):
                ordered.append(term)
                walk(term.id)

        walk(None)
        return tuple(ordered)

    def with_descendants(self, term: Term) -> frozenset[str]:
        """The term and every category under it now — the tree is read as it
        is, so moving a category changes published archives at once."""
        found = {term.id}
        grew = True
        while grew:
            grew = False
            for other in self.terms:
                if other.parent_id in found and other.id not in found:
                    found.add(other.id)
                    grew = True
        return frozenset(found)

    def trail(self, term: Term) -> tuple[Term, ...]:
        """The categories above the term, the topmost first, then the term."""
        terms, chain, seen = self.by_id(), [term], {term.id}
        while chain[0].parent_id and chain[0].parent_id in terms:
            parent = terms[chain[0].parent_id]
            if parent.id in seen:
                break
            seen.add(parent.id)
            chain.insert(0, parent)
        return tuple(chain)


def site_vocabulary(*, organization_id: Any, site_id: Any) -> Vocabulary:
    """A site's whole vocabulary in two reads, as the tenant given — on a
    visitor's request, the one its host named. Both tables force row-level
    security: read anywhere else on the public path they answer with nothing,
    which a test database, connecting as the tables' owner, never shows."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        taxonomies = list(
            ContentTaxonomy.all_objects.filter(
                organization_id=organization_id, site_id=site_id
            ).values("id", "key", "collection_id", "segment", "locale_segments", "former_segments")
        )
        terms = list(
            ContentTag.all_objects.filter(organization_id=organization_id, site_id=site_id)
            .order_by("slug")
            .values(
                "id",
                "slug",
                "name",
                "taxonomy_id",
                "parent_id",
                "position",
                "locale_slugs",
                "former_slugs",
            )
        )
    return Vocabulary(
        taxonomies=tuple(
            Taxonomy(
                id=str(row["id"]),
                key=str(row["key"]),
                collection_id=str(row["collection_id"]) if row["collection_id"] else None,
                segment=str(row["segment"]),
                locale_segments=dict(row["locale_segments"] or {}),
                former_segments=tuple(
                    item for item in row["former_segments"] or [] if isinstance(item, dict)
                ),
            )
            for row in taxonomies
        ),
        terms=tuple(
            Term(
                id=str(row["id"]),
                slug=str(row["slug"]),
                name=str(row["name"]),
                taxonomy_id=str(row["taxonomy_id"]) if row["taxonomy_id"] else None,
                parent_id=str(row["parent_id"]) if row["parent_id"] else None,
                position=int(row["position"] or 0),
                locale_slugs=dict(row["locale_slugs"] or {}),
                former_slugs=tuple(str(slug) for slug in row["former_slugs"] or []),
            )
            for row in terms
        ),
    )


def carried_terms(*, organization_id: Any, site_id: Any) -> tuple[frozenset[str], frozenset[str]]:
    """The terms a visitor can meet — those an entry's current publication
    carries, of a type switched on or off — as (ids, keys of tags named by
    snapshots older than `terms`). Read from the snapshots, never from what
    an entry's draft is filed under (ADR-079 pkt 10)."""
    ids: set[str] = set()
    keys: set[str] = set()
    for tags, terms in ContentEntry.all_objects.filter(
        organization_id=organization_id,
        site_id=site_id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    ).values_list("current_publication__snapshot__tags", "current_publication__snapshot__terms"):
        if isinstance(terms, list):
            ids.update(str(item["id"]) for item in terms if isinstance(item, dict) and "id" in item)
        elif isinstance(tags, list):
            keys.update(
                str(item["slug"]) for item in tags if isinstance(item, dict) and item.get("slug")
            )
    return frozenset(ids), frozenset(keys)


# -- what a publication carries and closes -------------------------------------


def snapshot_terms(
    terms: Iterable[ContentTag],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """What an entry's publication says about its terms (ADR-079 pkt 8):
    `tags` in the shape it always had and for the site's tags only, and
    `terms` for every taxonomy, each named by its id."""
    ordered = sorted(terms, key=lambda term: term.slug)
    return (
        [{"slug": term.slug, "name": term.name} for term in ordered if term.taxonomy_id is None],
        [
            {
                "id": str(term.id),
                "taxonomy": str(term.taxonomy_id) if term.taxonomy_id else None,
                "key": term.slug,
                "name": term.name,
            }
            for term in ordered
        ],
    )


def terms_to_close(
    *, organization_id: Any, entry_id: Any
) -> tuple[list[ContentTag], list[ContentTag]]:
    """What an entry's publication carries, and those with every category
    above them — whose archives list the entry too, and so answer with it.
    Both from one read that locks the rows in the order every writer of
    terms takes them (by id; `taxonomies.lock_vocabulary`), so two
    publications sharing a term or a branch of the tree, or a publication and
    a change of the vocabulary, wait for each other, never on each other.
    `FOR NO KEY UPDATE`, so filing another entry under a term it holds does
    not wait."""
    carried = set(
        ContentTag.all_objects.filter(
            organization_id=organization_id, entry_links__entry_id=entry_id
        ).values_list("id", flat=True)
    )
    wanted, frontier = set(carried), set(carried)
    while frontier:
        frontier = {
            parent_id
            for parent_id in ContentTag.all_objects.filter(
                organization_id=organization_id, pk__in=frontier, parent__isnull=False
            ).values_list("parent_id", flat=True)
            if parent_id not in wanted
        }
        wanted |= frontier
    locked = list(
        ContentTag.all_objects.select_for_update(no_key=True)
        .filter(organization_id=organization_id, pk__in=wanted)
        .order_by("pk")
    )
    return [term for term in locked if term.pk in carried], locked


def close_term_addresses(terms: Iterable[ContentTag], *, default_locale: str, locale: str) -> None:
    """An entry in `locale` carrying these terms goes out: their addresses
    close (ADR-079 pkt 11). The site's language's always — it is also where
    the archive answers in a language that has no name for the term yet — and
    the entry's language's once that has an address of its own. Only stamps
    what is there: it computes nothing, takes no lock but the rows', and
    never refuses — it runs inside the publication, which a translation job
    settles its credits in."""
    moment = timezone.now().isoformat()
    for term in terms:
        locks = dict(term.slug_locked_at or {})
        if EVERY_LOCALE in locks:
            continue
        before = len(locks)
        locks.setdefault(default_locale, moment)
        if locale != default_locale and (term.locale_slugs or {}).get(locale):
            locks.setdefault(locale, moment)
        if len(locks) != before:
            term.slug_locked_at = locks
            ContentTag.all_objects.filter(pk=term.pk).update(slug_locked_at=locks)


__all__ = [
    "CATEGORY_MAX_DEPTH",
    "CATEGORY_SEGMENTS",
    "CATEGORY_TAXONOMY_KEY",
    "ENTRY_TERMS_MAX",
    "KIND_CATEGORIES",
    "KIND_TAGS",
    "TAG_SEGMENT",
    "Taxonomy",
    "Term",
    "Vocabulary",
    "carried_terms",
    "close_term_addresses",
    "name_slug",
    "site_tags",
    "site_vocabulary",
    "snapshot_terms",
    "taxonomy_segment",
    "term_archive_path",
    "term_locked",
    "term_names",
    "term_slug",
    "terms_to_close",
]
