"""Categories and tags as a company runs them (ADR-079 pkt 2–12, 14, 24;
„Uzupełnienie CT2").

A content type's **categories** are a tree up to three deep, its own; the
site's **tags** are flat and shared by every type, as they always were. Both
are `ContentTag` rows; where their archives answer is `term_addresses`.

What this module decides:

- **Names and addresses.** A term's name in the site's language is its row's;
  in another language it is a text of the site (`tag/<id>`), written here by a
  person or by the translation engine through the site-text source. The
  address is made by code from the name. It follows the name until the first
  entry carrying the term goes out (`close_term_addresses`) and is closed from
  then on: changing it takes a person, a reason and a preview, and the old
  address answers one 308. In another language the archive answers under the
  site's language's address until a name is accepted there; then it moves
  once (`settle_term_addresses`) and closes.
- **One namespace per taxonomy across languages.** Checked under the site's
  row lock, like a section's names. Code never takes another term's former
  address; a person may, having been told which redirect stops.
- **What a visitor sees comes from publications.** Which entries an archive
  lists, how many, and which terms exist for a visitor at all is read from
  entries' current publications; a term is removed only when no draft and no
  current publication carries it. The tree and the names are read as they
  are: moving or renaming a category shows at once, without a publication.

Every operation is a service with typed arguments, a preview where it decides
something a visitor sees, and an audit row; the views only validate shape.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol.provenance import ORIGIN_AI, ORIGIN_HUMAN, Provenance, unit_hash
from saas_core.content_protocol.units import unit_state
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .content_type_limit import ContentTypeArchived
from .language_versions import site_locales
from .localization import collection_index_path
from .models import (
    EVERY_LOCALE,
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentTag,
    ContentTaxonomy,
    PublicationReason,
    Site,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import SiteNotFound, _is_automation, assert_person_required, assert_within_grant
from .site_texts import (
    TERM_NAME_MAX,
    republish_site_texts,
    shown_texts,
    store_row,
    targets,
    term_text_key,
    term_unit,
    translation_rows,
)
from .term_addresses import (
    CATEGORY_MAX_DEPTH,
    CATEGORY_SEGMENTS,
    CATEGORY_TAXONOMY_KEY,
    CATEGORY_TAXONOMY_NAMES,
    ENTRY_TERMS_MAX,
    KIND_CATEGORIES,
    KIND_TAGS,
    TAG_SEGMENT,
    TERM_SLUG_MAX,
    carried_terms,
    close_term_addresses,
    name_slug,
    pagination_segments,
    site_tags,
    taxonomy_segment,
    term_archive_path,
    term_locked,
    term_names,
    term_slug,
)

logger = logging.getLogger(__name__)

TERM_CREATED = "sites.taxonomy_term.created"
TERM_UPDATED = "sites.taxonomy_term.updated"
TERM_NAMES_SET = "sites.taxonomy_term.names_set"
TERM_ADDRESS_CHANGED = "sites.taxonomy_term.address_changed"
TERM_DELETED = "sites.taxonomy_term.deleted"
TAXONOMY_SEGMENTS_SET = "sites.taxonomy.segments_set"
ENTRY_TAGS_SET = "sites.entry.tags_set"
ENTRY_TERMS_SET = "sites.entry.terms_set"

#: Making, renaming, moving and naming terms. A name and a place in the tree
#: show to visitors at once, with no publication and no preview an
#: integration or the assistant could hand a person — so until they have
#: their own way in (ADR-079, CT5) a person manages the vocabulary. Filing
#: an entry is not part of it: that follows the entry's own rule and shows
#: only with the entry's publication.
TERM_MANAGE_GATE = "Zmiana kategorii i tagów"
TERM_ADDRESS_GATE = "Zmiana adresu kategorii lub tagu"
TERM_DELETE_GATE = "Usunięcie kategorii lub tagu"
SEGMENTS_GATE = "Zmiana adresu kategorii w adresach strony"

TERM_KINDS = (KIND_CATEGORIES, KIND_TAGS)
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

TERM_NAME_INVALID = "term_name_invalid"
TERM_NAME_TAKEN = "term_name_taken"
TERM_KIND_INVALID = "term_kind_invalid"
TERM_PARENT_INVALID = "term_parent_invalid"
TERM_TOO_DEEP = "term_too_deep"
TERM_SLUG_INVALID = "term_slug_invalid"
TERM_SLUG_TAKEN = "term_slug_taken"
TERM_SLUG_FORMER = "term_slug_former"
TERM_LOCALE_INVALID = "locale_not_enabled"
TERM_NOT_OF_TYPE = "term_not_of_type"
REASON_REQUIRED = "redirect_reason_required"
SEGMENT_INVALID = "taxonomy_segment_invalid"
SEGMENT_RESERVED = "taxonomy_segment_reserved"
SEGMENT_SOURCE_LOCALE = "taxonomy_segment_source_locale"


class TermNotFound(NotFound):
    default_detail = "Nie ma takiej kategorii ani tagu."
    default_code = "taxonomy_term_not_found"


class TaxonomyNotFound(NotFound):
    default_detail = "Ten typ treści nie ma jeszcze kategorii."
    default_code = "taxonomy_not_found"


class TermInUse(APIException):
    status_code = 409
    default_detail = (
        "Wpisy są przypisane do tej pozycji. Najpierw zdejmij ją z wpisów — także z tych "
        "opublikowanych, publikując je ponownie."
    )
    default_code = "term_in_use"


class TooManyTags(APIException):
    status_code = 400
    default_detail = "Wpis może mieć najwyżej dziesięć tagów."
    default_code = "entry_too_many_tags"


class TooManyCategories(APIException):
    status_code = 400
    default_detail = "Wpis może mieć najwyżej dziesięć kategorii."
    default_code = "entry_too_many_categories"


class TagNameInvalid(APIException):
    status_code = 400
    default_detail = "Nazwa tagu nie może być pusta."
    default_code = "entry_tag_name_invalid"


def _error(field_name: str, message: str, code: str) -> ValidationError:
    return ValidationError({field_name: [ErrorDetail(message, code=code)]})


def tag_slug(name: str) -> str:
    """A tag's key, derived from its name rather than typed twice.

    Polish letters fold to their ASCII shapes: an address a person cannot read
    aloud over the phone is one they will not link to. Kept as it always was —
    every tag older than categories has a key made this way, and a name typed
    again has to find it.
    """
    folded = name.strip().lower()
    for source_char, target in (
        ("ą", "a"),
        ("ć", "c"),
        ("ę", "e"),
        ("ł", "l"),
        ("ń", "n"),
        ("ó", "o"),
        ("ś", "s"),
        ("ź", "z"),
        ("ż", "z"),
    ):
        folded = folded.replace(source_char, target)
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug[:TERM_SLUG_MAX]


# -- what the panel reads ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TermName:
    """A term's name in another language, as the site's texts hold it."""

    text: str
    #: `human`, `ai` or "" — who wrote it.
    origin: str
    #: `fresh`, `stale` (the name changed since), `unverified`, `missing`.
    state: str


@dataclass(frozen=True, slots=True)
class TermRow:
    """A category or a tag with what the list says about it."""

    term: ContentTag
    #: 1 for a tag and a top category, up to `CATEGORY_MAX_DEPTH`.
    depth: int
    #: Its name in each other language of the site that has one.
    names: dict[str, TermName]
    #: Its address and its archive's path under this type, per language.
    slugs: dict[str, str]
    paths: dict[str, str]
    #: The languages its address is closed in.
    locked: tuple[str, ...]
    #: Entries of this type filed under it, drafts included; for a tag, also
    #: those of the site's other types.
    entries: int
    entries_elsewhere: int
    #: Entries its archive under this type lists to visitors now, per
    #: language — for a category with those of the categories under it. From
    #: publications: a language absent here has no archive.
    published: dict[str, int]
    #: Whether nothing carries it, in a draft or a current publication.
    removable: bool


@dataclass(frozen=True, slots=True)
class TermList:
    """A type's categories, or the site's tags as that type shows them."""

    site: Site
    collection: ContentCollection
    kind: str
    #: None for tags, and for categories until the type's first one is made.
    taxonomy: ContentTaxonomy | None
    #: The site's languages, its own first.
    locales: tuple[str, ...]
    #: The word between the type's name and a term in an address, per language.
    segments: dict[str, str]
    #: In tree order: a category, then those under it, by position.
    terms: tuple[TermRow, ...]
    max_depth: int = CATEGORY_MAX_DEPTH
    max_per_entry: int = ENTRY_TERMS_MAX


@dataclass(frozen=True, slots=True)
class TermChange:
    """A change of a term: as done, or — in a preview — as it would be."""

    row: TermRow
    changed: bool
    #: Archives visitors can open today that the change moves, and where each
    #: leads from then on (one 308): [{"locale", "from_path", "to_path"}].
    moved: tuple[dict[str, str], ...] = ()
    #: Redirects of other terms that stop, because this term takes the
    #: address they started from: [{"slug", "term_id", "name"}].
    takes_over: tuple[dict[str, str], ...] = ()
    #: Published entries whose archives change at once, with no publication.
    published: int = 0


@dataclass(frozen=True, slots=True)
class TermRemoval:
    """Removing a term: as done, or — in a preview — whether it can be."""

    term: ContentTag
    removable: bool
    #: Entries filed under it in the panel, and entries whose current
    #: publication carries it. Either keeps the term.
    drafts: int
    published: int
    #: Categories under it, which move one level up.
    children: int
    removed: bool = False


@dataclass(frozen=True, slots=True)
class TaxonomySegments:
    """The word for „category" in a type's addresses, as it is or would be."""

    taxonomy: ContentTaxonomy
    segments: dict[str, str]
    moved: tuple[dict[str, str], ...] = ()
    changed: bool = False


