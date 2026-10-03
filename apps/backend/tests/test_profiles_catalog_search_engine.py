"""The real engine: the REST client and what Meilisearch makes of Polish words.

Skipped unless `SEARCH_TEST_URL` and `SEARCH_TEST_KEY` name a throwaway engine,
because CI has none and a shared one would be written to:

    docker run -d --rm --name s-test -p 127.0.0.1:57701:7700 \\
      -e MEILI_MASTER_KEY=test-master-key-0123456789 -e MEILI_NO_ANALYTICS=true \\
      -e MEILI_MAX_INDEXING_MEMORY=128Mb getmeili/meilisearch:v1.54.1
    SEARCH_TEST_URL=http://127.0.0.1:57701 SEARCH_TEST_KEY=test-master-key-0123456789 \\
      uv run pytest tests/test_profiles_catalog_search_engine.py

The documents are built by hand in the shape `search_index._document` makes, so
this checks the engine and the client, not the database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.shared.profiles import search_index
from saas_core.modules.shared.profiles.search_engine import Meilisearch

URL = os.environ.get("SEARCH_TEST_URL", "")
KEY = os.environ.get("SEARCH_TEST_KEY", "")
pytestmark = pytest.mark.skipif(not (URL and KEY), reason="no throwaway search engine")

ENTRIES = [
    ("zlobek", "Żłobek Promyk", "Opieka nad dziećmi od 1 do 3 lat", "Łódź", [], "edukacja"),
    ("fryzjer", "Studio Fryzjerskie Anna", "Strzyżenie i koloryzacja", "Mrągowo", [], "uroda"),
    ("barber", "Barber Kłos", "Broda i strzyżenie męskie", "Olsztyn", [], "uroda"),
    ("dentysta", "Gabinet Uśmiech", "Leczenie zębów", "Olsztyn", ["Wybielanie"], "uroda"),
    ("groomer", "Salon Puszek", "Kąpiel psów", "Giżycko", ["Strzyżenie psa"], "zwierzeta"),
    ("racice", "Nowak i Syn", "Bydło mleczne", "Kętrzyn", ["Korekcja racic"], "zwierzeta"),
    ("wet", "Przychodnia Weterynaryjna Azor", "Psy i koty", "Ełk", [], "zwierzeta"),
    ("rolnik", "Usługi Kowalski", "Łąki i zboże", "Bartoszyce", ["Wynajem kombajnu"], "rolnictwo"),
]


def _document(
    key: str, name: str, headline: str, city: str, services: list[str], category: str
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
        "display_name": name,
        "headline": headline,
        "bio": "",
        "translations": [],
        "category": category,
        "category_labels": [],
        "category_keywords": [],
        "city_slug": search_index.fold(city).lower(),
        "city": city,
        "voivodeship": "",
        "services": services,
        "folded": search_index.fold(" ".join([name, headline, city, *services])),
        "source_updated_at": "2026-09-29T00:00:00+00:00",
    }


def _settings() -> dict[str, Any]:
    """What `index_settings` sends for a profile with Polish, English and
    German, without the embedder (the vector tests set their own)."""
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        built = search_index.index_settings()
    built.pop("embedders")
    return built


@pytest.fixture(scope="module")
def engine() -> Meilisearch:
    return Meilisearch(URL, KEY, 5.0)


@pytest.fixture(scope="module")
def index(engine: Meilisearch) -> Iterator[str]:
    name = f"test-{uuid.uuid4().hex[:8]}-catalog"
    engine.rebuild(name, _settings(), [_document(*entry) for entry in ENTRIES])
    yield name
    engine._drop(name)


def _found(engine: Meilisearch, index: str, query: str, **extra: Any) -> list[str]:
    body = {"q": query, "page": 1, "hitsPerPage": 3, "attributesToRetrieve": ["id"], **extra}
    ids = [hit["id"] for hit in engine.search(index, body)["hits"]]
    names = {_document(*entry)["id"]: entry[0] for entry in ENTRIES}
    return [names[found] for found in ids]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("fryzer", "fryzjer"),  # a typo
        ("zlobek", "zlobek"),  # no diacritics
        ("lodz", "zlobek"),  # ł, which only the folded field covers
        ("Łódź", "zlobek"),
        ("strzyzenie psa", "groomer"),  # a service name, without diacritics
        ("korekcja racic", "racice"),
        ("weterynaz", "wet"),
        ("kombajn", "rolnik"),
    ],
)
def test_polish_words_find_the_entry(
    engine: Meilisearch, index: str, query: str, expected: str
) -> None:
    assert expected in _found(engine, index, query)


def test_filters_narrow_by_town_and_category(engine: Meilisearch, index: str) -> None:
    assert _found(engine, index, "strzyżenie", filter=['city_slug IN ["olsztyn"]']) == ["barber"]
    assert _found(engine, index, "strzyżenie", filter=['category = "zwierzeta"']) == ["groomer"]


def test_documents_upsert_delete_and_list(engine: Meilisearch, index: str) -> None:
    extra = _document("nowy", "Nowa Firma", "", "Ełk", [], "inne")
    engine.upsert(index, [extra])
    engine._wait({"taskUid": _last_task(engine)})
    listed = {document["id"] for document in engine.documents(index, ["id", "source_updated_at"])}
    assert extra["id"] in listed

    engine.delete(index, [extra["id"]])
    engine._wait({"taskUid": _last_task(engine)})
    assert extra["id"] not in {document["id"] for document in engine.documents(index, ["id"])}


def _last_task(engine: Meilisearch) -> int:
    return int(engine._call("GET", "/tasks?limit=1")["results"][0]["uid"])


def test_ensure_index_settles_to_no_change(engine: Meilisearch, index: str) -> None:
    """Settings read back equal to what was written, or reconcile would patch forever."""
    current = engine._call("GET", f"/indexes/{index}/settings")
    built = _settings()
    assert {key: current[key] for key in built} == built


def test_meaning_scores_vectors_and_skips_documents_without_one(engine: Meilisearch) -> None:
    """The scale the threshold is set on: (1 + cosine) / 2, and 0 without a vector."""
    name = f"test-{uuid.uuid4().hex[:8]}-catalog"
    index_settings = {
        **_settings(),
        "embedders": {search_index.EMBEDDER: {"source": "userProvided", "dimensions": 2}},
    }
    documents = [
        {**_document(key, key, "", "Ełk", [], "inne"), "_vectors": {search_index.EMBEDDER: vector}}
        for key, vector in (("same", [1.0, 0.0]), ("apart", [0.0, 1.0]), ("none", None))
    ]
    engine.rebuild(name, index_settings, documents)
    try:
        body = {
            "q": "",
            "vector": [1.0, 0.0],
            "hybrid": {"embedder": search_index.EMBEDDER, "semanticRatio": 1.0},
            "limit": 5,
            "attributesToRetrieve": ["id"],
            "showRankingScore": True,
        }
        scores = {hit["id"]: hit["_rankingScore"] for hit in engine.search(name, body)["hits"]}
        ids = {
            key: _document(key, key, "", "Ełk", [], "inne")["id"]
            for key in ("same", "apart", "none")
        }
        assert scores[ids["same"]] == pytest.approx(1.0)
        assert scores[ids["apart"]] == pytest.approx(0.5)
        assert scores.get(ids["none"], 0.0) == 0.0

        kept = engine.search(name, {**body, "rankingScoreThreshold": 0.75})["hits"]
        assert [hit["id"] for hit in kept] == [ids["same"]]
        # Read back as written, so reconcile does not patch it every ten minutes.
        current = engine._call("GET", f"/indexes/{name}/settings")
        assert current["embedders"] == index_settings["embedders"]
    finally:
        engine._drop(name)


def test_a_german_page_finds_german_words(engine: Meilisearch) -> None:
    """TL20: a card whole in German is found by its German text, and a trade
    the category names in German finds the category's companies."""
    name = f"test-{uuid.uuid4().hex[:8]}-catalog"
    vet = {
        **_document("wet-de", "Przychodnia Azor", "Psy i koty", "Ełk", [], "zwierzeta"),
        "category_keywords": ["weterynarz", "Tierarzt", "Tierklinik"],
    }
    salon = {
        **_document("salon-de", "Studio Anna", "Fryzjer w centrum", "Mrągowo", [], "uroda"),
        "headline_de": "Friseursalon im Stadtzentrum",
        "bio_de": "Wir schneiden und färben seit 1990.",
    }
    engine.rebuild(name, _settings(), [vet, salon])
    try:

        def found(query: str) -> list[str]:
            body = {"q": query, "locales": ["deu"], "attributesToRetrieve": ["id"], "limit": 3}
            return [hit["id"] for hit in engine.search(name, body)["hits"]]

        assert found("Tierarzt") == [vet["id"]]
        assert found("Friseursalon") == [salon["id"]]
        assert found("Stadtzentrum") == [salon["id"]]
    finally:
        engine._drop(name)
