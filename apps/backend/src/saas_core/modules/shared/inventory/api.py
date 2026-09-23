"""Publiczne wejście magazynu dla innych modułów (ADR-049, ADR-055).

Moduł zużywa towar przez `consume` (jeden dokument RW na źródło), cofa go przez
`cancel_source`, odkłada przez `reserve` / `release_reservations`, a stan czyta
przez `holder_stock` i `available`. Modeli nie importuje — to, co magazyn uważa
za stan, zostaje jego sprawą. Bramkę uprawnień sprawdza wołający.
"""

from __future__ import annotations

from .permissions import INVENTORY_MANAGE, INVENTORY_READ, INVENTORY_USE
from .services import (
    INVENTORY_ENABLED,
    StockShortage,
    available,
    cancel_source,
    consume,
    default_warehouse,
    holder_stock,
    person_location,
    release_reservations,
    reserve,
)

__all__ = [
    "INVENTORY_ENABLED",
    "INVENTORY_MANAGE",
    "INVENTORY_READ",
    "INVENTORY_USE",
    "StockShortage",
    "available",
    "cancel_source",
    "consume",
    "default_warehouse",
    "holder_stock",
    "person_location",
    "release_reservations",
    "reserve",
]
