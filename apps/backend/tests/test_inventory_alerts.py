"""Minimum stock, its daily notice and the warehouse's settings (phase 10 of the
warehouse plan; settings plan M3–M6, ADR-078)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    OrganizationSetting,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.core.organizations.settings_service import Resolved, resolve
from saas_core.modules.shared.inventory.company_settings import LOW_STOCK
from test_inventory import (
    core_catalog,  # noqa: F401 — core's own catalogue, not a product's
    item,
    lot_item,
    membership,
    receive_lots,
    tenant,
)
from test_organization_api import PASSWORD, csrf_value, login

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        "shared.inventory" not in settings.ACTIVE_MODULES,
        reason="magazyn istnieje tylko w profilu, który go składa",
    ),
]


def member(owner: Membership, slug: str, role_key: str) -> Membership:
    role, _ = Role.objects.get_or_create(
        key=role_key,
        organization=None,
        organization_type="",
        defaults={
            "name": role_key,
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS[role_key]),
            "is_immutable": True,
        },
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    return Membership.objects.create(organization=owner.organization, user=user, role=role)


def choose(owner: Membership, **values: Any) -> None:
    """The company's own values, as if saved in Ustawienia › Magazyn."""
    for key, value in values.items():
        OrganizationSetting.objects.update_or_create(
            organization_id=owner.organization_id,
            key=key.replace("__", "."),
            defaults={"value": value},
        )


def receive(request: Any, item_id: Any, quantity: int) -> None:
    from saas_core.modules.shared.inventory.services import receive as pz  # noqa: PLC0415

    pz(request=request, item_id=item_id, quantity=Decimal(quantity), unit_cost_minor=100)


def low(owner: Membership, places: str = "all") -> dict[tuple[str, str], Decimal]:
    from saas_core.modules.shared.inventory.services import low_stock_rows  # noqa: PLC0415

    return {
        (row["item_name"], row["location_name"]): row["available"]
        for row in low_stock_rows(owner.organization_id, places)
    }


# --- the minimum: an item's, or one place's over it ----------------------------------


def test_an_items_minimum_is_the_warehouses_and_a_place_may_set_its_own() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        create_warehouse,
        issue,
        set_place_minimum,
        update_item,
    )

    owner = membership("minimum-miejsca")
    trimmer = member(owner, "minimum-korektor", "staff")
    with tenant(owner) as request:
        block = item(request, "Klocek")
        gloves = item(request, "Rękawiczki")
        update_item(request=request, item_id=block.id, data={"minimum_quantity": Decimal(5)})
        # Never received, with a minimum: zero in the main warehouse is short.
        assert low(owner) == {("Klocek", "Magazyn główny"): Decimal(0)}

        receive(request, block.id, 8)
        receive(request, gloves.id, 3)
        branch = create_warehouse(request=request, name="Oddział Gdańsk")
        issue(request=request, item_id=block.id, holder_id=trimmer.user_id, quantity=Decimal(4))
        # 4 left in the main warehouse, 4 in the trimmer's kit: the item's
        # minimum is for warehouses, a kit has none of its own yet.
        assert low(owner) == {("Klocek", "Magazyn główny"): Decimal(4)}

        kit = set_place_minimum(
            request=request,
            item_id=block.id,
            location_id=trimmer_place(owner, trimmer).id,
            minimum_quantity=Decimal(6),
        )
        assert kit.minimum_quantity == Decimal(6)
        # The main warehouse says „no minimum here”: 0 beats the item's 5.
        set_place_minimum(
            request=request,
            item_id=block.id,
            location_id=main(owner).id,
            minimum_quantity=Decimal(0),
        )
        assert low(owner) == {("Klocek", "Zapas osoby"): Decimal(4)}
        assert low(owner, "warehouses") == {}
        # A branch only counts what was ever there or has its own minimum.
        set_place_minimum(
            request=request, item_id=gloves.id, location_id=branch.id, minimum_quantity=Decimal(2)
        )
        assert low(owner, "warehouses") == {("Rękawiczki", "Oddział Gdańsk"): Decimal(0)}
        assert low(owner, "main") == {}


def main(owner: Membership) -> Any:
    from saas_core.modules.shared.inventory.api import default_warehouse  # noqa: PLC0415

    return default_warehouse(owner.organization_id)


def trimmer_place(owner: Membership, person: Membership) -> Any:
    from saas_core.modules.shared.inventory.api import person_location  # noqa: PLC0415

    return person_location(owner.organization_id, person.user_id)


