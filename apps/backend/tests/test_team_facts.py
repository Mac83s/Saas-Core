"""A person's results and history (team plan, phase 5): what counts, who may
read whose, and the warehouse's numbers beside the calendar's."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from django.utils import timezone

from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.lifecycle import update_membership
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.billing.models import EntitlementSnapshot, Feature
from saas_core.modules.shared.booking import facts
from saas_core.modules.shared.booking.dispatch import assign_crew
from saas_core.modules.shared.booking.facts import staff_facts, staff_history, team_performance
from saas_core.modules.shared.booking.models import Appointment, Service, StaffMember
from saas_core.modules.shared.booking.services import cancel_appointment, complete_appointment
from saas_core.modules.shared.booking.staff import add_time_off
from test_booking import _no_delivery, membership, tenant
from test_booking_slots import WARSAW, at, book, team
from test_team_people import acting, bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)


def company(slug: str) -> dict[str, Any]:
    """Two people doing a one-hour service 08:00–16:00, a week from today;
    the first of them works with an account."""
    owner = membership(slug)
    bookable(owner.organization)
    configured = team(owner, people=2, hours=(time(8), time(16)), duration=60)
    worker = member_of(owner, f"{slug}.pracownik@example.test", "staff")
    first, second = configured["staff"]
    StaffMember.all_objects.filter(pk=first.id).update(membership=worker)
    configured.update(
        owner=owner,
        worker=worker,
        day=timezone.localdate(timezone=WARSAW) + timedelta(days=7),
    )
    return configured


def numbers(member: Membership, staff_id: Any, day: Any, *, provider: str = "calendar") -> dict:
    with tenant(member):
        result = staff_facts(staff_id, day, day)
    group = next(item for item in result["groups"] if item["provider"] == provider)
    return {metric["key"]: metric for metric in group["metrics"]}


def after(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(facts, "_now", lambda: moment)


def test_a_visit_that_took_place_counts_and_a_canceled_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = company("fakty-liczenie")
    owner, day = configured["owner"], configured["day"]
    first = configured["staff"][0]
    booked = book(owner, configured, at(day, 9), "a", first)
    canceled = book(owner, configured, at(day, 11), "b", first)
    finished = book(owner, configured, at(day, 13), "c", first)
    chosen = book(owner, configured, at(day, 15), "d", first)
    with tenant(owner):
        cancel_appointment(
            appointment_id=canceled.id, idempotency_key="b-off", principal_ref=str(owner.user_id)
        )
        # Ended half an hour in: the hours count to the real end.
        complete_appointment(
            appointment_id=finished.id,
            idempotency_key="c-done",
            principal_ref=str(owner.user_id),
            ended_at=at(day, 13, 30),
        )
        Appointment.all_objects.filter(pk=chosen.id).update(requested_staff_id=first.id)

    # Time has passed for all of them; nobody pressed „Zakończ” on two (3A).
    after(monkeypatch, at(day + timedelta(days=1), 8))
    counted = numbers(owner, first.id, day)
    assert counted["visits_done"]["value"] == 3
    assert counted["visits_done"]["parts"] == {"lead": 3, "crew": 0}
    assert counted["hours"]["value"] == 60 + 30 + 60
    assert counted["canceled"]["value"] == 1
    assert counted["chosen_by_customer"]["value"] == 1
    assert counted["visits_done"]["previous"] == 0

    # Before the day, nothing has taken place yet.
    after(monkeypatch, at(day, 10, 30))
    assert numbers(owner, first.id, day)["visits_done"]["value"] == 1
    assert booked.id


def test_a_visit_in_the_crew_counts_apart_from_leading(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = company("fakty-sklad")
    owner, day = configured["owner"], configured["day"]
    first, second = configured["staff"]
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(staff_count=2)
    configured["service"].refresh_from_db()
    visit = book(owner, configured, at(day, 9), "dwoje")
    lead = visit.staff_id
    other = second.id if lead == first.id else first.id
    after(monkeypatch, at(day + timedelta(days=1), 8))
    assert numbers(owner, lead, day)["visits_done"]["parts"] == {"lead": 1, "crew": 0}
    assert numbers(owner, other, day)["visits_done"]["parts"] == {"lead": 0, "crew": 1}


def test_other_peoples_results_are_the_owners_and_administrators_only() -> None:
    configured = company("fakty-dostep")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    first, second = configured["staff"]
    manager = member_of(owner, "fakty-dostep.kierownik@example.test", "manager")
    admin = member_of(owner, "fakty-dostep.admin@example.test", "admin")

    # One's own, always.
    assert numbers(worker, first.id, day)["visits_done"]["value"] == 0
    # Somebody else's: not for the worker, and not for the manager who assigns visits.
    for member in (worker, manager):
        with tenant(member), pytest.raises(OrganizationPermissionDenied):
            staff_facts(second.id, day, day)
        with tenant(member), pytest.raises(OrganizationPermissionDenied):
            team_performance(day, day)
    for member in (owner, admin):
        assert numbers(member, second.id, day)["hours"]["value"] == 0
        with tenant(member):
            rows = team_performance(day, day)["items"]
        assert {row["staff_id"] for row in rows} == {first.id, second.id}
    assert "booking.staff.performance.read" in SYSTEM_ROLE_PERMISSIONS["owner"]
    assert "booking.staff.performance.read" in SYSTEM_ROLE_PERMISSIONS["admin"]
    assert "booking.staff.performance.read" not in SYSTEM_ROLE_PERMISSIONS["manager"]


def test_history_tells_assignments_absences_and_role_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = company("fakty-historia")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    first, second = configured["staff"]
    visit = book(owner, configured, at(day, 9), "h", second)
    today = timezone.localdate(timezone=WARSAW)
    with tenant(owner):
        assign_crew(
            appointment_id=visit.id,
            staff_ids=[first.id],
            lead_id=first.id,
            expected_version=visit.crew_version,
            notify_staff=False,
            idempotency_key="przydzial",
            principal_ref=str(owner.user_id),
        )
        add_time_off(
            staff_id=first.id,
            starts_at=at(day, 14),
            ends_at=at(day, 16),
            reason="Szkolenie",
        )
        update_membership(request=acting(owner), membership_id=worker.id, role_key="manager")

    with tenant(owner):
        seen = staff_history(first.id, today, day)
    events = {item["event"]: item for item in seen["items"]}
    assert events["assigned"]["params"]["customer"] == "Klient h"
    assert events["time_off"]["params"]["reason"] == "Szkolenie"
    assert (events["role_changed"]["params"]["from"], events["role_changed"]["params"]["to"]) == (
        "staff",
        "manager",
    )
    assert seen["items"] == sorted(seen["items"], key=lambda item: item["at"], reverse=True)
    with tenant(owner):
        taken_off = staff_history(second.id, today, day)
    assert [item["event"] for item in taken_off["items"]] == ["unassigned"]
    with tenant(owner):
        only = staff_history(first.id, today, day, kind="account")
    assert [item["kind"] for item in only["items"]] == ["account"]


@pytest.mark.skipif(
    "shared.inventory" not in settings.ACTIVE_MODULES, reason="magazyn tylko w profilu z nim"
)
def test_the_warehouse_counts_what_a_person_took_used_and_gave_back() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        balances,
        consume,
        create_item,
        give_back,
        issue,
        movements,
        receive,
    )

    configured = company("fakty-magazyn")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    first = configured["staff"][0]
    Feature.objects.get_or_create(
        key="inventory.enabled", defaults={"name": "Magazyn", "module": "shared.inventory"}
    )
    EntitlementSnapshot.all_objects.filter(organization_id=owner.organization_id).update(
        features={"booking.enabled": True, "inventory.enabled": True}
    )
    request = acting(owner)
    with tenant(owner):
        block = create_item(request=request, data={"name": "Klocek"})
        receive(request=request, item_id=block.id, quantity=Decimal(40), unit_cost_minor=250)
        issue(request=request, item_id=block.id, holder_id=worker.user_id, quantity=Decimal(10))
        consume(
            organization_id=owner.organization_id,
            source="test",
            source_reference="wizyta",
            lines=[(block.id, Decimal(4))],
            holder_id=worker.user_id,
            actor_id=worker.user_id,
        )
        give_back(request=request, item_id=block.id, holder_id=worker.user_id, quantity=Decimal(1))

    today = timezone.localdate(timezone=WARSAW)
    for member in (owner, worker):
        with tenant(member):
            result = staff_facts(first.id, today, day)
        stock = {
            metric["key"]: metric
            for group in result["groups"]
            if group["provider"] == "inventory"
            for metric in group["metrics"]
        }
        # Ten taken, four used, one back, five held — at 2,50 zł each.
        assert {key: stock[key]["value"] for key in stock} == {
            "taken": 2500,
            "used": 1000,
            "returned": 250,
            "on_hand": 1250,
        }
        assert stock["on_hand"]["previous"] is None
    with tenant(owner):
        page = staff_history(first.id, today, day, kind="inventory")
    kinds = [item["event"] for item in page["items"]]
    assert sorted(kinds) == ["returned", "taken", "used"]

    # Another person's stock is the warehouse keeper's (answer 2.2a, 29.09).
    colleague = member_of(owner, "fakty-magazyn.kolega@example.test", "staff")
    with tenant(colleague):
        with pytest.raises(OrganizationPermissionDenied):
            balances(holder_id=worker.user_id)
        assert balances(mine=True) == []
        assert not [move for move in movements() if move.location.holder_id == worker.user_id]
    with tenant(worker):
        assert {row.item.name: row.quantity for row in balances(mine=True)} == {"Klocek": 5}


def test_the_doors_answer_through_http(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = company("fakty-http")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    first, second = configured["staff"]
    book(owner, configured, at(day, 9), "http", first)
    after(monkeypatch, at(day + timedelta(days=1), 8))
    client = authenticated_client(owner)
    body = client.get(f"/api/v1/booking/staff/{first.id}/facts/?from={day}&to={day}").json()
    calendar = next(group for group in body["groups"] if group["provider"] == "calendar")
    assert {metric["key"]: metric["value"] for metric in calendar["metrics"]}["visits_done"] == 1
    assert client.get(f"/api/v1/booking/staff/{first.id}/history/").status_code == 200
    assert client.get(f"/api/v1/booking/performance/?from={day}&to={day}").status_code == 200
    assert client.get("/api/v1/booking/performance/?from=2026-02-30").status_code == 400

    colleague = authenticated_client(worker)
    assert colleague.get(f"/api/v1/booking/staff/{first.id}/facts/").status_code == 200
    assert colleague.get(f"/api/v1/booking/staff/{second.id}/facts/").status_code == 403
    assert colleague.get("/api/v1/booking/performance/").status_code == 403