@dataclass(frozen=True, slots=True)
class EntryTerms:
    tags: tuple[ContentTag, ...]
    categories: tuple[ContentTag, ...] = field(default=())


# -- finding rows --------------------------------------------------------------


def _site(context: Any, site_id: Any, *, lock: bool = False) -> Site:
    sites = Site.all_objects.select_related("organization").filter(
        pk=site_id, organization_id=context.organization_id
    )
    site = (sites.select_for_update(of=("self",)) if lock else sites).first()
    if site is None:
        raise SiteNotFound
    return site


def _type(
    context: Any, collection_id: Any, *, lock: bool = False
) -> tuple[Site, ContentCollection]:
    """The content type and its site — the site's row locked first when the
    vocabulary is about to change: one change at a time on a site, so two
    cannot each be free of the other's address and collide."""
    from .collections import CollectionNotFound

    collection = ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).first()
    if collection is None:
        raise CollectionNotFound
    site = _site(context, collection.site_id, lock=lock)
    collection.site = site
    return site, collection


def _kind(kind: str) -> str:
    if kind not in TERM_KINDS:
        raise _error("kind", "Rodzaj to „categories” albo „tags”.", TERM_KIND_INVALID)
    return kind


def _category_taxonomy(collection: ContentCollection) -> ContentTaxonomy | None:
    return ContentTaxonomy.all_objects.filter(
        organization_id=collection.organization_id,
        collection_id=collection.id,
        key=CATEGORY_TAXONOMY_KEY,
    ).first()


def _make_category_taxonomy(
    context: Any, site: Site, collection: ContentCollection
) -> ContentTaxonomy:
    """A type's categories begin with its first one: no switch to turn on.
    The segment is the reader's language's word from the table, for every
    language the table knows — a language the company adds later has its
    word already."""
    default = site.default_locale
    return ContentTaxonomy.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        collection=collection,
        key=CATEGORY_TAXONOMY_KEY,
        name=CATEGORY_TAXONOMY_NAMES.get(default, CATEGORY_TAXONOMY_NAMES["en"]),
        hierarchical=True,
        segment=CATEGORY_SEGMENTS.get(default, CATEGORY_SEGMENTS["en"]),
        locale_segments={
            code: word for code, word in sorted(CATEGORY_SEGMENTS.items()) if code != default
        },
        created_by_id=context.actor_id,
    )


def lock_vocabulary(site: Site) -> list[ContentTag]:
    """Every term of the site, locked in id order by one statement — the one
    way a change of the vocabulary takes term rows, whichever namespace it is
    about. A publication locks what it carries in the same order
    (`terms_to_close`), so the two wait for each other and never on each
    other; a namespace locked first and the rest later could meet a
    publication holding an older term of another namespace.

    `FOR NO KEY UPDATE`: a term's key never changes, and filing an entry —
    whose link only references the term — does not wait for either."""
    return list(
        ContentTag.all_objects.select_for_update(no_key=True)
        .filter(organization_id=site.organization_id, site_id=site.id)
        .order_by("pk")
    )


def _terms_of(
    site: Site, taxonomy: ContentTaxonomy | None, *, lock: bool = False
) -> list[ContentTag]:
    """The terms sharing one namespace: a taxonomy's, or the site's tags.
    `lock` takes the site's whole vocabulary (`lock_vocabulary`)."""
    if lock:
        own = taxonomy.pk if taxonomy is not None else None
        return sorted(
            (term for term in lock_vocabulary(site) if term.taxonomy_id == own),
            key=lambda term: (term.position, term.slug),
        )
    return list(
        ContentTag.all_objects.filter(
            organization_id=site.organization_id, site_id=site.id, taxonomy=taxonomy
        ).order_by("position", "slug")
    )


def _term(context: Any, term_id: Any) -> tuple[Site, ContentTag, list[ContentTag]]:
    """A term, its site locked, and the terms of its namespace locked."""
    found = ContentTag.all_objects.filter(
        pk=term_id, organization_id=context.organization_id
    ).first()
    if found is None:
        raise TermNotFound
    site = _site(context, found.site_id, lock=True)
    siblings = _terms_of(
        site,
        ContentTaxonomy.all_objects.filter(pk=found.taxonomy_id).first()
        if found.taxonomy_id
        else None,
        lock=True,
    )
    term = next((item for item in siblings if item.pk == found.pk), None)
    if term is None:
        raise TermNotFound
    return site, term, siblings


def _shown_under(
    context: Any, site: Site, term: ContentTag, collection_id: Any
) -> ContentCollection:
    """The content type a term is being worked on under: a category's own,
    or — a tag — any type of its site."""
    _site_row, collection = _type(context, collection_id)
    owner = _term_type(term)
    if collection.site_id != site.pk or (owner is not None and owner.pk != collection.pk):
        raise TermNotFound
    return collection


def _term_type(term: ContentTag) -> ContentCollection | None:
    """The content type a category belongs to; a tag belongs to none."""
    if term.taxonomy_id is None:
        return None
    taxonomy = ContentTaxonomy.all_objects.select_related("collection").get(pk=term.taxonomy_id)
    return taxonomy.collection


def _assert_may_write(context: Any, site: Site, collection: ContentCollection | None) -> None:
    """A key writes a type's categories with a grant for that type and the
    site's tags with one for the whole site; a switched-off type's
    categories take no work, like its entries."""
    assert_within_grant(
        context,
        site_id=site.id,
        collection_id=collection.id if collection is not None else None,
        writing=True,
    )
    if collection is not None and collection.archived_at is not None:
        raise ContentTypeArchived


# -- addresses -----------------------------------------------------------------


def _taken(siblings: Iterable[ContentTag], term: ContentTag | None) -> frozenset[str]:
    """Everything that leads to another term of the namespace."""
    own = term.pk if term is not None else None
    return frozenset(slug for other in siblings if other.pk != own for slug in term_names(other))


def _free(base: str, taken: frozenset[str] | set[str]) -> str:
    """`base`, or `base-2`, `base-3`… — the first nobody has."""
    slug, number = base, 2
    while slug in taken:
        suffix = f"-{number}"
        slug, number = f"{base[: TERM_SLUG_MAX - len(suffix)]}{suffix}", number + 1
    return slug


