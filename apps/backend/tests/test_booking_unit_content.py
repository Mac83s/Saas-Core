"""A unit as content (ADR-072, „Rozstrzygnięcia plastra 5c”): the company
says what a guest sees of a unit — whether it is shown, its address, town,
what it has and its pictures — and a guest gets that of the units it shows
only, with „od X zł/noc” from the quote and each picture at the form's own
address. An offer booked from–to has a booking window of its own."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.api import shown_media_ids
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.models import Resource, Service
from saas_core.modules.shared.booking.periods import StayRefused, plan_stay, stay_starts
from saas_core.modules.shared.booking.rules import save_rule
from saas_core.modules.shared.booking.setup import save_resource, save_service
from saas_core.modules.shared.booking.unit_content import MAX_UNIT_PHOTOS, UNIT_AMENITIES
from saas_core.modules.shared.media.models import MediaAsset
from saas_core.modules.shared.media.services import cleanup_tombstoned_media_asset
from test_booking import _no_delivery, company_today, tenant
from test_booking_prices import add, key
from test_booking_public_stays import form
from test_media_api import MemoryStorage, create_ready_asset
from test_organization_lifecycle import csrf_value
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> MemoryStorage:
    """Where the pictures' bytes are, in place of the object store."""
    memory = MemoryStorage()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: memory
    )
    return memory


def picture(owner: Membership, storage: MemoryStorage | None = None, name: str = "foto") -> Any:
    """A picture in the company's media library, scanned and ready."""
    # The library is the plan's too: room for files beside the bookings.
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    snapshot.features = {**snapshot.features, "storage.enabled": True}
    snapshot.quotas = {**snapshot.quotas, "storage.bytes": 10 * 1024**2}
    snapshot.sources = {
        **snapshot.sources,
        "storage.enabled": {"kind": "plan"},
        "storage.bytes": {"kind": "plan"},
    }
    snapshot.save()
    asset = create_ready_asset(owner.organization, owner.user, suffix=f"{name}-{uuid7().hex[:6]}")
    if storage is not None:
        for kind, variant in asset.variants.items():
            storage.objects[variant["object_key"]] = (kind.encode(), "image/webp")
        storage.objects[asset.object_key] = (b"original", "image/jpeg")
    return asset


def delete_from_library(owner: Membership, asset: Any) -> None:
    """The asset as `tombstone_media_asset` leaves it."""
    MediaAsset.all_objects.filter(pk=asset.id).update(
        deleted_at=timezone.now(),
        deleted_by=owner.user,
        deletion_idempotency_key=f"delete-{asset.id}",
    )


def change(owner: Membership, unit: Resource, **data: Any) -> Resource:
    with tenant(owner):
        return save_resource(
            resource_id=unit.id,
            data=data,
            expected_version=Resource.all_objects.get(pk=unit.id).version,
            idempotency_key=key(),
        ).value


def refused(owner: Membership, unit: Resource, **data: Any) -> tuple[str, str]:
    """The field and the code a change is refused with."""
    with pytest.raises(ValidationError) as error:
        change(owner, unit, **data)
    (problem,) = problem_errors(error.value)
    return problem["field"], problem["code"]


def stays(configured: dict[str, Any], locale: str | None = None) -> Any:
    answer = APIClient().get(f"{configured['url']}/", {"locale": locale} if locale else {})
    assert answer.status_code == 200
    return answer.json()["stays"]