def test_what_is_reserved_is_not_there_and_the_stock_page_says_so() -> None:
    from saas_core.modules.shared.inventory.api import reserve  # noqa: PLC0415
    from saas_core.modules.shared.inventory.serializers import (  # noqa: PLC0415
        InventoryBalanceSerializer,
    )
    from saas_core.modules.shared.inventory.services import balances, update_item  # noqa: PLC0415

    owner = membership("minimum-rezerwacja")
    with tenant(owner) as request:
        block = item(request)
        update_item(request=request, item_id=block.id, data={"minimum_quantity": Decimal(3)})
        receive(request, block.id, 5)
        (row,) = InventoryBalanceSerializer(balances(), many=True).data
        assert (row["minimum_quantity"], row["place_minimum"], row["below_minimum"]) == (
            "3.000",
            None,
            False,
        )
        reserve(
            organization_id=owner.organization_id,
            item_id=block.id,
            location_id=main(owner).id,
            quantity=Decimal(2),
            source="booking.appointment",
            source_reference="wizyta-1",
        )
        (row,) = InventoryBalanceSerializer(balances(), many=True).data
        assert row["below_minimum"] is True
        assert low(owner) == {("Klocek", "Magazyn główny"): Decimal(3)}


def test_a_place_minimum_is_the_warehouse_keepers_and_leaves_one_history_row() -> None:
    from saas_core.modules.shared.inventory.services import set_place_minimum  # noqa: PLC0415

    owner = membership("minimum-historia")
    worker = member(owner, "minimum-pracownik", "staff")
    with tenant(owner) as request:
        block = item(request)
        place = main(owner)
        for _ in range(2):  # A repeat sets the same value and writes nothing.
            set_place_minimum(
                request=request,
                item_id=block.id,
                location_id=place.id,
                minimum_quantity=Decimal("2.5"),
            )
        with pytest.raises(ValidationError) as refused:
            set_place_minimum(
                request=request,
                item_id=block.id,
                location_id=place.id,
                minimum_quantity=Decimal(-1),
            )
        assert refused.value.get_codes() == {"minimum_quantity": ["min_value"]}
        (entry,) = OrganizationAuditEntry.objects.filter(
            organization_id=owner.organization_id, action="inventory.minimum.changed"
        )
        assert entry.metadata["changes"] == {"minimum_quantity": {"from": None, "to": "2.5"}}
    with tenant(worker) as request, pytest.raises(OrganizationPermissionDenied):
        set_place_minimum(
            request=request, item_id=block.id, location_id=place.id, minimum_quantity=None
        )


def test_somebody_elses_kit_is_on_the_list_only_for_the_warehouse_keeper() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        issue,
        low_stock,
        set_place_minimum,
    )

    owner = membership("minimum-cudzy")
    first = member(owner, "minimum-pierwszy", "staff")
    second = member(owner, "minimum-drugi", "staff")
    with tenant(owner) as request:
        block = item(request)
        receive(request, block.id, 10)
        for person in (first, second):
            issue(request=request, item_id=block.id, holder_id=person.user_id, quantity=Decimal(1))
            set_place_minimum(
                request=request,
                item_id=block.id,
                location_id=trimmer_place(owner, person).id,
                minimum_quantity=Decimal(2),
            )
        assert {row["holder_id"] for row in low_stock()} == {first.user_id, second.user_id}
    with tenant(first):
        assert [row["holder_id"] for row in low_stock()] == [first.user_id]


# --- the daily notice -------------------------------------------------------------------


def notices(owner: Membership) -> list[Any]:
    from saas_core.modules.shared.notifications.models import AppNotification  # noqa: PLC0415

    return list(
        AppNotification.all_objects.filter(
            organization_id=owner.organization_id, kind="inventory.low_stock"
        ).order_by("user__email")
    )


def mails(owner: Membership) -> list[Any]:
    from saas_core.modules.shared.notifications.models import (  # noqa: PLC0415
        NotificationMessage,
    )

    return list(
        NotificationMessage.all_objects.filter(
            organization_id=owner.organization_id, template_key="inventory.low_stock"
        )
    )


def notify(at: datetime) -> int:
    from saas_core.modules.shared.inventory.alerts import notify_low_stock  # noqa: PLC0415

    return notify_low_stock(now=at)


def short_company(slug: str) -> Membership:
    """A company with one item under its minimum in the main warehouse."""
    from saas_core.modules.shared.inventory.services import update_item  # noqa: PLC0415

    owner = membership(slug)
    with tenant(owner) as request:
        block = item(request)
        update_item(request=request, item_id=block.id, data={"minimum_quantity": Decimal(5)})
        receive(request, block.id, 2)
    return owner


# 3 October 2026, 08:30 in Warsaw (CEST, UTC+2).
MORNING = datetime(2026, 10, 3, 6, 30, tzinfo=UTC)