def _free_key(site: Site, base: str, namespace: frozenset[str] = frozenset()) -> str:
    """A term's key is unique on the whole site, tags and every type's
    categories together — the constraint snapshots rely on."""
    taken = set(
        ContentTag.all_objects.filter(
            organization_id=site.organization_id, site_id=site.id
        ).values_list("slug", flat=True)
    )
    return _free(base, taken | namespace)


def _clean_name(name: str) -> str:
    clean = " ".join(str(name or "").split())
    if not clean or len(clean) > TERM_NAME_MAX or not name_slug(clean):
        raise _error(
            "name",
            f"Nazwa ma od 1 do {TERM_NAME_MAX} znaków i przynajmniej jedną literę albo cyfrę.",
            TERM_NAME_INVALID,
        )
    return clean


def _source_address(
    term: ContentTag, name: str, siblings: Iterable[ContentTag], default_locale: str
) -> dict[str, str]:
    """`locale_slugs` with the site's language's address made from `name`.
    Left out when it is the key: a term answers under its key anyway."""
    slugs = {
        code: slug for code, slug in (term.locale_slugs or {}).items() if code != default_locale
    }
    address = _free(name_slug(name), _taken(siblings, term))
    if address != term.slug:
        slugs[default_locale] = address
    return slugs


def _published_with(term: ContentTag, under: Iterable[ContentTag] = ()) -> Q:
    """Entries' publications in the term's archive: those that carry it —
    by its id, and, a tag in a snapshot older than `terms`, by its key — or
    a category under it."""
    carries = Q(snapshot__terms__contains=[{"id": str(term.id)}])
    for below in under:
        carries |= Q(snapshot__terms__contains=[{"id": str(below.id)}])
    if term.taxonomy_id is None:
        carries |= Q(snapshot__terms__isnull=True, snapshot__tags__contains=[{"slug": term.slug}])
    return carries


def _archive_answered(
    site: Site, term: ContentTag, locale: str, under: Iterable[ContentTag] = ()
) -> bool:
    """Whether the term's archive in a language ever answered a visitor: any
    publication of an entry in that language carried it or a category now
    under it, current or not, of a type switched on or off. Asked when a
    decision must not strand an address a search engine may hold."""
    return ContentEntryPublication.all_objects.filter(
        _published_with(term, under),
        organization_id=site.organization_id,
        entry__site_id=site.id,
        snapshot__locale=locale,
    ).exists()


def _currently_published(site: Site, term: ContentTag) -> int:
    """Entries whose current publication carries the term — any language,
    `noindex` or not, of a type switched on or off: all of them come back to
    an archive without anybody publishing anything."""
    carries = Q(current_publication__snapshot__terms__contains=[{"id": str(term.id)}])
    if term.taxonomy_id is None:
        carries |= Q(
            current_publication__snapshot__terms__isnull=True,
            current_publication__snapshot__tags__contains=[{"slug": term.slug}],
        )
    return ContentEntry.all_objects.filter(
        carries,
        organization_id=site.organization_id,
        site_id=site.id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    ).count()


def _filed(site: Site, term: ContentTag) -> int:
    """Entries filed under the term in the panel — drafts, whatever their
    state, except those a person removed."""
    return (
        ContentEntryTag.all_objects.filter(organization_id=site.organization_id, tag_id=term.id)
        .exclude(entry__state=ContentEntryState.REMOVED)
        .count()
    )


def settle_term_addresses(site: Site, locale: str) -> None:
    """The site's texts in `locale` changed: every term whose address there
    is still open takes it from its accepted name (ADR-079 pkt 11).

    Open means not closed in that language. With a name, the address is made
    from it; where the archive in that language already answered — an entry
    went out before the name — it moves there once and closes at once, and
    the address it answered under keeps leading to it (it is the term's in
    the site's language, or its key). Without a name the term answers under
    the site's language's address again.

    Called under the site's row lock by whatever wrote the texts — a person,
    a translation job, a person accepting or undoing a job — and inside their
    transaction, where a job's credits are settled too: it takes the first
    free address instead of refusing one, and a failure here is logged and
    leaves the texts written."""
    if locale == site.default_locale:
        return
    try:
        with transaction.atomic():
            _settle(site, locale)
    except Exception:
        logger.exception("sites.term_addresses_not_settled site=%s locale=%s", site.id, locale)


def _settle(site: Site, locale: str) -> None:
    terms = lock_vocabulary(site)
    open_terms = [term for term in terms if not term_locked(term, locale)]
    if not open_terms:
        return
    units = [term_unit(term) for term in open_terms]
    accepted = shown_texts(units, translation_rows(site, locale))
    moment = timezone.now().isoformat()
    for term in open_terms:
        slugs = dict(term.locale_slugs or {})
        wanted = name_slug(accepted.get(term_text_key(term.id), ""))
        if not wanted:
            if slugs.pop(locale, None) is not None:
                term.locale_slugs = slugs
                term.save(update_fields=["locale_slugs", "updated_at"])
            continue
        siblings = [other for other in terms if other.taxonomy_id == term.taxonomy_id]
        address = _free(wanted, _taken(siblings, term))
        locks = dict(term.slug_locked_at or {})
        if _archive_answered(site, term, locale, _descendants(term, siblings)):
            locks[locale] = moment
        if slugs.get(locale) == address and locks == (term.slug_locked_at or {}):
            continue
        slugs[locale] = address
        term.locale_slugs, term.slug_locked_at = slugs, locks
        term.save(update_fields=["locale_slugs", "slug_locked_at", "updated_at"])


# -- reading -------------------------------------------------------------------


def _tree_order(terms: Sequence[ContentTag]) -> list[tuple[ContentTag, int]]:
    """Terms with their depth, a category before those under it."""
    children: dict[Any, list[ContentTag]] = {}
    ids = {term.pk for term in terms}
    for term in terms:
        parent = term.parent_id if term.parent_id in ids else None
        children.setdefault(parent, []).append(term)
    ordered: list[tuple[ContentTag, int]] = []

    def walk(parent: Any, depth: int) -> None:
        for term in sorted(children.get(parent, []), key=lambda item: (item.position, item.slug)):
            ordered.append((term, depth))
            walk(term.pk, depth + 1)

    walk(None, 1)
    return ordered


def _depth(term: ContentTag, by_id: Mapping[Any, ContentTag]) -> int:
    depth, current, seen = 1, term, {term.pk}
    while current.parent_id is not None and current.parent_id in by_id:
        current = by_id[current.parent_id]
        if current.pk in seen:
            break
        seen.add(current.pk)
        depth += 1
    return depth


def _descendants(term: ContentTag, terms: Sequence[ContentTag]) -> list[ContentTag]:
    found: dict[Any, ContentTag] = {}
    grew = True
    while grew:
        grew = False
        for other in terms:
            if other.pk not in found and (other.parent_id == term.pk or other.parent_id in found):
                found[other.pk] = other
                grew = True
    return list(found.values())


def _height(term: ContentTag, terms: Sequence[ContentTag]) -> int:
    """Levels under the term, itself included."""
    by_id = {item.pk: item for item in terms}
    return 1 + max(
        (_depth(item, by_id) - _depth(term, by_id) for item in _descendants(term, terms)),
        default=0,
    )


def _listed(site: Site, collection: ContentCollection) -> list[dict[str, Any]]:
    """What the type lists to visitors now — the projection its archives are
    read from, so the panel counts what a visitor gets."""
    from .publication_routing import published_entries

    return [
        item
        for item in published_entries(organization_id=site.organization_id, site_id=site.id)
        if item["collection_id"] == str(collection.id)
    ]


