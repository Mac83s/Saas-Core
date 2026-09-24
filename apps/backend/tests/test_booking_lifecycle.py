"""An appointment's end of life: done, and not called off afterwards (HC-ADR-002, C2/C4)."""

from __future__ import annotations

import threading
import time as clock
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.booking.api import (
    AppointmentNotChangeable,
    AppointmentStatus,
    BookingIdempotencyConflict,
    SlotUnavailable,
    appointment_for_tenant,
    cancel_appointment,
    complete_appointment,
    create_appointment,
    list_appointments,
)
from saas_core.modules.shared.booking.availability import validate_start
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentResourceAllocation,
    AppointmentStaffAllocation,
    SelfServiceRoute,
    Service,
    ServiceStaff,
    StaffMember,
)
from saas_core.modules.shared.booking.security import public_booking_context
from test_booking import _no_delivery, catalog, create, membership, tenant
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)

WARSAW = ZoneInfo("Europe/Warsaw")


def walk_in(
    member: Membership,
    configured: dict[str, Any],
    starts_at: datetime,
    *,
    staff: StaffMember | None = None,
    key: str = "walk-in",
) -> Appointment:
    """Work already under way, blocked for the rest of the day: nobody knows when it ends."""
    with tenant(member):
        return create_appointment(
            service_id=configured["service"].id,
            staff_id=(staff or configured["staff"]).id,
            location_id=configured["location"].id,
            resource_id=None if staff else configured["resource"].id,
            starts_at=starts_at,
            customer_data={"display_name": "Gospodarstwo", "email": "farma@example.test"},
            idempotency_key=key,
            principal_ref=str(member.user_id),
            walk_in_minutes=12 * 60,
        ).appointment


def taken(model: Any, appointment: Appointment) -> tuple[datetime, datetime]:
    occupied = model.all_objects.get(appointment=appointment).occupied_range
    return occupied.lower, occupied.upper


def test_a_completed_visit_closes_the_customers_link_and_stays_done() -> None:
    member = membership("zakonczone")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    with tenant(member) as context:
        found = appointment_for_tenant(context.organization_id, appointment.id)
        assert found is not None and found.service.id == configured["service"].id
        done = complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
        again = complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
        assert done.status == again.status == AppointmentStatus.COMPLETED
        assert SelfServiceRoute.objects.get(appointment_id=appointment.id).revoked_at is not None
        with pytest.raises(AppointmentNotChangeable):
            cancel_appointment(
                appointment_id=appointment.id, idempotency_key="c", principal_ref="t"
            )


def test_the_customer_cannot_move_or_call_off_a_visit_that_started() -> None:
    member = membership("po-starcie")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    Appointment.all_objects.filter(pk=appointment.id).update(
        starts_at=timezone.now() - timedelta(minutes=5)
    )
    with (
        public_booking_context(member.organization_id),
        pytest.raises(AppointmentNotChangeable),
    ):
        cancel_appointment(appointment_id=appointment.id, idempotency_key="k", principal_ref="x")
    # The provider still can: a visit called off on the spot is theirs to record.
    with tenant(member):
        canceled = cancel_appointment(
            appointment_id=appointment.id, idempotency_key="k", principal_ref="staff"
        )
        assert canceled.status == AppointmentStatus.CANCELED


def test_a_vertical_lists_one_day_of_its_own_kind_of_visit() -> None:
    member = membership("dzien")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    with tenant(member):
        Service.all_objects.filter(pk=configured["service"].id).update(appointment_kind="x.visit")
        day = appointment.starts_at.replace(hour=0, minute=0, second=0, microsecond=0)
        window = {"starts_from": day, "starts_until": day + timedelta(days=1)}
        assert [a.id for a in list_appointments(**window, appointment_kinds={"x.visit"})] == [
            appointment.id
        ]
        assert list_appointments(**window, appointment_kinds={"y.visit"}) == []
        assert list_appointments(starts_from=day + timedelta(days=1)) == []


