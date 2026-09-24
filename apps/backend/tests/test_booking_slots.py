"""The slot engine in three parts and the server's pick of a person (ADR-058 §4, §5)."""

from __future__ import annotations

import contextlib
import threading
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from django.db import OperationalError, close_old_connections, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import Membership, Role, RoleScope
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.booking import availability, services
from saas_core.modules.shared.booking.availability import (
    available_days,
    available_slots,
    available_times,
    validate_start,
)
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    AvailabilityRule,
    Location,
    PublicBookingRoute,
    Resource,
    Service,
    ServiceLocation,
    ServiceStaff,
    StaffMember,
    TimeOff,
)
from saas_core.modules.shared.booking.security import public_booking_context
from saas_core.modules.shared.booking.services import SlotUnavailable, create_appointment
from test_booking import _no_delivery, catalog, membership, tenant
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)

WARSAW = ZoneInfo("Europe/Warsaw")


def team(
    member: Membership,
    *,
    people: int,
    hours: tuple[time, time],
    duration: int,
    weekdays: Iterable[int] = range(7),
) -> dict[str, Any]:
    """One service at one location, `people` doing it on the same hours, no resource."""
    with tenant(member):
        organization = member.organization
        location = Location.all_objects.create(
            organization=organization, name="Centrum", public_slug="centrum"
        )
        service = Service.all_objects.create(
            organization=organization,
            name="Wizyta",
            public_slug="wizyta",
            duration_minutes=duration,
            minimum_notice_minutes=0,
        )
        ServiceLocation.all_objects.create(
            organization=organization, service=service, location=location
        )
        staff = []
        for number in range(people):
            person = StaffMember.all_objects.create(
                organization=organization, display_name=f"Osoba {number}", public_slug=f"o{number}"
            )
            ServiceStaff.all_objects.create(
                organization=organization, service=service, staff=person
            )
            for weekday in weekdays:
                AvailabilityRule.all_objects.create(
                    organization=organization,
                    staff=person,
                    location=location,
                    weekday=weekday,
                    local_start=hours[0],
                    local_end=hours[1],
                )
            staff.append(person)
    return {"location": location, "service": service, "staff": sorted(staff, key=lambda x: x.id)}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), WARSAW)


def book(
    member: Membership,
    configured: dict[str, Any],
    starts_at: datetime,
    key: str,
    staff: StaffMember | None = None,
) -> Appointment:
    with tenant(member):
        return create_appointment(
            service_id=configured["service"].id,
            staff_id=staff.id if staff else None,
            location_id=configured["location"].id,
            resource_id=None,
            starts_at=starts_at,
            customer_data={"display_name": f"Klient {key}", "email": f"{key}@example.test"},
            idempotency_key=key,
            principal_ref=str(member.user_id),
        ).appointment