def _carriers(
    term: ContentTag, under: Iterable[ContentTag], listed: list[dict[str, Any]]
) -> dict[str, int]:
    """Listed entries per language that carry the term or a category under it."""
    ids = {str(term.pk), *(str(item.pk) for item in under)}
    counts: dict[str, int] = {}
    for item in listed:
        if term.taxonomy_id is None:
            carried = any(tag.get("slug") == term.slug for tag in item["tags"])
        else:
            carried = any(str(found.get("id")) in ids for found in item["terms"])
        if carried:
            counts[item["locale"]] = counts.get(item["locale"], 0) + 1
    return counts


def _names(
    site: Site, terms: Sequence[ContentTag], locales: Sequence[str]
) -> dict[Any, dict[str, TermName]]:
    names: dict[Any, dict[str, TermName]] = {term.pk: {} for term in terms}
    units = {term.pk: term_unit(term) for term in terms}
    for locale in locales:
        if locale == site.default_locale:
            continue
        found = targets(units.values(), translation_rows(site, locale))
        for term in terms:
            target = found.get(units[term.pk].key)
            if target is None or not target.text.strip():
                continue
            names[term.pk][locale] = TermName(
                text=target.text,
                origin=target.provenance.origin if target.provenance is not None else "",
                state=unit_state(units[term.pk], target).status,
            )
    return names


def _rows(
    site: Site,
    collection: ContentCollection,
    taxonomy: ContentTaxonomy | None,
    terms: Sequence[ContentTag],
) -> tuple[TermRow, ...]:
    locales = site_locales(site)
    default = site.default_locale
    listed = _listed(site, collection)
    names = _names(site, terms, locales)
    carried_ids, carried_keys = carried_terms(organization_id=site.organization_id, site_id=site.id)
    filed: dict[Any, list[Any]] = {}
    for tag_id, collection_id in (
        ContentEntryTag.all_objects.filter(
            organization_id=site.organization_id, tag_id__in=[term.pk for term in terms]
        )
        .exclude(entry__state=ContentEntryState.REMOVED)
        .values_list("tag_id", "entry__collection_id")
    ):
        filed.setdefault(tag_id, []).append(collection_id)
    rows = []
    for term, depth in _tree_order(terms):
        here = sum(1 for found in filed.get(term.pk, []) if found == collection.id)
        elsewhere = len(filed.get(term.pk, [])) - here
        rows.append(
            TermRow(
                term=term,
                depth=depth,
                names=names[term.pk],
                slugs={
                    code: term_slug(term, default_locale=default, locale=code) for code in locales
                },
                paths={
                    code: term_archive_path(
                        collection, taxonomy, term, default_locale=default, locale=code
                    )
                    for code in locales
                },
                locked=tuple(code for code in locales if term_locked(term, code)),
                entries=here,
                entries_elsewhere=elsewhere,
                published=_carriers(term, _descendants(term, terms), listed),
                removable=not filed.get(term.pk)
                and str(term.pk) not in carried_ids
                and not (term.taxonomy_id is None and term.slug in carried_keys),
            )
        )
    return tuple(rows)


def _row(site: Site, collection: ContentCollection, term: ContentTag) -> TermRow:
    taxonomy = (
        ContentTaxonomy.all_objects.filter(pk=term.taxonomy_id).first()
        if term.taxonomy_id
        else None
    )
    siblings = _terms_of(site, taxonomy)
    current = [term if item.pk == term.pk else item for item in siblings]
    if all(item.pk != term.pk for item in current):
        current.append(term)
    return next(row for row in _rows(site, collection, taxonomy, current) if row.term.pk == term.pk)


def _segments(site: Site, taxonomy: ContentTaxonomy | None) -> dict[str, str]:
    return {
        code: taxonomy_segment(taxonomy, default_locale=site.default_locale, locale=code)
        for code in site_locales(site)
    }


def list_terms(*, collection_id: UUID, kind: str) -> TermList:
    """A content type's categories as a tree (`kind="categories"`), or the
    site's tags as that type shows them (`kind="tags"`): each with its name
    per language, its archive's address under this type per language and
    whether it is closed, how many entries are filed under it, how many its
    archive lists to visitors per language, and whether it can be removed.
    Also the limits a caller needs: how deep categories nest and how many an
    entry takes."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    site, collection = _type(context, collection_id)
    kind = _kind(kind)
    assert_within_grant(context, site_id=site.id, collection_id=collection.id)
    taxonomy = _category_taxonomy(collection) if kind == KIND_CATEGORIES else None
    terms = [] if kind == KIND_CATEGORIES and taxonomy is None else _terms_of(site, taxonomy)
    segments = (
        _segments(site, taxonomy)
        if kind == KIND_TAGS or taxonomy is not None
        else {
            # What the word will be once the first category is made.
            code: CATEGORY_SEGMENTS.get(code)
            or CATEGORY_SEGMENTS.get(site.default_locale, CATEGORY_SEGMENTS["en"])
            for code in site_locales(site)
        }
    )
    return TermList(
        site=site,
        collection=collection,
        kind=kind,
        taxonomy=taxonomy,
        locales=site_locales(site),
        segments=segments,
        terms=_rows(site, collection, taxonomy, terms),
    )


# -- making and changing -------------------------------------------------------


def _parent_of(parent_id: Any, siblings: Sequence[ContentTag]) -> ContentTag | None:
    if parent_id is None:
        return None
    parent = next((item for item in siblings if str(item.pk) == str(parent_id)), None)
    if parent is None:
        raise _error(
            "parent_id", "Kategoria nadrzędna należy do innego typu treści.", TERM_PARENT_INVALID
        )
    return parent


def _assert_sibling_name_free(
    name: str, parent: ContentTag | None, siblings: Sequence[ContentTag], term: ContentTag | None
) -> None:
    wanted = name_slug(name)
    for other in siblings:
        if term is not None and other.pk == term.pk:
            continue
        if other.parent_id == (parent.pk if parent is not None else None) and (
            name_slug(other.name) == wanted
        ):
            raise _error("name", "Obok jest już pozycja o tej nazwie.", TERM_NAME_TAKEN)


def _find_named(name: str, tags: Sequence[ContentTag]) -> ContentTag | None:
    """The tag a typed name means (ADR-079 pkt 6): the one whose key or
    address in any language is the name's slug — „Wood” on an English entry
    finds `drewno` once that tag answers at `wood`. Both spellings of the
    slug are tried: keys older than categories fold Polish letters only."""
    spellings = {tag_slug(name), name_slug(name)} - {""}
    for tag in tags:
        if tag.slug in spellings:
            return tag
    for tag in tags:
        if spellings & set((tag.locale_slugs or {}).values()):
            return tag
    return None


def _new_term(
    context: Any,
    site: Site,
    taxonomy: ContentTaxonomy | None,
    name: str,
    siblings: Sequence[ContentTag],
    *,
    parent: ContentTag | None = None,
) -> ContentTag:
    natural = (tag_slug(name) if taxonomy is None else "") or name_slug(name)
    taken = _taken(siblings, None)
    term = ContentTag(
        organization_id=context.organization_id,
        site=site,
        taxonomy=taxonomy,
        parent=parent,
        # Free on the site and in its own vocabulary: a key always leads to
        # its term, so it is never what another term answers or answered at.
        slug=_free_key(site, natural, taken),
        name=name,
        slug_locked_at={},
        created_by_id=context.actor_id,
    )
    term.position = 1 + max(
        (other.position for other in siblings if other.parent_id == term.parent_id), default=-1
    )
    # A key with a number after it — another taxonomy has the natural one —
    # still answers under the name's own slug where that is free here.
    address = _free(natural, taken)
    term.locale_slugs = {site.default_locale: address} if address != term.slug else {}
    term.save()
    return term


@transaction.atomic
def create_term(
    *, collection_id: UUID, kind: str, name: str, parent_id: UUID | None = None
) -> tuple[TermRow, bool]:
    """Makes a category of a content type (`kind="categories"`, optionally
    under `parent_id`, up to three deep) or a tag of the site (`kind="tags"`).

    The first category of a type starts its categories; there is nothing to
    switch on. The address is made from the name and follows it until the
    first entry carrying the term is published. A name a category beside it
    already has is refused (`term_name_taken`) — sent again with the same
    parent it answers with the category it made, so a repeated request makes
    nothing twice; a tag's name that means an existing tag answers with that
    tag.

    A person's decision (`person_required` for an integration and the
    assistant). An integration still makes a tag by filing an entry under a
    name nobody has (`set_entry_tags`) — that tag meets no visitor before a
    publication carries it."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_MANAGE_GATE)
    site, collection = _type(context, collection_id, lock=True)
    kind = _kind(kind)
    _assert_may_write(context, site, collection if kind == KIND_CATEGORIES else None)
    clean = _clean_name(name)
    if kind == KIND_TAGS:
        if parent_id is not None:
            raise _error("parent_id", "Tagi nie mają tagów nadrzędnych.", TERM_PARENT_INVALID)
        tags = _terms_of(site, None, lock=True)
        existing = _find_named(clean, tags)
        if existing is not None:
            return _row(site, collection, existing), False
        term = _new_term(context, site, None, clean, tags)
    else:
        taxonomy = _category_taxonomy(collection) or _make_category_taxonomy(
            context, site, collection
        )
        siblings = _terms_of(site, taxonomy, lock=True)
        parent = _parent_of(parent_id, siblings)
        by_id = {item.pk: item for item in siblings}
        if parent is not None and _depth(parent, by_id) >= CATEGORY_MAX_DEPTH:
            raise _error(
                "parent_id",
                f"Kategorie mają najwyżej {CATEGORY_MAX_DEPTH} poziomy.",
                TERM_TOO_DEEP,
            )
        same = next(
            (
                other
                for other in siblings
                if other.parent_id == (parent.pk if parent is not None else None)
                and other.name == clean
            ),
            None,
        )
        if same is not None:
            return _row(site, collection, same), False
        _assert_sibling_name_free(clean, parent, siblings, None)
        term = _new_term(context, site, taxonomy, clean, siblings, parent=parent)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TERM_CREATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_tag",
        target_id=term.id,
        metadata={
            "kind": kind,
            "key": term.slug,
            "name": term.name,
            "collection_id": str(collection.id) if kind == KIND_CATEGORIES else None,
            "parent_id": str(term.parent_id) if term.parent_id else None,
        },
    )
    return _row(site, collection, term), True


