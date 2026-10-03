"""The keeper's „Dziś” reads (UX-078): visits over all farms, controls due."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.shared.farms.api import farm_animals
from saas_core.modules.shared.farms.herd_sync import (
    list_register_visits,
    publish_farm_visit,
    publish_health_entry,
)
from saas_core.modules.shared.farms.models import FarmShare, VisitStatus
from saas_core.modules.shared.farms.services import (
    create_animal,
    create_farm,
    list_follow_ups,
)
from saas_core.modules.shared.farms.sharing import (
    issue_activation_code,
    redeem_activation_code,
    revoke_share,
)
from test_farms import link_for_schedule, membership, tenant
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

WARSAW = ZoneInfo("Europe/Warsaw")


def at(day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, time(hour), WARSAW)


def visit(company: Any, card: Any, reference: str, status: str, day: date) -> None:
    with tenant(company):
        publish_farm_visit(
            company_organization_id=company.organization_id,
            company_farm_id=card.id,
            source="hoofcare.visit",
            reference=reference,
            status=status,
            scheduled_for=at(day),
            occurred_on=day if status == VisitStatus.DONE else None,
            summary=reference,
        )


def test_every_farms_visits_by_day_and_none_a_company_may_no_longer_move() -> None:
    farmer = membership("rolnik-dzis")
    first = membership("firma-dzis-1")
    second = membership("firma-dzis-2")
    with tenant(farmer) as request:
        north = create_farm(request=request, data={"name": "Gospodarstwo Północ"})
        south = create_farm(request=request, data={"name": "Gospodarstwo Południe"})
    north_card, north_share = link_for_schedule(first, farmer, north.id)
    south_card, south_share = link_for_schedule(second, farmer, south.id)
    today = timezone.localdate(timezone=WARSAW)
    visit(first, north_card, "north-done", VisitStatus.DONE, today - timedelta(days=2))
    visit(first, north_card, "north-planned", VisitStatus.PLANNED, today + timedelta(days=3))
    visit(second, south_card, "south-planned", VisitStatus.PLANNED, today + timedelta(days=10))
    visit(second, south_card, "south-canceled", VisitStatus.CANCELED, today + timedelta(days=1))

    with tenant(farmer) as request:
        everything = list_register_visits()
        assert [item.summary for item in everything] == [
            "north-done",
            "south-canceled",
            "north-planned",
            "south-planned",
        ]
        assert {item.farm.name for item in everything} == {
            "Gospodarstwo Północ",
            "Gospodarstwo Południe",
        }
        ahead = list_register_visits(starts_on=today, ends_on=today + timedelta(days=7))
        assert [item.summary for item in ahead] == ["south-canceled", "north-planned"]
        assert [item.summary for item in list_register_visits(status=VisitStatus.DONE)] == [
            "north-done"
        ]

        # The keeper takes the schedule consent back: the second company can
        # no longer move its planned visit, so it does not hang in the future.
        FarmShare.objects.filter(pk=south_share.pk).update(can_publish_schedule=False)
        assert [item.summary for item in list_register_visits()] == [
            "north-done",
            "south-canceled",
            "north-planned",
        ]
        # A revoked share: the same, and the history stays.
        revoke_share(request=request, share_id=north_share.id)
        assert [item.summary for item in list_register_visits()] == [
            "north-done",
            "south-canceled",
        ]

    client = authenticated_client(farmer)
    answer = client.get(f"/api/v1/farms/visits/?from={today}&status=canceled")
    assert answer.status_code == 200
    assert [(item["summary"], item["farm_name"]) for item in answer.json()] == [
        ("south-canceled", "Gospodarstwo Południe")
    ]
    assert client.get("/api/v1/farms/visits/?status=somewhen").status_code == 400
    assert client.get("/api/v1/farms/visits/?from=2026-02-30").status_code == 400


def test_the_visit_list_costs_the_same_few_queries_for_many_farms() -> None:
    farmer = membership("rolnik-dzis-duzo")
    today = timezone.localdate(timezone=WARSAW)

    def counted() -> int:
        with tenant(farmer), CaptureQueriesContext(connection) as queries:
            list_register_visits(starts_on=today - timedelta(days=30))
        return len(queries)

    def farms(count: int, offset: int) -> None:
        for n in range(count):
            with tenant(farmer) as request:
                farm = create_farm(request=request, data={"name": f"Gospodarstwo {offset + n}"})
            # Each farm with its own company: one card per company and name.
            company = membership(f"firma-dzis-duzo-{offset + n}")
            card, _ = link_for_schedule(company, farmer, farm.id)
            visit(company, card, f"planned-{offset + n}", VisitStatus.PLANNED, today + timedelta(1))
            visit(company, card, f"done-{offset + n}", VisitStatus.DONE, today - timedelta(1))

    farms(1, 0)
    few = counted()
    farms(8, 1)
    many = counted()
    # No query per farm, per share or per visit.
    assert many == few
    assert many <= 8


def test_a_control_reaches_the_keeper_only_under_the_health_consent() -> None:
    """ADR-052, addendum 2026-10-03: `follow_up_on` is the date the entry's text
    already gave the keeper; without the health consent there is no entry, so
    there is no date either."""
    company = membership("firma-kontrola")
    farmer = membership("rolnik-kontrola")
    with tenant(company) as request:
        card = create_farm(request=request, data={"name": "Gospodarstwo Kontrola"})
        cow = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432166001"}
        )
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        registry_cow = list(farm_animals(farmer.organization_id, taken["farm"].id))[0]
        share = taken["share"]
    today = timezone.localdate(timezone=WARSAW)
    due = today + timedelta(days=14)

    with tenant(company):
        assert publish_health_entry(
            animal=cow,
            occurred_on=today,
            source="hoofcare.visit",
            reference="visit-1",
            summary="Korekcja: DD M2 na LH, kontrola za 14 dni.",
            follow_up_on=due,
        )
    with tenant(farmer):
        (control,) = list_follow_ups(starts_on=today)
        assert (control.follow_up_on, control.animal_id) == (due, registry_cow.id)
        assert list_follow_ups(starts_on=due + timedelta(days=1)) == []
    body = authenticated_client(farmer).get(f"/api/v1/farms/follow-ups/?from={today}").json()
    assert [(item["follow_up_on"], item["national_id"], item["farm_name"]) for item in body] == [
        (due.isoformat(), "PL005432166001", "Gospodarstwo Kontrola")
    ]

    # A correction without a control replaces it: only what stands counts.
    with tenant(company):
        publish_health_entry(
            animal=cow,
            occurred_on=today,
            source="hoofcare.visit",
            reference="visit-1",
            summary="Korekcja: DD M2 na LH, bez kontroli.",
            correction="Kontrola niepotrzebna",
        )
    with tenant(farmer):
        assert list_follow_ups() == []

    # Without the health consent nothing is published, a date included.
    FarmShare.objects.filter(pk=share.pk).update(can_publish_health=False)
    with tenant(company):
        assert (
            publish_health_entry(
                animal=cow,
                occurred_on=today,
                source="hoofcare.visit",
                reference="visit-2",
                summary="Kontrola za tydzień.",
                follow_up_on=today + timedelta(days=7),
            )
            is None
        )
    with tenant(farmer) as request:
        assert list_follow_ups() == []
        revoke_share(request=request, share_id=share.id)
