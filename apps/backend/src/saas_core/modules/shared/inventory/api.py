"""Publiczne wejście magazynu dla innych modułów (ADR-049, ADR-055).

Moduł zużywa towar przez `consume` (jeden dokument RW albo WZ na źródło), cofa go przez
`cancel_source`, odkłada przez `reserve` / `release_reservations`, a stan czyta
przez `holder_stock` i `available`; które partie zeszły dla źródła, mówi
`source_lots`, a skąd brać produkty wizyty — `visit_place`. Czym było źródło
(wizyta, usługa, klient, osoba), moduł mówi raportom przez `register_usage_source`. Modeli nie
importuje — to, co magazyn uważa za stan, zostaje jego sprawą. Bramkę uprawnień
sprawdza wołający.
"""

from __future__ import annotations

from .permissions import INVENTORY_MANAGE, INVENTORY_READ, INVENTORY_USE
from .reports import UsageContext, register_usage_source
from .services import (
    INVENTORY_ENABLED,
    StockShortage,
    available,
    cancel_source,
    consume,
    default_warehouse,
    describe_items,
    holder_stock,
    lot_status,
    organization_today,
    person_location,
    release_reservations,
    reserve,
    source_lots,
    visit_place,
)

__all__ = [
    "INVENTORY_ENABLED",
    "INVENTORY_MANAGE",
    "INVENTORY_READ",
    "INVENTORY_USE",
    "StockShortage",
    "UsageContext",
    "available",
    "cancel_source",
    "consume",
    "default_warehouse",
    "describe_items",
    "holder_stock",
    "lot_status",
    "organization_today",
    "person_location",
    "register_usage_source",
    "release_reservations",
    "reserve",
    "source_lots",
    "visit_place",
]
