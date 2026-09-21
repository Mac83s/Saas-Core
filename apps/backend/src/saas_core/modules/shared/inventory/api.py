"""Publiczne wejście magazynu dla innych modułów (ADR-049).

Wertykał zdejmuje materiał przez `consume`, oddaje go z cofniętego wpisu
przez `release`, a stan czyta przez `holder_stock` —
modeli nie importuje, bo to, co magazyn uważa za stan, ma zostać jego sprawą.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.http import HttpRequest

from .models import InventoryBalance, InventoryItem, ItemCategory, MovementKind
from .permissions import INVENTORY_MANAGE, INVENTORY_READ
from .services import INVENTORY_ENABLED, consume, holder_stock, release

__all__ = [
    "INVENTORY_ENABLED",
    "INVENTORY_MANAGE",
    "INVENTORY_READ",
    "Decimal",
    "HttpRequest",
    "InventoryBalance",
    "InventoryItem",
    "ItemCategory",
    "MovementKind",
    "UUID",
    "consume",
    "holder_stock",
    "release",
]