def test_a_busy_day_keeps_its_last_person_and_their_last_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three people 06:00–16:00 and a one-hour service are 327 starts a day.

    The search used to stop at 250 in the middle of the day, so the afternoon of
    the person with the highest id vanished — and booking it failed too,
    because a booking was checked against that same cut list.
    """
    _no_delivery(monkeypatch)
    member = membership("sloty-limit")
    configured = team(member, people=3, hours=(time(6), time(16)), duration=60)
    day = timezone.localdate() + timedelta(days=7)
    last = configured["staff"][-1]
    with tenant(member):
        slots = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=day,
            to_date=day + timedelta(days=1),
        )
    # The cut falls after the day that crossed the limit, never inside it.
    assert {slot.starts_at.astimezone(WARSAW).date() for slot in slots} == {day}
    assert Counter(slot.staff_id for slot in slots) == {
        person.id: 109 for person in configured["staff"]
    }
    assert max(slot.starts_at for slot in slots if slot.staff_id == last.id) == at(day, 15)
    assert book(member, configured, at(day, 15), "ostatni", staff=last).staff_id == last.id


def test_one_person_nine_to_five_offers_every_working_day_of_two_weeks(
    django_assert_max_num_queries: Any,
) -> None:
    member = membership("sloty-dni")
    configured = team(member, people=1, hours=(time(9), time(17)), duration=30, weekdays=range(5))
    start = timezone.localdate() + timedelta(days=1)
    horizon = [start + timedelta(days=n) for n in range(14)]
    query = {"service_id": configured["service"].id, "location_id": configured["location"].id}
    with tenant(member):
        with django_assert_max_num_queries(10):
            days = available_days(**query, from_date=start, to_date=horizon[-1])
        with django_assert_max_num_queries(10):
            times = available_times(**query, day=days[0])
        slots = available_slots(**query, from_date=start, to_date=horizon[-1])
    assert days == [day for day in horizon if day.weekday() < 5]
    assert len(times) == 91
    # 91 starts a day: the list ends with the third day whole, not 68 starts into it.
    per_day = Counter(slot.starts_at.astimezone(WARSAW).date() for slot in slots)
    assert list(per_day.values()) == [91, 91, 91]


def test_nobody_named_gets_the_least_busy_person_that_day_then_week_then_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("sloty-dobor")
    configured = team(member, people=2, hours=(time(8), time(16)), duration=60)
    first, second = configured["staff"]
    today = timezone.localdate()
    monday = today + timedelta(days=14 - today.weekday())
    wednesday = monday + timedelta(days=2)
    book(member, configured, at(monday, 8), "pon-1", staff=first)
    book(member, configured, at(monday, 10), "pon-2", staff=first)
    # Nobody works on Wednesday yet: the week decides, over the lower id.
    assert book(member, configured, at(wednesday, 12), "sr-1").staff_id == second.id
    # Second works on Wednesday now: the day decides, though first has the busier week.
    assert book(member, configured, at(wednesday, 14), "sr-2").staff_id == first.id
    # A new week and nobody booked in it: the id decides.
    assert book(member, configured, at(monday + timedelta(days=7), 12), "pon-3").staff_id == (
        first.id
    )


def test_the_pick_skips_a_person_on_time_off_or_off_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("sloty-pomija")
    configured = team(member, people=2, hours=(time(8), time(16)), duration=60)
    first, second = configured["staff"]
    day = timezone.localdate() + timedelta(days=7)
    following = day + timedelta(days=1)
    with tenant(member):
        TimeOff.all_objects.create(
            organization=member.organization, staff=first, starts_at=at(day, 8), ends_at=at(day, 12)
        )
        AvailabilityRule.all_objects.filter(staff=first, weekday=following.weekday()).update(
            local_end=time(12)
        )
    # First has the lowest id and the emptier week, but is off that morning ...
    assert book(member, configured, at(day, 9), "urlop").staff_id == second.id
    # ... and works only until noon the day after.
    assert book(member, configured, at(following, 14), "po-grafiku").staff_id == second.id
    with pytest.raises(SlotUnavailable):
        book(member, configured, at(day, 7), "przed-grafikiem")


def test_losing_a_person_to_a_concurrent_booking_moves_on_to_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forced, like the deadlock in test_booking: the real interleaving is below."""
    _no_delivery(monkeypatch)
    member = membership("sloty-nastepny")
    configured = team(member, people=2, hours=(time(8), time(16)), duration=60)
    first, second = configured["staff"]
    create = AppointmentStaffAllocation.all_objects.create

    def lose_first(**kwargs: Any) -> Any:
        if kwargs["staff_id"] == first.id:
            try:
                raise psycopg.errors.DeadlockDetected("deadlock detected")
            except psycopg.errors.DeadlockDetected as cause:
                raise OperationalError("deadlock detected") from cause
        return create(**kwargs)

    monkeypatch.setattr(AppointmentStaffAllocation.all_objects, "create", lose_first)
    booked = book(member, configured, at(timezone.localdate() + timedelta(days=7), 9), "drugi")
    assert booked.staff_id == second.id
    with tenant(member):
        # The attempt on the first person rolled back to its savepoint, row and all.
        assert list(Appointment.objects.values_list("staff_id", flat=True)) == [second.id]