def test_the_company_sets_what_a_guest_sees_of_a_unit() -> None:
    configured = form("tresc-jednostki", priced=False, units=2)
    owner: Membership = configured["owner"]
    first, second = configured["units"]
    photos = [picture(owner, name=f"f{n}") for n in range(2)]

    shown = change(
        owner,
        first,
        public=True,
        amenities=["sauna", "wifi", "sauna"],
        city_slug="mragowo",
        latitude=Decimal("53.864500"),
        longitude=Decimal("21.305000"),
        photo_ids=[photos[1].id, photos[0].id, photos[1].id],
    )
    # A unit shown to guests has an address — from its name when none was
    # typed; what it has is kept in the list's own order, each picture once
    # and in the order given.
    assert (shown.public, shown.public_slug, shown.city_slug) == (True, "domek-1", "mragowo")
    assert shown.amenities == ["wifi", "sauna"]
    assert shown.photos == [photos[1].id, photos[0].id]
    assert (shown.latitude, shown.longitude) == (Decimal("53.864500"), Decimal("21.305000"))
    assert shown.version == 2
    entry = OrganizationAuditEntry.objects.filter(
        organization=owner.organization, target_id=first.id
    ).latest("occurred_at")
    assert set(entry.metadata["changes"]) == {
        "public",
        "public_slug",
        "amenities",
        "city_slug",
        "latitude",
        "longitude",
        "photos",
    }
    # The same values again change nothing: no new version.
    assert change(owner, first, amenities=["wifi", "sauna"], public=True).version == 2

    # An address is the company's to choose, one per unit.
    renamed = change(owner, first, public_slug="Domek nad Jeziorem")
    assert renamed.public_slug == "domek-nad-jeziorem"
    assert refused(owner, second, public_slug="domek-nad-jeziorem") == ("public_slug", "slug_taken")
    # A unit that is not shown needs none, and keeps the one it had.
    hidden = change(owner, first, public=False)
    assert (hidden.public, hidden.public_slug) == (False, "domek-nad-jeziorem")

    assert refused(owner, second, amenities=["wifi", "basen-olimpijski"]) == (
        "amenities",
        "amenity_unknown",
    )
    assert refused(owner, second, city_slug="nibylandia") == ("city_slug", "city_unknown")
    assert refused(owner, second, latitude=Decimal("53.8")) == (
        "longitude",
        "coordinates_incomplete",
    )
    too_many = [uuid7() for _ in range(MAX_UNIT_PHOTOS + 1)]
    assert refused(owner, second, photo_ids=too_many) == ("photo_ids", "photos_too_many")
    # „Pokaż dokładne położenie” needs a point to show — when it is switched
    # on, and when the point is taken away under it.
    assert first.show_exact_location is False
    assert refused(owner, second, show_exact_location=True) == (
        "show_exact_location",
        "coordinates_missing",
    )
    pinned = change(owner, first, show_exact_location=True)
    assert (pinned.show_exact_location, pinned.version) == (True, hidden.version + 1)
    assert refused(owner, first, latitude=None, longitude=None) == (
        "show_exact_location",
        "coordinates_missing",
    )
    cleared = change(owner, first, latitude=None, longitude=None, show_exact_location=False)
    assert (cleared.show_exact_location, cleared.latitude) == (False, None)
    # Nothing of a refused change was kept.
    with tenant(owner):
        untouched = Resource.all_objects.get(pk=second.id)
    assert (untouched.version, untouched.amenities, untouched.city_slug) == (1, [], "")


def test_a_units_picture_comes_from_the_companys_own_library() -> None:
    configured = form("tresc-zdjecia", priced=False)
    other = form("tresc-zdjecia-cudze", priced=False)
    owner: Membership = configured["owner"]
    (unit,) = configured["units"]
    mine, gone = picture(owner), picture(owner, name="usuniete")
    foreign = picture(other["owner"])

    # Not a file at all, another company's, or one deleted from the library.
    delete_from_library(owner, gone)
    for missing in (uuid7(), foreign.id, gone.id):
        assert refused(owner, unit, photo_ids=[mine.id, missing]) == (
            "photo_ids",
            "photo_unavailable",
        )
    assert change(owner, unit, photo_ids=[mine.id]).photos == [mine.id]
    # A picture the unit already shows stays when it is deleted from the
    # library later: only a new one has to be available.
    delete_from_library(owner, mine)
    assert change(owner, unit, photo_ids=[mine.id], amenities=["wifi"]).photos == [mine.id]


