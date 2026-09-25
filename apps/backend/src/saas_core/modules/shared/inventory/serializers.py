from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import DocumentKind, DocumentStatus, ItemUnit, LocationKind, VatRate


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=12, decimal_places=3, **kwargs)


class InventoryCategorySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    key = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=120)
    #: Startowa kategoria produktu: można zmienić nazwę, nie usunąć.
    system = serializers.BooleanField(read_only=True)


class StockLocationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    kind = serializers.ChoiceField(choices=LocationKind.choices, read_only=True)
    name = serializers.CharField(max_length=120)
    holder_id = serializers.UUIDField(read_only=True, allow_null=True)
    #: Czyj to zapas — z konta osoby, nie z magazynu.
    holder_name = serializers.SerializerMethodField()
    is_default = serializers.BooleanField(read_only=True)
    active = serializers.BooleanField(required=False)

    def get_holder_name(self, location: Any) -> str | None:
        holder = location.holder
        if holder is None:
            return None
        return " ".join(filter(None, [holder.first_name, holder.last_name])) or holder.email


class SupplierSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=160)
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class InventoryItemSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=120)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True)
    ean = serializers.CharField(max_length=14, required=False, allow_blank=True)
    category_id = serializers.UUIDField(read_only=True, allow_null=True)
    #: Klucz kategorii — produkt rozpoznaje po nim swoje pozycje.
    category = serializers.CharField(
        source="category.key", read_only=True, allow_null=True, default=None
    )
    category_name = serializers.CharField(
        source="category.name", read_only=True, allow_null=True, default=None
    )
    unit = serializers.ChoiceField(choices=ItemUnit.choices)
    minimum_quantity = _quantity()
    #: Średnia ważona cena zakupu w groszach; rozchód wycenia się po niej.
    average_cost_minor = serializers.IntegerField(read_only=True)
    sale_price_net_minor = serializers.IntegerField(allow_null=True, required=False)
    vat_rate = serializers.ChoiceField(choices=VatRate.choices)
    currency = serializers.CharField(read_only=True)
    #: Pozycja standardowa produktu: można ją zmienić i ukryć, nie usunąć.
    system_key = serializers.CharField(read_only=True)
    #: Partie i daty ważności: przyjęcie podaje partię, rozchód bierze je wg ważności.
    tracks_lots = serializers.BooleanField()
    active = serializers.BooleanField()
    notes = serializers.CharField(allow_blank=True)


class InventoryItemInputSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True)
    ean = serializers.CharField(max_length=14, required=False, allow_blank=True)
    #: Id kategorii albo jej klucz.
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    unit = serializers.ChoiceField(choices=ItemUnit.choices, required=False)
    minimum_quantity = _quantity(required=False, min_value=0)
    sale_price_net_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    vat_rate = serializers.ChoiceField(choices=VatRate.choices, required=False)
    tracks_lots = serializers.BooleanField(required=False)
    active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


LOT_STATUS = (
    ("expired", "Po terminie"),
    ("expiring", "Kończy się ważność"),
    ("ok", "Ważna"),
    ("no_date", "Bez daty ważności"),
)


class InventoryBalanceSerializer(serializers.Serializer[Any]):
    """Ile czego leży w jednym miejscu; dostępne = stan − zarezerwowane."""

    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    sku = serializers.CharField(source="item.sku")
    category = serializers.CharField(source="item.category.key", allow_null=True, default=None)
    category_name = serializers.CharField(
        source="item.category.name", allow_null=True, default=None
    )
    unit = serializers.CharField(source="item.unit")
    location_id = serializers.UUIDField()
    location_name = serializers.CharField(source="location.name")
    holder_id = serializers.UUIDField(source="location.holder_id", allow_null=True)
    quantity = _quantity()
    reserved = _quantity()
    available = serializers.SerializerMethodField()
    minimum_quantity = _quantity(source="item.minimum_quantity")
    tracks_lots = serializers.BooleanField(source="item.tracks_lots")
    #: Najbliższy termin partii, które tu leżą — i co z niego wynika.
    nearest_expiry = serializers.SerializerMethodField()
    lot_status = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField()

    def get_available(self, balance: Any) -> str:
        return f"{balance.quantity - balance.reserved:.3f}"

    def _nearest(self, balance: Any) -> dict[str, Any] | None:
        nearest: dict[tuple[Any, Any], dict[str, Any]] = self.context.get("nearest", {})
        return nearest.get((balance.item_id, balance.location_id))

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_nearest_expiry(self, balance: Any) -> Any:
        found = self._nearest(balance)
        return found["expires_on"] if found else None

    @extend_schema_field(serializers.ChoiceField(choices=LOT_STATUS, allow_null=True))
    def get_lot_status(self, balance: Any) -> str | None:
        found = self._nearest(balance)
        return found["status"] if found else None


