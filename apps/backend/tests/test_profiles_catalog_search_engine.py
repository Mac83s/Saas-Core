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


@pytest.fixture(scope="module")
def engine() -> Meilisearch:
    return Meilisearch(URL, KEY, 5.0)


@pytest.fixture(scope="module")
def index(engine: Meilisearch) -> Iterator[str]:
    name = f"test-{uuid.uuid4().hex[:8]}-catalog"
    engine.rebuild(name, search_index.INDEX_SETTINGS, [_document(*entry) for entry in ENTRIES])
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
    assert {key: current[key] for key in search_index.INDEX_SETTINGS} == search_index.INDEX_SETTINGS
