"""Produkty z magazynu przy wizycie (ADR-055, faza 6 planu magazynu).

Rezerwacja stanu od potwierdzenia, zejście przy zakończeniu (RW za zużycie, WZ
za sprzedaż klientowi), zwolnienie przy odwołaniu. Pomijane tam, gdzie profil
nie składa obu modułów.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from rest_framework.exceptions import ValidationError

import test_booking as booking_tests
from saas_core.modules.shared.billing.models import EntitlementSnapshot, Feature
from saas_core.modules.shared.booking.services import (
    AppointmentNotChangeable,
    cancel_appointment,
    complete_appointment,
    set_appointment_materials,
    set_service_materials,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not {"shared.booking", "shared.inventory"} <= set(settings.ACTIVE_MODULES),
        reason="produkty przy wizycie wymagają rezerwacji i magazynu",
    ),
]


def setup(slug: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Firma z kalendarzem, magazynem i dwiema pozycjami na stanie."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        create_item,
        receive,
    )

    member = booking_tests.membership(slug)
    # A transactional test flushes the migrations' feature rows after the first test.
    Feature.objects.get_or_create(
        key="inventory.enabled", defaults={"name": "Magazyn", "module": "shared.inventory"}
    )
    EntitlementSnapshot.all_objects.filter(organization_id=member.organization_id).update(
        features={"booking.enabled": True, "inventory.enabled": True}
    )
    configured = booking_tests.catalog(member)
    with booking_tests.tenant(member):
        request = type("Request", (), {"user": member.user})()
        oil = create_item(request=request, data={"name": "Olej", "sale_price_net_minor": 4000})
        towel = create_item(request=request, data={"name": "Ręcznik"})
        for item in (oil, towel):
            receive(request=request, item_id=item.id, quantity=Decimal(10), unit_cost_minor=100)
    return member, configured, {"oil": oil, "towel": towel}


def stock(member: Any, item: Any) -> tuple[Decimal, Decimal]:
    """(stan, dostępne) pozycji w magazynie głównym."""
    from saas_core.modules.shared.inventory.api import available, default_warehouse  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import balances  # noqa: PLC0415

    with booking_tests.tenant(member):
        warehouse = default_warehouse(member.organization_id)
        held = {row.item_id: Decimal(row.quantity) for row in balances()}
        return held[item.id], available(member.organization_id, item.id, warehouse.id)


def documents(member: Any, appointment_id: Any) -> list[tuple[str, str]]:
    from saas_core.modules.shared.inventory.services import list_documents  # noqa: PLC0415

    with booking_tests.tenant(member):
        return sorted(
            (document.kind, document.status)
            for document in list_documents()
            if document.source_reference == str(appointment_id)
        )


def test_a_visit_reserves_its_products_and_completion_takes_them_off_the_shelf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    booking_tests._no_delivery(monkeypatch)
    member, configured, items = setup("wizyta-produkty")
    with booking_tests.tenant(member):
        set_service_materials(
            service_id=configured["service"].id,
            materials=[
                {"item_id": str(items["towel"].id), "quantity": "1", "mode": "consume"},
                {"item_id": str(items["oil"].id), "quantity": "2", "mode": "sale"},
            ],
        )
    appointment = booking_tests.create(member, configured).appointment
    # Kopia z usługi, z nazwą i ceną sprzedaży z chwili rezerwacji.
    assert [(x["name"], x["mode"], x["unit_price_minor"]) for x in appointment.materials] == [
        ("Ręcznik", "consume", None),
        ("Olej", "sale", 4000),
    ]
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(8))

    with booking_tests.tenant(member):
        complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
    assert documents(member, appointment.id) == [("RW", "posted"), ("WZ", "posted")]
    assert stock(member, items["oil"]) == (Decimal(8), Decimal(8))
    assert stock(member, items["towel"]) == (Decimal(9), Decimal(9))


def test_a_canceled_visit_gives_the_reservation_back(monkeypatch: pytest.MonkeyPatch) -> None:
    booking_tests._no_delivery(monkeypatch)
    member, configured, items = setup("wizyta-odwolana")
    with booking_tests.tenant(member):
        set_service_materials(
            service_id=configured["service"].id,
            materials=[{"item_id": str(items["oil"].id), "quantity": "3", "mode": "consume"}],
        )
    appointment = booking_tests.create(member, configured).appointment
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(7))
    with booking_tests.tenant(member):
        cancel_appointment(
            appointment_id=appointment.id, idempotency_key="off-1", principal_ref="t"
        )
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(10))
    assert documents(member, appointment.id) == []


def test_products_typed_by_hand_replace_the_reservation_until_the_visit_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ręcznie można wpisać dowolną ilość — brak towaru ostrzega, nie blokuje."""
    booking_tests._no_delivery(monkeypatch)
    member, configured, items = setup("wizyta-recznie")
    appointment = booking_tests.create(member, configured).appointment
    assert appointment.materials == []
    with booking_tests.tenant(member):
        set_appointment_materials(
            appointment_id=appointment.id,
            materials=[{"item_id": str(items["oil"].id), "quantity": "12", "mode": "consume"}],
        )
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(-2))
    with booking_tests.tenant(member):
        set_appointment_materials(
            appointment_id=appointment.id,
            materials=[{"item_id": str(items["oil"].id), "quantity": "1", "mode": "consume"}],
        )
        with pytest.raises(ValidationError, match="Nie ma takiego produktu"):
            set_appointment_materials(
                appointment_id=appointment.id,
                materials=[{"item_id": str(configured["service"].id), "quantity": "1"}],
            )
        complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
        with pytest.raises(AppointmentNotChangeable):
            set_appointment_materials(appointment_id=appointment.id, materials=[])
    assert stock(member, items["oil"]) == (Decimal(9), Decimal(9))


