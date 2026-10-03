"""Whose visits a person sees (UX-023): everyone's by default; with a product's
permission declared, only one's own without it — MedPlano's doctors."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from saas_core.config.composition import (
    CompositionError,
    load_catalog,
    others_permission_for,
)
from test_booking import _no_delivery
from test_booking_slots import at, book
from test_team_facts import company
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)


def test_a_person_sees_others_visits_only_where_the_product_lets_them(settings: Any) -> None:
    configured = company("widocznosc-wizyt")
    owner, worker, day = configured["owner"], configured["worker"], configured["day"]
    first, second = configured["staff"]
    own = book(owner, configured, at(day, 9), "a", first)
    others = book(owner, configured, at(day, 11), "b", second)
    url = (
        f"/api/v1/booking/appointments/?from={day - timedelta(days=1)}&to={day + timedelta(days=2)}"
    )

    def seen(member: Any, extra: str = "") -> set[str]:
        response = authenticated_client(member).get(url + extra)
        assert response.status_code == 200, response.json()
        return {item["id"] for item in response.json()["items"]}

    both = {str(own.id), str(others.id)}
    # Core: a small team plans together, so the calendar is everyone's (a
    # product that declares the permission — MedPlano — starts elsewhere).
    settings.BOOKING_OTHERS_PERMISSION = None
    assert seen(worker) == both

    settings.BOOKING_OTHERS_PERMISSION = "test.visits.all"
    assert seen(worker) == {str(own.id)}
    # Somebody else named: their visits only where the caller is on them too.
    assert seen(worker, f"&staff_id={second.id}") == set()
    assert seen(worker, f"&staff_id={first.id}") == {str(own.id)}
    # Whoever plans visits sees everyone's.
    assert seen(owner) == both

    # The product's permission opens them (here one the staff role holds).
    settings.BOOKING_OTHERS_PERMISSION = "booking.schedule.own"
    assert seen(worker) == both


def test_the_permission_is_the_modules_own_and_there_is_one(tmp_path: Path) -> None:
    def write(module_id: str, permission: str, declared: list[str]) -> None:
        (tmp_path / f"{module_id}.json").write_text(
            json.dumps({
                "id": module_id,
                "layer": "vertical",
                "backend": {
                    "djangoApp": None,
                    "permissions": declared,
                    "appointmentsOfOthersPermission": permission,
                },
            })
        )

    write("vertical.one", "one.visits.all", ["one.visits.all"])
    catalog = load_catalog(tmp_path)
    assert others_permission_for(("vertical.one",), catalog) == "one.visits.all"

    write("vertical.two", "two.visits.all", ["two.visits.all"])
    with pytest.raises(CompositionError):
        others_permission_for(("vertical.one", "vertical.two"), load_catalog(tmp_path))

    write("vertical.two", "core.visits.all", ["two.visits.all"])
    with pytest.raises(CompositionError):
        load_catalog(tmp_path)