def test_the_panel_reads_and_writes_a_units_content_over_the_api() -> None:
    configured = form("tresc-api", priced=False)
    owner: Membership = configured["owner"]
    (unit,) = configured["units"]
    photo = picture(owner)
    client = authenticated_client(owner)
    client.get("/api/v1/auth/csrf/")
    csrf = csrf_value(client)

    listed = client.get("/api/v1/booking/setup/").json()
    # What can be picked is read, not known: the list with its words, the bound.
    options = listed["unit_options"]
    assert [item["key"] for item in options["amenities"]] == [key for key, _ in UNIT_AMENITIES]
    assert options["amenities"][0]["label"] == {"pl": "Wi-Fi", "en": "Wi-Fi", "de": "WLAN"}
    assert options["max_photos"] == MAX_UNIT_PHOTOS
    (before,) = listed["resources"]
    assert {name: before[name] for name in ("public", "public_slug", "amenities", "photo_ids")} == {
        "public": False,
        "public_slug": "",
        "amenities": [],
        "photo_ids": [],
    }

    body = {
        "public": True,
        "amenities": ["fireplace"],
        "city_slug": "mragowo",
        "latitude": "53.8645",
        "longitude": "21.305",
        "show_exact_location": True,
        "photo_ids": [str(photo.id)],
        "expected_version": 1,
    }
    assert before["show_exact_location"] is False
    url = f"/api/v1/booking/setup/resources/{unit.id}/"
    preview = client.post(f"{url}preview/", body, format="json", HTTP_X_CSRFTOKEN=csrf)
    assert preview.status_code == 200, preview.data
    assert preview.json()["public_slug"] == "domek-1"
    with tenant(owner):
        assert Resource.all_objects.get(pk=unit.id).public is False
    saved = client.patch(
        url, body, format="json", HTTP_X_CSRFTOKEN=csrf, HTTP_IDEMPOTENCY_KEY=key()
    )
    assert saved.status_code == 200, saved.data
    assert saved.json() | {"version": 2} == saved.json()
    assert (saved.json()["latitude"], saved.json()["longitude"]) == (53.8645, 21.305)
    assert saved.json()["show_exact_location"] is True
    assert saved.json()["photo_ids"] == [str(photo.id)]
    # Out of range, and one coordinate without the other, by field.
    wrong = client.patch(
        url,
        {"latitude": "123", "expected_version": 2},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert (wrong.status_code, wrong.json()["errors"][0]["field"]) == (400, "latitude")


def test_a_guest_sees_the_content_of_the_units_the_company_shows(storage: MemoryStorage) -> None:
    configured = form("tresc-katalog", priced=False, units=2)
    owner: Membership = configured["owner"]
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["pl", "en"])
    first, second = configured["units"]
    cover, inside = picture(owner, storage, "okladka"), picture(owner, storage, "wnetrze")
    with tenant(owner):
        apartment = save_resource(
            resource_id=None,
            data={"name": "Apartament", "location_id": configured["place"].id, "capacity": 2},
            idempotency_key=key(),
        ).value
        offer = Service.all_objects.get(pk=configured["service"].id)
        save_service(
            service_id=offer.id,
            data={"resource_ids": [apartment.id]},
            expected_version=offer.version,
            idempotency_key=key(),
        )
    # „Domek 2” is the cottage the company shows; „Domek 1” and the apartment
    # are booked by their names alone.
    change(
        owner,
        second,
        public=True,
        amenities=["fireplace", "wifi"],
        city_slug="mragowo",
        latitude=Decimal("53.8645"),
        longitude=Decimal("21.305"),
        photo_ids=[cover.id, inside.id],
    )
    change(owner, first, amenities=["sauna"], photo_ids=[inside.id])
    change(owner, apartment, amenities=["tv"], city_slug="olsztyn")

    (stay,) = stays(configured)
    (group,) = stay["groups"]
    (unit,) = stay["units"]
    base = f"/api/v1/booking/public/tresc-katalog/photos/{cover.id}"
    # The group speaks with its first unit the company shows.
    assert group["photos"][0] == {
        "id": str(cover.id),
        "thumbnail_url": f"{base}/thumbnail/",
        "preview_url": f"{base}/preview/",
    }
    assert [photo["id"] for photo in group["photos"]] == [str(cover.id), str(inside.id)]
    assert group["amenities"] == [
        {"key": "wifi", "label": "Wi-Fi"},
        {"key": "fireplace", "label": "Kominek"},
    ]
    assert group["town"] == {"slug": "mragowo", "name": "Mrągowo"}
    # A unit that is not shown gives a guest nothing but its name.
    assert (unit["photos"], unit["amenities"], unit["town"], unit["public_slug"]) == (
        [],
        [],
        None,
        "",
    )
    # Where a unit is exactly never leaves the server towards a guest.
    whole = json.dumps(APIClient().get(f"{configured['url']}/").json())
    assert "latitude" not in whole and "53.86" not in whole and "21.30" not in whole

    # In English where the list has the word.
    (english,) = stays(configured, "en")
    assert english["groups"][0]["amenities"][1] == {"key": "fireplace", "label": "Fireplace"}

    change(owner, apartment, public=True)
    assert stays(configured)[0]["units"][0] | {
        "public_slug": "apartament",
        "amenities": [{"key": "tv", "label": "Telewizor"}],
        "town": {"slug": "olsztyn", "name": "Olsztyn"},
    } == stays(configured)[0]["units"][0]


