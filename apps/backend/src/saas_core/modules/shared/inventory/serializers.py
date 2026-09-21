from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .models import ItemCategory, ItemUnit, MovementKind


class InventoryItemSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=120)
    category = serializers.ChoiceField(choices=ItemCategory.choices)
    unit = serializers.ChoiceField(choices=ItemUnit.choices)
    minimum_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    #: Średnia ważona cena zakupu w groszach; rozchód wycenia się po niej.
    average_cost_minor = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class InventoryItemInputSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    category = serializers.ChoiceField(choices=ItemCategory.choices, required=False)
    unit = serializers.ChoiceField(choices=ItemUnit.choices, required=False)
    minimum_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=0
    )
    active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class InventoryBalanceSerializer(serializers.Serializer[Any]):
    """Ile czego leży w jednym miejscu; `holder_id` puste to magazyn firmy."""

    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    category = serializers.CharField(source="item.category")
    unit = serializers.CharField(source="item.unit")
    holder_id = serializers.UUIDField(allow_null=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    minimum_quantity = serializers.DecimalField(
        source="item.minimum_quantity", max_digits=12, decimal_places=2
    )
    updated_at = serializers.DateTimeField()


class InventoryMovementSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    kind = serializers.ChoiceField(choices=MovementKind.choices)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    holder_id = serializers.UUIDField(allow_null=True)
    unit_cost_minor = serializers.IntegerField()
    source = serializers.CharField()  # type: ignore[assignment]
    source_reference = serializers.CharField()
    note = serializers.CharField()
    created_at = serializers.DateTimeField()


class InventoryReceiptInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    unit_cost_minor = serializers.IntegerField(min_value=0, default=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryIssueInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryAdjustInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    note = serializers.CharField(max_length=240)
