"""Co można zrobić z magazynem — i co to robi ze stanem.

Każdy ruch przechodzi tędy, bo stan i historia muszą powstać razem: wiersz
`InventoryMovement` opisuje, co się stało, a `InventoryBalance` jest tego
sumą, trzymaną obok tylko po to, żeby ekran w oborze nie sumował historii.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import F, QuerySet
from django.http import HttpRequest
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    InventoryBalance,
    InventoryItem,
    InventoryMovement,
    ItemCategory,
    MovementKind,
)
from .permissions import INVENTORY_MANAGE, INVENTORY_READ

#: Cecha planu, która włącza magazyn.
INVENTORY_ENABLED = "inventory.enabled"
PAGE_LIMIT = 500

#: Ruchy, które zdejmują ze stanu. Znak niesie sam ruch, ale kierunek decyduje
#: o tym, czy wolno go zapisać bez pokrycia.
OUTGOING = {MovementKind.ISSUE, MovementKind.CONSUMPTION}


def list_items(*, category: str = "", search: str = "") -> list[InventoryItem]:
    context = authorize_entitled(
        INVENTORY_READ, INVENTORY_ENABLED, operation=FeatureOperation.READ
    )
    query = InventoryItem.all_objects.filter(organization_id=context.organization_id)
    if category:
        query = query.filter(category=category)
    if search:
        query = query.filter(name__icontains=search.strip())
    return list(query[:PAGE_LIMIT])


@transaction.atomic
def create_item(*, request: HttpRequest, data: dict[str, Any]) -> InventoryItem:
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    name = str(data["name"]).strip()
    if InventoryItem.all_objects.filter(
        organization_id=context.organization_id, name__iexact=name
    ).exists():
        raise ValidationError({"name": "Taka pozycja już jest w katalogu."})
    item = InventoryItem.all_objects.create(
        organization_id=context.organization_id,
        name=name,
        category=data.get("category") or ItemCategory.OTHER,
        unit=data.get("unit") or "piece",
        minimum_quantity=data.get("minimum_quantity") or 0,
        notes=str(data.get("notes") or "").strip(),
    )
    _audit(request, context.organization_id, OrganizationAuditAction.INVENTORY_ITEM_CREATED, item)
    return item


@transaction.atomic
def update_item(*, request: HttpRequest, item_id: UUID, data: dict[str, Any]) -> InventoryItem:
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    item = _item(context.organization_id, item_id, lock=True)
    for field in ("name", "category", "unit", "minimum_quantity", "active", "notes"):
        if field in data:
            setattr(item, field, data[field])
    item.save()
    _audit(request, context.organization_id, OrganizationAuditAction.INVENTORY_ITEM_UPDATED, item)
    return item


def balances(*, holder_id: UUID | None = None, mine: bool = False) -> list[InventoryBalance]:
    """Stany jednego miejsca: magazynu firmy, wskazanej osoby albo własne.

    `mine` istnieje dla korektora w oborze: jego pakiet na dzień pracy widzi
    każdy, kto ma `inventory.read`, bez prawa do prowadzenia magazynu.
    """
    context = authorize_entitled(
        INVENTORY_READ, INVENTORY_ENABLED, operation=FeatureOperation.READ
    )
    return list(
        InventoryBalance.all_objects.filter(
            organization_id=context.organization_id,
            holder_id=context.actor_id if mine else holder_id,
        ).select_related("item")[:PAGE_LIMIT]
    )


@transaction.atomic
def receive(
    *, request: HttpRequest, item_id: UUID, quantity: Decimal, unit_cost_minor: int, note: str = ""
) -> InventoryMovement:
    """Przyjęcie do magazynu firmy, z ceną z faktury.

    Cena przelicza średnią ważoną pozycji: rozchód wycenia się po niej, więc
    koszt wizyty nie zmienia się przy następnej dostawie.
    """
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    item = _item(context.organization_id, item_id, lock=True)
    if quantity <= 0:
        raise ValidationError({"quantity": "Przyjęcie musi być dodatnie."})
    stock = _balance(context.organization_id, item, None, lock=True)
    total_before = Decimal(stock.quantity) * item.average_cost_minor
    total_new = Decimal(quantity) * unit_cost_minor
    after = Decimal(stock.quantity) + quantity
    item.average_cost_minor = int((total_before + total_new) / after) if after > 0 else 0
    item.save(update_fields=["average_cost_minor", "updated_at"])
    return _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.RECEIPT,
        quantity=quantity,
        holder_id=None,
        unit_cost_minor=unit_cost_minor,
        note=note,
    )


@transaction.atomic
def issue(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID, quantity: Decimal, note: str = ""
) -> InventoryMovement:
    """Wydanie pracownikowi: z magazynu firmy do jego imiennego zapasu."""
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    item = _item(context.organization_id, item_id)
    if quantity <= 0:
        raise ValidationError({"quantity": "Wydanie musi być dodatnie."})
    _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.ISSUE,
        quantity=-quantity,
        holder_id=None,
        unit_cost_minor=item.average_cost_minor,
        note=note,
    )
    return _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.ISSUE,
        quantity=quantity,
        holder_id=holder_id,
        unit_cost_minor=item.average_cost_minor,
        note=note,
    )


@transaction.atomic
def give_back(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID, quantity: Decimal, note: str = ""
) -> InventoryMovement:
    """Zwrot niewykorzystanego materiału do magazynu firmy."""
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    item = _item(context.organization_id, item_id)
    if quantity <= 0:
        raise ValidationError({"quantity": "Zwrot musi być dodatni."})
    _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.RETURN,
        quantity=-quantity,
        holder_id=holder_id,
        unit_cost_minor=item.average_cost_minor,
        note=note,
    )
    return _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.RETURN,
        quantity=quantity,
        holder_id=None,
        unit_cost_minor=item.average_cost_minor,
        note=note,
    )


@transaction.atomic
def adjust(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID | None, quantity: Decimal, note: str
) -> InventoryMovement:
    """Korekta stanu — jedyna droga do poprawienia pomyłki, zawsze z powodem."""
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    if not note.strip():
        raise ValidationError({"note": "Korekta wymaga powodu."})
    item = _item(context.organization_id, item_id)
    return _move(
        request,
        context.organization_id,
        item=item,
        kind=MovementKind.ADJUSTMENT,
        quantity=quantity,
        holder_id=holder_id,
        unit_cost_minor=item.average_cost_minor,
        note=note.strip(),
    )


def holder_stock(organization_id: UUID, holder_id: UUID) -> dict[UUID, Decimal]:
    """Ile czego ma przy sobie ten człowiek — dla ekranu, który o to pyta.

    Bez bramki uprawnień: wołający już sprawdził swoją (wertykał pyta o zapas
    osoby, która właśnie pracuje), a magazyn nie ma tu czego dokładać.
    """
    return {
        balance.item_id: Decimal(balance.quantity)
        for balance in InventoryBalance.all_objects.filter(
            organization_id=organization_id, holder_id=holder_id
        )
    }


def consume(
    *,
    request: HttpRequest,
    organization_id: UUID,
    holder_id: UUID,
    item_id: UUID,
    quantity: Decimal,
    source: str,
    source_reference: str,
) -> InventoryMovement | None:
    """Zużycie przy pracy: schodzi z zapasu człowieka, który je zużył.

    Brak pokrycia nie zatrzymuje pracy — stan schodzi poniżej zera, a ujemna
    wartość jest tym, co właściciel ma wyjaśnić (decyzja z 21.09). Powtórka z
    tym samym źródłem nie dokłada drugiego ruchu: wpis korekcji zapisany dwa
    razy to jeden klocek.
    """
    item = InventoryItem.all_objects.filter(
        organization_id=organization_id, id=item_id
    ).first()
    if item is None or quantity <= 0:
        return None
    existing = InventoryMovement.all_objects.filter(
        organization_id=organization_id,
        source=source,
        source_reference=source_reference,
        item=item,
        holder_id=holder_id,
    ).first()
    if existing is not None:
        return existing
    return _move(
        request,
        organization_id,
        item=item,
        kind=MovementKind.CONSUMPTION,
        quantity=-quantity,
        holder_id=holder_id,
        unit_cost_minor=item.average_cost_minor,
        source=source,
        source_reference=source_reference,
        actor_id=holder_id,
    )


@transaction.atomic
def release(
    *,
    request: HttpRequest,
    organization_id: UUID,
    source: str,
    source_reference: str,
) -> None:
    """Cofnięte źródło oddaje materiał temu, komu go zdjęło.

    Zużycie istnieje tylko razem ze swoim wpisem: kiedy wpis znika, zapas musi
    wrócić, bo inaczej właściciel widzi ubytek bez pracy, która go tłumaczy.
    Kasujemy osobnym wierszem, nie kasowaniem starego — księga zostaje
    dopisywalna, a dzień korektora daje się odtworzyć ruch po ruchu.
    """
    undone = f"{source_reference}:void"
    for movement in InventoryMovement.all_objects.filter(
        organization_id=organization_id,
        source=source,
        source_reference=source_reference,
        kind=MovementKind.CONSUMPTION,
        quantity__lt=0,
    ).select_related("item"):
        already = InventoryMovement.all_objects.filter(
            organization_id=organization_id,
            source=source,
            source_reference=undone,
            item_id=movement.item_id,
            holder_id=movement.holder_id,
        ).exists()
        if already:
            continue
        _move(
            request,
            organization_id,
            item=movement.item,
            kind=MovementKind.CONSUMPTION,
            quantity=-movement.quantity,
            holder_id=movement.holder_id,
            unit_cost_minor=movement.unit_cost_minor,
            source=source,
            source_reference=undone,
            actor_id=movement.holder_id,
        )


def movements(*, item_id: UUID | None = None) -> QuerySet[InventoryMovement]:
    context = authorize_entitled(
        INVENTORY_READ, INVENTORY_ENABLED, operation=FeatureOperation.READ
    )
    query = InventoryMovement.all_objects.filter(
        organization_id=context.organization_id
    ).select_related("item", "created_by")
    return query.filter(item_id=item_id) if item_id else query


def _item(organization_id: UUID, item_id: UUID, *, lock: bool = False) -> InventoryItem:
    query = InventoryItem.all_objects.filter(organization_id=organization_id, id=item_id)
    item = (query.select_for_update() if lock else query).first()
    if item is None:
        raise NotFound("Nie ma takiej pozycji w magazynie.")
    return item


def _balance(
    organization_id: UUID, item: InventoryItem, holder_id: UUID | None, *, lock: bool = False
) -> InventoryBalance:
    query = InventoryBalance.all_objects.filter(
        organization_id=organization_id, item=item, holder_id=holder_id
    )
    balance = (query.select_for_update() if lock else query).first()
    if balance is not None:
        return balance
    return InventoryBalance.all_objects.create(
        organization_id=organization_id, item=item, holder_id=holder_id, quantity=0
    )


def _move(
    request: HttpRequest,
    organization_id: UUID,
    *,
    item: InventoryItem,
    kind: str,
    quantity: Decimal,
    holder_id: UUID | None,
    unit_cost_minor: int,
    note: str = "",
    source: str = "",
    source_reference: str = "",
    actor_id: UUID | None = None,
) -> InventoryMovement:
    balance = _balance(organization_id, item, holder_id, lock=True)
    InventoryBalance.all_objects.filter(pk=balance.pk).update(quantity=F("quantity") + quantity)
    balance.refresh_from_db(fields=["quantity"])
    return InventoryMovement.all_objects.create(
        organization_id=organization_id,
        item=item,
        kind=kind,
        quantity=quantity,
        holder_id=holder_id,
        unit_cost_minor=unit_cost_minor,
        note=note,
        source=source,
        source_reference=source_reference,
        created_by_id=actor_id or cast(User, request.user).id,
    )


def _audit(
    request: HttpRequest, organization_id: UUID, action: str, item: InventoryItem
) -> None:
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=action,
        actor=cast(User, request.user),
        target_type="inventory_item",
        target_id=item.id,
    )