def test_from_x_a_night_is_the_quotes_lowest_price_of_one_night() -> None:
    configured = form("tresc-od-ceny", priced=False, units=2)
    owner: Membership = configured["owner"]
    first, second = configured["units"]
    today = company_today()
    assert stays(configured)[0]["groups"][0]["from_price"] is None

    with tenant(owner):
        # 300 gross a night for the offer, 250 in a season that begins in a
        # month, and one cottage dearer than the other all year.
        add(30000, "per_time_unit", service_id=configured["service"].id)
        add(
            25000,
            "per_time_unit",
            service_id=configured["service"].id,
            starts_on=today + timedelta(days=30),
            ends_on=today + timedelta(days=60),
        )
        add(40000, "per_time_unit", resource_id=first.id)
    lowest = stays(configured)[0]["groups"][0]["from_price"]
    assert lowest == {"gross_minor": 25000, "currency": "PLN", "per": "night"}

    with tenant(owner):
        # A season past the year the announcement looks at does not lower it.
        add(
            10000,
            "per_time_unit",
            service_id=configured["service"].id,
            starts_on=today + timedelta(days=400),
            ends_on=today + timedelta(days=420),
        )
    assert stays(configured)[0]["groups"][0]["from_price"] == lowest


def test_a_price_charged_once_is_said_without_per_night() -> None:
    configured = form("tresc-od-ceny-raz", priced=False)
    with tenant(configured["owner"]):
        add(90000, "per_booking", service_id=configured["service"].id)
    assert stays(configured)[0]["groups"][0]["from_price"] == {
        "gross_minor": 90000,
        "currency": "PLN",
        "per": "stay",
    }


