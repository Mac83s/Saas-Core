"""Magazyn uniwersalny (`shared.inventory`, ADR-055).

Pomijane tam, gdzie profil nie składa modułu. Stan zmienia tylko zatwierdzony
dokument, więc większość testów sprawdza jedno: czy po dokumencie zgadzają się
i księga ruchów, i stan trzymany obok niej.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.db import transaction
from django.test import override_settings
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.config.composition import (
    InventoryCategoryTemplate,
    InventoryItemTemplate,
    InventoryTemplate,
    OrganizationType,
)
from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    Feature,
    SubscriptionState,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        "shared.inventory" not in settings.ACTIVE_MODULES,
        reason="magazyn istnieje tylko w profilu, który go składa",
    ),
]

ENTRY = "hoofcare.entry"


@pytest.fixture(autouse=True)
def core_catalog(settings: Any) -> None:
    """Core's own set for every type: a product's declaration (HoofCare's
    „Klocek”) must not change what these tests start from."""
    settings.ORGANIZATION_TYPES = {
        key: replace(value, inventory=None) for key, value in settings.ORGANIZATION_TYPES.items()
    }


def membership(slug: str, *, organization_type: str | None = None) -> Membership:
    Feature.objects.get_or_create(
        key="inventory.enabled",
        defaults={"name": "Magazyn", "module": "shared.inventory"},
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    extra = {"organization_type": organization_type} if organization_type else {}
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE, timezone="Europe/Warsaw", **extra
    )
    role, _ = Role.objects.get_or_create(
        key="owner",
        organization=None,
        organization_type="",
        defaults={
            "name": "Owner",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["owner"]),
            "is_immutable": True,
        },
    )
    member = Membership.objects.create(organization=organization, user=user, role=role)
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"inventory.enabled": True},
        quotas={},
        sources={"inventory.enabled": {"kind": "plan"}},
    )
    return member


@contextmanager
def tenant(member: Membership) -> Any:
    context = context_from_membership(member)
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        yield SimpleNamespace(user=member.user)


def item(request: Any, name: str = "Klocek") -> Any:
    from saas_core.modules.shared.inventory.services import create_item  # noqa: PLC0415

    return create_item(request=request, data={"name": name})


def quantities(**query: Any) -> dict[str, Decimal]:
    from saas_core.modules.shared.inventory.services import balances  # noqa: PLC0415

    return {row.item.name: Decimal(row.quantity) for row in balances(**query)}


def test_the_warehouse_is_granted_to_core_roles() -> None:
    assert {"inventory.read", "inventory.use", "inventory.manage"} <= set(
        SYSTEM_ROLE_PERMISSIONS["owner"]
    )
    assert {"inventory.read", "inventory.use"} <= set(SYSTEM_ROLE_PERMISSIONS["staff"])
    assert "inventory.manage" not in SYSTEM_ROLE_PERMISSIONS["staff"]
    assert "inventory.use" not in SYSTEM_ROLE_PERMISSIONS["viewer"]


def test_a_type_without_a_declaration_gets_core_categories_and_a_main_warehouse() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        list_categories,
        list_items,
        list_locations,
    )

    owner = membership("magazyn-rdzen")
    with tenant(owner):
        assert {category.key for category in list_categories()} == {
            "product",
            "material",
            "tool",
            "other",
        }
        assert list_items() == []
        (warehouse,) = list_locations()
        assert (warehouse.is_default, warehouse.name) == (True, "Magazyn główny")


def test_the_product_declares_categories_and_standard_items_once() -> None:
    """Rdzeń nie zna branży: klocek przychodzi z deklaracji produktu (ADR-049)."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        delete_category,
        ensure_catalog,
        list_categories,
        list_items,
    )

    farrier = OrganizationType(
        key="farrier",
        label={"pl": "Korektor"},
        modules=frozenset({"shared.inventory"}),
        plan_keys=(),
        self_signup=False,
        inventory=InventoryTemplate(
            categories=(
                InventoryCategoryTemplate(key="block", label={"pl": "Klocek", "en": "Block"}),
                InventoryCategoryTemplate(key="drug", label={"pl": "Lek", "en": "Drug"}),
            ),
            default_items=(
                InventoryItemTemplate(
                    key="block",
                    name={"pl": "Klocek", "en": "Block"},
                    category="block",
                    unit="piece",
                ),
                InventoryItemTemplate(
                    key="drug",
                    name={"pl": "Lek", "en": "Drug"},
                    category="drug",
                    unit="ml",
                    tracks_lots=True,
                ),
            ),
        ),
    )
    with override_settings(ORGANIZATION_TYPES={**settings.ORGANIZATION_TYPES, "farrier": farrier}):
        owner = membership("magazyn-produkt", organization_type="farrier")
        with tenant(owner) as request:
            ensure_catalog(owner.organization_id)
            standard, drug = list_items()
            assert (
                standard.name,
                standard.system_key,
                standard.category and standard.category.key,
                standard.tracks_lots,
            ) == (
                "Klocek",
                "block",
                "block",
                False,
            )
            # A drug keeps lots and expiry dates from its first day.
            assert (drug.name, drug.tracks_lots) == ("Lek", True)
            categories = {category.key: category for category in list_categories()}
            assert set(categories) == {"block", "drug"}
            with pytest.raises(ValidationError, match="startowej"):
                delete_category(request=request, category_id=categories["drug"].id)
            # Pozycja ukryta albo przemianowana nie wraca jako druga.
            ensure_catalog(owner.organization_id)
            assert len(list_items()) == 2


