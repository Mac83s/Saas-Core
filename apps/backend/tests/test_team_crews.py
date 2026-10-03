"""Several people on a visit, teams, vacancies and the office's assignment
(ADR-058 §2, §3, §9 — team phase 3)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from typing import Any

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.core.organizations.tasks import tenant_task_context
from saas_core.modules.shared.booking import services
from saas_core.modules.shared.booking.api import (
    crew_member_filter,
    crew_people,
    join_visit_crew,
    leave_visit_crew,
    on_crew,
)
from saas_core.modules.shared.booking.availability import available_days, available_times
from saas_core.modules.shared.booking.crew import CrewChanged, PersonUnavailable
from saas_core.modules.shared.booking.dispatch import assign_crew, candidates, overview, queue
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    AvailabilityRule,
    Service,
    StaffMember,
    StaffTeam,
    TimeOff,
)
from saas_core.modules.shared.booking.security import public_booking_context
from saas_core.modules.shared.booking.services import (
    SlotUnavailable,
    cancel_appointment,
    create_appointment,
    list_appointments,
    reschedule_appointment,
)
from saas_core.modules.shared.booking.staff import add_time_off, list_people
from saas_core.modules.shared.booking.teams import create_team, delete_team, update_team
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from test_booking import _no_delivery, membership, tenant
from test_booking_slots import at, team
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import add_staff, bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


def crew(owner: Membership, *, people: int = 3, need: int = 2) -> dict[str, Any]:
    """`people` doing a `need`-person service, 08:00–16:00 every day."""
    configured = team(owner, people=people, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(staff_count=need)
        configured["service"].refresh_from_db()
    configured["day"] = timezone.localdate() + timedelta(days=7)
    return configured


def book(
    owner: Membership,
    configured: dict[str, Any],
    hour: int,
    key: str,
    *,
    public: bool = False,
    **people: Any,
) -> Appointment:
    arguments = {
        "service_id": configured["service"].id,
        "location_id": configured["location"].id,
        "starts_at": at(configured["day"], hour),
        "customer_data": {"display_name": f"Klient {key}", "email": f"{key}@example.test"},
        "idempotency_key": key,
        "principal_ref": "public" if public else str(owner.user_id),
        **people,
    }
    if public:
        with public_booking_context(owner.organization_id):
            return create_appointment(**arguments).appointment
    with tenant(owner):
        return create_appointment(**arguments).appointment


def people_on(appointment: Appointment) -> list[Any]:
    return sorted(
        AppointmentStaffAllocation.all_objects.filter(
            appointment=appointment, active=True
        ).values_list("staff_id", flat=True)
    )


def test_a_two_person_service_takes_the_two_least_loaded_free_people() -> None:
    owner = membership("ekipa-dobor")
    configured = crew(owner)
    first, second, third = configured["staff"]
    morning = book(owner, configured, 9, "rano")
    assert people_on(morning) == sorted([first.id, second.id])
    assert (morning.staff_required, morning.needs_assignment) == (2, False)
    later = book(owner, configured, 11, "pozniej")
    # The one without a visit that day comes first and leads.
    assert later.staff_id == third.id
    assert len(people_on(later)) == 2


def test_the_office_looks_at_a_pick_only_when_there_was_a_choice() -> None:
    owner = membership("ekipa-wybor")
    configured = crew(owner, people=3, need=2)
    public = book(owner, configured, 9, "strona", public=True)
    assert (public.auto_assigned, public.queue_reason) == (True, "public")
    # The office picking "anybody" sees the result at once: nothing to review.
    panel = book(owner, configured, 12, "panel")
    assert panel.auto_assigned is False


def test_with_exactly_enough_people_a_public_pick_needs_no_look() -> None:
    owner = membership("ekipa-dwoje")
    configured = crew(owner, people=2, need=2)
    visit = book(owner, configured, 9, "dwoje", public=True)
    assert (visit.auto_assigned, visit.needs_assignment, visit.queue_reason) == (False, False, "")


def test_named_people_short_of_the_service_leave_a_vacancy() -> None:
    owner = membership("ekipa-wakat")
    configured = crew(owner)
    first = configured["staff"][0]
    visit = book(owner, configured, 9, "jeden", staff_ids=[first.id])
    assert people_on(visit) == [first.id]
    assert (visit.needs_assignment, visit.queue_reason) == (True, "short")


def test_an_absence_takes_the_person_off_and_the_rest_keep_their_time() -> None:
    owner = membership("ekipa-urlop")
    configured = crew(owner)
    first, second, _ = configured["staff"]
    visit = book(owner, configured, 9, "urlop", staff_ids=[first.id, second.id])
    with tenant(owner):
        _, touched = add_time_off(
            staff_id=first.id,
            starts_at=at(configured["day"], 0),
            ends_at=at(configured["day"], 23),
        )
    assert touched == 1
    visit.refresh_from_db()
    assert people_on(visit) == [second.id]
    # The lead left, so the one who stays leads; the visit still needs a second.
    assert (visit.staff_id, visit.needs_assignment, visit.queue_reason) == (
        second.id,
        True,
        "time_off",
    )


def test_the_office_assigns_with_the_version_it_saw() -> None:
    owner = membership("ekipa-przydzial")
    configured = crew(owner)
    first, second, third = configured["staff"]
    visit = book(owner, configured, 9, "przydzial", staff_ids=[first.id])
    busy = book(owner, configured, 9, "zajety", staff_ids=[second.id])
    assert busy.needs_assignment
    with tenant(owner), pytest.raises(PersonUnavailable, match="Osoba"):
        assign_crew(
            appointment_id=visit.id,
            staff_ids=[first.id, second.id],
            lead_id=first.id,
            expected_version=visit.crew_version,
            notify_staff=True,
            idempotency_key="zajety",
            principal_ref=str(owner.user_id),
        )
    with tenant(owner):
        assigned = assign_crew(
            appointment_id=visit.id,
            staff_ids=[third.id, first.id],
            lead_id=third.id,
            expected_version=visit.crew_version,
            notify_staff=True,
            idempotency_key="dobrze",
            principal_ref=str(owner.user_id),
        )
    assert (assigned.staff_id, assigned.needs_assignment, assigned.queue_reason) == (
        third.id,
        False,
        "",
    )
    assert people_on(assigned) == sorted([first.id, third.id])
    # A second office looked at the old crew: it hears who changed it.
    with tenant(owner), pytest.raises(CrewChanged, match=owner.user.email):
        assign_crew(
            appointment_id=visit.id,
            staff_ids=[first.id],
            lead_id=None,
            expected_version=visit.crew_version,
            notify_staff=False,
            idempotency_key="stare",
            principal_ref=str(owner.user_id),
        )


def test_keeping_the_systems_pick_takes_the_visit_off_the_queue() -> None:
    owner = membership("ekipa-zostaw")
    configured = crew(owner)
    visit = book(owner, configured, 9, "zostaw", public=True)
    assert visit.auto_assigned
    with tenant(owner):
        assert [item.id for item in queue()] == [visit.id]
        kept = assign_crew(
            appointment_id=visit.id,
            staff_ids=[visit.staff_id, *[p for p in people_on(visit) if p != visit.staff_id]],
            lead_id=visit.staff_id,
            expected_version=visit.crew_version,
            notify_staff=True,
            idempotency_key="zostaw",
            principal_ref=str(owner.user_id),
        )
        assert (kept.auto_assigned, kept.queue_reason, kept.queued_at) == (False, "", None)
        assert queue() == []


def test_moving_a_visit_moves_everybody_or_names_who_cannot() -> None:
    owner = membership("ekipa-przeloz")
    configured = crew(owner)
    first, second, _ = configured["staff"]
    visit = book(owner, configured, 9, "ruch", staff_ids=[first.id, second.id])
    book(owner, configured, 13, "koliduje", staff_ids=[second.id])
    with tenant(owner), pytest.raises(PersonUnavailable, match=second.display_name):
        reschedule_appointment(
            appointment_id=visit.id,
            starts_at=at(configured["day"], 13),
            idempotency_key="nie",
            principal_ref=str(owner.user_id),
        )
    # Refused as a whole: the visit keeps both people at nine.
    assert people_on(visit) == sorted([first.id, second.id])
    with tenant(owner):
        moved = reschedule_appointment(
            appointment_id=visit.id,
            starts_at=at(configured["day"], 14),
            idempotency_key="tak",
            principal_ref=str(owner.user_id),
        )
    allocations = AppointmentStaffAllocation.all_objects.filter(appointment=moved)
    assert sorted(allocations.filter(active=True).values_list("staff_id", flat=True)) == sorted([
        first.id,
        second.id,
    ])
    assert all(
        row.occupied_range.lower == at(configured["day"], 14)
        for row in allocations.filter(active=True)
    )


def test_a_customer_moving_their_visit_gets_whoever_is_free_then() -> None:
    owner = membership("ekipa-klient")
    configured = crew(owner)
    visit = book(owner, configured, 9, "klient", public=True)
    before = people_on(visit)
    blocker = next(person for person in before)
    book(owner, configured, 14, "blokuje", staff_ids=[blocker])
    with public_booking_context(owner.organization_id):
        moved = reschedule_appointment(
            appointment_id=visit.id,
            starts_at=at(configured["day"], 14),
            idempotency_key="sam",
            principal_ref="token",
        )
    after = people_on(moved)
    assert blocker not in after and len(after) == 2
    moved.refresh_from_db()
    assert (moved.auto_assigned, moved.queue_reason) == (True, "moved")


def test_the_people_on_a_visit_hear_about_it_and_whoever_acted_does_not() -> None:
    owner = membership("ekipa-wiesci")
    configured = crew(owner)
    first, second, _ = configured["staff"]
    colleague = member_of(owner, "kolega@example.test", "staff")
    with tenant(owner):
        StaffMember.all_objects.filter(pk=first.id).update(membership=owner)
        StaffMember.all_objects.filter(pk=second.id).update(membership=colleague)
    visit = book(owner, configured, 9, "wiesci", staff_ids=[first.id, second.id])
    with tenant(owner):
        told = AppNotification.all_objects.filter(kind="booking.assigned")
        assert list(told.values_list("user_id", flat=True)) == [colleague.user_id]
        mail = NotificationMessage.all_objects.get(template_key="booking.staff_assigned")
        assert mail.recipient_email == "kolega@example.test"
        # Where to look, never who the customer is.
        assert "Klient" not in str(mail.context)
        assert set(mail.context) == {"organization_name", "starts_at", "panel_url"}
        cancel_appointment(
            appointment_id=visit.id, idempotency_key="stop", principal_ref=str(owner.user_id)
        )
        assert AppNotification.all_objects.filter(
            kind="booking.canceled", user_id=colleague.user_id
        ).exists()
        visit.refresh_from_db()
        assert (visit.needs_assignment, visit.auto_assigned) == (False, False)
    # Signed as the organization's own job, which delivery has to open.
    with tenant_task_context(
        mail.signed_tenant_context, expected_causation_id=f"email:{mail.id}"
    ) as context:
        assert context.role_key == "booking_notify"


def test_a_helper_finds_the_visit_among_their_own() -> None:
    owner = membership("ekipa-pomocnik")
    configured = crew(owner)
    first, second, _ = configured["staff"]
    colleague = member_of(owner, "pomocnik@example.test", "staff")
    with tenant(owner):
        StaffMember.all_objects.filter(pk=second.id).update(membership=colleague)
    visit = book(owner, configured, 9, "pomocnik", staff_ids=[first.id, second.id])
    with tenant(owner):
        assert [item.id for item in list_appointments(staff_id=second.id)] == [visit.id]
    with tenant(colleague):
        assert [item.id for item in list_appointments(mine=True)] == [visit.id]


def test_joining_a_visit_under_way_blocks_the_time_and_frees_the_other_visit() -> None:
    owner = membership("ekipa-dolacza")
    configured = crew(owner, people=3, need=1)
    first, second, _ = configured["staff"]
    colleague = member_of(owner, "dolacza@example.test", "staff")
    with tenant(owner):
        StaffMember.all_objects.filter(pk=second.id).update(membership=colleague)
    running = book(owner, configured, 9, "trwa", staff_ids=[first.id])
    # The helper's own visit at the same hour, which they leave to join.
    own = book(owner, configured, 9, "wlasna", staff_ids=[second.id])
    since = running.starts_at + timedelta(minutes=20)
    with tenant(owner):
        assert join_visit_crew(appointment_id=running.id, staff_id=second.id, since=since)
        # A second tap changes nothing.
        assert not join_visit_crew(appointment_id=running.id, staff_id=second.id, since=since)
        running.refresh_from_db()
        own.refresh_from_db()
        assert [(p.name, p.lead) for p in crew_people(running)] == [
            (first.display_name, True),
            (second.display_name, False),
        ]
        joined = AppointmentStaffAllocation.all_objects.get(
            appointment=running, staff=second, active=True
        )
        assert joined.occupied_range.lower == since
        assert on_crew(running.id, colleague.id)
        # The visit the helper would have missed waits for somebody else.
        assert (own.needs_assignment, own.queue_reason) == (True, "joined")
        # The helper finds the visit they joined among their own; the one they
        # left only keeps their name as its lead until the office staffs it.
        mine = Appointment.all_objects.filter(crew_member_filter(colleague.id)).distinct()
        assert set(mine.values_list("id", flat=True)) == {running.id}
        assert [item.id for item in list_appointments(staff_id=second.id)] == [running.id]
    with tenant(colleague):
        assert [item.id for item in list_appointments(mine=True)] == [running.id]
    with tenant(owner):
        assert leave_visit_crew(appointment_id=running.id, staff_id=second.id)
        assert not leave_visit_crew(appointment_id=running.id, staff_id=first.id)
        running.refresh_from_db()
        assert [p.staff_id for p in crew_people(running)] == [first.id]
        assert not on_crew(running.id, colleague.id)


def test_who_is_free_for_a_visit_and_why_not() -> None:
    owner = membership("ekipa-kto")
    configured = crew(owner, people=4, need=2)
    first, second, third, fourth = configured["staff"]
    visit = book(owner, configured, 9, "kto", staff_ids=[first.id])
    book(owner, configured, 9, "inna", staff_ids=[second.id])
    with tenant(owner):
        TimeOff.all_objects.create(
            organization_id=owner.organization_id,
            staff=third,
            starts_at=at(configured["day"], 0),
            ends_at=at(configured["day"], 23),
            reason="L4",
        )
        AvailabilityRule.all_objects.filter(staff=fourth).update(local_start=time(13))
        rows = {item.staff.id: item for item in candidates(appointment_id=visit.id)}
    assert rows[first.id].on_visit and rows[first.id].lead
    assert rows[second.id].status.state == "busy"
    assert rows[second.id].next_free is not None
    assert rows[third.id].status.state == "time_off"
    assert rows[fourth.id].status.state == "off_schedule"
    assert rows[fourth.id].status.hours


def test_teams_are_named_once_and_never_touch_booked_visits() -> None:
    owner = membership("ekipa-zespoly")
    configured = crew(owner)
    first, second, third = configured["staff"]
    with tenant(owner):
        north = create_team(name="Brygada Północ", member_ids=[first.id, second.id])
        with pytest.raises(ValidationError):
            create_team(name="  brygada  północ ", member_ids=[])
    visit = book(owner, configured, 9, "zespol", team_id=north.id)
    assert set(people_on(visit)) == {first.id, second.id}
    assert visit.requested_team_id == north.id
    with tenant(owner):
        update_team(team_id=north.id, member_ids=[third.id])
        delete_team(team_id=north.id)
    visit.refresh_from_db()
    assert visit.requested_team_id is None
    assert set(people_on(visit)) == {first.id, second.id}


def test_a_new_person_joins_the_teams_named_and_only_the_companys_own() -> None:
    owner = membership("ekipa-nowy")
    stranger = membership("ekipa-obcy")
    crew(owner)
    foreign = StaffTeam.all_objects.create(organization=stranger.organization, name="Obcy")
    with tenant(owner):
        north = create_team(name="Brygada Północ", member_ids=[])
        piotr = add_staff(name="Piotr", team_ids=[north.id, north.id])
        assert {item.staff.id: item.team_ids for item in list_people()}[piotr.id] == [north.id]
        # Another company's team is not there to join, and nobody is added.
        with pytest.raises(ValidationError):
            add_staff(name="Obcy", team_ids=[foreign.id])
    assert not StaffMember.all_objects.filter(display_name="Obcy").exists()


def test_the_queue_and_what_the_menu_needs() -> None:
    owner = membership("ekipa-kolejka")
    configured = crew(owner)
    first = configured["staff"][0]
    vacancy = book(owner, configured, 9, "wakat", staff_ids=[first.id])
    picked = book(owner, configured, 12, "strona2", public=True)
    with tenant(owner):
        assert [item.id for item in queue()] == [vacancy.id, picked.id]
        summary = overview()
    assert (summary.bookable_staff, summary.teams, summary.waiting) == (3, 0, 2)


def test_days_and_times_for_two_people_count_them_at_one_start() -> None:
    owner = membership("ekipa-terminy")
    configured = crew(owner, people=2, need=2)
    first, second = configured["staff"]
    day = configured["day"]
    with tenant(owner):
        AvailabilityRule.all_objects.filter(staff=second, weekday=day.weekday()).update(
            local_start=time(12)
        )
        times = available_times(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            day=day,
            need=2,
        )
        assert times and times[0].starts_at == at(day, 12)
        AvailabilityRule.all_objects.filter(staff=second, weekday=day.weekday()).delete()
        assert day not in available_days(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=day,
            to_date=day,
            need=2,
        )


@pytest.mark.django_db(transaction=True)
def test_two_bookings_for_one_two_person_crew_leave_one_and_no_stray_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    owner = membership("ekipa-wyscig")
    configured = crew(owner, people=2, need=2)
    starts_at = at(configured["day"], 9)
    both_looked = threading.Barrier(2, timeout=60)
    free_at = services.free_at

    def free_at_then_wait(**kwargs: Any) -> Any:
        found = free_at(**kwargs)
        both_looked.wait()
        return found

    monkeypatch.setattr(services, "free_at", free_at_then_wait)

    def attempt(number: int) -> str:
        close_old_connections()
        try:
            with public_booking_context(owner.organization_id):
                create_appointment(
                    service_id=configured["service"].id,
                    location_id=configured["location"].id,
                    starts_at=starts_at,
                    customer_data={
                        "display_name": f"Klient {number}",
                        "email": f"race-{number}@example.test",
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
        assert sorted(executor.map(attempt, (1, 2))) == ["conflict", "created"]
    with tenant(owner):
        assert Appointment.objects.count() == 1
        assert AppointmentStaffAllocation.all_objects.filter(active=True).count() == 2


def test_the_dispatch_api_answers_the_office_and_refuses_the_others() -> None:
    _, owner, client = authenticated_member(
        email="api-biuro@example.test", role_key="owner", slug="api-ekipa"
    )
    bookable(owner.organization)
    configured = crew(owner)
    first, second, third = configured["staff"]
    headers = {"HTTP_X_CSRFTOKEN": csrf_value(client)}
    made = client.post(
        "/api/v1/booking/teams/",
        {"name": "Brygada Północ", "member_ids": [str(first.id), str(second.id)]},
        format="json",
        **headers,
    )
    assert made.status_code == 201, made.data
    assert client.get("/api/v1/booking/teams/").json()["items"][0]["name"] == "Brygada Północ"
    visit = book(owner, configured, 9, "api", staff_ids=[first.id])
    waiting = client.get("/api/v1/booking/queue/").json()["items"]
    assert [item["id"] for item in waiting] == [str(visit.id)]
    assert waiting[0]["crew"][0]["lead"] is True
    assert waiting[0]["customer_email"] == "api@example.test"
    assert client.get("/api/v1/booking/overview/").json()["waiting"] == 1
    people = client.get(f"/api/v1/booking/appointments/{visit.id}/candidates/").json()["items"]
    assert {item["staff_id"] for item in people} == {str(x.id) for x in (first, second, third)}
    assigned = client.post(
        f"/api/v1/booking/appointments/{visit.id}/crew/",
        {
            "staff_ids": [str(first.id), str(third.id)],
            "lead_id": str(first.id),
            "expected_version": visit.crew_version,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="api-przydzial",
        **headers,
    )
    assert assigned.status_code == 200, assigned.data
    assert assigned.json()["needs_assignment"] is False
    assert [person["staff_id"] for person in assigned.json()["crew"]] == [
        str(first.id),
        str(third.id),
    ]

    worker = member_of(owner, "api-korektor@example.test", "staff")
    worker_client = authenticated_client(worker)
    worker_client.get("/api/v1/auth/csrf/")
    refused = worker_client.post(
        f"/api/v1/booking/appointments/{visit.id}/crew/",
        {"staff_ids": [str(second.id)], "expected_version": assigned.json()["crew_version"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="api-pracownik",
        HTTP_X_CSRFTOKEN=csrf_value(worker_client),
    )
    assert refused.status_code == 403
    assert worker_client.get("/api/v1/booking/queue/").status_code == 403
    assert worker_client.get("/api/v1/booking/overview/").json()["waiting"] is None

    _, stranger, stranger_client = authenticated_member(
        email="api-obcy-ekipa@example.test", role_key="owner", slug="api-obca-ekipa"
    )
    bookable(stranger.organization)
    assert (
        stranger_client.get(f"/api/v1/booking/appointments/{visit.id}/candidates/").status_code
        == 404
    )
