"""What the catalogue search engine holds, and keeping it in step with the database.

ADR-064. `profiles_catalogentry` stays the truth about who is in the catalogue;
the engine holds one document per entry, built from that row plus the public
fields the entry's own tenant keeps (description, translations, service names).
A document is a projection that can be rebuilt at any time, never a record.

Three ways a document follows its row:

- every write of a catalogue row, and every change a module reports through
  `catalog_changed`, queues `index_catalog_organization` after commit;
- `reconcile` compares the whole index with the table every ten minutes, so an
  engine that was down, or a task that was lost, costs minutes of staleness;
- `rebuild` fills a fresh index and swaps it in — for a first deploy and for a
  change of `INDEX_SETTINGS`.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization

from . import search_engine
from .catalog_contract import categories, cities
from .models import CatalogEntry, ProfileSubjectKind, PublicProfile, PublicProfileTranslation

logger = logging.getLogger(__name__)

#: Order is rank: a word in the name beats the same word in the description.
#: `folded` is the text again without diacritics the engine keeps (ł, ø, ß —
#: it folds ż and ó itself), so "lodz" finds Łódź.
INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": [
        "display_name",
        "services",
        "category_labels",
        "category_keywords",
        "headline",
        "translations",
        "city",
        "voivodeship",
        "folded",
        "bio",
    ],
    "filterableAttributes": ["category", "city_slug"],
    "localizedAttributes": [{"attributePatterns": ["*"], "locales": ["pol", "eng"]}],
}

#: Bio is the least specific field; its start says what the company does.
_BIO_CHARS = 1000
#: After a failed search, visitors skip the engine for this long. Without it
#: every search during an outage waits out the timeout — longer than the
#: timeout itself when the engine's name no longer resolves (measured ~4 s).
ENGINE_DOWN_SECONDS = 30
_ENGINE_DOWN = "catalog-search-engine-down"

_FOLD = str.maketrans({
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ø": "o",
    "Ø": "O",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
})

TermsProvider = Callable[[UUID], Iterable[str]]
_terms_providers: dict[str, TermsProvider] = {}


def register_catalog_terms(name: str, provider: TermsProvider) -> None:
    """A module adds public words to its tenants' catalogue documents.

    Booking contributes service names. The provider runs with the tenant
    already set, so it reads its own tables under policy.
    """
    _terms_providers[name] = provider


def index_name() -> str:
    # One engine may serve several deployments on a shared host; the name keeps
    # their catalogues apart without anything else knowing about the sharing.
    return f"{settings.DEPLOYMENT}-catalog"


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def enqueue(organization_id: UUID) -> None:
    """Reindex one tenant's document once the current transaction commits."""
    if search_engine.engine() is None:
        return

    def send() -> None:
        from .tasks import index_catalog_organization

        index_catalog_organization.delay(str(organization_id))

    # robust: a broker hiccup must not fail the request that changed the row;
    # the reconcile sweep repairs what the task would have done.
    transaction.on_commit(send, robust=True)


def follow_catalog_entry(sender: object, instance: CatalogEntry, **_kwargs: object) -> None:
    """Signal receiver; module level, because signals hold receivers weakly."""
    enqueue(instance.organization_id)


def catalog_changed(organization_id: UUID) -> None:
    """Something a document shows changed outside the catalogue row.

    The row's `updated_at` moves too, so the reconcile sweep sees the document
    as stale even if the task queued here never runs.
    """
    touched = CatalogEntry.all_objects.filter(organization_id=organization_id).update(
        updated_at=timezone.now()
    )
    if touched:
        enqueue(organization_id)


