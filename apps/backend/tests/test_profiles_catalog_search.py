"""The catalogue's search engine and the index it holds (ADR-064).

The engine itself is not here — CI has none — so a fake stands in for it and
these tests hold the plumbing that a later change could quietly undo:

- every way a catalogue row changes moves its search document too, including
  a published card edited after publication and a service renamed in Booking;
- the document carries only public fields, is built inside its own tenant, and
  folds the letters the engine keeps (ł), so "lodz" can find Łódź;
- words go to the engine, rows still come from the table, and an engine that
  does not answer leaves the catalogue searching PostgreSQL;
- distance is town centre to town centre, the same on both paths.

What the engine makes of Polish words is proven against a real one by
`test_profiles_catalog_search_engine.py` (skipped without one), not here.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.booking.models import Service
from saas_core.modules.shared.profiles import embeddings, search_engine, search_index
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import CatalogEntry
from saas_core.modules.shared.profiles.search_engine import SearchEngineUnavailable

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
PROFILE_URL = "/api/v1/profiles/organization/"
PUBLISH_URL = "/api/v1/profiles/organization/catalog/"
CATALOG_URL = "/api/v1/public/catalog/"


class FakeEngine:
    """In-memory stand-in: substring match over the searchable fields."""

    def __init__(self) -> None:
        self.indexes: dict[str, dict[str, dict[str, Any]]] = {}
        self.down = False
        self.searches: list[dict[str, Any]] = []

    def _answer(self) -> None:
        if self.down:
            raise SearchEngineUnavailable("search_unreachable")

    def ensure_index(self, index: str, index_settings: dict[str, Any]) -> None:
        self._answer()
        self.indexes.setdefault(index, {})

    def upsert(self, index: str, documents: list[dict[str, Any]]) -> None:
        self._answer()
        for document in documents:
            self.indexes.setdefault(index, {})[document["id"]] = document

    def delete(self, index: str, ids: list[str]) -> None:
        self._answer()
        for document_id in ids:
            self.indexes.get(index, {}).pop(document_id, None)

    def documents(self, index: str, fields: list[str]) -> list[dict[str, Any]]:
        self._answer()
        return [{field: doc.get(field) for field in fields} for doc in self.index(index)]

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self._answer()
        self.searches.append(body)
        if "vector" in body:
            return self._by_meaning(index, body)
        words = search_index.fold(body["q"]).lower().split()
        hits = []
        for document in self.index(index):
            text = search_index.fold(
                json.dumps(
                    [document.get(field, "") for field in search_index.searchable_attributes()],
                    ensure_ascii=False,
                )
            ).lower()
            if all(word in text for word in words) and self._passes(document, body):
                hits.append({"id": document["id"]})
        start = (body["page"] - 1) * body["hitsPerPage"]
        return {"hits": hits[start : start + body["hitsPerPage"]], "totalHits": len(hits)}

    def _by_meaning(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        # The engine's scale: (1 + cosine) / 2, and 0 for a document without one.
        scored = []
        for document in self.index(index):
            vector = (document.get("_vectors") or {}).get(search_index.EMBEDDER)
            score = 0.0
            if vector is not None:
                score = (1 + sum(a * b for a, b in zip(vector, body["vector"], strict=True))) / 2
            if score >= body.get("rankingScoreThreshold", 0) and self._passes(document, body):
                scored.append((score, document["id"]))
        scored.sort(reverse=True)
        return {"hits": [{"id": found} for _score, found in scored[: body["limit"]]]}

    @staticmethod
    def _passes(document: dict[str, Any], body: dict[str, Any]) -> bool:
        for condition in body.get("filter", []):
            field, operator, value = condition.split(" ", 2)
            allowed = json.loads(value) if operator == "IN" else [json.loads(value)]
            if document[field] not in allowed:
                return False
        return True

    def rebuild(
        self, index: str, index_settings: dict[str, Any], documents: list[dict[str, Any]]
    ) -> None:
        self._answer()
        self.indexes[index] = {document["id"]: document for document in documents}

    def index(self, name: str | None = None) -> list[dict[str, Any]]:
        return list(self.indexes.get(name or search_index.index_name(), {}).values())


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine()
    monkeypatch.setattr(search_engine, "engine", lambda: fake)
    return fake


#: The fake provider's whole understanding of language: a text means a concept
#: when it contains one of its stems. Four dimensions, like the setting below.
CONCEPTS = (
    ("zęb", "ząb", "stomatolog", "ortodon", "dentyst"),
    ("fryzjer", "włos", "strzyż"),
    ("krow", "racic", "bydł"),
)


class FakeProvider:
    def __init__(self) -> None:
        self.down = False
        self.calls: list[list[str]] = []

    def post(self, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if self.down:
            raise embeddings.EmbeddingUnavailable("embedding_unreachable")
        self.calls.append(list(body["input"]))
        return {
            "data": [
                {"index": position, "embedding": self.vector(text)}
                for position, text in enumerate(body["input"])
            ]
        }

    @staticmethod
    def vector(text: str) -> list[float]:
        found = [1.0 if any(stem in text.lower() for stem in stems) else 0.0 for stems in CONCEPTS]
        return [*found, 0.0 if any(found) else 1.0]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, settings: Any) -> FakeProvider:
    fake = FakeProvider()
    settings.CATALOG_EMBEDDING_API_KEY = "test-key"
    settings.CATALOG_EMBEDDING_DIMENSIONS = 4
    monkeypatch.setattr(embeddings, "_post", fake.post)
    return fake


def catalog_client(*, slug: str) -> tuple[APIClient, Organization]:
    user = User.objects.create_user(email=f"{slug}@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug.replace("-", " ").title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"profiles.enabled": True, "sites.enabled": True},
        quotas={"sites.max": 3},
        sources={"profiles.enabled": {"kind": "plan"}},
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    login = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert login.status_code == 200
    return client, organization


def _csrf(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def _category() -> str:
    return next(iter(categories(settings.DEFAULT_ORGANIZATION_TYPE)))


def _edit(client: APIClient, **values: Any) -> Any:
    profile = client.get(PROFILE_URL).data["profile"]
    return client.put(
        f"/api/v1/profiles/{profile['id']}/",
        {
            "display_name": profile["display_name"],
            "city_slug": profile["city_slug"] or "mragowo",
            "category": profile["category"] or _category(),
            "expected_version": profile["version"],
            **values,
        },
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )


def _published(
    slug: str, captured: Any, *, city: str = "mragowo", **values: Any
) -> tuple[APIClient, Organization]:
    client, organization = catalog_client(slug=slug)
    assert _edit(client, city_slug=city, **values).status_code == 200
    with captured(execute=True):
        assert (
            client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client)).status_code
            == 200
        )
    return client, organization


def _document(engine: FakeEngine, organization: Organization) -> dict[str, Any] | None:
    return engine.indexes.get(search_index.index_name(), {}).get(str(organization.id))


def test_publication_indexes_public_fields_with_active_services_and_folded_letters(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    client, organization = catalog_client(slug="szukaj-publikacja")
    Service.all_objects.create(
        organization=organization,
        name="Strzyżenie psa",
        public_slug="strzyzenie",
        duration_minutes=60,
    )
    Service.all_objects.create(
        organization=organization,
        name="Usługa wycofana",
        public_slug="wycofana",
        duration_minutes=30,
        active=False,
    )
    _edit(
        client,
        city_slug="lodz",
        headline="Groomer z Łodzi",
        bio="Kąpiel i strzyżenie wszystkich ras.",
        contact_phone="+48 600 100 200",
    )
    with django_capture_on_commit_callbacks(execute=True):
        client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))

    document = _document(engine, organization)
    assert document is not None
    assert document["services"] == ["Strzyżenie psa"]
    assert document["city"] == "Łódź"
    assert "Lodz" in document["folded"]
    assert document["bio"] == "Kąpiel i strzyżenie wszystkich ras."
    category = categories(settings.DEFAULT_ORGANIZATION_TYPE)[_category()]
    assert document["category_labels"] == sorted(set(category.label.values()))
    assert set(document["category_keywords"]) >= set(category.keywords.get("pl", ()))
    # Contact data is on the public page, but it is not what anybody searches by.
    assert "+48 600 100 200" not in json.dumps(document, ensure_ascii=False)
    assert (
        document["source_updated_at"]
        == CatalogEntry.all_objects.get(organization=organization).updated_at.isoformat()
    )


def test_the_document_is_built_inside_its_tenant() -> None:
    """The ordering AGENTS.md asks for: the row names the tenant, then policy reads."""
    client, organization = catalog_client(slug="szukaj-kolejnosc")
    _edit(client, headline="Salon")
    client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    entry = CatalogEntry.all_objects.get(organization=organization)

    with CaptureQueriesContext(connection) as captured:
        document = search_index._document(entry)

    assert document is not None
    statements = [query["sql"] for query in captured.captured_queries]
    set_local = next(index for index, sql in enumerate(statements) if "app.organization_id" in sql)
    tenant_reads = [
        index
        for index, sql in enumerate(statements)
        if "profiles_publicprofile" in sql
        or "booking_service" in sql
        or "organizations_organization" in sql
    ]
    assert tenant_reads and set_local < min(tenant_reads)


def test_withdrawal_removes_the_document(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    client, organization = _published("szukaj-wycofanie", django_capture_on_commit_callbacks)
    assert _document(engine, organization) is not None

    with django_capture_on_commit_callbacks(execute=True):
        client.delete(PUBLISH_URL, HTTP_X_CSRFTOKEN=_csrf(client))

    assert _document(engine, organization) is None


def test_editing_a_published_card_refreshes_the_row_and_the_document(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    client, organization = _published("szukaj-edycja", django_capture_on_commit_callbacks)

    with django_capture_on_commit_callbacks(execute=True):
        assert _edit(client, display_name="Nowa Nazwa", headline="Nowy opis").status_code == 200

    entry = CatalogEntry.all_objects.get(organization=organization)
    assert (entry.display_name, entry.headline) == ("Nowa Nazwa", "Nowy opis")
    assert _document(engine, organization)["display_name"] == "Nowa Nazwa"  # type: ignore[index]
    listing = APIClient().get(CATALOG_URL, {"city": "mragowo"})
    assert [item["display_name"] for item in listing.data["items"]] == ["Nowa Nazwa"]

    # Taking the card out of the catalogue is the owner's switch, not a side
    # effect of an emptied field.
    emptied = _edit(client, city_slug="")
    assert emptied.status_code == 409
    assert emptied.data["code"] == "profile_not_publishable"


def test_a_service_change_reaches_the_document_and_marks_the_row(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _client, organization = _published("szukaj-uslugi", django_capture_on_commit_callbacks)
    before = CatalogEntry.all_objects.get(organization=organization).updated_at

    with django_capture_on_commit_callbacks(execute=True):
        Service.all_objects.create(
            organization=organization,
            name="Korekcja racic",
            public_slug="korekcja",
            duration_minutes=45,
        )

    # The row moves too, so the reconcile sweep would repair a lost task.
    assert CatalogEntry.all_objects.get(organization=organization).updated_at > before
    assert _document(engine, organization)["services"] == ["Korekcja racic"]  # type: ignore[index]


def test_words_go_to_the_engine_and_rows_come_from_the_table(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-anna", django_capture_on_commit_callbacks, headline="Fryzjer Anna")
    _published("szukaj-barber", django_capture_on_commit_callbacks, headline="Barber")
    # A document for an entry withdrawn a moment ago: the table has the last word.
    engine.upsert(
        search_index.index_name(),
        [{**engine.index()[0], "id": "00000000-0000-0000-0000-000000000001"}],
    )

    listing = APIClient().get(CATALOG_URL, {"q": "anna"})

    assert listing.status_code == 200
    assert engine.searches[-1]["q"] == "anna"
    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-anna"]
    assert listing.data["similar"] == []


def test_an_engine_that_does_not_answer_leaves_the_database_search(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-awaria", django_capture_on_commit_callbacks, headline="Fryzjer")
    engine.down = True

    listing = APIClient().get(CATALOG_URL, {"q": "fryzjer"})

    assert listing.status_code == 200
    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-awaria"]


def test_after_a_failed_search_visitors_skip_the_engine_for_a_while(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-przerwa", django_capture_on_commit_callbacks, headline="Fryzjer")
    engine.down = True
    APIClient().get(CATALOG_URL, {"q": "fryzjer"})
    engine.down = False

    listing = APIClient().get(CATALOG_URL, {"q": "fryzjer"})

    # The engine answers again, but the next searches do not wait on it.
    assert engine.searches == []
    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-przerwa"]


def test_an_address_keeps_the_letters_slugify_would_drop() -> None:
    client, _organization = catalog_client(slug="szukaj-adres")
    _edit(client, display_name="Żłobek i Usługi")
    published = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    assert published.data["catalog"]["slug"] == "zlobek-i-uslugi"


def test_without_an_engine_nothing_is_queued_and_search_uses_the_database(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    from saas_core.modules.shared.profiles import tasks

    def refuse(*_args: object) -> None:
        raise AssertionError("no engine, no indexing task")

    monkeypatch.setattr(tasks.index_catalog_organization, "delay", refuse)
    _published("szukaj-bez-silnika", django_capture_on_commit_callbacks, headline="Fryzjer")
    listing = APIClient().get(CATALOG_URL, {"q": "fryz"})
    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-bez-silnika"]


def test_distance_is_town_to_town_and_the_same_on_both_paths(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    for slug, city in (
        ("szukaj-olsztyn", "olsztyn"),
        ("szukaj-mragowo", "mragowo"),
        ("szukaj-warszawa", "warszawa"),
    ):
        _published(slug, django_capture_on_commit_callbacks, city=city, headline="Weterynarz")

    around = APIClient().get(CATALOG_URL, {"city": "olsztyn", "radius_km": "60"})
    assert [item["slug"] for item in around.data["items"]] == ["szukaj-olsztyn", "szukaj-mragowo"]
    assert around.data["items"][0]["distance_km"] == 0.0
    assert 50 < around.data["items"][1]["distance_km"] < 60

    # "Near me": a point, no town — the point is used for this answer only.
    near = APIClient().get(
        CATALOG_URL, {"lat": "52.23", "lng": "21.01", "radius_km": "30", "q": "weterynarz"}
    )
    assert [item["slug"] for item in near.data["items"]] == ["szukaj-warszawa"]
    assert engine.searches[-1]["filter"] == ['city_slug IN ["warszawa"]']

    engine.down = True
    fallback = APIClient().get(
        CATALOG_URL, {"lat": "52.23", "lng": "21.01", "radius_km": "30", "q": "weterynarz"}
    )
    assert [item["slug"] for item in fallback.data["items"]] == ["szukaj-warszawa"]

    nothing_near = APIClient().get(CATALOG_URL, {"lat": "50.0", "lng": "14.0", "radius_km": "10"})
    assert nothing_near.data["total"] == 0


def test_reconcile_adds_the_missing_refreshes_the_stale_and_drops_the_gone(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _client, kept = _published("szukaj-zgodne", django_capture_on_commit_callbacks)
    _client, stale = _published("szukaj-stare", django_capture_on_commit_callbacks)
    _client, missing = _published("szukaj-brak", django_capture_on_commit_callbacks)
    index = search_index.index_name()
    engine.delete(index, [str(missing.id)])
    engine.upsert(index, [{**_document(engine, stale), "source_updated_at": "2020-01-01"}])  # type: ignore[dict-item]
    engine.upsert(index, [{"id": "00000000-0000-0000-0000-000000000002"}])

    assert search_index.reconcile() == {"refreshed": 2, "removed": 1}
    assert {document["id"] for document in engine.index()} == {
        str(kept.id),
        str(stale.id),
        str(missing.id),
    }
    assert search_index.reconcile() == {"refreshed": 0, "removed": 0}


def test_the_rebuild_command_fills_a_fresh_index(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _client, organization = _published("szukaj-przebudowa", django_capture_on_commit_callbacks)
    engine.indexes.clear()

    call_command("reindex_catalog")

    assert [document["id"] for document in engine.index()] == [str(organization.id)]


def test_folding_covers_the_letters_the_engine_keeps() -> None:
    assert search_index.fold("Łódź, Gdańsk, Straße, Ørsted") == "Lodz, Gdansk, Strasse, Orsted"


def test_meaning_finds_what_the_words_do_not(
    engine: FakeEngine, provider: FakeProvider, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-zeby", django_capture_on_commit_callbacks, headline="Leczenie zębów")
    _published("szukaj-wlosy", django_capture_on_commit_callbacks, headline="Fryzjer")

    listing = APIClient().get(CATALOG_URL, {"q": "boli mnie ząb"})

    # "Nie znaleźliśmy dokładnie… Podobne:" — nothing contains the words.
    assert listing.data["items"] == []
    assert [item["slug"] for item in listing.data["similar"]] == ["szukaj-zeby"]


def test_may_also_lists_what_fits_below_what_contains_the_words(
    engine: FakeEngine, provider: FakeProvider, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-usmiech", django_capture_on_commit_callbacks, headline="Uśmiech, zęby")
    _published("szukaj-aparaty", django_capture_on_commit_callbacks, headline="Ortodonta")
    _published("szukaj-fryzjer", django_capture_on_commit_callbacks, headline="Fryzjer")

    listing = APIClient().get(CATALOG_URL, {"q": "uśmiech zęby"})

    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-usmiech"]
    # "Może też": the orthodontist by meaning, never the entry already above,
    # and not the hairdresser, whose meaning is unrelated.
    assert [item["slug"] for item in listing.data["similar"]] == ["szukaj-aparaty"]
    # Meaning only on the first page of results.
    second = APIClient().get(CATALOG_URL, {"q": "uśmiech zęby", "page": 2})
    assert second.data["similar"] == []


def test_without_a_key_documents_carry_no_vector_and_search_is_words_only(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any
) -> None:
    _client, organization = _published(
        "szukaj-bez-klucza", django_capture_on_commit_callbacks, headline="Stomatolog"
    )
    document = _document(engine, organization)
    assert document["_vectors"] == {search_index.EMBEDDER: None}  # type: ignore[index]
    assert document["meaning_model"] == ""  # type: ignore[index]
    assert APIClient().get(CATALOG_URL, {"q": "boli mnie ząb"}).data["similar"] == []


def test_a_document_indexed_while_the_provider_was_down_gets_its_vector_later(
    engine: FakeEngine, provider: FakeProvider, django_capture_on_commit_callbacks: Any
) -> None:
    provider.down = True
    _client, organization = _published(
        "szukaj-pozniej", django_capture_on_commit_callbacks, headline="Stomatolog"
    )
    # Indexed by its words all the same.
    assert _document(engine, organization)["meaning_model"] == ""  # type: ignore[index]
    provider.down = False

    assert search_index.reconcile() == {"refreshed": 1, "removed": 0}
    document = _document(engine, organization)
    assert document["meaning_model"] == embeddings.model()  # type: ignore[index]
    # The dental concept is in it; others may be too — the category's own
    # label is part of the text, and a product's label says what it says.
    assert document["_vectors"][search_index.EMBEDDER][0] > 0  # type: ignore[index]
    assert search_index.reconcile() == {"refreshed": 0, "removed": 0}


def test_a_repeated_query_costs_one_provider_call(
    engine: FakeEngine, provider: FakeProvider, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-pamiec", django_capture_on_commit_callbacks, headline="Stomatolog")
    provider.calls.clear()

    for _ in range(3):
        APIClient().get(CATALOG_URL, {"q": "boli mnie ząb"})

    assert len(provider.calls) == 1
    # Qwen3 wants the task said before a query, never before a document.
    assert provider.calls[0][0].startswith(embeddings.QUERY_INSTRUCTION)


def test_a_provider_that_does_not_answer_leaves_the_words(
    engine: FakeEngine, provider: FakeProvider, django_capture_on_commit_callbacks: Any
) -> None:
    _published("szukaj-slowa", django_capture_on_commit_callbacks, headline="Stomatolog")
    provider.down = True

    listing = APIClient().get(CATALOG_URL, {"q": "stomatolog"})

    assert listing.status_code == 200
    assert [item["slug"] for item in listing.data["items"]] == ["szukaj-slowa"]
    assert listing.data["similar"] == []


# -- per language (TL20d) ----------------------------------------------------


def _languages(organization: Organization, locales: list[str]) -> None:
    Organization.objects.filter(pk=organization.pk).update(public_locales=locales)


def _translate(client: APIClient, locale: str, **values: Any) -> Any:
    profile = client.get(PROFILE_URL).data["profile"]
    current = client.get(f"/api/v1/profiles/{profile['id']}/translations/").data
    version = next(
        (entry["version"] for entry in current["languages"] if entry["locale"] == locale), 0
    )
    return client.put(
        f"/api/v1/profiles/{profile['id']}/translations/{locale}/",
        {"expected_version": version, **values},
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )


def test_the_index_reads_its_languages_from_the_profile(settings: Any) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")

    built = search_index.index_settings()

    assert built["localizedAttributes"] == [
        {"attributePatterns": ["*_pl"], "locales": ["pol"]},
        {"attributePatterns": ["*_en"], "locales": ["eng"]},
        {"attributePatterns": ["*_de"], "locales": ["deu"]},
        {"attributePatterns": ["*"], "locales": ["pol", "eng", "deu"]},
    ]
    assert "headline_de" in built["searchableAttributes"]
    assert "bio_de" in built["searchableAttributes"]
    assert not any(name.endswith("_*") for name in built["searchableAttributes"])


def test_a_card_is_searchable_in_a_language_only_when_it_is_whole_in_it(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any, settings: Any
) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    client, organization = _published(
        "szukaj-niemiecki",
        django_capture_on_commit_callbacks,
        headline="Fryzjer w centrum",
        bio="Strzyżemy od 1990 roku.",
    )
    _languages(organization, ["pl", "de"])

    with django_capture_on_commit_callbacks(execute=True):
        assert _translate(client, "de", headline="Friseur im Zentrum").status_code == 200
    half = _document(engine, organization)
    assert half is not None
    assert "headline_de" not in half

    with django_capture_on_commit_callbacks(execute=True):
        assert _translate(client, "de", bio="Wir schneiden seit 1990.").status_code == 200
    whole = _document(engine, organization)
    assert whole is not None
    assert (whole["headline_de"], whole["bio_de"]) == (
        "Friseur im Zentrum",
        "Wir schneiden seit 1990.",
    )
    found = APIClient().get(CATALOG_URL, {"q": "Zentrum", "locale": "de"}).data
    assert [item["headline"] for item in found["items"]] == ["Friseur im Zentrum"]
    # The page's language goes with the words, so the engine reads them as German.
    assert engine.searches[-1]["locales"] == ["deu"]


def test_a_vet_is_found_by_its_german_trade(
    engine: FakeEngine, django_capture_on_commit_callbacks: Any, settings: Any
) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    _client, organization = _published(
        "szukaj-weterynarz",
        django_capture_on_commit_callbacks,
        category="zwierzeta",
        headline="Przychodnia dla psów i kotów",
    )

    found = APIClient().get(CATALOG_URL, {"q": "Tierarzt", "locale": "de"}).data

    assert [item["display_name"] for item in found["items"]] == [organization.name]


def test_every_registry_language_has_the_name_the_engine_keeps() -> None:
    """A language without one would be written as `xx`, read back as `xxx`,
    and the settings patched on every sync."""
    for code in settings.LOCALE_REGISTRY:
        assert len(search_index.search_locale(code)) == 3, code
