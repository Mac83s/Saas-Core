"""Seasons and closures (ADR-072 §5, B11 — ADR-078 pkt 17, phase 2b)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from saas_core.modules.shared.booking.availability import available_days, validate_start
from saas_core.modules.shared.booking.models import BookingClosure, BookingRule, Location
from saas_core.modules.shared.booking.rules import (
    copy_closures_to_next_year,
    copy_rules_to_next_year,
    delete_closure,
    next_year,
    rule_for,
    save_closure,
    save_rule,
)
from saas_core.modules.shared.booking.services import BookingVersionConflict
from saas_core.modules.shared.booking.setup import save_group, save_resource
from test_booking import catalog, membership, tenant
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    # Logins are throttled per client address, and the API tests log in.
    cache.clear()


def key() -> str:
    return str(uuid4())


def season(starts: str, ends: str, **scope: Any) -> dict[str, Any]:
    return {"starts_on": date.fromisoformat(starts), "ends_on": date.fromisoformat(ends), **scope}


def test_the_most_specific_season_applies_and_the_later_start_breaks_a_tie() -> None:
    owner = membership("sezony-pierwszenstwo")
    configured = catalog(owner)
    service = configured["service"]
    with tenant(owner):
        group = save_group(group_id=None, data={"name": "Domek"}, idempotency_key=key()).value
        unit = save_resource(
            resource_id=configured["resource"].id,
            data={"group_id": group.id},
            expected_version=1,
            idempotency_key=key(),
        ).value
        offer = save_rule(
            rule_id=None,
            data={**season("2027-06-01", "2027-09-30", service_id=service.id), "min_length": 2},
            idempotency_key=key(),
        ).value
        july = save_rule(
            rule_id=None,
            data={
                **season("2027-07-01", "2027-08-31", service_id=service.id),
                "min_length": 7,
                "length_multiple": 7,
                "start_weekdays": [6, 5, 5],
            },
            idempotency_key=key(),
        ).value
        grouped = save_rule(
            rule_id=None,
            data={**season("2027-08-01", "2027-08-31", group_id=group.id), "min_length": 3},
            idempotency_key=key(),
        ).value
        own = save_rule(
            rule_id=None,
            data={**season("2027-08-15", "2027-08-20", resource_id=unit.id), "closed": True},
            idempotency_key=key(),
        ).value
        rules = list(BookingRule.all_objects.filter(organization=owner.organization))
    assert july.start_weekdays == [5, 6]

    def applies(day: str) -> BookingRule | None:
        return rule_for(
            rules,
            day=date.fromisoformat(day),
            service_id=service.id,
            group_id=group.id,
            resource_id=unit.id,
        )

    assert applies("2027-06-10") == offer
    # Two of the offer's own seasons: the later start.
    assert applies("2027-07-10") == july
    assert applies("2027-08-05") == grouped
    assert applies("2027-08-16") == own
    assert applies("2027-10-01") is None
    # Another unit of no group gets only the offer's seasons.
    assert (
        rule_for(rules, day=date(2027, 8, 16), service_id=service.id, resource_id=uuid4()) == july
    )


def test_a_season_is_checked_before_it_is_kept() -> None:
    owner = membership("sezony-odmowy")
    stranger = membership("sezony-obcy")
    configured = catalog(owner)
    foreign = catalog(stranger)
    with tenant(owner):
        for data, field in (
            (season("2027-01-01", "2027-01-31"), "service_id"),
            (
                season(
                    "2027-01-01",
                    "2027-01-31",
                    service_id=configured["service"].id,
                    resource_id=configured["resource"].id,
                ),
                "service_id",
            ),
            (season("2027-01-01", "2027-01-31", service_id=foreign["service"].id), "service_id"),
            (season("2027-02-01", "2027-01-31", service_id=configured["service"].id), "ends_on"),
            (
                {
                    **season("2027-01-01", "2027-01-31", service_id=configured["service"].id),
                    "min_length": 5,
                    "max_length": 3,
                },
                "max_length",
            ),
        ):
            with pytest.raises(ValidationError) as refused:
                save_rule(rule_id=None, data=data, idempotency_key=key())
            assert field in refused.value.detail, data
    assert not BookingRule.all_objects.filter(organization=owner.organization).exists()


def test_a_closure_takes_the_days_out_of_every_calendar() -> None:
    owner = membership("zamkniecia")
    configured = catalog(owner)
    service, location, day = configured["service"], configured["location"], configured["date"]
    with tenant(owner):
        other = Location.all_objects.create(
            organization=owner.organization, name="Filia", public_slug="filia"
        )
        assert available_days(
            service_id=service.id, location_id=location.id, from_date=day, to_date=day
        ) == [day]
        starts_at = datetime(day.year, day.month, day.day, 9, tzinfo=ZoneInfo("Europe/Warsaw"))
        start = {
            "service": service,
            "location": location,
            "starts_at": starts_at,
            "staff_id": configured["staff"].id,
            "resource_id": configured["resource"].id,
        }
        assert validate_start(**start)
        # Another place's closure leaves this one open.
        save_closure(
            closure_id=None,
            data={"starts_on": day, "ends_on": day, "location_id": other.id},
            idempotency_key=key(),
        )
        assert available_days(
            service_id=service.id, location_id=location.id, from_date=day, to_date=day
        ) == [day]
        closure = save_closure(
            closure_id=None,
            data={"starts_on": day - timedelta(days=1), "ends_on": day, "note": "Wigilia"},
            idempotency_key=key(),
        ).value
        assert available_days(
            service_id=service.id,
            location_id=location.id,
            from_date=day,
            to_date=day + timedelta(days=7),
        ) == [day + timedelta(days=7)]
        # Neither the website nor the panel books a start on a closed day.
        assert not validate_start(**start)
        with pytest.raises(BookingVersionConflict):
            delete_closure(closure_id=closure.id, expected_version=2, idempotency_key=key())
        delete_closure(closure_id=closure.id, expected_version=1, idempotency_key=key())
        assert available_days(
            service_id=service.id, location_id=location.id, from_date=day, to_date=day
        ) == [day]


def test_copy_to_next_year_makes_new_items_and_a_preview_only_counts() -> None:
    owner = membership("sezony-kopia")
    configured = catalog(owner)
    with tenant(owner):
        save_rule(
            rule_id=None,
            data={**season("2028-02-29", "2028-03-10", service_id=configured["service"].id)},
            idempotency_key=key(),
        )
        save_closure(
            closure_id=None,
            data={"starts_on": date(2028, 12, 24), "ends_on": date(2028, 12, 26)},
            idempotency_key=key(),
        )
        counted = copy_rules_to_next_year(year=2028, preview=True)
        assert len(counted.value) == 1
        assert BookingRule.all_objects.filter(organization=owner.organization).count() == 1
        copy_rules_to_next_year(year=2028, idempotency_key="kopia-2028")
        copy_rules_to_next_year(year=2028, idempotency_key="kopia-2028")
        copy_closures_to_next_year(year=2028, idempotency_key=key())
    seasons = BookingRule.all_objects.filter(organization=owner.organization).order_by("starts_on")
    assert [(item.starts_on, item.ends_on) for item in seasons] == [
        (date(2028, 2, 29), date(2028, 3, 10)),
        (date(2029, 2, 28), date(2029, 3, 10)),
    ]
    assert sorted(
        BookingClosure.all_objects.filter(organization=owner.organization).values_list(
            "starts_on", flat=True
        )
    ) == [date(2028, 12, 24), date(2029, 12, 24)]
    assert next_year(date(2027, 7, 3)) == date(2028, 7, 3)


def test_the_seasons_api_answers_management() -> None:
    _, owner, client = authenticated_member(
        email="sezony-api@example.test", role_key="owner", slug="sezony-api"
    )
    bookable(owner.organization)
    configured = catalog(owner)
    csrf = csrf_value(client)

    def headers() -> dict[str, str]:
        return {"HTTP_X_CSRFTOKEN": csrf, "HTTP_IDEMPOTENCY_KEY": key()}

    made = client.post(
        "/api/v1/booking/setup/rules/",
        {
            "name": "Sezon wysoki",
            "service_id": str(configured["service"].id),
            "starts_on": "2027-07-01",
            "ends_on": "2027-08-31",
            "min_length": 7,
            "length_multiple": 7,
            "start_weekdays": [5, 6],
        },
        format="json",
        **headers(),
    )
    assert made.status_code == 201, made.data
    preview = client.post(
        f"/api/v1/booking/setup/rules/{made.json()['id']}/preview/",
        {"min_length": 3, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert preview.json()["changes"] == {"min_length": {"from": 7, "to": 3}}
    assert [
        item["name"] for item in client.get("/api/v1/booking/setup/rules/").json()["items"]
    ] == ["Sezon wysoki"]
    copy = client.post(
        "/api/v1/booking/setup/rules/copy-year/", {"year": 2027}, format="json", **headers()
    )
    assert (copy.status_code, copy.json()["count"]) == (201, 1)
    gone = client.delete(f"/api/v1/booking/setup/rules/{made.json()['id']}/", **headers())
    assert gone.status_code == 400
    gone = client.delete(
        f"/api/v1/booking/setup/rules/{made.json()['id']}/?expected_version=1", **headers()
    )
    assert gone.status_code == 204
    closure = client.post(
        "/api/v1/booking/setup/closures/",
        {"starts_on": "2027-12-24", "ends_on": "2027-12-26", "note": "Święta"},
        format="json",
        **headers(),
    )
    assert closure.status_code == 201, closure.data
    assert client.get("/api/v1/booking/setup/closures/").json()["items"][0]["note"] == "Święta"
