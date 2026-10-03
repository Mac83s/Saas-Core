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

from . import embeddings, search_engine
from .catalog_contract import categories, cities
from .models import CatalogEntry, ProfileSubjectKind, PublicProfile, PublicProfileTranslation

logger = logging.getLogger(__name__)

#: Order is rank: a word in the name beats the same word in the description.
#: `folded` is the text again without diacritics the engine keeps (ł, ø, ß —
#: it folds ż and ó itself), so "lodz" finds Łódź. A `*_<code>` field holds
#: the card's text in one of its other languages (TL20), only where the card
#: is whole in it.
INDEX_SETTINGS: dict[str, Any] = {
    "searchableAttributes": [
        "display_name",
        "services",
        "category_labels",
        "category_keywords",
        "headline",
        "headline_*",
        "city",
        "voivodeship",
        "folded",
        "bio",
        "bio_*",
    ],
    "filterableAttributes": ["category", "city_slug"],
}

#: Fields of one language: `<field>_<code>` (TL20).
_LOCALIZED_FIELDS = ("headline", "bio")

#: The engine's name for the vectors the backend sends (`userProvided`).
EMBEDDER = "meaning"


def searchable_attributes() -> list[str]:
    """`INDEX_SETTINGS` with each `<field>_*` spelled out for the profile's
    languages: the engine takes names, not patterns, here."""
    names: list[str] = []
    for name in INDEX_SETTINGS["searchableAttributes"]:
        if name.endswith("_*"):
            names.extend(f"{name[:-2]}_{code}" for code in settings.SITES_SUPPORTED_LOCALES)
        else:
            names.append(name)
    return names


#: The engine's names for the registry's languages. It takes `pl` too, but
#: reads it back as `pol`, and `ensure_index` would then patch the settings on
#: every sync; so the three-letter name it keeps (ISO 639-3) is what is sent.
ENGINE_LOCALES = {"pl": "pol", "en": "eng", "de": "deu", "es": "spa", "ru": "rus"}


def search_locale(code: str) -> str:
    """The engine's name for a registry language, from its `searchCode`."""
    search_code = settings.LOCALE_REGISTRY[code].search_code.split("-")[0]
    return ENGINE_LOCALES.get(search_code, search_code)


def localized_attributes() -> list[dict[str, Any]]:
    """Which language each field is in, from the profile (TL20): a `*_<code>`
    field in that language; the rest — the card's own texts, names, towns —
    in any of the profile's languages, which the engine tells apart."""
    codes = [code for code in settings.SITES_SUPPORTED_LOCALES if code in settings.LOCALE_REGISTRY]
    return [
        *({"attributePatterns": [f"*_{code}"], "locales": [search_locale(code)]} for code in codes),
        {"attributePatterns": ["*"], "locales": [search_locale(code) for code in codes]},
    ]


def index_settings() -> dict[str, Any]:
    return {
        **INDEX_SETTINGS,
        "searchableAttributes": searchable_attributes(),
        "localizedAttributes": localized_attributes(),
        "embedders": {
            EMBEDDER: {
                "source": "userProvided",
                "dimensions": settings.CATALOG_EMBEDDING_DIMENSIONS,
            }
        },
    }


#: Bio is the least specific field; its start says what the company does.
_BIO_CHARS = 1000
#: How much of it the meaning of an entry is read from.
_MEANING_BIO_CHARS = 500
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
        # Only the languages the card is whole in (the row's copy, TL20): a
        # half-translated card is not found in a language it is not shown in.
        from .card_languages import card_in_language

        in_languages: dict[str, str] = {}
        for row in PublicProfileTranslation.all_objects.filter(
            organization_id=entry.organization_id,
            profile_id=profile.id,
            locale__in=list(entry.translated_locales or ()),
        ):
            shown = card_in_language(profile, row)
            for field in _LOCALIZED_FIELDS:
                in_languages[f"{field}_{row.locale}"] = shown[field][:_BIO_CHARS]
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
        **in_languages,
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


def _meaning_text(document: dict[str, Any]) -> str:
    """What an entry is about, in one passage — the text its vector stands for."""
    parts = [
        document["display_name"],
        ", ".join(document["category_labels"]),
        document["headline"],
        f"Usługi: {', '.join(document['services'])}" if document["services"] else "",
        document["city"],
        document["bio"][:_MEANING_BIO_CHARS],
    ]
    return ". ".join(part for part in parts if part)