def test_a_new_company_starts_with_the_daily_notice_and_an_older_one_keeps_it_off(
    settings: Any,  # noqa: F811 — pytest's fixture, not django.conf's object
) -> None:
    """Owner's answer 61a: the product's "daily" becomes a new company's own
    value at its creation and is never read live."""
    older = membership("alert-starsza")
    user = older.user
    user.set_password(PASSWORD)
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    settings.SETTINGS_DEFAULTS = {LOW_STOCK: "daily"}

    created = client.post(
        "/api/v1/organizations/",
        {
            "name": "Nowa firma",
            "slug": "alert-nowsza",
            "organization_type": settings.DEFAULT_ORGANIZATION_TYPE,
            "workspace_kind": "business",
            "default_locale": "pl",
            "timezone": "Europe/Warsaw",
            "currency": "PLN",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert created.status_code == 201
    newer = Membership.objects.get(organization__slug="alert-nowsza", user=user)

    with tenant(older):
        assert resolve(LOW_STOCK) == Resolved("off", "code")
    with tenant(newer):
        assert resolve(LOW_STOCK) == Resolved("daily", "organization")


def test_nothing_is_sent_until_the_company_switches_the_notice_on() -> None:
    owner = short_company("alert-wylaczony")
    assert notify(MORNING) == 0
    assert notices(owner) == [] and mails(owner) == []


def test_once_a_day_from_the_companys_hour_to_whoever_runs_the_warehouse() -> None:
    owner = short_company("alert-codziennie")
    keeper = member(owner, "alert-magazynier", "manager")
    member(owner, "alert-pracownik", "staff")
    choose(owner, inventory__alerts__low_stock="daily", inventory__alerts__hour=9)
    assert notify(MORNING) == 0  # 08:30 in Warsaw: before its hour.
    at_nine = MORNING + timedelta(hours=1)
    assert notify(at_nine) == 2
    assert {notice.user_id for notice in notices(owner)} == {owner.user_id, keeper.user_id}
    (first, *_) = notices(owner)
    assert first.payload["count"] == 1
    assert first.payload["items"][0]["name"] == "Klocek"
    assert first.payload["items"][0]["available"] == "2"
    assert sorted(mail.recipient_email for mail in mails(owner)) == [
        "alert-codziennie@example.test",
        "alert-magazynier@example.test",
    ]
    # Signed as the organization's own job, which delivery has to open: a
    # role the task contract does not know leaves the mail queued for ever.
    from saas_core.modules.core.organizations.tasks import tenant_task_context  # noqa: PLC0415

    for mail in mails(owner):
        with tenant_task_context(
            mail.signed_tenant_context, expected_causation_id=f"email:{mail.id}"
        ) as context:
            assert context.role_key == "inventory_notifications"
        assert mail.status != "queued"
    # Later the same day: nobody hears twice. The next day: again.
    assert notify(at_nine + timedelta(hours=5)) == 0
    assert notify(at_nine + timedelta(days=1)) == 2
    assert len(mails(owner)) == 4


def test_nothing_short_nothing_sent_and_the_owner_alone_when_chosen() -> None:
    from saas_core.modules.shared.inventory.services import update_item  # noqa: PLC0415

    owner = membership("alert-wlasciciel")
    member(owner, "alert-kierownik", "manager")
    choose(
        owner,
        inventory__alerts__low_stock="daily",
        inventory__alerts__recipients="owner",
    )
    with tenant(owner) as request:
        block = item(request)
        update_item(request=request, item_id=block.id, data={"minimum_quantity": Decimal(1)})
        receive(request, block.id, 4)
    assert notify(MORNING) == 0
    with tenant(owner) as request:
        update_item(request=request, item_id=block.id, data={"minimum_quantity": Decimal(4)})
    assert notify(MORNING) == 1
    assert [notice.user_id for notice in notices(owner)] == [owner.user_id]


def test_a_person_hears_about_their_own_kit_only() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        issue,
        set_place_minimum,
    )

    owner = short_company("alert-pakiet")
    trimmer = member(owner, "alert-pakiet-korektor", "staff")
    other = member(owner, "alert-pakiet-drugi", "staff")
    with tenant(owner) as request:
        gloves = item(request, "Rękawiczki")
        receive(request, gloves.id, 10)
        for person in (trimmer, other):
            issue(request=request, item_id=gloves.id, holder_id=person.user_id, quantity=Decimal(1))
        set_place_minimum(
            request=request,
            item_id=gloves.id,
            location_id=trimmer_place(owner, trimmer).id,
            minimum_quantity=Decimal(3),
        )
    choose(owner, inventory__alerts__low_stock="daily", inventory__alerts__places="all")
    assert notify(MORNING) == 2
    by_user = {notice.user_id: notice.payload for notice in notices(owner)}
    assert by_user[owner.user_id]["count"] == 2
    assert by_user[trimmer.user_id]["count"] == 1
    assert by_user[trimmer.user_id]["items"][0]["name"] == "Rękawiczki"
    assert other.user_id not in by_user


def test_a_change_of_the_clocks_neither_sends_twice_nor_skips_a_day() -> None:
    """Warsaw: 25 Oct 2026 03:00 CEST → 02:00 CET (02:xx happens twice);
    29 Mar 2026 02:00 CET → 03:00 CEST (02:xx does not happen)."""
    owner = short_company("alert-zmiana-czasu")
    choose(owner, inventory__alerts__low_stock="daily", inventory__alerts__hour=2)
    first_two = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 02:30 CEST
    second_two = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)  # 02:30 CET, same day
    assert notify(first_two) == 1
    assert notify(second_two) == 0
    spring = datetime(2026, 3, 29, 1, 30, tzinfo=UTC)  # 03:30 CEST; 02:30 never was
    assert notify(spring) == 1
    assert len(mails(owner)) == 2