def test_a_receipt_sets_the_price_the_next_one_averages_and_is_numbered() -> None:
    """Rozchód wycenia się średnią, więc koszt wizyty nie zmienia się po dostawie."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        list_items,
        receive,
    )

    owner = membership("magazyn-cena")
    with tenant(owner) as request:
        block = item(request)
        first = receive(
            request=request, item_id=block.id, quantity=Decimal(100), unit_cost_minor=250
        )
        second = receive(
            request=request, item_id=block.id, quantity=Decimal(100), unit_cost_minor=350
        )
        (refreshed,) = list_items()
        # Sto sztuk po 2,50 zł i sto po 3,50 zł to trzy złote za sztukę.
        assert refreshed.average_cost_minor == 300
        assert quantities() == {"Klocek": Decimal(200)}
        year = first.document_date.year
        assert (first.number, second.number) == (f"PZ/{year}/0001", f"PZ/{year}/0002")


def test_what_goes_to_a_person_leaves_the_warehouse_and_comes_back() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        give_back,
        issue,
        receive,
    )

    owner = membership("magazyn-wydanie")
    trimmer = User.objects.create_user(email="korektor@example.test")
    with tenant(owner) as request:
        dressing = item(request, "Opatrunek")
        receive(request=request, item_id=dressing.id, quantity=Decimal(50), unit_cost_minor=120)
        issue(request=request, item_id=dressing.id, holder_id=trimmer.id, quantity=Decimal(12))
        assert quantities() == {"Opatrunek": Decimal(38)}
        assert quantities(holder_id=trimmer.id) == {"Opatrunek": Decimal(12)}

        give_back(request=request, item_id=dressing.id, holder_id=trimmer.id, quantity=Decimal(2))
        assert quantities() == {"Opatrunek": Decimal(40)}
        assert quantities(holder_id=trimmer.id) == {"Opatrunek": Decimal(10)}


def test_work_never_stops_for_a_stock_level_and_one_source_is_one_document() -> None:
    """Brak pokrycia ostrzega, ale zapisuje (decyzja z 21.09); powtórzony wpis
    to wciąż jeden dokument RW, nie dwa."""
    from saas_core.modules.shared.inventory.api import consume, holder_stock  # noqa: PLC0415

    owner = membership("magazyn-minus")
    trimmer = User.objects.create_user(email="korektor-minus@example.test")
    with tenant(owner) as request:
        block = item(request)
        lines = [(block.id, Decimal(2))]
        first = consume(
            organization_id=owner.organization_id,
            holder_id=trimmer.id,
            source=ENTRY,
            source_reference="wpis-1",
            lines=lines,
        )
        again = consume(
            organization_id=owner.organization_id,
            holder_id=trimmer.id,
            source=ENTRY,
            source_reference="wpis-1",
            lines=lines,
        )
        assert first is not None and again is not None
        assert (first.id, first.kind, first.status) == (again.id, "RW", "posted")
        (held,) = holder_stock(owner.organization_id, trimmer.id)
        assert (held["item_id"], held["quantity"]) == (block.id, Decimal(-2))


def test_a_cancelled_source_gives_the_material_back_once() -> None:
    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        cancel_source,
        consume,
        holder_stock,
    )

    owner = membership("magazyn-cofniecie")
    trimmer = User.objects.create_user(email="korektor-cofniecie@example.test")
    with tenant(owner) as request:
        block = item(request)
        for reference in ("wpis-1", "wpis-2"):
            consume(
                organization_id=owner.organization_id,
                holder_id=trimmer.id,
                source=ENTRY,
                source_reference=reference,
                lines=[(block.id, Decimal(1))],
            )
        for _ in range(2):
            cancel_source(
                organization_id=owner.organization_id,
                actor_id=owner.user_id,
                source=ENTRY,
                source_reference="wpis-1",
            )
        # Powtórka cofnięcia nie oddaje drugi raz, a cudzego wpisu nie rusza.
        (held,) = holder_stock(owner.organization_id, trimmer.id)
        assert (held["item_id"], held["quantity"]) == (block.id, Decimal(-1))


def test_a_reservation_holds_stock_until_released() -> None:
    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        available,
        cancel_source,
        default_warehouse,
        reserve,
    )
    from saas_core.modules.shared.inventory.services import receive  # noqa: PLC0415

    owner = membership("magazyn-rezerwacja")
    with tenant(owner) as request:
        block = item(request)
        receive(request=request, item_id=block.id, quantity=Decimal(10), unit_cost_minor=100)
        warehouse = default_warehouse(owner.organization_id)
        for amount in (Decimal(3), Decimal(4)):
            reserve(
                organization_id=owner.organization_id,
                item_id=block.id,
                location_id=warehouse.id,
                quantity=amount,
                source="booking.appointment",
                source_reference="wizyta-1",
            )
        # Druga rezerwacja tego samego źródła zmienia ilość, nie dokłada.
        assert available(owner.organization_id, block.id, warehouse.id) == Decimal(6)
        cancel_source(
            organization_id=owner.organization_id,
            actor_id=owner.user_id,
            source="booking.appointment",
            source_reference="wizyta-1",
        )
        assert available(owner.organization_id, block.id, warehouse.id) == Decimal(10)


def test_a_sale_is_refused_when_the_goods_are_not_there() -> None:
    """Zewnętrzne wydanie (sklep) blokuje, gdy dostępne — po rezerwacjach — nie
    pokrywa ilości; zużycie w pracy nie blokuje nigdy."""
    from saas_core.modules.shared.inventory.api import default_warehouse, reserve  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        StockShortage,
        create_document,
        post_document,
        receive,
    )

    owner = membership("magazyn-sprzedaz")
    with tenant(owner) as request:
        block = item(request)
        receive(request=request, item_id=block.id, quantity=Decimal(5), unit_cost_minor=100)
        warehouse = default_warehouse(owner.organization_id)
        reserve(
            organization_id=owner.organization_id,
            item_id=block.id,
            location_id=warehouse.id,
            quantity=Decimal(2),
            source="booking.appointment",
            source_reference="wizyta-1",
        )
        sale = create_document(
            request=request,
            kind="WZ",
            data={"source_location_id": warehouse.id, "counterparty": "Klient"},
            lines=[LineInput(item_id=block.id, quantity=Decimal(4))],
        )
        with pytest.raises(StockShortage):
            post_document(request=request, document_id=sale.id)
        assert quantities() == {"Klocek": Decimal(5)}


def test_a_count_sets_the_stock_and_its_correction_undoes_only_the_difference() -> None:
    from saas_core.modules.shared.inventory.api import default_warehouse  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        DocumentAlreadyCorrected,
        DocumentPosted,
        LineInput,
        correct_document,
        create_document,
        post_document,
        receive,
        update_document,
    )

    owner = membership("magazyn-inwentaryzacja")
    with tenant(owner) as request:
        block = item(request)
        receive(request=request, item_id=block.id, quantity=Decimal(10), unit_cost_minor=100)
        count = create_document(
            request=request,
            kind="INW",
            data={"target_location_id": default_warehouse(owner.organization_id).id},
            lines=[LineInput(item_id=block.id, quantity=Decimal(7))],
        )
        post_document(request=request, document_id=count.id)
        assert quantities() == {"Klocek": Decimal(7)}
        with pytest.raises(DocumentPosted):
            update_document(request=request, document_id=count.id, data={"note": "x"}, lines=None)

        correction = correct_document(request=request, document_id=count.id)
        assert correction.number.startswith("INW/") and correction.corrects_id == count.id
        assert quantities() == {"Klocek": Decimal(10)}
        with pytest.raises(DocumentAlreadyCorrected):
            correct_document(request=request, document_id=count.id)


def test_an_adjustment_needs_a_reason_and_leaves_the_history_alone() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        adjust,
        movements,
        receive,
    )

    owner = membership("magazyn-korekta")
    with tenant(owner) as request:
        glue = item(request, "Klej")
        receive(request=request, item_id=glue.id, quantity=Decimal(10), unit_cost_minor=999)
        with pytest.raises(ValidationError, match="powodu"):
            adjust(request=request, item_id=glue.id, holder_id=None, quantity=Decimal(-3), note=" ")
        adjust(
            request=request,
            item_id=glue.id,
            holder_id=None,
            quantity=Decimal(-3),
            note="Zbita butelka przy załadunku.",
        )
        assert quantities() == {"Klej": Decimal(7)}
        # Przyjęcie zostaje w historii: korekta prostuje stan, nie przeszłość.
        assert sorted(row.kind for row in movements(item_id=glue.id)) == ["PZ", "RW"]


def test_the_catalogue_refuses_a_second_item_with_the_same_name() -> None:
    owner = membership("magazyn-nazwa")
    with tenant(owner) as request:
        item(request)
        with pytest.raises(ValidationError, match="już jest"):
            item(request, "klocek")


def test_another_companys_warehouse_is_simply_not_there() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        create_document,
        list_items,
    )

    first = membership("magazyn-jeden")
    second = membership("magazyn-dwa")
    with tenant(first) as request:
        foreign = item(request)
    with tenant(second) as request:
        # Baza testowa omija RLS, więc to dowodzi filtra w zapytaniu; izolacja
        # pod polityką jest sprawdzana na uruchomionym stacku.
        assert list_items() == []
        with pytest.raises(NotFound):
            create_document(
                request=request,
                kind="PZ",
                data={},
                lines=[LineInput(item_id=foreign.id, quantity=Decimal(1))],
            )


def test_a_retried_request_is_the_same_document() -> None:
    """Odpowiedź zgubiona w sieci: klient powtarza z tym samym id i dostaje
    ten sam dokument — dostawa nie wchodzi na stan dwa razy."""
    from uuid import uuid4  # noqa: PLC0415

    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        create_document,
        post_document,
        receive,
    )

    owner = membership("magazyn-powtorka")
    with tenant(owner) as request:
        block = item(request)
        key = uuid4()
        for _ in range(2):
            first = receive(
                request=request,
                item_id=block.id,
                quantity=Decimal(5),
                unit_cost_minor=100,
                document_id=key,
            )
        assert first.id == key and quantities() == {"Klocek": Decimal(5)}

        draft_key = uuid4()
        drafts = [
            create_document(
                request=request,
                kind="RW",
                data={"source_location_id": first.target_location_id},
                lines=[LineInput(item_id=block.id, quantity=Decimal(2))],
                document_id=draft_key,
            )
            for _ in range(2)
        ]
        assert drafts[0].id == drafts[1].id == draft_key
        numbers = {post_document(request=request, document_id=draft_key).number for _ in range(2)}
        assert len(numbers) == 1 and quantities() == {"Klocek": Decimal(3)}


# --- partie i ważność (faza 9 magazynu, decyzje 25.09) ------------------------------


def lot_item(request: Any, name: str = "Oksytetracyklina") -> Any:
    from saas_core.modules.shared.inventory.services import create_item  # noqa: PLC0415

    return create_item(request=request, data={"name": name, "unit": "ml", "tracks_lots": True})


def receive_lots(
    request: Any, organization_id: Any, item_id: Any, *lots: tuple[str, Any, int]
) -> Any:
    """PZ with one line per (number, expiry, quantity)."""
    from saas_core.modules.shared.inventory.api import default_warehouse  # noqa: PLC0415
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        create_document,
        post_document,
    )

    document = create_document(
        request=request,
        kind="PZ",
        data={"target_location_id": default_warehouse(organization_id).id},
        lines=[
            LineInput(
                item_id=item_id,
                quantity=Decimal(quantity),
                unit_price_minor=100,
                lot_number=number,
                expires_on=expires_on,
            )
            for number, expires_on, quantity in lots
        ],
    )
    return post_document(request=request, document_id=document.id)


def held(organization_id: Any, **where: Any) -> dict[str, Decimal]:
    from saas_core.modules.shared.inventory.services import lot_rows  # noqa: PLC0415

    return {row["number"]: row["quantity"] for row in lot_rows(organization_id, **where)}


def test_a_rozchod_takes_the_lot_that_expires_first_and_says_which_it_took() -> None:
    """FEFO: bez wskazanej partii schodzi ta z najkrótszym terminem; co nie
    mieści się w partiach, schodzi bez partii — praca nie staje (decyzja 21.09)."""
    from datetime import timedelta  # noqa: PLC0415

    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        consume,
        default_warehouse,
        organization_today,
        source_lots,
    )

    owner = membership("partie-fefo")
    with tenant(owner) as request:
        today = organization_today(owner.organization_id)
        drug = lot_item(request)
        receive_lots(
            request,
            owner.organization_id,
            drug.id,
            ("L-LATER", today + timedelta(days=200), 5),
            ("L-SOON", today + timedelta(days=20), 3),
        )
        warehouse = default_warehouse(owner.organization_id).id
        consume(
            organization_id=owner.organization_id,
            source=ENTRY,
            source_reference="wpis-1",
            lines=[(drug.id, Decimal(4))],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        taken = {
            row["number"]: row["quantity"]
            for row in source_lots(owner.organization_id, source=ENTRY, source_reference="wpis-1")
        }
        assert taken == {"L-SOON": Decimal(3), "L-LATER": Decimal(1)}
        assert held(owner.organization_id) == {"L-LATER": Decimal(4)}

        # A lot the person pointed at goes as named, even if another expires first.
        receive_lots(
            request, owner.organization_id, drug.id, ("L-SOON-2", today + timedelta(days=10), 2)
        )
        consume(
            organization_id=owner.organization_id,
            source=ENTRY,
            source_reference="wpis-2",
            lines=[(drug.id, Decimal(1), held_lot(owner.organization_id, "L-LATER"))],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        assert held(owner.organization_id) == {"L-SOON-2": Decimal(2), "L-LATER": Decimal(3)}

        # More than the lots hold: the rest goes without a lot, below zero.
        consume(
            organization_id=owner.organization_id,
            source=ENTRY,
            source_reference="wpis-3",
            lines=[(drug.id, Decimal(7))],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        assert held(owner.organization_id) == {}
        assert quantities() == {"Oksytetracyklina": Decimal(-2)}


def held_lot(organization_id: Any, number: str) -> Any:
    from saas_core.modules.shared.inventory.models import InventoryLot  # noqa: PLC0415

    return InventoryLot.all_objects.get(organization_id=organization_id, number=number).id


def test_an_expired_lot_warns_at_work_but_is_never_sold() -> None:
    """Decyzja 25.09 (1a): partia po terminie w pracy tylko ostrzega; WZ
    zatwierdzane w panelu jej nie sprzeda i omija ją przy wyborze partii."""
    from datetime import timedelta  # noqa: PLC0415

    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        consume,
        default_warehouse,
        lot_status,
        organization_today,
    )
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        LotExpired,
        StockShortage,
        create_document,
        list_lots,
        post_document,
    )

    owner = membership("partie-termin")
    with tenant(owner) as request:
        today = organization_today(owner.organization_id)
        assert lot_status(today, today) == "expiring"
        assert lot_status(today + timedelta(days=31), today) == "ok"
        assert lot_status(None, today) == "no_date"
        drug = lot_item(request)
        receive_lots(
            request,
            owner.organization_id,
            drug.id,
            ("OLD", today - timedelta(days=1), 2),
            ("NEW", today + timedelta(days=90), 2),
        )
        statuses = {row["number"]: row["status"] for row in list_lots(item_id=drug.id)}
        assert statuses == {"OLD": "expired", "NEW": "ok"}
        warehouse = default_warehouse(owner.organization_id).id

        # The valid lot goes first, although the expired one has the earlier date.
        consume(
            organization_id=owner.organization_id,
            source=ENTRY,
            source_reference="wpis-ok",
            lines=[(drug.id, Decimal(1))],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        assert held(owner.organization_id) == {"OLD": Decimal(2), "NEW": Decimal(1)}

        named = create_document(
            request=request,
            kind="WZ",
            data={"source_location_id": warehouse, "counterparty": "Klient"},
            lines=[
                LineInput(
                    item_id=drug.id,
                    quantity=Decimal(1),
                    lot_id=held_lot(owner.organization_id, "OLD"),
                )
            ],
        )
        with pytest.raises(LotExpired):
            post_document(request=request, document_id=named.id)
        # Two needed, one valid: the expired lot does not make up the rest.
        short = create_document(
            request=request,
            kind="WZ",
            data={"source_location_id": warehouse, "counterparty": "Klient"},
            lines=[LineInput(item_id=drug.id, quantity=Decimal(2))],
        )
        with pytest.raises(StockShortage):
            post_document(request=request, document_id=short.id)
        assert held(owner.organization_id) == {"OLD": Decimal(2), "NEW": Decimal(1)}


def test_a_transfer_carries_the_lots_a_count_goes_lot_by_lot_and_a_correction_undoes_both() -> None:
    from datetime import timedelta  # noqa: PLC0415

    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        default_warehouse,
        holder_stock,
        organization_today,
    )
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        correct_document,
        create_document,
        issue,
        post_document,
    )

    owner = membership("partie-mm")
    trimmer = User.objects.create_user(email="korektor-partie@example.test")
    with tenant(owner) as request:
        today = organization_today(owner.organization_id)
        drug = lot_item(request)
        receive_lots(
            request,
            owner.organization_id,
            drug.id,
            ("A", today + timedelta(days=300), 4),
            ("B", today + timedelta(days=60), 1),
        )
        transfer = issue(
            request=request, item_id=drug.id, holder_id=trimmer.id, quantity=Decimal(3)
        )
        (kit,) = holder_stock(owner.organization_id, trimmer.id)
        assert kit["tracks_lots"] is True
        # FEFO order: the first lot is the one that goes next.
        assert [(lot["number"], lot["quantity"]) for lot in kit["lots"]] == [
            ("B", Decimal(1)),
            ("A", Decimal(2)),
        ]
        warehouse = default_warehouse(owner.organization_id).id
        assert held(owner.organization_id, location_ids=[warehouse]) == {"A": Decimal(2)}

        count = create_document(
            request=request,
            kind="INW",
            data={"target_location_id": warehouse},
            lines=[
                LineInput(
                    item_id=drug.id,
                    quantity=Decimal(5),
                    lot_id=held_lot(owner.organization_id, "A"),
                )
            ],
        )
        post_document(request=request, document_id=count.id)
        assert held(owner.organization_id, location_ids=[warehouse]) == {"A": Decimal(5)}

        correct_document(request=request, document_id=count.id)
        correct_document(request=request, document_id=transfer.id)
        assert held(owner.organization_id, location_ids=[warehouse]) == {
            "A": Decimal(4),
            "B": Decimal(1),
        }
        assert holder_stock(owner.organization_id, trimmer.id)[0]["lots"] == []


def test_a_lot_belongs_to_an_item_that_keeps_lots_and_keeps_its_date() -> None:
    from datetime import date  # noqa: PLC0415

    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        consume,
        default_warehouse,
    )
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        LineInput,
        create_document,
    )

    owner = membership("partie-granice")
    with tenant(owner) as request:
        block = item(request)
        drug = lot_item(request)
        warehouse = default_warehouse(owner.organization_id).id
        with pytest.raises(ValidationError, match="nie prowadzi partii"):
            create_document(
                request=request,
                kind="PZ",
                data={"target_location_id": warehouse},
                lines=[LineInput(item_id=block.id, quantity=Decimal(1), lot_number="X")],
            )
        receive_lots(request, owner.organization_id, drug.id, ("L1", date(2030, 1, 31), 1))
        with pytest.raises(ValidationError, match="ma już termin"):
            receive_lots(request, owner.organization_id, drug.id, ("L1", date(2031, 1, 31), 1))
        with pytest.raises(ValidationError, match="Nie ma partii"):
            create_document(
                request=request,
                kind="RW",
                data={"source_location_id": warehouse},
                lines=[LineInput(item_id=drug.id, quantity=Decimal(1), lot_number="NOPE")],
            )
        # A lot the field no longer knows does not stop the work: FEFO takes over.
        document = consume(
            organization_id=owner.organization_id,
            source=ENTRY,
            source_reference="wpis-stary",
            lines=[(drug.id, Decimal(1), block.id)],
            location_id=warehouse,
            actor_id=owner.user_id,
        )
        assert document is not None
        assert held(owner.organization_id) == {}