_UNSET: Any = object()


@transaction.atomic
def update_term(
    *,
    term_id: UUID,
    collection_id: UUID,
    name: str | None = None,
    parent_id: Any = _UNSET,
    position: int | None = None,
    dry_run: bool = False,
) -> TermChange:
    """Renames a category or a tag, moves a category under another
    (`parent_id`; null: to the top) and puts it at `position` among those
    beside it. What is left out stays.

    All of it shows to visitors at once, with no publication: the new name on
    every archive and entry that names the term, and — after a move — the
    category's published entries in the archives of the categories now above
    it instead of those it left. Addresses do not move with any of this: a
    category's archive is `/<type>/<category word>/<category>/` wherever it
    hangs, and a name changes the address only while no entry carrying the
    term has been published.

    Because it shows at once, it is a person's decision (`person_required`
    for an integration and the assistant, the preview too).

    `collection_id` is the content type the answer's addresses are for.
    `dry_run` answers with the term as it would be and `published` — how many
    published entries are under it — and writes nothing."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_MANAGE_GATE)
    site, term, siblings = _term(context, term_id)
    collection = _shown_under(context, site, term, collection_id)
    _assert_may_write(context, site, _term_type(term))

    def place() -> int:
        beside_now = sorted(
            (other for other in siblings if other.parent_id == term.parent_id),
            key=lambda item: (item.position, item.slug),
        )
        return next(index for index, item in enumerate(beside_now) if item.pk == term.pk)

    before = {
        "name": term.name,
        "parent_id": str(term.parent_id) if term.parent_id else None,
        "position": place(),
    }
    by_id = {item.pk: item for item in siblings}
    renamed = False
    if name is not None:
        clean = _clean_name(name)
        if clean != term.name:
            above = by_id.get(term.parent_id) if term.parent_id is not None else None
            _assert_sibling_name_free(clean, above, siblings, term)
            term.name, renamed = clean, True
            if not term_locked(term, site.default_locale):
                term.locale_slugs = _source_address(term, clean, siblings, site.default_locale)
    if parent_id is not _UNSET:
        if term.taxonomy_id is None and parent_id is not None:
            raise _error("parent_id", "Tagi nie mają tagów nadrzędnych.", TERM_PARENT_INVALID)
        parent = _parent_of(parent_id, siblings)
        if parent is not None and (
            parent.pk == term.pk or parent.pk in {item.pk for item in _descendants(term, siblings)}
        ):
            raise _error(
                "parent_id", "Kategoria nie może leżeć pod sobą samą.", TERM_PARENT_INVALID
            )
        if (parent.pk if parent is not None else None) != term.parent_id:
            depth = (_depth(parent, by_id) if parent is not None else 0) + _height(term, siblings)
            if depth > CATEGORY_MAX_DEPTH:
                raise _error(
                    "parent_id",
                    f"Kategorie mają najwyżej {CATEGORY_MAX_DEPTH} poziomy.",
                    TERM_TOO_DEEP,
                )
            _assert_sibling_name_free(term.name, parent, siblings, term)
            term.parent = parent
            term.position = 1 + max(
                (
                    other.position
                    for other in siblings
                    if other.pk != term.pk and other.parent_id == term.parent_id
                ),
                default=-1,
            )
    beside = sorted(
        (other for other in siblings if other.pk != term.pk and other.parent_id == term.parent_id),
        key=lambda item: (item.position, item.slug),
    )
    if position is not None:
        beside.insert(max(0, min(position, len(beside))), term)
    else:
        beside = sorted([*beside, term], key=lambda item: (item.position, item.slug))
    order = {item.pk: index for index, item in enumerate(beside)}
    after = {
        "name": term.name,
        "parent_id": str(term.parent_id) if term.parent_id else None,
        "position": order[term.pk],
    }
    changed = before != after
    published = sum(
        _carriers(term, _descendants(term, siblings), _listed(site, collection)).values()
    )
    term.position = order[term.pk]
    if dry_run or not changed:
        return TermChange(row=_row(site, collection, term), changed=changed, published=published)
    for other in beside:
        if other.pk != term.pk and other.position != order[other.pk]:
            ContentTag.all_objects.filter(pk=other.pk).update(position=order[other.pk])
    term.save(update_fields=["name", "parent", "position", "locale_slugs", "updated_at"])
    if after["parent_id"] != before["parent_id"]:
        # The categories now above it list its published entries from this
        # moment: their archives answer, so their addresses close — as at a
        # publication, in each language those entries are in.
        ancestors: list[ContentTag] = []
        current = by_id.get(term.parent_id) if term.parent_id is not None else None
        while current is not None and all(current.pk != item.pk for item in ancestors):
            ancestors.append(current)
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
        for locale in _carriers(term, _descendants(term, siblings), _listed(site, collection)):
            close_term_addresses(ancestors, default_locale=site.default_locale, locale=locale)
    if renamed:
        # A machine's translation of the old name is no name any more; an
        # address made from it and still open goes with it.
        for locale in site_locales(site):
            settle_term_addresses(site, locale)
        term.refresh_from_db()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TERM_UPDATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_tag",
        target_id=term.id,
        metadata={"from": before, "to": after},
    )
    return TermChange(row=_row(site, collection, term), changed=True, published=published)


@transaction.atomic
def set_term_names(*, term_id: UUID, collection_id: UUID, names: Mapping[str, str]) -> TermChange:
    """A person's names of a category or a tag in the site's other languages,
    by language code; an empty one removes the name there. Sent for the
    languages that change only.

    A name is a text of the site: the translation engine never overwrites it
    and offers the term's name only in languages still without one. Where the
    term's address in that language is still open it is made from the name;
    if the archive there already answered under the site's language's
    address, it moves once and closes (`moved` says from where to where), and
    the old address answers one 308. The names are published at once when the
    caller may publish; otherwise they go out with the site's next
    publication. A person's decision (`person_required` for an integration
    and the assistant): an address made from a name answers at once. The
    translation engine names terms its own way, through the site's texts."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_MANAGE_GATE)
    site, term, _siblings = _term(context, term_id)
    collection = _shown_under(context, site, term, collection_id)
    _assert_may_write(context, site, _term_type(term))
    allowed = [code for code in site_locales(site) if code != site.default_locale]
    cleaned: dict[str, str] = {}
    for locale, raw in names.items():
        if locale not in allowed:
            raise ValidationError({
                "names": {
                    locale: [ErrorDetail("Strona nie ma tego języka.", code=TERM_LOCALE_INVALID)]
                }
            })
        text = " ".join(str(raw or "").split())
        if len(text) > TERM_NAME_MAX or (text and not name_slug(text)):
            raise ValidationError({
                "names": {
                    locale: [
                        ErrorDetail(
                            f"Nazwa ma najwyżej {TERM_NAME_MAX} znaków i przynajmniej jedną "
                            "literę albo cyfrę.",
                            code=TERM_NAME_INVALID,
                        )
                    ]
                }
            })
        cleaned[locale] = text
    before = _row(site, collection, term)
    unit = term_unit(term)
    origin = ORIGIN_AI if context.acting_via else ORIGIN_HUMAN
    at = timezone.now().isoformat()
    for locale, text in cleaned.items():
        row = store_row(site, locale, unit)
        row.text = text
        row.provenance = (
            Provenance(
                origin=origin,
                source_hash=unit.source_hash,
                written_hash=unit_hash(unit.kind, text),
                model="",
                at=at,
            ).as_dict()
            if text
            else None
        )
        row.origin_ref = context.acting_ref or ""
        row.save()
        settle_term_addresses(site, locale)
    term.refresh_from_db()
    may_publish = (
        not _is_automation(context)
        and not context.acting_via
        and context.has_permission(SITE_PUBLISH)
        and site.current_publication_id is not None
    )
    if may_publish:
        for locale in cleaned:
            republish_site_texts(
                context,
                Site.all_objects.select_related("current_publication", "organization").get(
                    pk=site.pk
                ),
                locale,
                reason=PublicationReason.LOCALE_PUBLISH,
                idempotency_key=f"term-names:{term.id}:{at}",
                keys={unit.key},
            )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TERM_NAMES_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_tag",
        target_id=term.id,
        metadata={"locales": sorted(cleaned)},
    )
    after = _row(site, collection, term)
    moved = tuple(
        {"locale": locale, "from_path": before.paths[locale], "to_path": after.paths[locale]}
        for locale in after.paths
        if before.paths[locale] != after.paths[locale]
        and _archive_answered(site, term, locale, _descendants(term, _siblings))
    )
    return TermChange(row=after, changed=True, moved=moved)


