"""Booking items in the company's other languages (TL12b; ADR-069): a setup
write with a key, a version and a preview, a list of each language's state,
and the public form in the visitor's language. Needs no translation engine:
the product profiles compose booking without it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import time
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.booking.models import (
    PublicBookingRoute,
    Resource,
    Service,
    ServiceTranslation,
)
from saas_core.modules.shared.booking.teams import create_team
from test_booking import tenant
from test_booking_slots import team
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    cache.clear()  # logins are throttled per client address
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


def company(slug: str) -> dict[str, Any]:
    _, owner, client = authenticated_member(
        email=f"{slug}@example.test", role_key="owner", slug=slug
    )
    organization = owner.organization
    organization.public_locales = ["pl", "de"]
    organization.save(update_fields=["public_locales"])
    bookable(organization)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    configured.update(owner=owner, client=client, csrf=csrf_value(client))
    return configured


def put(configured: dict[str, Any], url: str, body: dict[str, Any], key: str | None) -> Any:
    headers = {"HTTP_X_CSRFTOKEN": configured["csrf"]}
    if key:
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return configured["client"].put(url, body, format="json", **headers)


def test_a_service_name_in_german_has_a_key_a_version_and_a_preview() -> None:
    configured = company("tl12b-write")
    service = configured["service"]
    url = f"/api/v1/booking/setup/translations/service/{service.id}/de/"
    body = {"texts": {"name": "Termin"}, "expected_version": 0}

    preview = configured["client"].post(
        f"{url}preview/", body, format="json", HTTP_X_CSRFTOKEN=configured["csrf"]
    )
    assert preview.status_code == 200, preview.data
    assert preview.json()["units"][0]["text"] == "Termin"
    assert not ServiceTranslation.all_objects.exists()

    assert put(configured, url, body, key=None).status_code == 400
    first_key = str(uuid4())
    saved = put(configured, url, body, key=first_key)
    assert saved.status_code == 200, saved.data
    assert saved.json()["version"] == 1
    assert saved.json()["units"] == [
        {
            "key": "name",
            "source_text": "Wizyta",
            "text": "Termin",
            "status": "fresh",
            "origin": "human",
        }
    ]
    # The same key answers again; a stale version is told, not overwritten.
    assert put(configured, url, body, key=first_key).json()["version"] == 1
    stale = put(configured, url, {"texts": {"name": "Besuch"}, "expected_version": 0}, str(uuid4()))
    assert (stale.status_code, stale.json()["code"]) == (409, "booking_version_conflict")
    assert OrganizationAuditEntry.objects.filter(
        organization=configured["owner"].organization, target_type="service_translation"
    ).exists()

    listing = configured["client"].get(f"/api/v1/booking/setup/translations/service/{service.id}/")
    assert listing.status_code == 200
    assert listing.json()["source_locale"] == "pl"
    assert [language["locale"] for language in listing.json()["languages"]] == ["de"]


def test_what_a_translation_may_not_be() -> None:
    configured = company("tl12b-refuse")
    service = configured["service"]
    base = f"/api/v1/booking/setup/translations/service/{service.id}"
    unknown = put(
        configured,
        f"{base}/de/",
        {"texts": {"description": "Opis"}, "expected_version": 0},
        str(uuid4()),
    )
    assert [error["code"] for error in unknown.json()["errors"]] == ["unknown_field"]
    own = put(
        configured, f"{base}/pl/", {"texts": {"name": "X"}, "expected_version": 0}, str(uuid4())
    )
    assert [error["code"] for error in own.json()["errors"]] == ["locale_is_source"]
    absent = put(
        configured, f"{base}/es/", {"texts": {"name": "X"}, "expected_version": 0}, str(uuid4())
    )
    assert absent.status_code == 400
    kind = configured["client"].get(f"/api/v1/booking/setup/translations/price/{service.id}/")
    assert kind.status_code == 404


def test_the_public_form_names_things_in_the_visitors_language() -> None:
    configured = company("tl12b-public")
    owner = configured["owner"]
    with tenant(owner):
        crew = create_team(name="Ekipa Południe", member_ids=[configured["staff"][0].id])
        Resource.all_objects.create(organization=owner.organization, name="Fotel")
        Service.all_objects.filter(pk=configured["service"].id).update(public_staff_choice="team")
    PublicBookingRoute.objects.create(
        public_slug="tl12b-public", organization_id=owner.organization_id
    )
    for kind, item_id, name in (
        ("service", configured["service"].id, "Termin"),
        ("location", configured["location"].id, "Zentrum"),
        ("team", crew.id, "Team Süd"),
    ):
        response = put(
            configured,
            f"/api/v1/booking/setup/translations/{kind}/{item_id}/de/",
            {"texts": {"name": name}, "expected_version": 0},
            str(uuid4()),
        )
        assert response.status_code == 200, response.data
    url = "/api/v1/booking/public/tl12b-public/"
    german = APIClient().get(url, {"locale": "de"}).json()
    assert german["locale"] == "de"
    assert [s["name"] for s in german["services"]] == ["Termin"]
    assert [x["name"] for x in german["locations"]] == ["Zentrum"]
    assert [r["name"] for r in german["resources"]] == ["Fotel"]  # not translated: its own
    assert [t["name"] for t in german["teams"]] == ["Team Süd"]
    polish = APIClient().get(url).json()
    assert (polish["locale"], polish["services"][0]["name"]) == ("pl", "Wizyta")
    assert APIClient().get(url, {"locale": "es"}).json()["locale"] == "pl"


@pytest.mark.parametrize(
    "table",
    [
        "booking_servicetranslation",
        "booking_locationtranslation",
        "booking_resourcetranslation",
        "booking_resourcegrouptranslation",
        "booking_staffteamtranslation",
    ],
)
def test_translation_tables_force_rls(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [table]
        )
        assert cursor.fetchone() == (True, True)