def test_a_plan_without_the_warehouse_keeps_the_choice_not_the_notice() -> None:
    from saas_core.modules.shared.billing.models import EntitlementSnapshot  # noqa: PLC0415

    owner = short_company("alert-bez-planu")
    choose(owner, inventory__alerts__low_stock="daily")
    EntitlementSnapshot.all_objects.filter(organization_id=owner.organization_id).update(
        features={"inventory.enabled": False}
    )
    assert notify(MORNING) == 0


# --- lots: expiring days (M3) and an expired lot sold (M6) --------------------------------


def test_a_category_or_the_company_says_when_a_lot_is_expiring() -> None:
    from saas_core.modules.shared.inventory.api import organization_today  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        list_categories,
        list_lots,
        update_category,
        update_item,
    )

    owner = membership("partie-dni")
    with tenant(owner) as request:
        today = organization_today(owner.organization_id)
        drug = lot_item(request)
        receive_lots(
            request, owner.organization_id, drug.id, ("L-45", today + timedelta(days=45), 1)
        )
        assert [row["status"] for row in list_lots()] == ["ok"]
    choose(owner, inventory__lots__expiring_days=60)
    with tenant(owner) as request:
        assert [row["status"] for row in list_lots()] == ["expiring"]
        category = next(c for c in list_categories() if c.key == "material")
        update_item(request=request, item_id=drug.id, data={"category": str(category.id)})
        update_category(request=request, category_id=category.id, data={"expiring_days": 14})
        assert [row["status"] for row in list_lots()] == ["ok"]
        update_category(request=request, category_id=category.id, data={"expiring_days": None})
        assert [row["status"] for row in list_lots()] == ["expiring"]
        (entry, *_) = OrganizationAuditEntry.objects.filter(
            organization_id=owner.organization_id, action="inventory.category.updated"
        ).order_by("occurred_at")
        assert entry.metadata["changes"] == {"expiring_days": {"from": None, "to": 14}}


def test_a_company_that_only_warns_sells_an_expired_lot_after_the_valid_ones() -> None:
    from saas_core.modules.shared.inventory.api import organization_today  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        StockShortage,
        create_document,
        post_document,
    )

    owner = membership("partie-sprzedaz")
    with tenant(owner) as request:
        today = organization_today(owner.organization_id)
        drug = lot_item(request)
        receive_lots(
            request,
            owner.organization_id,
            drug.id,
            ("L-OLD", today - timedelta(days=3), 2),
            ("L-NEW", today + timedelta(days=90), 1),
        )
        sale = create_document(
            request=request,
            kind="WZ",
            data={"source_location_id": main(owner).id, "counterparty": "Klient"},
            lines=[LineInput(item_id=drug.id, quantity=Decimal(3))],
        )
        # As before (block): only one valid piece, and the expired ones are not sold.
        with pytest.raises(StockShortage):
            post_document(request=request, document_id=sale.id)
    choose(owner, inventory__lots__expired_sale="warn")
    with tenant(owner) as request:
        posted = post_document(request=request, document_id=sale.id)
        taken = sorted(
            (move.lot.number, -move.quantity) for move in posted.movements.select_related("lot")
        )
        assert taken == [("L-NEW", Decimal(1)), ("L-OLD", Decimal(2))]


# --- where a visit's products come from (M5) ------------------------------------------------


def test_a_visit_takes_from_the_main_warehouse_or_the_leading_persons_stock() -> None:
    from saas_core.modules.shared.inventory.api import visit_place  # noqa: PLC0415

    owner = membership("materialy-wizyty")
    technician = member(owner, "materialy-serwisant", "staff")
    with tenant(owner):
        assert visit_place(owner.organization_id, lead_user_id=technician.user_id).is_default
    choose(owner, inventory__materials__source="lead_person")
    with tenant(owner):
        place = visit_place(owner.organization_id, lead_user_id=technician.user_id)
        assert (place.kind, place.holder_id) == ("person", technician.user_id)
        # Somebody without an account has no stock: the main warehouse.
        assert visit_place(owner.organization_id, lead_user_id=None).is_default