def test_a_walk_in_frees_the_person_and_the_room_when_the_work_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A walk-in held the trimmer until evening; completing it at 10:30 ends it at 10:30."""
    _no_delivery(monkeypatch)
    member = membership("koniec-z-marszu")
    configured = catalog(member)
    ten = datetime.combine(configured["date"], time(10), WARSAW)
    visit = walk_in(member, configured, ten)
    eleven = ten + timedelta(hours=1)
    with tenant(member):
        complete_appointment(
            appointment_id=visit.id,
            idempotency_key="done",
            principal_ref="t",
            ended_at=ten + timedelta(minutes=30),
        )
        # A walk-in took no buffer, so nothing is added after the work.
        for model in (AppointmentStaffAllocation, AppointmentResourceAllocation):
            assert taken(model, visit) == (ten, ten + timedelta(minutes=30))
        assert validate_start(
            service=configured["service"],
            location=configured["location"],
            starts_at=eleven,
            staff_id=configured["staff"].id,
            resource_id=configured["resource"].id,
        )
    configured["starts_at"] = eleven
    assert create(member, configured, key="po-wizycie").created


def test_a_planned_visit_done_early_keeps_its_buffer_and_one_done_late_is_not_lengthened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("koniec-planowej")
    configured = catalog(member)
    early = create(member, configured).appointment
    configured["starts_at"] = early.starts_at + timedelta(hours=1)
    late = create(member, configured, key="create-2").appointment
    done_at = early.starts_at + timedelta(minutes=10)
    with tenant(member):
        for visit, ended_at, key in (
            (early, done_at, "early"),
            (late, late.ends_at + timedelta(hours=1), "late"),
        ):
            complete_appointment(
                appointment_id=visit.id, idempotency_key=key, principal_ref="t", ended_at=ended_at
            )
        # A retry changes nothing, the same key with another end is another
        # request, and a visit already done is not trimmed twice.
        complete_appointment(
            appointment_id=early.id, idempotency_key="early", principal_ref="t", ended_at=done_at
        )
        with pytest.raises(BookingIdempotencyConflict):
            complete_appointment(
                appointment_id=early.id, idempotency_key="early", principal_ref="t"
            )
        complete_appointment(appointment_id=early.id, idempotency_key="again", principal_ref="t")
        # The service's ten minutes after the visit stay booked.
        for model in (AppointmentStaffAllocation, AppointmentResourceAllocation):
            assert taken(model, early) == (early.occupied_from, done_at + timedelta(minutes=10))
            assert taken(model, late) == (late.occupied_from, late.occupied_until)
        # What was booked stays on record as booked.
        assert Appointment.all_objects.get(pk=early.id).occupied_until == early.occupied_until


def test_a_walk_in_racing_the_trim_waits_for_it_and_takes_the_freed_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next walk-in inserts while the completion is still uncommitted.

    The exclusion check then meets the old, still-live range and must wait for
    the trim rather than refuse the time or deadlock over it.
    """
    _no_delivery(monkeypatch)
    member = membership("koniec-wyscig")
    configured = catalog(member)
    ten = datetime.combine(configured["date"], time(10), WARSAW)
    visit = walk_in(member, configured, ten)
    trimmed = threading.Event()

    def complete() -> bool:
        close_old_connections()
        try:
            with tenant(member):
                complete_appointment(
                    appointment_id=visit.id,
                    idempotency_key="done",
                    principal_ref="t",
                    ended_at=ten + timedelta(minutes=30),
                )
                trimmed.set()
                # Commit only once the other booking is queued behind this one.
                deadline = clock.monotonic() + 30
                while clock.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        # A transaction reads activity once and keeps it; ask afresh.
                        cursor.execute("SELECT pg_stat_clear_snapshot()")
                        cursor.execute(
                            "SELECT count(*) FROM pg_stat_activity"
                            " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        )
                        row = cursor.fetchone()
                    if row and row[0]:
                        return True
                    clock.sleep(0.05)
                return False
        finally:
            close_old_connections()

    def book() -> str:
        close_old_connections()
        try:
            assert trimmed.wait(30)
            walk_in(member, configured, ten + timedelta(hours=1), key="next")
            return "created"
        except SlotUnavailable:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        waited, booked = executor.submit(complete), executor.submit(book)
        assert (booked.result(), waited.result()) == ("created", True)


def test_the_calendar_reads_a_window_of_local_days_and_one_persons_visits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("okno-listy")
    configured = catalog(member)
    planned = create(member, configured).appointment
    day = configured["date"]
    with tenant(member):
        bea = StaffMember.all_objects.create(organization=member.organization, display_name="Bea")
        ServiceStaff.all_objects.create(
            organization=member.organization, service=configured["service"], staff=bea
        )
    # Half past midnight in Warsaw is the evening before in UTC: a date bound
    # at UTC midnight would put this visit in the wrong day.
    night = walk_in(
        member,
        configured,
        datetime.combine(day + timedelta(days=1), time(0, 30), WARSAW),
        staff=bea,
    )
    client = authenticated_client(member)

    def listed(**query: Any) -> list[str]:
        response = client.get("/api/v1/booking/appointments/", query)
        assert response.status_code == 200, response.content
        return [item["id"] for item in response.json()["items"]]

    tomorrow, after = day + timedelta(days=1), day + timedelta(days=2)
    assert listed() == [str(planned.id), str(night.id)]
    assert listed(**{"from": str(day), "to": str(tomorrow)}) == [str(planned.id)]
    assert listed(**{"from": str(tomorrow), "to": str(after)}) == [str(night.id)]
    assert listed(**{"from": (planned.starts_at + timedelta(minutes=1)).isoformat()}) == [
        str(night.id)
    ]
    assert listed(**{"to": planned.starts_at.isoformat()}) == []
    assert listed(staff_id=str(bea.id)) == [str(night.id)]
    for bad in ({"from": "wczoraj"}, {"to": "2026-13-01"}, {"staff_id": "bea"}):
        assert client.get("/api/v1/booking/appointments/", bad).status_code == 400
    # Another organization naming this one's person sees nothing of it.
    stranger = authenticated_client(membership("okno-obcy"))
    response = stranger.get("/api/v1/booking/appointments/", {"staff_id": str(bea.id)})
    assert response.status_code == 200 and response.json() == {"items": []}
