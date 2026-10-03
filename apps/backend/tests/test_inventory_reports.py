"""The warehouse's reports (phase 10b): stock value, usage in a period, the cost
of a visit — for whoever runs the warehouse only."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from rest_framework.exceptions import ValidationError

import test_booking as booking_tests
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import Membership, Role, RoleScope
from test_inventory import (
    core_catalog,  # noqa: F401 — core's own catalogue, not a product's
    item,
    membership,
    tenant,
)
from test_inventory_alerts import member

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        "shared.inventory" not in settings.ACTIVE_MODULES,
        reason="magazyn istnieje tylko w profilu, który go składa",
    ),
]

VISIT = "test.visit"


def receive(request: Any, item_id: Any, quantity: int, cost: int) -> None:
    from saas_core.modules.shared.inventory.services import receive as pz  # noqa: PLC0415

    pz(request=request, item_id=item_id, quantity=Decimal(quantity), unit_cost_minor=cost)


def period(owner: Membership) -> dict[str, Any]:
    from saas_core.modules.shared.inventory.api import organization_today  # noqa: PLC0415

    today = organization_today(owner.organization_id)
    return {"first": today - timedelta(days=7), "last": today}


def rows(report: dict[str, Any]) -> dict[str, tuple[int, int]]:
    return {row["name"]: (row["cost_minor"], row["sold_minor"]) for row in report["rows"]}


def test_stock_value_is_quantity_times_average_cost_by_item_category_and_place() -> None:
    from saas_core.modules.shared.inventory.reports import stock_value  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        issue,
        list_categories,
        update_item,
    )

    owner = membership("raport-wartosc")
    trimmer = member(owner, "raport-wartosc-korektor", "staff")
    with tenant(owner) as request:
        block, gloves = item(request, "Klocek"), item(request, "Rękawiczki")
        material = next(c for c in list_categories() if c.key == "material")
        update_item(request=request, item_id=gloves.id, data={"category": str(material.id)})
        receive(request, block.id, 10, 250)
        receive(request, gloves.id, 4, 1000)
        issue(request=request, item_id=block.id, holder_id=trimmer.user_id, quantity=Decimal(4))

        by_item = stock_value()
        assert [(row["name"], row["quantity"], row["value_minor"]) for row in by_item["rows"]] == [
            ("Rękawiczki", Decimal(4), 4000),
            ("Klocek", Decimal(10), 2500),
        ]
        assert by_item["totals"] == [{"currency": "PLN", "value_minor": 6500}]

        by_category = stock_value(group="category")
        assert {row["name"]: row["value_minor"] for row in by_category["rows"]} == {
            "Materiał": 4000,
            "": 2500,
        }
        by_place = stock_value(group="location")
        assert {(row["kind"], row["value_minor"]) for row in by_place["rows"]} == {
            ("warehouse", 5500),
            ("person", 1000),
        }
        # One place only: the trimmer's kit.
        from saas_core.modules.shared.inventory.api import person_location  # noqa: PLC0415

        kit = person_location(owner.organization_id, trimmer.user_id)
        assert stock_value(location_id=kit.id)["totals"] == [
            {"currency": "PLN", "value_minor": 1000}
        ]


def test_usage_counts_what_went_out_at_its_cost_and_a_correction_nets_out() -> None:
    from saas_core.modules.shared.inventory.api import cancel_source, consume  # noqa: PLC0415
    from saas_core.modules.shared.inventory.reports import usage  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import adjust, issue  # noqa: PLC0415

    owner = membership("raport-zuzycie")
    trimmer = member(owner, "raport-zuzycie-korektor", "staff")
    with tenant(owner) as request:
        block = item(request, "Klocek")
        receive(request, block.id, 20, 300)
        # A transfer and a receipt are not usage.
        issue(request=request, item_id=block.id, holder_id=trimmer.user_id, quantity=Decimal(10))
        for reference, quantity in (("wpis-1", 2), ("wpis-2", 3)):
            consume(
                organization_id=owner.organization_id,
                holder_id=trimmer.user_id,
                source="hoofcare.entry",
                source_reference=reference,
                lines=[(block.id, Decimal(quantity))],
            )
        # A later, dearer delivery does not rewrite what was already used.
        receive(request, block.id, 20, 900)
        adjust(
            request=request,
            item_id=block.id,
            holder_id=None,
            quantity=Decimal(-1),
            note="Zniszczony",
        )
        by_item = usage(**period(owner))
        (row,) = by_item["rows"]
        assert (row["name"], row["quantity"], row["unit"]) == ("Klocek", Decimal(6), "piece")
        # 5 at 300, then one at the new average: (15×300 + 20×900) / 35 = 642.
        assert (row["cost_minor"], row["documents"]) == (5 * 300 + 642, 3)
        assert by_item["totals"] == [{"currency": "PLN", "cost_minor": 2142, "sold_minor": 0}]

        by_person = usage(group="person", **period(owner))
        assert rows(by_person) == {
            "raport-zuzycie-korektor@example.test": (1500, 0),
            "raport-zuzycie@example.test": (642, 0),
        }

        # A withdrawn entry gives the material back: the pair nets out.
        cancel_source(
            organization_id=owner.organization_id,
            actor_id=owner.user_id,
            source="hoofcare.entry",
            source_reference="wpis-2",
        )
        assert usage(**period(owner))["rows"][0]["cost_minor"] == 2 * 300 + 642


def test_a_source_says_which_visit_service_and_customer_the_usage_was_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.utils import timezone  # noqa: PLC0415

    from saas_core.modules.shared.inventory import reports  # noqa: PLC0415
    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        UsageContext,
        consume,
        default_warehouse,
    )
    from saas_core.modules.shared.inventory.services import adjust  # noqa: PLC0415

    owner = membership("raport-zrodlo")
    worker = member(owner, "raport-zrodlo-pracownik", "staff")
    now = timezone.now()

    def describe(organization_id: Any, references: Any) -> dict[str, UsageContext]:
        assert organization_id == owner.organization_id
        return {
            "v1": UsageContext("v1", now, "s1", "Strzyżenie", "c1", "Jan Kowalski", worker.user_id),
            "v2": UsageContext(
                "v2", now - timedelta(hours=1), "s1", "Strzyżenie", "c2", "Ewa Nowak"
            ),
        }

    monkeypatch.setitem(reports._sources, VISIT, describe)
    with tenant(owner) as request:
        oil = item(request, "Olej")
        receive(request, oil.id, 10, 400)
        warehouse = default_warehouse(owner.organization_id).id
        consume(
            organization_id=owner.organization_id,
            source=VISIT,
            source_reference="v1",
            lines=[(oil.id, Decimal(2))],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        consume(
            organization_id=owner.organization_id,
            source=VISIT,
            source_reference="v2",
            lines=[(oil.id, Decimal(1))],
            location_id=warehouse,
            actor_id=owner.user_id,
            kind="WZ",
            unit_prices={oil.id: 1500},
        )
        # Nothing caused it but the company itself: a loss.
        adjust(
            request=request, item_id=oil.id, holder_id=None, quantity=Decimal(-1), note="Rozlany"
        )
        span = period(owner)
        assert rows(reports.usage(group="service", **span)) == {
            "Strzyżenie": (1200, 1500),
            "": (400, 0),
        }
        assert rows(reports.usage(group="customer", **span)) == {
            "Jan Kowalski": (800, 0),
            "Ewa Nowak": (400, 1500),
            "": (400, 0),
        }
        # The visit's lead, where the source knows; else who posted.
        assert rows(reports.usage(group="person", **span)) == {
            "raport-zrodlo-pracownik@example.test": (800, 0),
            "raport-zrodlo@example.test": (800, 1500),
        }
        visits = reports.usage(group="visit", **span)
        assert [
            (row["key"], row["service_name"], row["customer_name"], row["cost_minor"])
            for row in visits["rows"]
        ] == [
            ("v1", "Strzyżenie", "Jan Kowalski", 800),
            ("v2", "Strzyżenie", "Ewa Nowak", 400),
            ("", "", "", 400),
        ]
        assert visits["rows"][0]["person_name"] == "raport-zrodlo-pracownik@example.test"
        # A customer's name is in the customer and visit reports only.
        for group in ("item", "person", "service"):
            for row in reports.usage(group=group, **span)["rows"]:
                assert row["customer_name"] == ""
                assert "Kowalski" not in row["name"] and "Nowak" not in row["name"]
        # Pages: the total is every row, a page holds its slice.
        page = reports.usage(group="visit", page=2, page_size=2, **span)
        assert (page["total"], len(page["rows"])) == (3, 1)


def test_reports_are_for_whoever_runs_the_warehouse_and_a_period_has_limits() -> None:
    from saas_core.modules.shared.inventory.reports import stock_value, usage  # noqa: PLC0415
    from saas_core.modules.shared.inventory.serializers import (  # noqa: PLC0415
        UsageQuerySerializer,
    )

    owner = membership("raport-dostep")
    worker = member(owner, "raport-dostep-pracownik", "staff")
    with tenant(worker):
        with pytest.raises(OrganizationPermissionDenied):
            stock_value()
        for group in ("item", "customer", "visit"):
            with pytest.raises(OrganizationPermissionDenied):
                usage(group=group, **period(owner))
    with tenant(owner):
        span = period(owner)
        with pytest.raises(ValidationError) as backwards:
            usage(first=span["last"], last=span["first"])
        assert backwards.value.get_codes() == {"to": ["period"]}
        with pytest.raises(ValidationError) as long:
            usage(first=span["last"] - timedelta(days=366), last=span["last"])
        assert long.value.get_codes() == {"to": ["period_too_long"]}
        with pytest.raises(ValidationError):
            usage(group="supplier", **span)
    query = UsageQuerySerializer(data={"from": "2026-10-01", "to": "2026-10-03"})
    assert query.is_valid(), query.errors
    assert (query.validated_data["group"], query.validated_data["page_size"]) == ("item", 50)
    assert not UsageQuerySerializer(data={"to": "2026-10-03"}).is_valid()


@pytest.mark.skipif(
    "shared.booking" not in settings.ACTIVE_MODULES, reason="koszt wizyty wymaga kalendarza"
)
def test_a_calendar_visit_has_its_cost_and_its_customer_only_for_who_may_see_them(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    from saas_core.modules.shared.billing.models import (  # noqa: PLC0415
        EntitlementSnapshot,
        Feature,
    )
    from saas_core.modules.shared.booking.services import (  # noqa: PLC0415
        complete_appointment,
        set_service_materials,
    )
    from saas_core.modules.shared.inventory.reports import usage  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import create_item  # noqa: PLC0415

    booking_tests._no_delivery(monkeypatch)
    owner = booking_tests.membership("raport-wizyta")
    Feature.objects.get_or_create(
        key="inventory.enabled", defaults={"name": "Magazyn", "module": "shared.inventory"}
    )
    EntitlementSnapshot.all_objects.filter(organization_id=owner.organization_id).update(
        features={"booking.enabled": True, "inventory.enabled": True}
    )
    configured = booking_tests.catalog(owner)
    with booking_tests.tenant(owner):
        request = type("Request", (), {"user": owner.user})()
        oil = create_item(request=request, data={"name": "Olej", "sale_price_net_minor": 4000})
        towel = create_item(request=request, data={"name": "Ręcznik"})
        receive(request, oil.id, 10, 1000)
        receive(request, towel.id, 10, 200)
        set_service_materials(
            service_id=configured["service"].id,
            materials=[
                {"item_id": str(towel.id), "quantity": "1", "mode": "consume"},
                {"item_id": str(oil.id), "quantity": "2", "mode": "sale"},
            ],
        )
    appointment = booking_tests.create(owner, configured).appointment
    with booking_tests.tenant(owner):
        complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-report", principal_ref="t"
        )
        (visit,) = usage(group="visit", **period(owner))["rows"]
        assert (visit["key"], visit["service_name"]) == (str(appointment.id), "Konsultacja")
        # A towel used (200) and two oils sold (2 × 1000 at cost, 2 × 4000 charged).
        assert (visit["cost_minor"], visit["sold_minor"], visit["documents"]) == (2200, 8000, 2)
        assert visit["customer_name"] == appointment.customer.display_name
        (customer,) = usage(group="customer", **period(owner))["rows"]
        assert customer["key"] == str(appointment.customer_id)

    # A warehouse keeper who may not see other people's visits (a product that
    # says so, UX-023) gets the visit and its cost, not whose it was.
    settings.BOOKING_OTHERS_PERMISSION = "medical.visits.all"
    role = Role.objects.create(
        key="warehouse-keeper",
        organization=owner.organization,
        name="Magazynier",
        scope=RoleScope.ORGANIZATION,
        permissions=["inventory.read", "inventory.manage"],
    )
    keeper = member(owner, "raport-wizyta-magazynier", "staff")
    Membership.objects.filter(pk=keeper.pk).update(role=role)
    keeper.refresh_from_db()
    with booking_tests.tenant(keeper):
        (visit,) = usage(group="visit", **period(owner))["rows"]
        assert (visit["cost_minor"], visit["customer_name"]) == (2200, "")
        (customer,) = usage(group="customer", **period(owner))["rows"]
        assert (customer["key"], customer["name"]) == ("hidden", "")