def _document(entry: CatalogEntry) -> dict[str, Any] | None:
    """The engine's copy of one entry, or None when its tenant no longer answers."""
    with transaction.atomic():
        # The row named the tenant (ADR-053 §4); everything beyond it is read
        # inside that tenant, under policy — the same order the public page uses.
        set_local_organization_id(entry.organization_id)
        profile = PublicProfile.all_objects.filter(
            pk=entry.profile_id,
            organization_id=entry.organization_id,
            subject_kind=ProfileSubjectKind.ORGANIZATION,
        ).first()
        if profile is None:
            return None
        translations = [
            text
            for headline, bio in PublicProfileTranslation.all_objects.filter(
                organization_id=entry.organization_id, profile_id=profile.id
            ).values_list("headline", "bio")
            for text in (headline, bio[:_BIO_CHARS])
            if text
        ]
        organization_type = (
            Organization.objects.filter(pk=entry.organization_id)
            .values_list("organization_type", flat=True)
            .first()
        )
        services = sorted({
            term.strip()
            for provider in _terms_providers.values()
            for term in provider(entry.organization_id)
            if term.strip()
        })[:100]

    category = categories(organization_type or settings.DEFAULT_ORGANIZATION_TYPE).get(
        entry.category
    )
    labels = sorted(set(category.label.values())) if category else []
    keywords = [word for words in category.keywords.values() for word in words] if category else []
    city = cities().get(entry.city_slug)
    voivodeship = city.voivodeship if city else ""
    return {
        "id": str(entry.organization_id),
        "display_name": entry.display_name,
        "headline": entry.headline,
        "bio": profile.bio[:_BIO_CHARS],
        "translations": translations,
        "category": entry.category,
        "category_labels": labels,
        "category_keywords": keywords,
        "city_slug": entry.city_slug,
        "city": entry.city,
        "voivodeship": voivodeship,
        "services": services,
        "folded": fold(
            " ".join([
                entry.display_name,
                entry.headline,
                entry.city,
                voivodeship,
                *services,
                *labels,
                *keywords,
            ])
        ),
        "source_updated_at": entry.updated_at.isoformat(),
    }


def sync_organization(organization_id: UUID) -> None:
    engine = search_engine.engine()
    if engine is None:
        return
    entry = CatalogEntry.all_objects.filter(organization_id=organization_id).first()
    document = _document(entry) if entry is not None else None
    engine.ensure_index(index_name(), INDEX_SETTINGS)
    if document is None:
        engine.delete(index_name(), [str(organization_id)])
    else:
        engine.upsert(index_name(), [document])


def reconcile() -> dict[str, int]:
    """Make the index match the table: add missing, refresh stale, drop gone."""
    engine = search_engine.engine()
    if engine is None:
        return {}
    engine.ensure_index(index_name(), INDEX_SETTINGS)
    indexed = {
        document["id"]: document.get("source_updated_at")
        for document in engine.documents(index_name(), ["id", "source_updated_at"])
    }
    entries = list(CatalogEntry.all_objects.order_by("organization_id"))
    present = {str(entry.organization_id) for entry in entries}
    documents: list[dict[str, Any]] = []
    gone = set(indexed) - present
    for entry in entries:
        if indexed.get(str(entry.organization_id)) == entry.updated_at.isoformat():
            continue
        document = _document(entry)
        if document is None:
            gone.add(str(entry.organization_id))
        else:
            documents.append(document)
    engine.upsert(index_name(), documents)
    engine.delete(index_name(), sorted(gone))
    return {"refreshed": len(documents), "removed": len(gone)}


def rebuild() -> int:
    engine = search_engine.engine()
    if engine is None:
        raise search_engine.SearchEngineUnavailable("search_unconfigured")
    documents = [
        document
        for entry in CatalogEntry.all_objects.order_by("organization_id")
        if (document := _document(entry)) is not None
    ]
    engine.rebuild(index_name(), INDEX_SETTINGS, documents)
    return len(documents)


def search_ids(
    *,
    query: str,
    city_slugs: list[str] | None,
    category: str,
    page: int,
    page_size: int,
) -> tuple[list[UUID], int]:
    """Organization ids of the matching entries, best first, and how many match.

    Filters are dictionary values (ADR-053 §7), quoted anyway: a filter is a
    small language, and a value is never part of its grammar.
    """
    engine = search_engine.engine()
    if engine is None:
        raise search_engine.SearchEngineUnavailable("search_unconfigured")
    filters = []
    if city_slugs is not None:
        filters.append(f"city_slug IN [{', '.join(json.dumps(slug) for slug in city_slugs)}]")
    if category:
        filters.append(f"category = {json.dumps(category)}")
    body: dict[str, Any] = {
        "q": query,
        "page": page,
        "hitsPerPage": page_size,
        "attributesToRetrieve": ["id"],
    }
    if filters:
        body["filter"] = filters
    if cache.get(_ENGINE_DOWN):
        raise search_engine.SearchEngineUnavailable("search_recently_down")
    try:
        result = engine.search(index_name(), body)
    except search_engine.SearchEngineUnavailable:
        cache.set(_ENGINE_DOWN, True, ENGINE_DOWN_SECONDS)
        raise
    return [UUID(hit["id"]) for hit in result["hits"]], int(result.get("totalHits") or 0)