def test_a_picture_is_served_only_for_a_unit_the_company_shows(storage: MemoryStorage) -> None:
    """The rows of the authorization matrix of the picture's public address:
    the company's own picture of a unit it shows and has switched on, in one
    of our copies; 404 for every other picture, whatever the reason; and 403
    where the company's plan has no booking, as its form answers."""
    configured = form("tresc-foto", priced=False, units=2)
    other = form("tresc-foto-cudze", priced=False)
    owner: Membership = configured["owner"]
    shown, hidden = configured["units"]
    cover, private, loose = (picture(owner, storage, name) for name in ("a", "b", "c"))
    foreign = picture(other["owner"], storage, "cudze")
    change(owner, shown, public=True, photo_ids=[cover.id])
    change(owner, hidden, photo_ids=[private.id])
    change(other["owner"], other["units"][0], public=True, photo_ids=[foreign.id])
    client = APIClient()

    def get(slug: str, asset: Any, variant: str = "preview") -> Any:
        return client.get(f"/api/v1/booking/public/{slug}/photos/{asset}/{variant}/")

    statements: list[str] = []

    def note(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        statements.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(note):
        served = get("tresc-foto", cover.id)
    assert served.status_code == 200
    assert (served["Content-Type"], served.content) == ("image/webp", b"preview")
    assert served["Cache-Control"] == "public, max-age=31536000, immutable"
    assert get("tresc-foto", cover.id, "thumbnail").content == b"thumbnail"
    # The tenant is set before the first read of a tenant's table (RLS): the
    # address names the company, nothing else does.
    tenant_set = next(i for i, sql in enumerate(statements) if "app.organization_id" in sql)
    first_read = next(
        i for i, sql in enumerate(statements) if "booking_resource" in sql or "media_" in sql
    )
    assert tenant_set < first_read

    not_served = {
        "the original, or a copy we do not make": get("tresc-foto", cover.id, "original"),
        "a unit that is not shown": get("tresc-foto", private.id),
        "a picture no unit lists": get("tresc-foto", loose.id),
        "no such file": get("tresc-foto", uuid7()),
        "another company's picture through this form": get("tresc-foto", foreign.id),
        "this company's picture through another form": get("tresc-foto-cudze", cover.id),
        "no such form": get("nie-ma-takiej", cover.id),
    }
    assert {why: answer.status_code for why, answer in not_served.items()} == dict.fromkeys(
        not_served, 404
    )
    assert all(answer.content == b"" for answer in not_served.values())
    # The other company's own form serves its own.
    assert get("tresc-foto-cudze", foreign.id).status_code == 200

    # Switched off, the unit shows nothing; and a plan without booking has no form.
    change(owner, shown, active=False)
    assert get("tresc-foto", cover.id).status_code == 404
    change(owner, shown, active=True)
    assert get("tresc-foto", cover.id).status_code == 200
    EntitlementSnapshot.all_objects.filter(organization_id=owner.organization_id).update(
        features={}
    )
    cache.clear()
    lost = get("tresc-foto", cover.id)
    assert (lost.status_code, lost.content) == (403, b"")


def test_a_picture_a_unit_shows_outlives_its_deletion_from_the_library(
    storage: MemoryStorage,
) -> None:
    configured = form("tresc-sprzatanie", priced=False)
    owner: Membership = configured["owner"]
    (unit,) = configured["units"]
    photo = picture(owner, storage)
    change(owner, unit, public=True, photo_ids=[photo.id])
    with tenant(owner):
        assert shown_media_ids(owner.organization_id) == {photo.id}

    # Deleted from the library while the unit shows it: the objects stay, and
    # the guest still gets the picture.
    delete_from_library(owner, photo)
    with tenant(owner):
        kept = cleanup_tombstoned_media_asset(asset_id=photo.id, storage=storage)
    assert kept is not None and kept.cleanup_completed_at is None
    assert storage.delete_calls == []
    url = f"/api/v1/booking/public/tresc-sprzatanie/photos/{photo.id}/thumbnail/"
    assert APIClient().get(url).status_code == 200

    # The unit lets it go: nothing holds the objects any more.
    change(owner, unit, photo_ids=[])
    assert APIClient().get(url).status_code == 404
    with tenant(owner):
        assert shown_media_ids(owner.organization_id) == set()
        cleaned = cleanup_tombstoned_media_asset(asset_id=photo.id, storage=storage)
    assert cleaned is not None and cleaned.cleanup_completed_at is not None
    assert storage.objects == {}


def test_an_offer_without_a_season_has_a_booking_window_of_its_own() -> None:
    configured = form("tresc-okno", priced=False)
    owner: Membership = configured["owner"]
    today = company_today()
    target = {"service_id": configured["service"].id, "group_id": configured["group"].id}

    def last_start() -> Any:
        with tenant(owner):
            days = stay_starts(
                **target, from_date=today, to_date=today + timedelta(days=120)
            )
        return max(days)

    def window(days: int | None) -> None:
        with tenant(owner):
            offer = Service.all_objects.get(pk=configured["service"].id)
            save_service(
                service_id=offer.id,
                data={"booking_window_days": days},
                expected_version=offer.version,
                idempotency_key=key(),
            )

    assert last_start() == today + timedelta(days=120)
    window(30)
    assert last_start() == today + timedelta(days=30)
    with tenant(owner), pytest.raises(StayRefused) as late:
        plan_stay(
            **target,
            start_date=today + timedelta(days=31),
            end_date=today + timedelta(days=33),
        )
    assert problem_errors(late.value)[0]["code"] == "rule_window"

    # A season's own window comes first, wider or narrower than the offer's.
    with tenant(owner):
        save_rule(
            rule_id=None,
            data={
                "service_id": configured["service"].id,
                "name": "Lato",
                "starts_on": today + timedelta(days=40),
                "ends_on": today + timedelta(days=100),
                "window_days": 60,
            },
            idempotency_key=key(),
        )
    assert last_start() == today + timedelta(days=60)
    # Empty again: only the platform's bound.
    window(None)
    assert last_start() == today + timedelta(days=120)
    listed = authenticated_client(owner).get("/api/v1/booking/setup/options/").json()["keys"]
    (option,) = [item for item in listed if item["key"] == "booking.offer.booking_window_days"]
    assert (option["minimum"], option["maximum"], option["default"]) == (1, 731, None)