@transaction.atomic
def change_term_address(
    *,
    term_id: UUID,
    collection_id: UUID,
    locale: str,
    slug: str,
    reason: str = "",
    take_over_former: bool = False,
    dry_run: bool = False,
) -> TermChange:
    """Gives a category's or a tag's archive another address in one language
    (`slug`: lower-case Latin letters, digits and single hyphens). In the
    site's own language it also moves every language that has no address of
    its own.

    A person's decision, like moving a page's address: an archive visitors
    could open — `moved` lists each, from where to where — costs what it
    earned, so it takes a stated `reason`; the old address answers one 308
    from the moment this is saved and nothing is republished. The address is
    closed afterwards: the name no longer changes it.

    An address another term of the same vocabulary has is refused
    (`term_slug_taken`). One that only redirects to another term today can be
    taken: the preview's `takes_over` names the redirect that stops, and
    saving needs `take_over_former` (`term_slug_former` without it).

    `collection_id` is the content type the answer's addresses are for.
    `dry_run` validates and answers with what would move, and writes nothing."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_ADDRESS_GATE)
    site, term, siblings = _term(context, term_id)
    collection = _shown_under(context, site, term, collection_id)
    _assert_may_write(context, site, _term_type(term))
    locales = site_locales(site)
    if locale not in locales:
        raise _error("locale", "Strona nie ma tego języka.", TERM_LOCALE_INVALID)
    wanted = str(slug or "").strip().lower()
    if not SLUG_PATTERN.fullmatch(wanted) or len(wanted) > TERM_SLUG_MAX:
        raise _error(
            "slug",
            "Adres to małe litery łacińskie, cyfry i pojedyncze łączniki.",
            TERM_SLUG_INVALID,
        )
    takes_over: list[dict[str, str]] = []
    for other in siblings:
        if other.pk == term.pk:
            continue
        if wanted == other.slug or wanted in (other.locale_slugs or {}).values():
            raise _error("slug", f"Ten adres ma już „{other.name}”.", TERM_SLUG_TAKEN)
        if wanted in (other.former_slugs or []):
            takes_over.append({"slug": wanted, "term_id": str(other.pk), "name": other.name})
    before = _row(site, collection, term)
    old_slugs = dict(term.locale_slugs or {})
    slugs = dict(old_slugs)
    slugs[locale] = wanted
    term.locale_slugs = slugs
    after_paths = {
        code: term_archive_path(
            collection,
            ContentTaxonomy.all_objects.filter(pk=term.taxonomy_id).first()
            if term.taxonomy_id
            else None,
            term,
            default_locale=site.default_locale,
            locale=code,
        )
        for code in locales
    }
    changed_locales = [code for code in locales if before.paths[code] != after_paths[code]]
    moved = tuple(
        {"locale": code, "from_path": before.paths[code], "to_path": after_paths[code]}
        for code in changed_locales
        if _archive_answered(site, term, code, _descendants(term, siblings))
    )
    changed = bool(changed_locales) or old_slugs != slugs
    if dry_run or not changed:
        result_row = _row(site, collection, term)
        return TermChange(
            row=result_row, changed=changed, moved=moved, takes_over=tuple(takes_over)
        )
    if takes_over and not take_over_former:
        raise _error(
            "slug",
            f"Ten adres przekierowuje dziś do „{takes_over[0]['name']}”. Potwierdź, że to "
            "przekierowanie ma przestać działać.",
            TERM_SLUG_FORMER,
        )
    normalized_reason = reason.strip()
    if moved and not normalized_reason:
        raise _error("reason", "Zmiana adresu wymaga uzasadnienia.", REASON_REQUIRED)
    # Old addresses answer with one move to today's; one taken back is the
    # term's again, not a former one.
    current = {term.slug, *slugs.values()}
    former = [
        *(term.former_slugs or []),
        *(before.slugs[item["locale"]] for item in moved),
    ]
    term.former_slugs = [
        item
        for index, item in enumerate(former)
        if item not in former[:index] and item not in current
    ]
    locks = dict(term.slug_locked_at or {})
    if EVERY_LOCALE not in locks:
        locks.setdefault(locale, timezone.now().isoformat())
        term.slug_locked_at = locks
    term.save(update_fields=["locale_slugs", "former_slugs", "slug_locked_at", "updated_at"])
    for taken in takes_over:
        other = next(item for item in siblings if str(item.pk) == taken["term_id"])
        other.former_slugs = [item for item in other.former_slugs or [] if item != wanted]
        other.save(update_fields=["former_slugs", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TERM_ADDRESS_CHANGED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_tag",
        target_id=term.id,
        metadata={
            "locale": locale,
            "from": before.slugs,
            "to": {
                code: term_slug(term, default_locale=site.default_locale, locale=code)
                for code in locales
            },
            "moved": list(moved),
            "takes_over": takes_over,
            "reason": normalized_reason,
        },
    )
    return TermChange(
        row=_row(site, collection, term), changed=True, moved=moved, takes_over=tuple(takes_over)
    )


@transaction.atomic
def delete_term(*, term_id: UUID, collection_id: UUID, dry_run: bool = False) -> TermRemoval:
    """Removes a category or a tag that nothing carries: no entry is filed
    under it in the panel (`drafts`) and no entry's current publication
    names it (`published`) — otherwise an archive visitors can open would
    turn into a 404, so it is refused (`term_in_use`); take the term off the
    entries and publish them first. Categories under a removed one move one
    level up. Its addresses become free and its former addresses stop
    leading anywhere. A person's decision.

    `dry_run` answers whether it can be removed and what holds it, and
    writes nothing."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_DELETE_GATE)
    site, term, siblings = _term(context, term_id)
    _shown_under(context, site, term, collection_id)
    _assert_may_write(context, site, _term_type(term))
    drafts, published = _filed(site, term), _currently_published(site, term)
    children = [other for other in siblings if other.parent_id == term.pk]
    removable = drafts == 0 and published == 0
    result = TermRemoval(
        term=term,
        removable=removable,
        drafts=drafts,
        published=published,
        children=len(children),
    )
    if dry_run:
        return result
    if not removable:
        raise TermInUse
    position = 1 + max(
        (
            other.position
            for other in siblings
            if other.pk != term.pk and other.parent_id == term.parent_id
        ),
        default=-1,
    )
    for offset, child in enumerate(sorted(children, key=lambda item: (item.position, item.slug))):
        ContentTag.all_objects.filter(pk=child.pk).update(
            parent_id=term.parent_id, position=position + offset
        )
    metadata = {
        "key": term.slug,
        "name": term.name,
        "taxonomy_id": str(term.taxonomy_id) if term.taxonomy_id else None,
        "locale_slugs": dict(term.locale_slugs or {}),
        "former_slugs": list(term.former_slugs or []),
        "children_moved": len(children),
    }
    target_id = term.id
    # Removed entries may still be filed under it; those rows go with it.
    ContentEntryTag.all_objects.filter(
        organization_id=context.organization_id, tag_id=term.pk
    ).delete()
    ContentTag.all_objects.filter(pk=term.pk).delete()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TERM_DELETED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_tag",
        target_id=target_id,
        metadata=metadata,
    )
    return TermRemoval(
        term=term,
        removable=True,
        drafts=0,
        published=0,
        children=len(children),
        removed=True,
    )


