"""Co można zrobić z magazynem — i co to robi ze stanem (ADR-055).

Stan zmienia się wyłącznie przez zatwierdzenie dokumentu: wiersze dokumentu
stają się ruchami księgi, a `InventoryBalance` przesuwa się razem z nimi w tej
samej transakcji. Zatwierdzony dokument się nie zmienia; pomyłkę cofa korekta.
Katalog, kategorie i magazyn główny firmy powstają leniwie przy pierwszym
dostępie — z deklaracji produktu dla typu organizacji albo z zestawu rdzenia.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Model, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    DocumentKind,
    DocumentSequence,
    DocumentStatus,
    InventoryBalance,
    InventoryCategory,
    InventoryItem,
    InventoryMovement,
    LocationKind,
    ReservationStatus,
    StockDocument,
    StockDocumentLine,
    StockLocation,
    StockReservation,
    Supplier,
)
from .permissions import INVENTORY_MANAGE, INVENTORY_READ

#: Cecha planu, która włącza magazyn.
INVENTORY_ENABLED = "inventory.enabled"
PAGE_LIMIT = 500

#: Zestaw rdzenia dla typu, którego produkt nie zadeklarował magazynu.
CORE_CATEGORIES = (
    ("product", {"pl": "Produkt", "en": "Product"}),
    ("material", {"pl": "Materiał", "en": "Material"}),
    ("tool", {"pl": "Narzędzie", "en": "Tool"}),
    ("other", {"pl": "Inne", "en": "Other"}),
)
MAIN_WAREHOUSE = {"pl": "Magazyn główny", "en": "Main warehouse"}
PERSONAL_STOCK = {"pl": "Zapas osoby", "en": "Personal stock"}

#: Czego dokument potrzebuje: skąd schodzi i dokąd przybywa.
NEEDS_SOURCE = {DocumentKind.WZ, DocumentKind.RW, DocumentKind.MM}
NEEDS_TARGET = {DocumentKind.PZ, DocumentKind.PW, DocumentKind.MM, DocumentKind.INW}
#: Przyjęcia z ceną przeliczają średnią ważoną pozycji.
PRICED_RECEIPTS = {DocumentKind.PZ, DocumentKind.PW}


class StockShortage(APIException):
    """Sprzedaż towaru, którego nie ma — jedyny przypadek, w którym stan blokuje."""

    status_code = 409
    default_code = "stock_shortage"
    default_detail = "Brakuje towaru na stanie."


class DocumentPosted(APIException):
    status_code = 409
    default_code = "stock_document_posted"
    default_detail = "Zatwierdzony dokument się nie zmienia — wystaw korektę."


class DocumentAlreadyCorrected(APIException):
    status_code = 409
    default_code = "stock_document_corrected"
    default_detail = "Ten dokument ma już korektę."


@dataclass(frozen=True, slots=True)
class LineInput:
    item_id: UUID
    quantity: Decimal
    unit_price_minor: int | None = None
    note: str = ""


# --- katalog, kategorie, miejsca --------------------------------------------------


def _organization(organization_id: UUID) -> Organization:
    return Organization.objects.get(pk=organization_id)


def _label(labels: dict[str, str], organization: Organization) -> str:
    return (
        labels.get(organization.default_locale) or labels.get("pl") or next(iter(labels.values()))
    )


def ensure_catalog(organization_id: UUID) -> None:
    """Kategorie startowe, pozycje standardowe i magazyn główny — raz na firmę.

    Rdzeń nie zna branży (ADR-049): zestaw bierze się z deklaracji produktu dla
    typu organizacji. Wołane na początku każdej operacji; po pierwszym razie to
    jedno zapytanie o istnienie magazynu głównego.
    """
    if StockLocation.all_objects.filter(organization_id=organization_id, is_default=True).exists():
        return
    organization = _organization(organization_id)
    organization_type = settings.ORGANIZATION_TYPES.get(organization.organization_type)
    template = getattr(organization_type, "inventory", None)
    categories = (
        [(category.key, category.label) for category in template.categories]
        if template is not None
        else list(CORE_CATEGORIES)
    )
    with transaction.atomic():
        by_key: dict[str, InventoryCategory] = {}
        for key, labels in categories:
            category, _ = InventoryCategory.all_objects.get_or_create(
                organization_id=organization_id,
                key=key,
                defaults={"name": _label(labels, organization), "system": True},
            )
            by_key[key] = category
        for item in template.default_items if template is not None else ():
            InventoryItem.all_objects.get_or_create(
                organization_id=organization_id,
                system_key=item.key,
                defaults={
                    "name": _label(item.name, organization),
                    "category": by_key.get(item.category),
                    "unit": item.unit,
                },
            )
        try:
            with transaction.atomic():
                StockLocation.all_objects.create(
                    organization_id=organization_id,
                    kind=LocationKind.WAREHOUSE,
                    name=_label(MAIN_WAREHOUSE, organization),
                    is_default=True,
                )
        except IntegrityError:
            pass  # A concurrent request created it first.


def default_warehouse(organization_id: UUID) -> StockLocation:
    ensure_catalog(organization_id)
    return StockLocation.all_objects.get(organization_id=organization_id, is_default=True)


def person_location(organization_id: UUID, holder_id: UUID) -> StockLocation:
    """Zapas osoby: powstaje, gdy pierwszy raz coś do niej trafia.

    Nazwa jest ogólna, a to, czyj to zapas, mówi `holder` — imię i e-mail
    zostają w koncie osoby, nie w magazynie, więc znikają razem z nim.
    """
    existing = StockLocation.all_objects.filter(
        organization_id=organization_id, holder_id=holder_id
    ).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            return StockLocation.all_objects.create(
                organization_id=organization_id,
                kind=LocationKind.PERSON,
                name=_label(PERSONAL_STOCK, _organization(organization_id)),
                holder_id=holder_id,
            )
    except IntegrityError:
        return StockLocation.all_objects.get(organization_id=organization_id, holder_id=holder_id)


def _read_context() -> Any:
    context = authorize_entitled(INVENTORY_READ, INVENTORY_ENABLED, operation=FeatureOperation.READ)
    ensure_catalog(context.organization_id)
    return context


def _manage_context() -> Any:
    context = authorize_entitled(INVENTORY_MANAGE, INVENTORY_ENABLED)
    ensure_catalog(context.organization_id)
    return context


def list_categories() -> list[InventoryCategory]:
    context = _read_context()
    return list(InventoryCategory.all_objects.filter(organization_id=context.organization_id))


@transaction.atomic
def create_category(*, request: HttpRequest, name: str) -> InventoryCategory:
    context = _manage_context()
    name = name.strip()
    if InventoryCategory.all_objects.filter(
        organization_id=context.organization_id, name__iexact=name
    ).exists():
        raise ValidationError({"name": "Taka kategoria już jest."})
    base = slugify(name)[:56] or "category"
    key, number = base, 1
    while InventoryCategory.all_objects.filter(
        organization_id=context.organization_id, key=key
    ).exists():
        number += 1
        key = f"{base}-{number}"
    category = InventoryCategory.all_objects.create(
        organization_id=context.organization_id, key=key, name=name
    )
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_CATEGORY_CREATED,
        "inventory_category",
        category.id,
        {"name": name},
    )
    return category


@transaction.atomic
def rename_category(*, request: HttpRequest, category_id: UUID, name: str) -> InventoryCategory:
    context = _manage_context()
    category = _get(InventoryCategory, context.organization_id, category_id, lock=True)
    before = audit_snapshot(category, ["name"])
    category.name = name.strip()
    category.save(update_fields=["name"])
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_CATEGORY_UPDATED,
        "inventory_category",
        category.id,
        {"changes": field_changes(before, audit_snapshot(category, ["name"]))},
    )
    return category


@transaction.atomic
def delete_category(*, request: HttpRequest, category_id: UUID) -> None:
    """Tylko własną i pustą — startowa kategoria produktu zostaje (ADR-055)."""
    context = _manage_context()
    category = _get(InventoryCategory, context.organization_id, category_id, lock=True)
    if category.system:
        raise ValidationError({
            "category": "Kategorii startowej nie usuwa się; możesz zmienić jej nazwę."
        })
    if InventoryItem.all_objects.filter(
        organization_id=context.organization_id, category=category
    ).exists():
        raise ValidationError({"category": "W tej kategorii są pozycje — przenieś je najpierw."})
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_CATEGORY_DELETED,
        "inventory_category",
        category.id,
        {"name": category.name},
    )
    category.delete()


def list_locations() -> list[StockLocation]:
    context = _read_context()
    return list(
        StockLocation.all_objects.filter(organization_id=context.organization_id).select_related(
            "holder"
        )
    )


@transaction.atomic
def create_warehouse(*, request: HttpRequest, name: str) -> StockLocation:
    context = _manage_context()
    location = StockLocation.all_objects.create(
        organization_id=context.organization_id,
        kind=LocationKind.WAREHOUSE,
        name=name.strip(),
    )
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_LOCATION_CREATED,
        "stock_location",
        location.id,
        {"name": location.name},
    )
    return location


@transaction.atomic
def update_location(
    *, request: HttpRequest, location_id: UUID, data: dict[str, Any]
) -> StockLocation:
    context = _manage_context()
    location = _get(StockLocation, context.organization_id, location_id, lock=True)
    fields = [field for field in ("name", "active") if field in data]
    if location.is_default and data.get("active") is False:
        raise ValidationError({"active": "Magazynu głównego nie wyłącza się."})
    before = audit_snapshot(location, fields)
    for field in fields:
        setattr(location, field, data[field])
    location.save(update_fields=fields)
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_LOCATION_UPDATED,
        "stock_location",
        location.id,
        {"changes": field_changes(before, audit_snapshot(location, fields))},
    )
    return location


def list_suppliers() -> list[Supplier]:
    context = _read_context()
    return list(Supplier.all_objects.filter(organization_id=context.organization_id)[:PAGE_LIMIT])


SUPPLIER_FIELDS = ("name", "tax_id", "email", "phone", "notes", "active")
#: A sole trader's supplier record can be a person: history keeps only the change.
SUPPLIER_PRIVATE = ("tax_id", "email", "phone", "notes")


@transaction.atomic
def save_supplier(
    *, request: HttpRequest, data: dict[str, Any], supplier_id: UUID | None = None
) -> Supplier:
    context = _manage_context()
    if supplier_id is None:
        supplier = Supplier.all_objects.create(
            organization_id=context.organization_id,
            **{field: data[field] for field in SUPPLIER_FIELDS if field in data},
        )
        _audit(
            request,
            context.organization_id,
            OrganizationAuditAction.INVENTORY_SUPPLIER_CREATED,
            "supplier",
            supplier.id,
            {"name": supplier.name},
        )
        return supplier
    supplier = _get(Supplier, context.organization_id, supplier_id, lock=True)
    fields = [field for field in SUPPLIER_FIELDS if field in data]
    before = audit_snapshot(supplier, fields)
    for field in fields:
        setattr(supplier, field, data[field])
    supplier.save()
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_SUPPLIER_UPDATED,
        "supplier",
        supplier.id,
        {
            "changes": field_changes(
                before, audit_snapshot(supplier, fields), private=SUPPLIER_PRIVATE
            )
        },
    )
    return supplier


# --- pozycje katalogu ---------------------------------------------------------------

ITEM_FIELDS = (
    "name",
    "sku",
    "ean",
    "category",
    "unit",
    "minimum_quantity",
    "sale_price_net_minor",
    "vat_rate",
    "active",
    "notes",
)


def list_items(
    *, category: str = "", search: str = "", include_hidden: bool = True
) -> list[InventoryItem]:
    context = _read_context()
    query = InventoryItem.all_objects.filter(
        organization_id=context.organization_id
    ).select_related("category")
    if category:
        query = query.filter(Q(category__key=category) | Q(category_id__in=_uuid_or_none(category)))
    if search:
        term = search.strip()
        query = query.filter(Q(name__icontains=term) | Q(sku__iexact=term) | Q(ean=term))
    if not include_hidden:
        query = query.filter(active=True)
    return list(query[:PAGE_LIMIT])


def _uuid_or_none(value: str) -> list[UUID]:
    try:
        return [UUID(value)]
    except ValueError:
        return []


def _category(organization_id: UUID, value: Any) -> InventoryCategory | None:
    """A category by its id or its key; the v1 panel still sends keys."""
    if value in (None, ""):
        return None
    query = InventoryCategory.all_objects.filter(organization_id=organization_id)
    found = query.filter(Q(key=str(value)) | Q(id__in=_uuid_or_none(str(value)))).first()
    if found is None:
        raise ValidationError({"category": "Nie ma takiej kategorii."})
    return found


def _item_values(organization_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    values = {field: data[field] for field in ITEM_FIELDS if field in data}
    if "category" in values:
        values["category"] = _category(organization_id, values["category"])
    for text in ("name", "sku", "ean", "notes"):
        if text in values:
            values[text] = str(values[text] or "").strip()
    return values


@transaction.atomic
def create_item(*, request: HttpRequest, data: dict[str, Any]) -> InventoryItem:
    context = _manage_context()
    values = _item_values(context.organization_id, data)
    if InventoryItem.all_objects.filter(
        organization_id=context.organization_id, name__iexact=values["name"]
    ).exists():
        raise ValidationError({"name": "Taka pozycja już jest w katalogu."})
    if (
        values.get("sku")
        and InventoryItem.all_objects.filter(
            organization_id=context.organization_id, sku=values["sku"]
        ).exists()
    ):
        raise ValidationError({"sku": "Ten kod SKU ma już inna pozycja."})
    item = InventoryItem.all_objects.create(organization_id=context.organization_id, **values)
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_ITEM_CREATED,
        "inventory_item",
        item.id,
    )
    return item


@transaction.atomic
def update_item(*, request: HttpRequest, item_id: UUID, data: dict[str, Any]) -> InventoryItem:
    context = _manage_context()
    item = _get(InventoryItem, context.organization_id, item_id, lock=True)
    values = _item_values(context.organization_id, data)
    before = audit_snapshot(item, values)
    for field, value in values.items():
        setattr(item, field, value)
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError as error:
        raise ValidationError({"name": "Nazwa albo SKU jest już zajęte."}) from error
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_ITEM_UPDATED,
        "inventory_item",
        item.id,
        {"changes": field_changes(before, audit_snapshot(item, values))},
    )
    return item


# --- stany i ruchy ---------------------------------------------------------------------


def balances(
    *, location_id: UUID | None = None, holder_id: UUID | None = None, mine: bool = False
) -> list[InventoryBalance]:
    """Stany jednego miejsca: magazynu, wskazanej osoby albo własne.

    `mine` istnieje dla pracownika w terenie: swój zapas widzi każdy, kto ma
    `inventory.read`, bez prawa do prowadzenia magazynu.
    """
    context = _read_context()
    query = InventoryBalance.all_objects.filter(
        organization_id=context.organization_id
    ).select_related("item", "item__category", "location")
    if mine:
        query = query.filter(location__holder_id=context.actor_id)
    elif holder_id is not None:
        query = query.filter(location__holder_id=holder_id)
    elif location_id is not None:
        query = query.filter(location_id=location_id)
    else:
        query = query.filter(location__is_default=True)
    return list(query[:PAGE_LIMIT])


def movements(
    *, item_id: UUID | None = None, location_id: UUID | None = None
) -> QuerySet[InventoryMovement]:
    context = _read_context()
    query = InventoryMovement.all_objects.filter(
        organization_id=context.organization_id
    ).select_related("item", "location", "document", "created_by")
    if item_id:
        query = query.filter(item_id=item_id)
    if location_id:
        query = query.filter(location_id=location_id)
    return query


# --- dokumenty -------------------------------------------------------------------------


def list_documents(*, kind: str = "", status: str = "") -> list[StockDocument]:
    context = _read_context()
    query = StockDocument.all_objects.filter(
        organization_id=context.organization_id
    ).prefetch_related("lines__item")
    if kind:
        query = query.filter(kind=kind)
    if status:
        query = query.filter(status=status)
    return list(query[:PAGE_LIMIT])


def get_document(document_id: UUID) -> StockDocument:
    context = _read_context()
    return _get(StockDocument, context.organization_id, document_id)


def _location(organization_id: UUID, location_id: UUID | None) -> StockLocation | None:
    if location_id is None:
        return None
    return _get(StockLocation, organization_id, location_id)


def _write_lines(document: StockDocument, lines: Sequence[LineInput]) -> None:
    if not lines:
        raise ValidationError({"lines": "Dokument musi mieć co najmniej jedną pozycję."})
    StockDocumentLine.all_objects.filter(document=document).delete()
    for position, line in enumerate(lines, start=1):
        if line.quantity < 0 or (line.quantity == 0 and document.kind != DocumentKind.INW):
            raise ValidationError({"lines": "Ilość musi być dodatnia."})
        StockDocumentLine.all_objects.create(
            organization_id=document.organization_id,
            document=document,
            position=position,
            item=_get(InventoryItem, document.organization_id, line.item_id),
            quantity=line.quantity,
            unit_price_minor=line.unit_price_minor,
            note=line.note,
        )


def _document_values(organization_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "source_location_id" in data:
        values["source_location"] = _location(organization_id, data["source_location_id"])
    if "target_location_id" in data:
        values["target_location"] = _location(organization_id, data["target_location_id"])
    if "supplier_id" in data:
        values["supplier"] = (
            _get(Supplier, organization_id, data["supplier_id"]) if data["supplier_id"] else None
        )
    for field in ("counterparty", "note", "document_date"):
        if field in data:
            values[field] = data[field]
    return values


@transaction.atomic
def create_document(
    *, request: HttpRequest, kind: str, data: dict[str, Any], lines: Sequence[LineInput]
) -> StockDocument:
    context = _manage_context()
    document = StockDocument.all_objects.create(
        organization_id=context.organization_id,
        kind=kind,
        document_date=data.get("document_date") or timezone.localdate(),
        created_by_id=context.actor_id,
        **{
            key: value
            for key, value in _document_values(context.organization_id, data).items()
            if key != "document_date"
        },
    )
    _write_lines(document, lines)
    return document


@transaction.atomic
def update_document(
    *,
    request: HttpRequest,
    document_id: UUID,
    data: dict[str, Any],
    lines: Sequence[LineInput] | None,
) -> StockDocument:
    context = _manage_context()
    document = _get(StockDocument, context.organization_id, document_id, lock=True)
    if document.status != DocumentStatus.DRAFT:
        raise DocumentPosted
    for field, value in _document_values(context.organization_id, data).items():
        setattr(document, field, value)
    document.save()
    if lines is not None:
        _write_lines(document, lines)
    return document


@transaction.atomic
def post_document(*, request: HttpRequest, document_id: UUID) -> StockDocument:
    context = _manage_context()
    document = _get(StockDocument, context.organization_id, document_id, lock=True)
    if document.status != DocumentStatus.DRAFT:
        raise DocumentPosted
    _post(document, actor_id=context.actor_id, allow_negative=document.kind != DocumentKind.WZ)
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_DOCUMENT_POSTED,
        "stock_document",
        document.id,
        {"number": document.number, "kind": document.kind},
    )
    return document


@transaction.atomic
def correct_document(*, request: HttpRequest, document_id: UUID, note: str = "") -> StockDocument:
    """Korekta cofa ruchy zatwierdzonego dokumentu w całości — nowym dokumentem."""
    context = _manage_context()
    original = _get(StockDocument, context.organization_id, document_id, lock=True)
    correction = _correct(original, actor_id=context.actor_id, note=note)
    _audit(
        request,
        context.organization_id,
        OrganizationAuditAction.INVENTORY_DOCUMENT_CORRECTED,
        "stock_document",
        original.id,
        {"number": original.number, "correction": correction.number},
    )
    return correction


def _next_number(organization_id: UUID, kind: str, on: date) -> str:
    sequence, _ = DocumentSequence.all_objects.select_for_update().get_or_create(
        organization_id=organization_id, kind=kind, year=on.year
    )
    DocumentSequence.all_objects.filter(pk=sequence.pk).update(last=F("last") + 1)
    sequence.refresh_from_db(fields=["last"])
    return f"{kind}/{on.year}/{sequence.last:04d}"


def _post(document: StockDocument, *, actor_id: UUID, allow_negative: bool) -> None:
    """Wiersze stają się ruchami; stan i średnia przesuwają się w tej transakcji."""
    kind = document.kind
    if kind in (DocumentKind.PZ, DocumentKind.PW) and document.target_location_id is None:
        document.target_location = default_warehouse(document.organization_id)
    source = document.source_location_id if kind in NEEDS_SOURCE else None
    target = document.target_location_id if kind in NEEDS_TARGET else None
    if kind in NEEDS_SOURCE and source is None:
        raise ValidationError({"source_location_id": "Wskaż miejsce, z którego towar schodzi."})
    if kind in NEEDS_TARGET and target is None:
        raise ValidationError({"target_location_id": "Wskaż miejsce docelowe."})
    if kind == DocumentKind.MM and source == target:
        raise ValidationError({"target_location_id": "Przesunięcie wymaga dwóch różnych miejsc."})
    lines = list(StockDocumentLine.all_objects.filter(document=document))
    if not lines:
        raise ValidationError({"lines": "Dokument musi mieć co najmniej jedną pozycję."})
    for line in lines:
        item = InventoryItem.all_objects.select_for_update().get(pk=line.item_id)
        quantity = Decimal(line.quantity)
        if kind in PRICED_RECEIPTS:
            _average(item, quantity, line.unit_price_minor)
        if kind == DocumentKind.INW and target is not None:
            balance = _balance(document.organization_id, item.id, target, lock=True)
            delta = quantity - Decimal(balance.quantity)
            if delta != 0:
                _move(document, item, target, delta, actor_id)
            continue
        if source is not None:
            if not allow_negative:
                balance = _balance(document.organization_id, item.id, source, lock=True)
                if Decimal(balance.quantity) - Decimal(balance.reserved) < quantity:
                    raise StockShortage(f"Brakuje „{item.name}” na stanie.")
            _move(document, item, source, -quantity, actor_id)
        if target is not None:
            _move(document, item, target, quantity, actor_id, line.unit_price_minor)
    document.number = _next_number(document.organization_id, kind, document.document_date)
    document.status = DocumentStatus.POSTED
    document.posted_by_id = actor_id
    document.posted_at = timezone.now()
    document.save()


def _correct(original: StockDocument, *, actor_id: UUID, note: str) -> StockDocument:
    if original.status != DocumentStatus.POSTED or original.corrects_id is not None:
        raise ValidationError({
            "document": "Korygować można tylko zatwierdzony dokument, nie korektę."
        })
    if StockDocument.all_objects.filter(corrects=original).exists():
        raise DocumentAlreadyCorrected
    correction = StockDocument.all_objects.create(
        organization_id=original.organization_id,
        kind=original.kind,
        document_date=timezone.localdate(),
        source_location=original.source_location,
        target_location=original.target_location,
        supplier=original.supplier,
        counterparty=original.counterparty,
        corrects=original,
        source=original.source,
        source_reference=original.source_reference,
        note=note or f"Korekta {original.number}",
        created_by_id=actor_id,
    )
    for position, line in enumerate(
        StockDocumentLine.all_objects.filter(document=original), start=1
    ):
        StockDocumentLine.all_objects.create(
            organization_id=original.organization_id,
            document=correction,
            position=position,
            item_id=line.item_id,
            quantity=line.quantity,
            unit_price_minor=line.unit_price_minor,
            note=line.note,
        )
    # Reversing the ledger, not re-running the kind: an INW counted "10" must
    # undo the difference it booked, whatever the stock is today.
    for movement in InventoryMovement.all_objects.filter(document=original).select_related("item"):
        _move(
            correction,
            movement.item,
            movement.location_id,
            -Decimal(movement.quantity),
            actor_id,
            movement.unit_cost_minor,
        )
    correction.number = _next_number(
        original.organization_id, original.kind, correction.document_date
    )
    correction.status = DocumentStatus.POSTED
    correction.posted_by_id = actor_id
    correction.posted_at = timezone.now()
    correction.save()
    return correction


def _average(item: InventoryItem, quantity: Decimal, unit_price_minor: int | None) -> None:
    """Średnia ważona krocząca liczona ze stanu całej firmy (wszystkich miejsc)."""
    if unit_price_minor is None:
        return
    held = sum(
        (
            Decimal(value)
            for value in InventoryBalance.all_objects.filter(item=item).values_list(
                "quantity", flat=True
            )
        ),
        Decimal(0),
    )
    held = max(held, Decimal(0))
    after = held + quantity
    if after > 0:
        item.average_cost_minor = int(
            (held * item.average_cost_minor + quantity * unit_price_minor) / after
        )
        item.save(update_fields=["average_cost_minor", "updated_at"])


def _balance(
    organization_id: UUID, item_id: UUID, location_id: UUID, *, lock: bool = False
) -> InventoryBalance:
    query = InventoryBalance.all_objects.filter(
        organization_id=organization_id, item_id=item_id, location_id=location_id
    )
    balance = (query.select_for_update() if lock else query).first()
    if balance is not None:
        return balance
    try:
        with transaction.atomic():
            return InventoryBalance.all_objects.create(
                organization_id=organization_id, item_id=item_id, location_id=location_id
            )
    except IntegrityError:
        return query.select_for_update().get()


def _move(
    document: StockDocument,
    item: InventoryItem,
    location_id: UUID,
    quantity: Decimal,
    actor_id: UUID,
    unit_cost_minor: int | None = None,
) -> InventoryMovement:
    balance = _balance(document.organization_id, item.id, location_id, lock=True)
    InventoryBalance.all_objects.filter(pk=balance.pk).update(quantity=F("quantity") + quantity)
    return InventoryMovement.all_objects.create(
        organization_id=document.organization_id,
        item=item,
        location_id=location_id,
        document=document,
        kind=document.kind,
        quantity=quantity,
        unit_cost_minor=unit_cost_minor if unit_cost_minor is not None else item.average_cost_minor,
        created_by_id=actor_id,
    )


# --- operacje dla innych modułów (przez api.py) -----------------------------------------


def holder_stock(organization_id: UUID, holder_id: UUID) -> dict[UUID, Decimal]:
    """Ile czego ma przy sobie ten człowiek. Bramkę sprawdził już wołający."""
    return {
        balance.item_id: Decimal(balance.quantity)
        for balance in InventoryBalance.all_objects.filter(
            organization_id=organization_id, location__holder_id=holder_id
        )
    }


def available(organization_id: UUID, item_id: UUID, location_id: UUID) -> Decimal:
    balance = InventoryBalance.all_objects.filter(
        organization_id=organization_id, item_id=item_id, location_id=location_id
    ).first()
    return Decimal(0) if balance is None else Decimal(balance.quantity) - Decimal(balance.reserved)


@transaction.atomic
def consume(
    *,
    organization_id: UUID,
    holder_id: UUID,
    source: str,
    source_reference: str,
    lines: Iterable[tuple[UUID, Decimal]],
) -> StockDocument | None:
    """Zużycie przy pracy: jeden dokument RW na źródło, z zapasu osoby.

    Brak pokrycia nie zatrzymuje pracy — stan schodzi poniżej zera (decyzja z
    21.09). Powtórka tego samego źródła zwraca istniejący dokument: wpis
    zapisany dwa razy to jeden klocek.
    """
    existing = StockDocument.all_objects.filter(
        organization_id=organization_id,
        kind=DocumentKind.RW,
        source=source,
        source_reference=source_reference,
        corrects__isnull=True,
    ).first()
    if existing is not None:
        return existing
    rows = [
        LineInput(item_id=item_id, quantity=Decimal(quantity))
        for item_id, quantity in lines
        if Decimal(quantity) > 0
        and InventoryItem.all_objects.filter(organization_id=organization_id, id=item_id).exists()
    ]
    if not rows:
        return None
    ensure_catalog(organization_id)
    document = StockDocument.all_objects.create(
        organization_id=organization_id,
        kind=DocumentKind.RW,
        document_date=timezone.localdate(),
        source_location=person_location(organization_id, holder_id),
        source=source,
        source_reference=source_reference,
        created_by_id=holder_id,
    )
    _write_lines(document, rows)
    _post(document, actor_id=holder_id, allow_negative=True)
    return document


@transaction.atomic
def cancel_source(
    *, organization_id: UUID, actor_id: UUID, source: str, source_reference: str
) -> None:
    """Cofnięte źródło oddaje towar i zwalnia swoje rezerwacje.

    Każdy zatwierdzony, jeszcze nieskorygowany dokument źródła dostaje korektę;
    księga zostaje dopisywalna, a dzień pracy daje się odtworzyć ruch po ruchu.
    """
    for document in StockDocument.all_objects.select_for_update(of=("self",)).filter(
        organization_id=organization_id,
        source=source,
        source_reference=source_reference,
        status=DocumentStatus.POSTED,
        corrects__isnull=True,
        correction__isnull=True,
    ):
        _correct(document, actor_id=actor_id, note=f"Cofnięte: {source}")
    release_reservations(
        organization_id=organization_id, source=source, source_reference=source_reference
    )


@transaction.atomic
def reserve(
    *,
    organization_id: UUID,
    item_id: UUID,
    location_id: UUID,
    quantity: Decimal,
    source: str,
    source_reference: str,
) -> StockReservation:
    """Odkłada towar dla źródła; powtórka zmienia ilość tej samej rezerwacji."""
    reservation = (
        StockReservation.all_objects.select_for_update()
        .filter(
            organization_id=organization_id,
            source=source,
            source_reference=source_reference,
            item_id=item_id,
            location_id=location_id,
        )
        .first()
    )
    balance = _balance(organization_id, item_id, location_id, lock=True)
    previous = (
        Decimal(reservation.quantity)
        if reservation is not None and reservation.status == ReservationStatus.ACTIVE
        else Decimal(0)
    )
    if reservation is None:
        reservation = StockReservation.all_objects.create(
            organization_id=organization_id,
            item_id=item_id,
            location_id=location_id,
            quantity=quantity,
            source=source,
            source_reference=source_reference,
        )
    else:
        reservation.quantity = quantity
        reservation.status = ReservationStatus.ACTIVE
        reservation.save(update_fields=["quantity", "status", "updated_at"])
    InventoryBalance.all_objects.filter(pk=balance.pk).update(
        reserved=F("reserved") + quantity - previous
    )
    return reservation


@transaction.atomic
def release_reservations(*, organization_id: UUID, source: str, source_reference: str) -> int:
    released = 0
    for reservation in StockReservation.all_objects.select_for_update().filter(
        organization_id=organization_id,
        source=source,
        source_reference=source_reference,
        status=ReservationStatus.ACTIVE,
    ):
        InventoryBalance.all_objects.filter(
            organization_id=organization_id,
            item_id=reservation.item_id,
            location_id=reservation.location_id,
        ).update(reserved=F("reserved") - reservation.quantity)
        reservation.status = ReservationStatus.RELEASED
        reservation.save(update_fields=["status", "updated_at"])
        released += 1
    return released


# --- skróty v1: zatwierdzone dokumenty w jednym kroku ------------------------------------


@transaction.atomic
def receive(
    *, request: HttpRequest, item_id: UUID, quantity: Decimal, unit_cost_minor: int, note: str = ""
) -> StockDocument:
    """Przyjęcie do magazynu głównego z ceną z faktury (PZ)."""
    context = _manage_context()
    document = create_document(
        request=request,
        kind=DocumentKind.PZ,
        data={"target_location_id": default_warehouse(context.organization_id).id, "note": note},
        lines=[LineInput(item_id=item_id, quantity=quantity, unit_price_minor=unit_cost_minor)],
    )
    return post_document(request=request, document_id=document.id)


@transaction.atomic
def issue(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID, quantity: Decimal, note: str = ""
) -> StockDocument:
    """Wydanie osobie: przesunięcie z magazynu głównego do jej zapasu (MM)."""
    context = _manage_context()
    document = create_document(
        request=request,
        kind=DocumentKind.MM,
        data={
            "source_location_id": default_warehouse(context.organization_id).id,
            "target_location_id": person_location(context.organization_id, holder_id).id,
            "note": note,
        },
        lines=[LineInput(item_id=item_id, quantity=quantity)],
    )
    return post_document(request=request, document_id=document.id)


@transaction.atomic
def give_back(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID, quantity: Decimal, note: str = ""
) -> StockDocument:
    """Zwrot niewykorzystanego towaru do magazynu głównego (MM)."""
    context = _manage_context()
    document = create_document(
        request=request,
        kind=DocumentKind.MM,
        data={
            "source_location_id": person_location(context.organization_id, holder_id).id,
            "target_location_id": default_warehouse(context.organization_id).id,
            "note": note,
        },
        lines=[LineInput(item_id=item_id, quantity=quantity)],
    )
    return post_document(request=request, document_id=document.id)


@transaction.atomic
def adjust(
    *, request: HttpRequest, item_id: UUID, holder_id: UUID | None, quantity: Decimal, note: str
) -> StockDocument:
    """Korekta stanu z powodem: nadwyżka jako PW, ubytek jako RW."""
    context = _manage_context()
    if not note.strip():
        raise ValidationError({"note": "Korekta wymaga powodu."})
    if quantity == 0:
        raise ValidationError({"quantity": "Korekta musi coś zmienić."})
    location = (
        person_location(context.organization_id, holder_id)
        if holder_id is not None
        else default_warehouse(context.organization_id)
    )
    surplus = quantity > 0
    document = create_document(
        request=request,
        kind=DocumentKind.PW if surplus else DocumentKind.RW,
        data={
            ("target_location_id" if surplus else "source_location_id"): location.id,
            "note": note.strip(),
        },
        lines=[LineInput(item_id=item_id, quantity=abs(quantity))],
    )
    return post_document(request=request, document_id=document.id)


# --- pomocnicze ----------------------------------------------------------------------------


def _get[M: Model](model: type[M], organization_id: UUID, pk: UUID, *, lock: bool = False) -> M:
    query = cast(Any, model).all_objects.filter(organization_id=organization_id, pk=pk)
    found = (query.select_for_update() if lock else query).first()
    if found is None:
        raise NotFound("Nie ma tego w magazynie firmy.")
    return cast(M, found)


def _audit(
    request: HttpRequest,
    organization_id: UUID,
    action: str,
    target_type: str,
    target_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_audit(
        organization=_organization(organization_id),
        action=action,
        actor=cast(User, request.user),
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
