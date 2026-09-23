from __future__ import annotations

from typing import Any

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
    active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


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
    updated_at = serializers.DateTimeField()

    def get_available(self, balance: Any) -> str:
        return f"{balance.quantity - balance.reserved:.3f}"


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


class StockDocumentLineSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    quantity = _quantity()
    unit_price_minor = serializers.IntegerField(allow_null=True)
    note = serializers.CharField()


class StockDocumentLineInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_price_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
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
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_cost_minor = serializers.IntegerField(min_value=0, default=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryIssueInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryAdjustInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    quantity = _quantity()
    note = serializers.CharField(max_length=240)