@pytest.mark.parametrize(
    ("people", "outcomes"), [(2, ["created", "created"]), (1, ["conflict", "created"])]
)
def test_two_bookings_for_anybody_at_one_start_race_to_different_people(
    monkeypatch: pytest.MonkeyPatch, people: int, outcomes: list[str]
) -> None:
    _no_delivery(monkeypatch)
    member = membership(f"sloty-wyscig-{people}")
    configured = team(member, people=people, hours=(time(8), time(16)), duration=60)
    starts_at = at(timezone.localdate() + timedelta(days=7), 9)
    both_looked = threading.Barrier(2, timeout=60)
    free_at = services.free_at

    def free_at_then_wait(**kwargs: Any) -> Any:
        found = free_at(**kwargs)
        # Both saw the same people free: only the database can settle it now.
        both_looked.wait()
        return found

    monkeypatch.setattr(services, "free_at", free_at_then_wait)

    def attempt(number: int) -> str:
        close_old_connections()
        try:
            with public_booking_context(member.organization_id):
                create_appointment(
                    service_id=configured["service"].id,
                    location_id=configured["location"].id,
                    resource_id=None,
                    starts_at=starts_at,
                    customer_data={
                        "display_name": f"Klient {number}",
                        "email": f"client-{number}@example.test",
                    },
                    idempotency_key=f"wyscig-{number}",
                    principal_ref=f"public-{number}",
                )
            return "created"
        except SlotUnavailable:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, (1, 2))) == outcomes
    with tenant(member):
        staff = list(Appointment.objects.values_list("staff_id", flat=True))
    assert len(staff) == len(set(staff)) == outcomes.count("created")


def test_one_key_sent_twice_at_once_books_once_and_answers_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A double click, or a retry after a timeout, while the first request still runs.

    Both used to miss each other's booking: the second lost the first person,
    took the next one and died on the idempotency key's unique index — a 500
    for a booking that exists.
    """
    _no_delivery(monkeypatch)
    member = membership("sloty-klucz")
    configured = team(member, people=2, hours=(time(8), time(16)), duration=60)
    starts_at = at(timezone.localdate() + timedelta(days=7), 9)
    both_looked = threading.Barrier(2, timeout=5)
    free_at = services.free_at

    def free_at_then_wait(**kwargs: Any) -> Any:
        found = free_at(**kwargs)
        # The second request queues on the key and never looks: the first goes on alone.
        with contextlib.suppress(threading.BrokenBarrierError):
            both_looked.wait()
        return found

    monkeypatch.setattr(services, "free_at", free_at_then_wait)

    def attempt(_: int) -> tuple[Any, bool]:
        close_old_connections()
        try:
            with public_booking_context(member.organization_id):
                created = create_appointment(
                    service_id=configured["service"].id,
                    location_id=configured["location"].id,
                    resource_id=None,
                    starts_at=starts_at,
                    customer_data={"display_name": "Anna", "email": "anna@example.test"},
                    idempotency_key="podwojny-klik",
                    principal_ref="public",
                )
            return created.appointment.id, created.created
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    with tenant(member):
        assert Appointment.objects.count() == 1


def test_a_start_is_checked_against_that_persons_visits_that_day_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window's bookings are loaded once, and every candidate of every day
    used to scan all of them: a booked-out month made the day picker crawl."""
    _no_delivery(monkeypatch)
    member = membership("sloty-okno")
    configured = team(member, people=2, hours=(time(8), time(10)), duration=60)
    start = timezone.localdate() + timedelta(days=7)
    window = [start, start + timedelta(days=1)]
    for number, day in enumerate(window):
        for person in configured["staff"]:
            book(member, configured, at(day, 8), f"okno-{number}-{person.public_slug}", person)
    seen: list[int] = []
    is_free = availability._is_free

    def counting(schedule: Any, *args: Any) -> bool:
        seen.append(len(schedule.staff_allocations))
        return is_free(schedule, *args)

    monkeypatch.setattr(availability, "_is_free", counting)
    with tenant(member):
        days = available_days(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=window[0],
            to_date=window[-1],
        )
    assert days == window  # 09:00 is still free every day
    assert seen and max(seen) == 1