def _with_meaning(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach vectors; without a key or an answer the words still work.

    `meaning_model` says what made the vector, so reconcile can tell a document
    that has none, or one from another model, and try again.
    """
    vectors: list[list[float]] | None = None
    if documents and embeddings.configured():
        try:
            vectors = embeddings.embed_documents([_meaning_text(doc) for doc in documents])
        except embeddings.EmbeddingUnavailable as error:
            logger.warning("catalog_embedding_failed", extra={"reason": str(error)})
    for position, document in enumerate(documents):
        vector = vectors[position] if vectors is not None else None
        document["_vectors"] = {EMBEDDER: vector}
        document["meaning_model"] = embeddings.model() if vector is not None else ""
    return documents


def sync_organization(organization_id: UUID) -> None:
    engine = search_engine.engine()
    if engine is None:
        return
    entry = CatalogEntry.all_objects.filter(organization_id=organization_id).first()
    document = _document(entry) if entry is not None else None
    engine.ensure_index(index_name(), index_settings())
    if document is None:
        engine.delete(index_name(), [str(organization_id)])
    else:
        engine.upsert(index_name(), _with_meaning([document]))


def reconcile() -> dict[str, int]:
    """Make the index match the table: add missing, refresh stale, drop gone."""
    engine = search_engine.engine()
    if engine is None:
        return {}
    engine.ensure_index(index_name(), index_settings())
    wanted_model = embeddings.model() if embeddings.configured() else ""
    indexed = {
        document["id"]: (document.get("source_updated_at"), document.get("meaning_model") or "")
        for document in engine.documents(index_name(), ["id", "source_updated_at", "meaning_model"])
    }
    entries = list(CatalogEntry.all_objects.order_by("organization_id"))
    present = {str(entry.organization_id) for entry in entries}
    documents: list[dict[str, Any]] = []
    gone = set(indexed) - present
    for entry in entries:
        if indexed.get(str(entry.organization_id)) == (entry.updated_at.isoformat(), wanted_model):
            continue
        document = _document(entry)
        if document is None:
            gone.add(str(entry.organization_id))
        else:
            documents.append(document)
    engine.upsert(index_name(), _with_meaning(documents))
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
    engine.rebuild(index_name(), index_settings(), _with_meaning(documents))
    return len(documents)


def _filters(city_slugs: list[str] | None, category: str) -> list[str]:
    """Filters are dictionary values (ADR-053 §7), quoted anyway: a filter is a
    small language, and a value is never part of its grammar."""
    filters = []
    if city_slugs is not None:
        filters.append(f"city_slug IN [{', '.join(json.dumps(slug) for slug in city_slugs)}]")
    if category:
        filters.append(f"category = {json.dumps(category)}")
    return filters


def _search(body: dict[str, Any]) -> dict[str, Any]:
    engine = search_engine.engine()
    if engine is None:
        raise search_engine.SearchEngineUnavailable("search_unconfigured")
    if cache.get(_ENGINE_DOWN):
        raise search_engine.SearchEngineUnavailable("search_recently_down")
    try:
        return engine.search(index_name(), body)
    except search_engine.SearchEngineUnavailable:
        cache.set(_ENGINE_DOWN, True, ENGINE_DOWN_SECONDS)
        raise


def _query_locales(locale: str | None) -> dict[str, Any]:
    """The page's language as a hint for reading the words (TL20): "Tierarzt"
    is split and stemmed as German on a German page."""
    if locale and locale in settings.SITES_SUPPORTED_LOCALES and locale in settings.LOCALE_REGISTRY:
        return {"locales": [search_locale(locale)]}
    return {}


def search_ids(
    *,
    query: str,
    city_slugs: list[str] | None,
    category: str,
    page: int,
    page_size: int,
    locale: str | None = None,
) -> tuple[list[UUID], int]:
    """Organization ids of the entries that contain the words, best first, and how many."""
    body: dict[str, Any] = {
        "q": query,
        "page": page,
        "hitsPerPage": page_size,
        "attributesToRetrieve": ["id"],
        **_query_locales(locale),
    }
    if filters := _filters(city_slugs, category):
        body["filter"] = filters
    result = _search(body)
    return [UUID(hit["id"]) for hit in result["hits"]], int(result.get("totalHits") or 0)


def similar_ids(
    *,
    query: str,
    city_slugs: list[str] | None,
    category: str,
    exclude: set[UUID],
    limit: int,
    locale: str | None = None,
) -> list[UUID]:
    """Entries that fit the words by meaning, best first (ADR-064 §8).

    Empty without a key or when the provider does not answer: meaning is the
    extra, the words are the search. Only vectors, so a word match cannot lift
    an entry that means something else; the threshold keeps the rest out
    instead of always returning somebody.
    """
    if not embeddings.configured():
        return []
    try:
        vector = embeddings.embed_query(query)
    except embeddings.EmbeddingUnavailable as error:
        logger.warning("catalog_query_embedding_failed", extra={"reason": str(error)})
        return []
    body: dict[str, Any] = {
        "q": query,
        "vector": vector,
        "hybrid": {"embedder": EMBEDDER, "semanticRatio": 1.0},
        "limit": limit + len(exclude),
        "attributesToRetrieve": ["id"],
        "rankingScoreThreshold": settings.CATALOG_SIMILAR_MIN_SCORE,
        **_query_locales(locale),
    }
    if filters := _filters(city_slugs, category):
        body["filter"] = filters
    found = [UUID(hit["id"]) for hit in _search(body)["hits"]]
    return [organization_id for organization_id in found if organization_id not in exclude][:limit]
