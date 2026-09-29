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
from saas_core.modules.shared.profiles import search_engine, search_index
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
        words = search_index.fold(body["q"]).lower().split()
        hits = []
        for document in self.index(index):
            text = search_index.fold(
                json.dumps(
                    [
                        document[field]
                        for field in search_index.INDEX_SETTINGS["searchableAttributes"]
                    ],
                    ensure_ascii=False,
                )
            ).lower()
            if all(word in text for word in words) and self._passes(document, body):
                hits.append({"id": document["id"]})
        start = (body["page"] - 1) * body["hitsPerPage"]
        return {"hits": hits[start : start + body["hitsPerPage"]], "totalHits": len(hits)}

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