def test_a_named_resource_that_is_gone_is_refused_when_nobody_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pick used to drop it and take whichever room was free instead."""
    _no_delivery(monkeypatch)
    member = membership("sloty-zasob")
    configured = catalog(member)
    with tenant(member):
        Resource.all_objects.filter(pk=configured["resource"].id).update(active=False)
        with pytest.raises(SlotUnavailable):
            create_appointment(
                service_id=configured["service"].id,
                location_id=configured["location"].id,
                resource_id=configured["resource"].id,
                starts_at=at(configured["date"], 9),
                customer_data={"display_name": "Jan", "email": "jan@example.test"},
                idempotency_key="zasob",
                principal_ref=str(member.user_id),
            )
        assert not Appointment.objects.exists()


def test_more_people_to_choose_from_cost_no_more_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    counts = []
    for people in (1, 6):
        member = membership(f"sloty-zapytania-{people}")
        configured = team(member, people=people, hours=(time(8), time(16)), duration=60)
        day = timezone.localdate() + timedelta(days=7)
        query = {"service_id": configured["service"].id, "location_id": configured["location"].id}
        # Warm whatever a first booking of an organization sets up once. Keys
        # differ per organization: the test database ignores RLS, so a shared
        # e-mail would find the other organization's customer.
        book(member, configured, at(day, 8), f"rozgrzewka-{people}")
        with tenant(member):
            with CaptureQueriesContext(connection) as days:
                available_days(**query, from_date=day, to_date=day + timedelta(days=13))
            with CaptureQueriesContext(connection) as times:
                available_times(**query, day=day)
        with CaptureQueriesContext(connection) as pick:
            book(member, configured, at(day, 9), f"dobor-{people}")
        counts.append((len(days), len(times), len(pick)))
    assert counts[0] == counts[1]


def _fall_back_sunday() -> date:
    """The next night Warsaw sets its clocks back: the last Sunday of October."""
    today = timezone.localdate()
    ends = (date(year, 10, 31) for year in (today.year, today.year + 1))
    sundays = (end - timedelta(days=(end.weekday() - 6) % 7) for end in ends)
    return next(sunday for sunday in sundays if sunday > today + timedelta(days=1))


def test_the_night_the_clocks_go_back_offers_both_half_past_twos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("sloty-dst")
    configured = team(member, people=1, hours=(time(1), time(4)), duration=60, weekdays=[6])
    person = configured["staff"][0]
    sunday = _fall_back_sunday()
    query = {"service_id": configured["service"].id, "location_id": configured["location"].id}

    def fits(starts_at: datetime) -> bool:
        return validate_start(
            service=configured["service"],
            location=configured["location"],
            starts_at=starts_at,
            staff_id=person.id,
            resource_id=None,
        )

    with tenant(member):
        days = available_days(
            **query, from_date=sunday - timedelta(days=1), to_date=sunday + timedelta(days=1)
        )
        starts = [item.starts_at for item in available_times(**query, day=sunday)]
        # 01:00 CEST to 04:00 CET is four real hours: 37 hourly visits five minutes apart.
        assert days == [sunday]
        assert len(starts) == 37 and starts == sorted(set(starts))
        twice = [x for x in starts if x.astimezone(WARSAW).strftime("%H:%M") == "02:30"]
        assert len(twice) == 2 and twice[1] - twice[0] == timedelta(hours=1)
        assert fits(twice[1]) and fits(starts[0]) and fits(starts[-1])
        assert not fits(twice[1] + timedelta(minutes=2))  # off the five-minute grid
        assert not fits(starts[-1] + timedelta(minutes=5))  # would end after 04:00
    assert book(member, configured, twice[1], "dst", staff=person).starts_at == twice[1]


def test_the_public_calendar_shows_hours_not_people_and_books_without_naming_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("sloty-publiczne")
    configured = catalog(member)
    day = configured["date"]
    with tenant(member):
        other = StaffMember.all_objects.create(
            organization=member.organization, display_name="Bea", public_slug="bea"
        )
        ServiceStaff.all_objects.create(
            organization=member.organization, service=configured["service"], staff=other
        )
        AvailabilityRule.all_objects.create(
            organization=member.organization,
            staff=other,
            location=configured["location"],
            weekday=day.weekday(),
            local_start=time(9),
            local_end=time(12),
        )
    PublicBookingRoute.objects.create(
        public_slug="sloty-publiczne", organization_id=member.organization_id
    )
    client = APIClient()
    url = "/api/v1/booking/public/sloty-publiczne"
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    days = client.get(
        f"{url}/days/",
        {**query, "from": str(day - timedelta(days=1)), "to": str(day + timedelta(days=1))},
    )
    assert days.status_code == 200
    assert days.json() == {"items": [day.isoformat()]}
    times = client.get(f"{url}/times/", {**query, "date": day.isoformat()})
    assert times.status_code == 200
    items = times.json()["items"]
    assert items and all(set(item) == {"starts_at", "ends_at"} for item in items)
    # Two people free at every start, and each start is listed once.
    assert len({item["starts_at"] for item in items}) == len(items)
    assert str(configured["staff"].id) not in times.content.decode()
    assert str(other.id) not in times.content.decode()
    created = client.post(
        f"{url}/appointments/",
        {
            **query,
            "starts_at": items[0]["starts_at"],
            "customer": {"display_name": "Anna", "email": "anna@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="publiczna-1",
    )
    assert created.status_code == 201
    with tenant(member):
        appointment = Appointment.objects.get()
    # The server picked a person and took the room the service needs along with them.
    assert appointment.staff_id in {configured["staff"].id, other.id}
    assert appointment.resource_id == configured["resource"].id


def test_the_panel_sees_who_is_free_and_books_without_naming_anyone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("sloty-panel")
    configured = catalog(member)
    staff, resource, day = configured["staff"], configured["resource"], configured["date"]
    client = authenticated_client(member)
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    days = client.get(
        "/api/v1/booking/slots/days/",
        {**query, "from": str(day), "to": str(day + timedelta(days=6)), "staff_id": str(staff.id)},
    )
    assert days.status_code == 200
    assert days.json() == {"items": [day.isoformat()]}
    times = client.get("/api/v1/booking/slots/times/", {**query, "date": day.isoformat()})
    assert times.status_code == 200
    first = times.json()["items"][0]
    assert first["staff"] == [{"staff_id": str(staff.id), "resource_id": str(resource.id)}]
    body = {
        **query,
        "starts_at": first["starts_at"],
        "customer": {"display_name": "Jan", "email": "jan@example.test"},
    }
    created = client.post(
        "/api/v1/booking/appointments/", body, format="json", HTTP_IDEMPOTENCY_KEY="panel-1"
    )
    assert created.status_code == 201
    assert created.json()["staff_id"] == str(staff.id)
    # A retry of "anybody" is the same request, so it finds the same booking.
    retry = client.post(
        "/api/v1/booking/appointments/", body, format="json", HTTP_IDEMPOTENCY_KEY="panel-1"
    )
    assert retry.status_code == 200
    assert retry.json()["id"] == created.json()["id"]


def test_who_is_free_is_for_the_calendars_managers_of_that_organization() -> None:
    member = membership("sloty-odmowa")
    configured = catalog(member)
    url = "/api/v1/booking/slots/times/"
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
        "date": configured["date"].isoformat(),
    }
    assert APIClient().get(url, query).status_code in {401, 403}
    user = User.objects.create_user(email="pracownik@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    role, _ = Role.objects.get_or_create(
        key="staff",
        organization=None,
        organization_type="",
        defaults={
            "name": "Staff",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["staff"]),
            "is_immutable": True,
        },
    )
    worker = Membership.objects.create(organization=member.organization, user=user, role=role)
    assert authenticated_client(worker).get(url, query).status_code == 403
    # Another organization's manager asks about this one's service and finds nothing.
    stranger = membership("sloty-obcy")
    response = authenticated_client(stranger).get(url, query)
    assert response.status_code == 200
    assert response.json() == {"items": []}
