"""Stays: a range offer booked from–to on a unit (ADR-072 §1–§5, phase 2c)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.http.exceptions import problem_errors
from saas_core.modules.shared.booking.dispatch import assign_crew
from saas_core.modules.shared.booking.models import Appointment, AppointmentStatus, Service
from saas_core.modules.shared.booking.periods import (
    StayPlan,
    book_stay,
    move_stay,
    stay_ends,
    stay_starts,
)
from saas_core.modules.shared.booking.rules import save_closure, save_rule
from saas_core.modules.shared.booking.services import (
    SlotUnavailable,
    cancel_appointment,
    create_appointment,
    reschedule_appointment,
)
from saas_core.modules.shared.booking.setup import (
    save_group,
    save_location,
    save_resource,
    save_service,
)
from saas_core.modules.shared.booking.units import add_unit_block
from test_booking import membership, tenant
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    # Logins are throttled per client address, and the API tests log in.
    cache.clear()


WARSAW = ZoneInfo("Europe/Warsaw")
GUEST = {"display_name": "Gość", "email": "gosc@example.test"}


def key() -> str:
    return str(uuid4())


def saturday_after(days: int) -> date:
    day = timezone.localdate() + timedelta(days=days)
    return day + timedelta(days=(5 - day.weekday()) % 7)


def cottages(member: Any, units: int = 2) -> dict[str, Any]:
    """A „Nocleg” offer on a group of identical cottages at one place."""
    with tenant(member):
        place = save_location(
            location_id=None, data={"name": "Mazury"}, idempotency_key=key()
        ).value
        group = save_group(group_id=None, data={"name": "Domek 6-os."}, idempotency_key=key()).value
        made = [
            save_resource(
                resource_id=None,
                data={
                    "name": f"Domek {n}",
                    "group_id": group.id,
                    "location_id": place.id,
                    "capacity": 6,
                },
                idempotency_key=key(),
            ).value
            for n in range(1, units + 1)
        ]
        offer = save_service(
            service_id=None,
            data={
                "name": "Pobyt w domku",
                "time_model": "range",
                "range_unit": "night",
                "staff_count": 0,
                "minimum_notice_minutes": 0,
                "group_ids": [group.id],
            },
            idempotency_key=key(),
        ).value.service
    return {"place": place, "group": group, "units": made, "service": offer}


def stay(setup: dict[str, Any], first: date, last: date, **extra: Any) -> Any:
    return book_stay(
        service_id=setup["service"].id,
        start_date=first,
        end_date=last,
        customer_data=GUEST,
        idempotency_key=extra.pop("idempotency_key", key()),
        principal_ref="test",
        **{"group_id": setup["group"].id, **extra},
    )


def codes(refused: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str | None, str | None]]:
    return [(error["field"], error["code"]) for error in problem_errors(refused.value)]


def test_a_range_offer_takes_its_shape_from_its_time_model() -> None:
    owner = membership("pobyty-oferta")
    setup = cottages(owner)
    offer: Service = setup["service"]
    assert (offer.duration_minutes, offer.staff_count) == (None, 0)
    # Check-in and check-out of the „Nocleg” preset when the offer names none.
    assert (offer.range_start_local, offer.range_end_local) == (time(16), time(11))
    with tenant(owner):
        with pytest.raises(ValidationError) as refused:
            save_service(
                service_id=None,
                data={"name": "Wizyta", "staff_count": 1},
                idempotency_key=key(),
            )
        assert codes(refused) == [("duration_minutes", "required")]
        with pytest.raises(ValidationError) as refused:
            save_service(
                service_id=None,
                data={"name": "Bez osoby", "duration_minutes": 30, "staff_count": 0},
                idempotency_key=key(),
            )
        assert codes(refused) == [("staff_count", "min_value")]
    first = saturday_after(30)
    with tenant(owner):
        stay(setup, first, first + timedelta(days=2))
        with pytest.raises(ValidationError) as refused:
            save_service(
                service_id=offer.id,
                data={"time_model": "slot", "duration_minutes": 60},
                expected_version=1,
                idempotency_key=key(),
            )
        assert codes(refused) == [("time_model", "time_model_locked")]


def test_a_group_hands_out_its_free_units_and_then_says_no() -> None:
    owner = membership("pobyty-grupa")
    setup = cottages(owner, units=2)
    first = saturday_after(30)
    last = first + timedelta(days=3)
    with tenant(owner):
        one = stay(setup, first, last, idempotency_key="pierwszy").appointment
        again = stay(setup, first, last, idempotency_key="pierwszy").appointment
        two = stay(setup, first, last).appointment
        with pytest.raises(SlotUnavailable):
            stay(setup, first + timedelta(days=1), last + timedelta(days=1))
    assert again.id == one.id
    assert {one.resource_id, two.resource_id} == {unit.id for unit in setup["units"]}
    # Check-in 16:00 on the arrival day, check-out 11:00 on the departure day.
    assert one.starts_at == datetime.combine(first, time(16), WARSAW)
    assert one.ends_at == datetime.combine(last, time(11), WARSAW)
    assert (one.staff_id, one.staff_required, one.location_id) == (None, 0, setup["place"].id)
    # A departure at 11:00 and an arrival at 16:00 the same day do not collide.
    with tenant(owner):
        following = stay(setup, last, last + timedelta(days=2)).appointment
    assert following.resource_id in {one.resource_id, two.resource_id}


def test_the_season_of_the_arrival_day_decides() -> None:
    owner = membership("pobyty-sezon")
    setup = cottages(owner, units=1)
    first = saturday_after(30)
    with tenant(owner):
        save_rule(
            rule_id=None,
            data={
                "name": "Sezon wysoki",
                "service_id": setup["service"].id,
                "starts_on": first - timedelta(days=14),
                "ends_on": first + timedelta(days=60),
                "min_length": 7,
                "length_multiple": 7,
                "start_weekdays": [5, 6],
            },
            idempotency_key=key(),
        )
        for start, end, expected in (
            (first, first + timedelta(days=3), ("end_date", "rule_min_length")),
            (first, first + timedelta(days=10), ("end_date", "rule_length_multiple")),
            (
                first + timedelta(days=2),
                first + timedelta(days=9),
                ("start_date", "rule_start_weekday"),
            ),
        ):
            with pytest.raises(ValidationError) as refused:
                stay(setup, start, end)
            assert codes(refused) == [expected]
        week = stay(setup, first, first + timedelta(days=7)).appointment
        assert week.status == AppointmentStatus.CONFIRMED
        save_closure(
            closure_id=None,
            data={"starts_on": first + timedelta(days=17), "ends_on": first + timedelta(days=17)},
            idempotency_key=key(),
        )
        with pytest.raises(ValidationError) as refused:
            stay(setup, first + timedelta(days=14), first + timedelta(days=21))
        assert codes(refused) == [("start_date", "closed_day")]


def test_the_calendar_offers_free_arrivals_and_the_departures_that_fit() -> None:
    owner = membership("pobyty-kalendarz")
    setup = cottages(owner, units=1)
    unit = setup["units"][0]
    first = saturday_after(30)
    with tenant(owner):
        stay(setup, first + timedelta(days=4), first + timedelta(days=6))
        add_unit_block(
            resource_id=unit.id,
            starts_at=datetime.combine(first + timedelta(days=9), time(12), WARSAW),
            ends_at=datetime.combine(first + timedelta(days=10), time(12), WARSAW),
            idempotency_key=key(),
        )
        starts = stay_starts(
            service_id=setup["service"].id,
            group_id=setup["group"].id,
            from_date=first,
            to_date=first + timedelta(days=11),
        )
        ends = stay_ends(service_id=setup["service"].id, resource_id=unit.id, start_date=first)
    day = {first + timedelta(days=n) for n in range(12)}
    # Nights 4 and 5 are booked, night 9 blocked (the block covers its check-in).
    assert set(starts) == day - {first + timedelta(days=n) for n in (4, 5, 9)}
    # From the first day the stay can last until the next guest arrives.
    assert ends == [first + timedelta(days=n) for n in range(1, 5)]


def test_a_stay_moves_by_its_dates_and_keeps_out_of_the_visit_paths() -> None:
    owner = membership("pobyty-zmiana")
    setup = cottages(owner, units=2)
    first = saturday_after(30)
    with tenant(owner):
        one = stay(setup, first, first + timedelta(days=2)).appointment
        later = first + timedelta(days=7)
        # Somebody takes the stay's unit on the new dates: the other one is free.
        stay(setup, later, later + timedelta(days=2), resource_id=one.resource_id)
        preview = move_stay(
            appointment_id=one.id,
            start_date=later,
            end_date=later + timedelta(days=2),
            idempotency_key="",
            principal_ref="test",
            preview=True,
        )
        assert isinstance(preview, StayPlan)
        moved = move_stay(
            appointment_id=one.id,
            start_date=later,
            end_date=later + timedelta(days=2),
            idempotency_key=key(),
            principal_ref="test",
        )
        assert isinstance(moved, Appointment)
        assert moved.resource_id != one.resource_id
        assert moved.starts_at == datetime.combine(later, time(16), WARSAW)
        with pytest.raises(ValidationError) as refused:
            reschedule_appointment(
                appointment_id=one.id,
                starts_at=moved.starts_at + timedelta(days=1),
                idempotency_key=key(),
                principal_ref="test",
            )
        assert codes(refused) == [("starts_at", "stay_moves_by_dates")]
        with pytest.raises(ValidationError) as refused:
            assign_crew(
                appointment_id=one.id,
                staff_ids=[],
                lead_id=None,
                expected_version=1,
                notify_staff=False,
                idempotency_key=key(),
                principal_ref="test",
            )
        assert codes(refused) == [("staff_ids", "no_people_needed")]
        with pytest.raises(ValidationError) as refused:
            create_appointment(
                service_id=setup["service"].id,
                location_id=setup["place"].id,
                starts_at=moved.starts_at,
                customer_data=GUEST,
                idempotency_key=key(),
                principal_ref="test",
            )
        assert codes(refused) == [("service_id", "not_a_slot_offer")]
        canceled = cancel_appointment(
            appointment_id=one.id, idempotency_key=key(), principal_ref="test"
        )
    assert canceled.status == AppointmentStatus.CANCELED


def test_the_stays_api_books_previews_and_lists_days() -> None:
    _, owner, client = authenticated_member(
        email="pobyty-api@example.test", role_key="owner", slug="pobyty-api"
    )
    bookable(owner.organization)
    setup = cottages(owner, units=1)
    first = saturday_after(30)
    csrf = csrf_value(client)
    body = {
        "service_id": str(setup["service"].id),
        "group_id": str(setup["group"].id),
        "start_date": first.isoformat(),
        "end_date": (first + timedelta(days=2)).isoformat(),
        "customer": GUEST,
    }
    preview = client.post(
        "/api/v1/booking/stays/preview/", body, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert preview.status_code == 200, preview.data
    assert (preview.json()["length"], preview.json()["resource_name"]) == (2, "Domek 1")
    made = client.post(
        "/api/v1/booking/stays/",
        body,
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert made.status_code == 201, made.data
    payload = made.json()
    assert (payload["staff_id"], payload["staff_name"], payload["time_model"]) == (
        None,
        None,
        "range",
    )
    taken = client.post(
        "/api/v1/booking/stays/preview/", body, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert (taken.status_code, taken.json()["code"]) == (409, "slot_unavailable")
    starts = client.get(
        "/api/v1/booking/stays/starts/",
        {
            "service_id": str(setup["service"].id),
            "from": first.isoformat(),
            "to": (first + timedelta(days=3)).isoformat(),
        },
    )
    assert starts.status_code == 200, starts.data
    assert first.isoformat() not in starts.json()["items"]
    listed = client.get("/api/v1/booking/appointments/")
    assert listed.status_code == 200
    # The visit calendar's catalogue keeps offering visits only.
    catalog = client.get("/api/v1/booking/catalog/").json()
    assert setup["service"].name not in {item["name"] for item in catalog["services"]}
