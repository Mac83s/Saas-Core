"""A visit that has passed, and one the customer did not come to (UX-031, W3)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from django.db.models import F
from django.utils import timezone

from saas_core.config.composition import CompositionError, load_catalog
from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.booking import passing
from saas_core.modules.shared.booking.api import (
    NO_SHOW,
    AppointmentNotChangeable,
    AppointmentStatus,
    VisitNotStartedYet,
    cancel_appointment,
    complete_appointment,
    mark_no_show,
)
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentResourceAllocation,
    AppointmentStaffAllocation,
    AppointmentStatusHistory,
    SelfServiceRoute,
)
from test_booking import _no_delivery, tenant, watching
from test_booking_slots import WARSAW, at, book
from test_team_facts import after, company, numbers
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)


@pytest.fixture(autouse=True)
def core_closing(settings: Any) -> None:
    """Core's own rule — a product's `appointmentKindsCompletedExplicitly`
    (HoofCare lists "") must not change what these tests start from."""
    settings.APPOINTMENT_KINDS_COMPLETED_EXPLICITLY = frozenset()


def moved(appointment: Appointment, starts_at: datetime) -> Appointment:
    """The booked visit, with the time its people and resource hold, moved to
    start at `starts_at` — booking refuses the past, and the clock is real."""
    by = starts_at - appointment.starts_at
    Appointment.all_objects.filter(pk=appointment.pk).update(
        starts_at=F("starts_at") + by,
        ends_at=F("ends_at") + by,
        occupied_from=F("occupied_from") + by,
        occupied_until=F("occupied_until") + by,
    )
    for model in (AppointmentStaffAllocation, AppointmentResourceAllocation):
        for allocation in model.all_objects.filter(appointment=appointment):
            held = allocation.occupied_range
            allocation.occupied_range = (held.lower + by, held.upper + by)
            allocation.save(update_fields=["occupied_range"])
    return Appointment.all_objects.get(pk=appointment.pk)


def visit(appointment: Appointment, member: Any) -> dict[str, Any]:
    # A day either side: the list's dates are the company's, the visit's UTC.
    day = appointment.starts_at.date()
    response = authenticated_client(member).get(
        f"/api/v1/booking/appointments/?from={day - timedelta(days=1)}&to={day + timedelta(days=2)}"
    )
    assert response.status_code == 200, response.json()
    return next(item for item in response.json()["items"] if item["id"] == str(appointment.id))


def test_a_confirmed_visit_has_passed_once_its_end_is_behind_us() -> None:
    configured = company("minela-regula")
    owner, day = configured["owner"], configured["day"]
    booked = book(owner, configured, at(day, 9), "a")
    assert passing.has_passed(booked, at(day, 9, 59)) is False
    assert passing.has_passed(booked, at(day, 10)) is True
    assert visit(booked, owner)["passed"] is False

    over = moved(booked, timezone.now() - timedelta(hours=1, minutes=1))
    shown = visit(over, owner)
    assert (shown["passed"], shown["closes_explicitly"]) == (True, False)

    # Closed, it no longer waits for anybody: done is done.
    with tenant(owner):
        complete_appointment(appointment_id=booked.id, idempotency_key="z", principal_ref="t")
    assert visit(over, owner)["passed"] is False


def test_a_plain_service_a_product_closes_itself_counts_only_when_completed(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    configured = company("minela-jawnie")
    owner, day = configured["owner"], configured["day"]
    first = configured["staff"][0]
    unfinished = book(owner, configured, at(day, 9), "a", first)
    finished = book(owner, configured, at(day, 11), "b", first)
    with tenant(owner):
        complete_appointment(appointment_id=finished.id, idempotency_key="b", principal_ref="t")
    after(monkeypatch, at(day + timedelta(days=1), 8))

    # 3A: by default a visit whose time passed took place.
    assert numbers(owner, first.id, day)["visits_done"]["value"] == 2

    # "" — the plain service — listed by the product, matched literally.
    settings.APPOINTMENT_KINDS_COMPLETED_EXPLICITLY = frozenset({""})
    assert passing.closes_explicitly("") is True
    assert numbers(owner, first.id, day)["visits_done"]["value"] == 1
    over = moved(unfinished, timezone.now() - timedelta(hours=2))
    shown = visit(over, owner)
    assert (shown["passed"], shown["closes_explicitly"]) == (True, True)


def test_the_customer_who_did_not_come_frees_the_people_and_counts_apart(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    configured = company("nieobecnosc")
    owner, day = configured["owner"], configured["day"]
    first = configured["staff"][0]
    absent = book(owner, configured, at(day, 9), "a", first)
    route = SelfServiceRoute.objects.get(appointment_id=absent.id)
    assert route.revoked_at is None
    Appointment.all_objects.filter(pk=absent.id).update(needs_assignment=True)

    # Before the visit begins nobody can tell.
    with tenant(owner), pytest.raises(VisitNotStartedYet):
        mark_no_show(appointment_id=absent.id, idempotency_key="n", principal_ref="t")

    absent = moved(absent, timezone.now() - timedelta(minutes=20))
    with (
        watching() as seen,
        django_capture_on_commit_callbacks(execute=True),
        tenant(owner),
    ):
        marked = mark_no_show(appointment_id=absent.id, idempotency_key="n", principal_ref="t")
        again = mark_no_show(appointment_id=absent.id, idempotency_key="n", principal_ref="t")
    assert marked.status == again.status == AppointmentStatus.NO_SHOW
    assert [change.change for change in seen] == [NO_SHOW]
    assert marked.needs_assignment is False
    # The person is free from the moment it was marked, not from the planned end.
    held = AppointmentStaffAllocation.all_objects.get(appointment=absent).occupied_range
    assert absent.starts_at < held.upper <= timezone.now() < absent.ends_at
    assert SelfServiceRoute.objects.get(pk=route.pk).revoked_at is not None
    history = AppointmentStatusHistory.all_objects.get(
        appointment=absent, to_status=AppointmentStatus.NO_SHOW
    )
    assert history.from_status == AppointmentStatus.CONFIRMED
    assert OrganizationAuditEntry.objects.filter(
        action="booking.appointment.no_show", target_id=absent.id
    ).exists()
    assert passing.has_passed(marked) is False

    # Closed: neither done afterwards, nor called off.
    with tenant(owner):
        with pytest.raises(AppointmentNotChangeable):
            complete_appointment(appointment_id=absent.id, idempotency_key="z", principal_ref="t")
        with pytest.raises(AppointmentNotChangeable):
            cancel_appointment(appointment_id=absent.id, idempotency_key="c", principal_ref="t")

    today = timezone.localdate(timezone=WARSAW)
    after(monkeypatch, timezone.now() + timedelta(days=1))
    counted = numbers(owner, first.id, today)
    assert counted["visits_done"]["value"] == 0
    assert counted["no_shows"]["value"] == 1
    assert counted["canceled"]["value"] == 0


def test_no_show_answers_through_http() -> None:
    configured = company("nieobecnosc-http")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    booked = book(owner, configured, at(day, 9), "a")
    url = f"/api/v1/booking/appointments/{booked.id}/no-show/"
    client = authenticated_client(owner)

    early = client.post(url, HTTP_IDEMPOTENCY_KEY="wczesnie")
    assert (early.status_code, early.json()["code"]) == (409, "visit_not_started_yet")

    moved(booked, timezone.now() - timedelta(minutes=30))
    # Somebody without the calendar's management may look, not close it.
    assert authenticated_client(worker).post(url, HTTP_IDEMPOTENCY_KEY="p").status_code == 403
    answer = client.post(url, HTTP_IDEMPOTENCY_KEY="teraz")
    assert answer.status_code == 200
    assert (answer.json()["status"], answer.json()["passed"]) == ("no_show", False)
    assert client.post(url, HTTP_IDEMPOTENCY_KEY="teraz").status_code == 200
    closed = client.post(
        f"/api/v1/booking/appointments/{booked.id}/complete/", HTTP_IDEMPOTENCY_KEY="potem"
    )
    assert (closed.status_code, closed.json()["code"]) == (409, "appointment_not_changeable")


def test_a_module_lists_only_its_own_kinds_or_the_plain_service(tmp_path: Path) -> None:
    def descriptor(kinds: list[str]) -> str:
        return json.dumps({
            "id": "vertical.test",
            "layer": "vertical",
            "backend": {
                "djangoApp": None,
                "appointmentKinds": {"test.visit": "Wizyta"},
                "appointmentKindsCompletedExplicitly": kinds,
            },
        })

    (tmp_path / "vertical.test.json").write_text(descriptor(["test.visit", ""]))
    assert load_catalog(tmp_path)["vertical.test"].completed_explicitly_kinds == ("test.visit", "")
    (tmp_path / "vertical.test.json").write_text(descriptor(["other.visit"]))
    with pytest.raises(CompositionError):
        load_catalog(tmp_path)
