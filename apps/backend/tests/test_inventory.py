"""Magazyn materiałów (`shared.inventory`).

Pomijane tam, gdzie profil nie składa modułu. Stan wynika z ruchów, więc
większość tych testów sprawdza jedno: czy po ruchu zgadza się i historia, i
suma, którą trzymamy obok niej.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

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


def membership(slug: str, *, entitled: bool = True) -> Membership:
    Feature.objects.get_or_create(
        key="inventory.enabled",
        defaults={"name": "Magazyn materiałów", "module": "shared.inventory"},
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE, timezone="Europe/Warsaw"
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
        features={"inventory.enabled": entitled},
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


def test_the_warehouse_is_granted_to_core_roles() -> None:
    assert {"inventory.read", "inventory.manage"} <= set(SYSTEM_ROLE_PERMISSIONS["owner"])
    assert "inventory.read" in SYSTEM_ROLE_PERMISSIONS["staff"]
    assert "inventory.manage" not in SYSTEM_ROLE_PERMISSIONS["staff"]


def test_a_receipt_sets_the_price_the_next_one_averages() -> None:
    """Rozchód wycenia się średnią, więc koszt wizyty nie zmienia się po dostawie."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        balances,
        create_item,
        list_items,
        receive,
    )

    owner = membership("magazyn-cena")
    with tenant(owner) as request:
        item = create_item(
            request=request, data={"name": "Klocek drewniany", "category": "block"}
        )
        receive(
            request=request, item_id=item.id, quantity=Decimal(100), unit_cost_minor=250
        )
        receive(
            request=request, item_id=item.id, quantity=Decimal(100), unit_cost_minor=350
        )
        (refreshed,) = list_items()
        # Sto sztuk po 2,50 zł i sto po 3,50 zł to trzy złote za sztukę.
        assert refreshed.average_cost_minor == 300
        (stock,) = balances()
        assert stock.quantity == Decimal(200)


def test_what_goes_to_a_trimmer_leaves_the_warehouse_and_comes_back() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        balances,
        create_item,
        give_back,
        issue,
        receive,
    )

    owner = membership("magazyn-wydanie")
    trimmer = User.objects.create_user(email="korektor@example.test")
    with tenant(owner) as request:
        item = create_item(request=request, data={"name": "Opatrunek", "category": "dressing"})
        receive(request=request, item_id=item.id, quantity=Decimal(50), unit_cost_minor=120)
        issue(request=request, item_id=item.id, holder_id=trimmer.id, quantity=Decimal(12))

        (company,) = balances()
        (personal,) = balances(holder_id=trimmer.id)
        assert (company.quantity, personal.quantity) == (Decimal(38), Decimal(12))

        give_back(request=request, item_id=item.id, holder_id=trimmer.id, quantity=Decimal(2))
        (company,) = balances()
        (personal,) = balances(holder_id=trimmer.id)
        assert (company.quantity, personal.quantity) == (Decimal(40), Decimal(10))


def test_work_never_stops_for_a_stock_level() -> None:
    """Brak pokrycia ostrzega, ale zapisuje: stan schodzi poniżej zera, a to
    jest właśnie to, co właściciel ma wyjaśnić (decyzja z 21.09)."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        balances,
        consume,
        create_item,
        movements,
    )

    owner = membership("magazyn-minus")
    trimmer = User.objects.create_user(email="korektor-minus@example.test")
    with tenant(owner) as request:
        item = create_item(request=request, data={"name": "Klocek", "category": "block"})
        consume(
            request=request,
            organization_id=owner.organization_id,
            holder_id=trimmer.id,
            item_id=item.id,
            quantity=Decimal(1),
            source="hoofcare.entry",
            source_reference="wpis-1",
        )
        (personal,) = balances(holder_id=trimmer.id)
        assert personal.quantity == Decimal(-1)

        # Ten sam wpis zapisany drugi raz to jeden klocek, nie dwa.
        consume(
            request=request,
            organization_id=owner.organization_id,
            holder_id=trimmer.id,
            item_id=item.id,
            quantity=Decimal(1),
            source="hoofcare.entry",
            source_reference="wpis-1",
        )
        (personal,) = balances(holder_id=trimmer.id)
        assert personal.quantity == Decimal(-1)
        assert movements(item_id=item.id).count() == 1


def test_a_voided_entry_gives_the_material_back() -> None:
    """Cofnięty wpis oddaje klocek temu, komu go zdjął — inaczej pomyłka w
    poskromie na stałe zjadałaby zapas korektora."""
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        balances,
        consume,
        create_item,
        movements,
        release,
    )

    owner = membership("magazyn-cofniecie")
    trimmer = User.objects.create_user(email="korektor-cofniecie@example.test")
    with tenant(owner) as request:
        item = create_item(request=request, data={"name": "Klocek", "category": "block"})
        for reference in ("wpis-1", "wpis-2"):
            consume(
                request=request,
                organization_id=owner.organization_id,
                holder_id=trimmer.id,
                item_id=item.id,
                quantity=Decimal(1),
                source="hoofcare.entry",
                source_reference=reference,
            )
        release(
            request=request,
            organization_id=owner.organization_id,
            source="hoofcare.entry",
            source_reference="wpis-1",
        )
        (personal,) = balances(holder_id=trimmer.id)
        assert personal.quantity == Decimal(-1)

        # Powtórka cofnięcia nie oddaje drugi raz, a cudzego wpisu nie rusza.
        release(
            request=request,
            organization_id=owner.organization_id,
            source="hoofcare.entry",
            source_reference="wpis-1",
        )
        (personal,) = balances(holder_id=trimmer.id)
        assert personal.quantity == Decimal(-1)
        assert movements(item_id=item.id).count() == 3


def test_a_correction_needs_a_reason_and_leaves_the_history_alone() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        adjust,
        balances,
        create_item,
        movements,
        receive,
    )

    owner = membership("magazyn-korekta")
    with tenant(owner) as request:
        item = create_item(request=request, data={"name": "Klej", "category": "other"})
        receive(request=request, item_id=item.id, quantity=Decimal(10), unit_cost_minor=999)
        with pytest.raises(ValidationError, match="powodu"):
            adjust(
                request=request,
                item_id=item.id,
                holder_id=None,
                quantity=Decimal(-3),
                note="   ",
            )
        adjust(
            request=request,
            item_id=item.id,
            holder_id=None,
            quantity=Decimal(-3),
            note="Zbita butelka przy załadunku.",
        )
        (stock,) = balances()
        assert stock.quantity == Decimal(7)
        # Przyjęcie zostaje w historii: korekta prostuje stan, nie przeszłość.
        assert [row.kind for row in movements(item_id=item.id)] == ["adjustment", "receipt"]


def test_the_catalogue_refuses_a_second_item_with_the_same_name() -> None:
    from saas_core.modules.shared.inventory.services import create_item  # noqa: PLC0415

    owner = membership("magazyn-nazwa")
    with tenant(owner) as request:
        create_item(request=request, data={"name": "Klocek", "category": "block"})
        with pytest.raises(ValidationError, match="już jest"):
            create_item(request=request, data={"name": "klocek", "category": "block"})


def test_another_companys_warehouse_is_simply_not_there() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        create_item,
        list_items,
    )

    first = membership("magazyn-jeden")
    second = membership("magazyn-dwa")
    with tenant(first) as request:
        create_item(request=request, data={"name": "Klocek", "category": "block"})
    with tenant(second):
        # Baza testowa omija RLS, więc to dowodzi filtra w zapytaniu; izolacja
        # pod polityką jest sprawdzana na uruchomionym stacku.
        assert list_items() == []