@transaction.atomic
def set_taxonomy_segments(
    *,
    collection_id: UUID,
    segment: str,
    locale_segments: Mapping[str, str],
    reason: str = "",
    dry_run: bool = False,
) -> TaxonomySegments:
    """Changes the word for „category” in a content type's addresses —
    `/<type>/<segment>/<category>/`: `segment` in the site's own language,
    `locale_segments` in others (a language left out, or given an empty word,
    follows `segment`). The whole set is sent each time.

    Every category archive under a word that stops being the type's answers
    one 308 to today's from the moment this is saved; nothing is republished.
    Moving archives visitors can open today takes a person and a stated
    `reason`, like renaming the type in addresses. A word is lower-case Latin
    letters, digits and single hyphens, never `tag` and never a language's
    word for „page”.

    `dry_run` validates and answers with the words as they would be and what
    would move, and writes nothing."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, SEGMENTS_GATE)
    site, collection = _type(context, collection_id, lock=True)
    _assert_may_write(context, site, collection)
    found = _category_taxonomy(collection)
    if found is None:
        raise TaxonomyNotFound
    taxonomy = ContentTaxonomy.all_objects.select_for_update().get(pk=found.pk)
    reserved = {TAG_SEGMENT, *pagination_segments()}

    def checked(field_name: str, locale: str | None, raw: Any) -> str:
        word = str(raw or "").strip().lower()
        detail: list[ErrorDetail] = []
        if not SLUG_PATTERN.fullmatch(word) or len(word) > TERM_SLUG_MAX:
            detail = [
                ErrorDetail(
                    "Słowo w adresie to małe litery łacińskie, cyfry i pojedyncze łączniki.",
                    code=SEGMENT_INVALID,
                )
            ]
        elif word in reserved:
            detail = [
                ErrorDetail(
                    "To słowo jest zajęte: tak nazywają się w adresach tagi albo kolejne strony.",
                    code=SEGMENT_RESERVED,
                )
            ]
        if detail:
            raise ValidationError({field_name: {locale: detail} if locale else detail})
        return word

    new_segment = checked("segment", None, segment)
    names: dict[str, str] = {}
    for locale, raw in sorted(locale_segments.items()):
        if not str(raw or "").strip():
            continue
        if locale == site.default_locale:
            raise ValidationError({
                "locale_segments": {
                    locale: [
                        ErrorDetail(
                            "Słowo w języku strony ustawia pole segment.",
                            code=SEGMENT_SOURCE_LOCALE,
                        )
                    ]
                }
            })
        names[locale] = checked("locale_segments", locale, raw)
    locales = site_locales(site)
    before = _segments(site, taxonomy)
    previous = (taxonomy.segment, dict(taxonomy.locale_segments or {}))
    old = {
        code: taxonomy_segment(taxonomy, default_locale=site.default_locale, locale=code)
        for code in {*locales, *previous[1], *names}
    }
    taxonomy.segment, taxonomy.locale_segments = new_segment, names
    after = _segments(site, taxonomy)
    changed = {
        code: word
        for code, word in old.items()
        if taxonomy_segment(taxonomy, default_locale=site.default_locale, locale=code) != word
    }
    # The languages a category's archive of this type ever answered in.
    answered = set(
        ContentEntryPublication.all_objects.filter(
            organization_id=site.organization_id,
            entry__collection_id=collection.id,
            snapshot__terms__contains=[{"taxonomy": str(taxonomy.id)}],
        ).values_list("entry__locale", flat=True)
    )

    def base(code: str, word: str) -> str:
        index = collection_index_path(collection, default_locale=site.default_locale, locale=code)
        return f"{index}{word}/"

    moved = tuple(
        {"locale": code, "from_path": base(code, before[code]), "to_path": base(code, after[code])}
        for code in locales
        if code in changed and code in answered
    )
    stored = previous != (new_segment, names)
    result = TaxonomySegments(taxonomy=taxonomy, segments=after, moved=moved, changed=stored)
    if dry_run or not stored:
        return result
    normalized_reason = reason.strip()
    if moved and not normalized_reason:
        raise _error("reason", "Zmiana adresu wymaga uzasadnienia.", REASON_REQUIRED)
    former = [
        *(taxonomy.former_segments or []),
        *({"locale": code, "segment": word} for code, word in sorted(changed.items())),
    ]
    taxonomy.former_segments = [
        item
        for index, item in enumerate(former)
        if item not in former[:index]
        and item.get("segment")
        != taxonomy_segment(
            taxonomy, default_locale=site.default_locale, locale=str(item.get("locale"))
        )
    ]
    taxonomy.save(update_fields=["segment", "locale_segments", "former_segments", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=TAXONOMY_SEGMENTS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_taxonomy",
        target_id=taxonomy.id,
        metadata={
            "from": {"segment": previous[0], "locale_segments": previous[1]},
            "to": {"segment": new_segment, "locale_segments": names},
            "moved": list(moved),
            "reason": normalized_reason,
        },
    )
    return result


# -- an entry's terms ----------------------------------------------------------


def _locked_entry(context: Any, entry_id: UUID) -> tuple[Site, ContentEntry]:
    """The entry with its site's row locked first — the order every change
    of a site's vocabulary takes its locks in."""
    from .collections import EntryNotFound, _assert_entry_writable

    found = ContentEntry.all_objects.filter(
        pk=entry_id, organization_id=context.organization_id
    ).first()
    if found is None or found.state == ContentEntryState.REMOVED:
        raise EntryNotFound
    site = _site(context, found.site_id, lock=True)
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("collection")
        .get(pk=found.pk)
    )
    if entry.state == ContentEntryState.REMOVED:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection)
    return site, entry