class InventoryLotStockSerializer(serializers.Serializer[Any]):
    """Partia, która gdzieś leży: ile i jak z jej ważnością."""

    lot_id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    item_name = serializers.CharField()
    unit = serializers.CharField()
    number = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    status = serializers.ChoiceField(choices=LOT_STATUS)
    location_id = serializers.UUIDField()
    location_name = serializers.CharField()
    holder_id = serializers.UUIDField(allow_null=True)
    quantity = _quantity()


class InventoryMovementSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    location_id = serializers.UUIDField()
    location_name = serializers.CharField(source="location.name")
    document_id = serializers.UUIDField()
    document_number = serializers.CharField(source="document.number")
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    quantity = _quantity()
    unit_cost_minor = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class MovedLotSerializer(serializers.Serializer[Any]):
    number = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    quantity = _quantity()


class StockDocumentLineSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    quantity = _quantity()
    unit_price_minor = serializers.IntegerField(allow_null=True)
    #: Partia wiersza: przyjęta albo wskazana do rozchodu.
    lot_id = serializers.UUIDField(allow_null=True)
    lot_number = serializers.CharField(source="lot.number", allow_null=True, default=None)
    expires_on = serializers.DateField(source="lot.expires_on", allow_null=True, default=None)
    #: Co naprawdę zeszło albo przybyło — partie z ruchów zatwierdzonego dokumentu.
    moved_lots = serializers.SerializerMethodField()
    note = serializers.CharField()

    @extend_schema_field(MovedLotSerializer(many=True))
    def get_moved_lots(self, line: Any) -> list[dict[str, Any]]:
        document = line.document
        place = document.source_location_id or document.target_location_id
        totals: dict[Any, dict[str, Any]] = {}
        for movement in document.movements.all():
            if movement.item_id != line.item_id or movement.lot is None:
                continue
            if movement.location_id != place:
                continue
            lot = movement.lot
            row = totals.setdefault(
                movement.lot_id,
                {"number": lot.number, "expires_on": lot.expires_on, "quantity": 0},
            )
            row["quantity"] += abs(movement.quantity)
        return list(totals.values())


class StockDocumentLineInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_price_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    #: Partia do rozchodu; bez niej rozchód bierze partie wg ważności.
    lot_id = serializers.UUIDField(required=False, allow_null=True)
    #: Numer partii — przyjęcie i inwentaryzacja zakładają nową.
    lot_number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    expires_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class StockDocumentSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    status = serializers.ChoiceField(choices=DocumentStatus.choices)
    #: Pusty do zatwierdzenia; potem `RODZAJ/RRRR/NNNN`.
    number = serializers.CharField()
    document_date = serializers.DateField()
    source_location_id = serializers.UUIDField(allow_null=True)
    target_location_id = serializers.UUIDField(allow_null=True)
    supplier_id = serializers.UUIDField(allow_null=True)
    counterparty = serializers.CharField()
    corrects_id = serializers.UUIDField(allow_null=True)
    source = serializers.CharField()  # type: ignore[assignment]
    source_reference = serializers.CharField()
    note = serializers.CharField()
    created_by_id = serializers.UUIDField()
    posted_at = serializers.DateTimeField(allow_null=True)
    lines = StockDocumentLineSerializer(many=True, source="lines.all")


class StockDocumentInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    document_date = serializers.DateField(required=False)
    source_location_id = serializers.UUIDField(required=False, allow_null=True)
    target_location_id = serializers.UUIDField(required=False, allow_null=True)
    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    counterparty = serializers.CharField(max_length=160, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    lines = StockDocumentLineInputSerializer(many=True, required=False)


class StockDocumentCorrectionSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryReceiptInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_cost_minor = serializers.IntegerField(min_value=0, default=0)
    lot_number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    expires_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryIssueInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryAdjustInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    quantity = _quantity()
    note = serializers.CharField(max_length=240)
