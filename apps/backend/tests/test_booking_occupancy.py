"""Obłożenie: units against days, from one read (ADR-072 phase 2d)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from saas_core.modules.shared.booking.occupancy import occupancy
from saas_core.modules.shared.booking.rules import save_closure
from saas_core.modules.shared.booking.setup import save_resource
from saas_core.modules.shared.booking.units import add_unit_block
from test_booking import membership, tenant
from test_booking_stays import WARSAW, cottages, key, saturday_after, stay
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def company(slug: str, units: int = 2) -> tuple[Any, dict[str, Any]]:
    owner = membership(slug)
    bookable(owner.organization)
    return owner, cottages(owner, units)


def test_the_grid_has_every_unit_with_its_stays_blocks_and_closed_days() -> None:
    owner, setup = company("oblozenie")
    first = saturday_after(14)
    first_unit, second_unit = setup["units"]
    with tenant(owner):
        booked = stay(setup, first, first + timedelta(days=3), resource_id=first_unit.id)
        add_unit_block(
            resource_id=second_unit.id,
            starts_at=datetime.combine(first + timedelta(days=1), time(), WARSAW),
            ends_at=datetime.combine(first + timedelta(days=4), time(), WARSAW),
            reason="Malowanie",
            idempotency_key=key(),
        )
        save_closure(
            closure_id=None,
            data={"starts_on": first + timedelta(days=6), "ends_on": first + timedelta(days=6)},
            idempotency_key=key(),
        )
        grid = occupancy(first=first, last=first + timedelta(days=13))
    assert [unit.name for unit in grid.units] == ["Domek 1", "Domek 2"]
    assert [(item.kind, item.unit_id) for item in grid.held] == [
        ("stay", first_unit.id),
        ("block", second_unit.id),
    ]
    assert grid.held[0].appointment is not None
    assert grid.held[0].appointment.id == booked.appointment.id
    assert [closure.starts_on for closure in grid.closures] == [first + timedelta(days=6)]

    body = (
        authenticated_client(owner)
        .get(f"/api/v1/booking/occupancy/?from={first}&to={first + timedelta(days=13)}")
        .json()
    )
    assert [unit["group_name"] for unit in body["units"]] == ["Domek 6-os.", "Domek 6-os."]
    assert [(item["kind"], item["title"], item["status"]) for item in body["held"]] == [
        ("stay", "Gość", "confirmed"),
        ("block", "Malowanie", ""),
    ]
    assert body["timezone"] == "Europe/Warsaw"
    # The calendar shows „Obłożenie” to a company that books by dates.
    assert authenticated_client(owner).get("/api/v1/booking/overview/").json()["stays"] is True


def test_a_long_window_over_many_units_costs_the_same_few_queries() -> None:
    owner, setup = company("oblozenie-duze", units=3)
    first = saturday_after(7)
    with tenant(owner):
        for n in range(3):
            stay(setup, first + timedelta(days=3 * n), first + timedelta(days=3 * n + 2))

        def counted() -> int:
            with CaptureQueriesContext(connection) as queries:
                occupancy(first=first, last=first + timedelta(days=61))
            return len(queries)

        few = counted()
        for n in range(4, 31):
            save_resource(
                resource_id=None,
                data={
                    "name": f"Domek {n}",
                    "group_id": setup["group"].id,
                    "location_id": setup["place"].id,
                },
                idempotency_key=key(),
            )
        for n in range(3, 20):
            stay(setup, first + timedelta(days=3 * n), first + timedelta(days=3 * n + 2))
        many = counted()
    # 62 days of 30 units and 20 stays: no query per unit, per day or per stay.
    assert many == few
    assert many <= 12


def test_the_window_is_bounded_and_the_grid_is_the_managers() -> None:
    owner, _ = company("oblozenie-granice")
    worker = member_of(owner, "oblozenie-granice.pracownik@example.test", "staff")
    first = saturday_after(7)
    client = authenticated_client(owner)
    too_long = client.get(
        f"/api/v1/booking/occupancy/?from={first}&to={first + timedelta(days=62)}"
    )
    assert (too_long.status_code, too_long.json()["errors"][0]["field"]) == (400, "to")
    backwards = client.get(f"/api/v1/booking/occupancy/?from={first}&to={first - timedelta(1)}")
    assert backwards.status_code == 400
    assert client.get("/api/v1/booking/occupancy/?from=2026-02-30&to=2026-03-01").status_code == 400
    # Until a product narrows who sees whose bookings (UX-023), the grid is
    # the calendar manager's.
    staff = authenticated_client(worker).get(
        f"/api/v1/booking/occupancy/?from={first}&to={first + timedelta(days=6)}"
    )
    assert staff.status_code == 403