def _file(context: Any, entry: ContentEntry, terms: Sequence[ContentTag], *, tags: bool) -> None:
    """Replaces what the entry is filed under within one vocabulary — the
    site's tags or its type's categories — and leaves the other alone."""
    links = ContentEntryTag.all_objects.filter(
        organization_id=context.organization_id, entry_id=entry.id, tag__taxonomy__isnull=tags
    )
    links.exclude(tag_id__in=[term.id for term in terms]).delete()
    for term in terms:
        ContentEntryTag.all_objects.get_or_create(
            organization_id=context.organization_id, entry_id=entry.id, tag_id=term.id
        )


@transaction.atomic
def set_entry_tags(*, entry_id: UUID, names: list[str]) -> list[ContentTag]:
    """Replaces the whole set rather than adding to it.

    A caller sending the tags it wants cannot accidentally leave one behind,
    which is what makes this safe to call from an automation replaying the same
    change set twice. A name means the tag whose key or address in any
    language is the name's slug, and makes a new tag only when there is none
    (ADR-079 pkt 6). The entry's categories are not touched.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    site, entry = _locked_entry(context, entry_id)
    # No lock on the tags: this makes tags and links and changes no tag that
    # exists, and the site's row — held — is what keeps two writers from
    # making one name twice. Holding term rows after an entry's is also the
    # one order a publication does not take them in.
    existing = _terms_of(site, None)
    wanted: dict[Any, ContentTag] = {}
    fresh: dict[str, str] = {}
    for raw in names:
        clean = str(raw or "").strip()
        natural = tag_slug(clean) or name_slug(clean)
        if not natural:
            raise TagNameInvalid
        found = _find_named(clean, existing)
        if found is not None:
            wanted.setdefault(found.pk, found)
        else:
            # First spelling wins, so "Porady" and "porady" are one tag rather
            # than two addresses holding half the archive each.
            fresh.setdefault(natural, clean)
    if len(wanted) + len(fresh) > ENTRY_TERMS_MAX:
        raise TooManyTags
    tags = list(wanted.values())
    for name in fresh.values():
        tag = _new_term(context, site, None, name, existing)
        existing.append(tag)
        tags.append(tag)
    # One order everywhere — the listing, the snapshot and this reply — so
    # nothing downstream reads meaning into a sequence nothing preserves.
    tags.sort(key=lambda item: item.slug)
    _file(context, entry, tags, tags=True)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_TAGS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"tags": [tag.slug for tag in tags]},
    )
    return tags


@transaction.atomic
def set_entry_categories(*, entry_id: UUID, term_ids: Sequence[UUID]) -> list[ContentTag]:
    """Files an entry under these categories of its content type, replacing
    the whole set (at most ten); its tags are not touched. A category of
    another type is refused (`term_not_of_type`). Visitors see the change
    when the entry is next published: an archive lists what publications
    carry."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    site, entry = _locked_entry(context, entry_id)
    wanted = list(dict.fromkeys(str(term_id) for term_id in term_ids))
    if len(wanted) > ENTRY_TERMS_MAX:
        raise TooManyCategories
    taxonomy = _category_taxonomy(entry.collection)
    available = {str(term.pk): term for term in _terms_of(site, taxonomy)} if taxonomy else {}
    if any(term_id not in available for term_id in wanted):
        raise _error(
            "term_ids",
            "Kategoria należy do innego typu treści albo nie istnieje.",
            TERM_NOT_OF_TYPE,
        )
    categories = sorted((available[term_id] for term_id in wanted), key=lambda item: item.slug)
    _file(context, entry, categories, tags=False)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_TERMS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"kind": KIND_CATEGORIES, "terms": [term.slug for term in categories]},
    )
    return categories


@transaction.atomic
def set_entry_tag_ids(*, entry_id: UUID, term_ids: Sequence[UUID]) -> list[ContentTag]:
    """Files an entry under these tags of its site, by id, replacing the
    whole set (at most ten); its categories are not touched. For a caller
    that holds the tags already — the content import — where a name would
    have to be matched again. A term that is not a tag of the site is refused
    (`term_not_of_type`)."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    site, entry = _locked_entry(context, entry_id)
    wanted = list(dict.fromkeys(str(term_id) for term_id in term_ids))
    if len(wanted) > ENTRY_TERMS_MAX:
        raise TooManyTags
    available = {
        str(term.pk): term
        for term in site_tags(organization_id=context.organization_id, site_id=site.id).filter(
            pk__in=wanted
        )
    }
    if any(term_id not in available for term_id in wanted):
        raise _error(
            "term_ids", "Tag nie należy do tej strony albo nie istnieje.", TERM_NOT_OF_TYPE
        )
    tags = sorted((available[term_id] for term_id in wanted), key=lambda item: item.slug)
    _file(context, entry, tags, tags=True)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_TAGS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"tags": [tag.slug for tag in tags]},
    )
    return tags


@transaction.atomic
def record_former_term_slugs(
    *, term_id: UUID, slugs: Sequence[str]
) -> tuple[list[str], dict[str, str]]:
    """An import's own right (ADR-079 pkt 34): addresses a term's archive had
    somewhere else, recorded as former — each answers one 308 to today's —
    without the term ever having answered under them here.

    Returns the slugs recorded now and, for each one left out, why: not
    slug-shaped (`invalid`), or the key, an address or a former address of
    another term of the same vocabulary (`taken`) — one namespace, pkt 6."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, TERM_ADDRESS_GATE)
    site, term, siblings = _term(context, term_id)
    _assert_may_write(context, site, _term_type(term))
    own = term_names(term)
    elsewhere: set[str] = set()
    for other in siblings:
        if other.pk != term.pk:
            elsewhere |= set(term_names(other))
    recorded: list[str] = []
    refused: dict[str, str] = {}
    for raw in slugs:
        slug = str(raw or "").strip().lower()
        if not slug or slug in own or slug in recorded:
            continue
        if not SLUG_PATTERN.fullmatch(slug) or len(slug) > TERM_SLUG_MAX:
            refused[slug] = "invalid"
        elif slug in elsewhere:
            refused[slug] = "taken"
        else:
            recorded.append(slug)
    if recorded:
        term.former_slugs = [*(term.former_slugs or []), *recorded]
        term.save(update_fields=["former_slugs", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=TERM_ADDRESS_CHANGED,
            actor=User.objects.get(pk=context.actor_id),
            target_type="content_tag",
            target_id=term.id,
            metadata={"former_recorded": recorded, "reason": "import"},
        )
    return recorded, refused


def entry_terms(*, entry_id: UUID) -> EntryTerms:
    """What an entry is filed under in the panel: its tags and its
    categories, each by key."""
    from .collections import EntryNotFound

    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    entry = ContentEntry.all_objects.filter(
        pk=entry_id, organization_id=context.organization_id
    ).first()
    if entry is None or entry.state == ContentEntryState.REMOVED:
        raise EntryNotFound
    assert_within_grant(context, site_id=entry.site_id, collection_id=entry.collection_id)
    terms = list(
        ContentTag.all_objects.filter(
            organization_id=context.organization_id, entry_links__entry_id=entry_id
        ).order_by("slug")
    )
    return EntryTerms(
        tags=tuple(term for term in terms if term.taxonomy_id is None),
        categories=tuple(term for term in terms if term.taxonomy_id is not None),
    )


def entry_tags(*, entry_id: UUID) -> list[ContentTag]:
    return list(entry_terms(entry_id=entry_id).tags)


__all__ = [
    "EntryTerms",
    "TagNameInvalid",
    "TaxonomyNotFound",
    "TaxonomySegments",
    "TermChange",
    "TermInUse",
    "TermList",
    "TermName",
    "TermNotFound",
    "TermRemoval",
    "TermRow",
    "TooManyCategories",
    "TooManyTags",
    "change_term_address",
    "create_term",
    "delete_term",
    "entry_tags",
    "entry_terms",
    "list_terms",
    "set_entry_categories",
    "set_entry_tags",
    "set_taxonomy_segments",
    "set_term_names",
    "settle_term_addresses",
    "tag_slug",
    "update_term",
]