def test_a_product_hidden_after_setting_the_service_does_not_block_a_booking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from saas_core.modules.shared.inventory.services import update_item  # noqa: PLC0415

    booking_tests._no_delivery(monkeypatch)
    member, configured, items = setup("wizyta-ukryty")
    with booking_tests.tenant(member):
        set_service_materials(
            service_id=configured["service"].id,
            materials=[
                {"item_id": str(items["oil"].id), "quantity": "1", "mode": "consume"},
                {"item_id": str(items["towel"].id), "quantity": "1", "mode": "consume"},
            ],
        )
        request = type("Request", (), {"user": member.user})()
        update_item(request=request, item_id=items["oil"].id, data={"active": False})
    appointment = booking_tests.create(member, configured).appointment
    assert [x["name"] for x in appointment.materials] == ["Ręcznik"]


def test_the_customer_sees_the_visit_not_the_companys_stock_sheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rest_framework.test import APIClient  # noqa: PLC0415

    booking_tests._no_delivery(monkeypatch)
    member, configured, items = setup("wizyta-klient")
    with booking_tests.tenant(member):
        set_service_materials(
            service_id=configured["service"].id,
            materials=[{"item_id": str(items["oil"].id), "quantity": "1", "mode": "consume"}],
        )
    created = booking_tests.create(member, configured)
    response = APIClient().get(f"/api/v1/booking/self-service/{created.token}/")
    assert response.status_code == 200
    assert "materials" not in response.data


def test_a_kind_whose_module_takes_its_own_material_stays_out_of_the_warehouse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HoofCare takes material per cow from the trimmer's own stock; the calendar
    neither offers products for its visits nor settles any at completion,
    or the same material would go twice (ADR-055, owner 24.09 answer 4A)."""
    from saas_core.modules.shared.booking.models import Service  # noqa: PLC0415

    booking_tests._no_delivery(monkeypatch)
    monkeypatch.setattr(
        settings, "APPOINTMENT_KINDS_OWN_MATERIALS", frozenset({"field.visit"}), raising=False
    )
    member, configured, items = setup("wizyta-wlasny-material")
    line = {"item_id": str(items["oil"].id), "quantity": "2", "mode": "consume"}
    with booking_tests.tenant(member):
        # Materials set while the kind still took them (or by hand in the DB)
        # must not reach a visit either.
        Service.all_objects.filter(pk=configured["service"].id).update(
            appointment_kind="field.visit", materials=[line]
        )
        with pytest.raises(ValidationError, match="rozlicza jej moduł"):
            set_service_materials(service_id=configured["service"].id, materials=[line])

    # A visit confirmed before its module said so still holds a reservation.
    monkeypatch.setattr(settings, "APPOINTMENT_KINDS_OWN_MATERIALS", frozenset(), raising=False)
    earlier = booking_tests.create(member, configured).appointment
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(8))
    monkeypatch.setattr(
        settings, "APPOINTMENT_KINDS_OWN_MATERIALS", frozenset({"field.visit"}), raising=False
    )
    with booking_tests.tenant(member):
        complete_appointment(
            appointment_id=earlier.id, idempotency_key="done-earlier", principal_ref="t"
        )
    # Completing it lets the reservation go and settles nothing.
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(10))
    assert documents(member, earlier.id) == []

    configured.pop("starts_at")  # the first slot is taken now
    appointment = booking_tests.create(member, configured, key="own-2").appointment
    assert appointment.materials == []
    assert stock(member, items["oil"]) == (Decimal(10), Decimal(10))
    with booking_tests.tenant(member):
        with pytest.raises(ValidationError, match="rozlicza jej moduł"):
            set_appointment_materials(appointment_id=appointment.id, materials=[line])
        complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-own", principal_ref="t"
        )
    assert documents(member, appointment.id) == []

    from saas_core.modules.shared.booking.services import list_catalog  # noqa: PLC0415
    from saas_core.modules.shared.booking.views import _catalog_payload  # noqa: PLC0415

    with booking_tests.tenant(member):
        services = _catalog_payload(list_catalog())["services"]
    # The panel hides the products editor for such a service.
    assert [service["takes_materials"] for service in services] == [False]
