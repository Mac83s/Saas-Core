"""Produkty z magazynu przy wizycie (ADR-055, faza 6 planu magazynu).

Usługa niesie listę produktów; wizyta dostaje jej kopię (albo listę wpisaną
ręcznie) i rezerwuje stan w magazynie głównym od potwierdzenia. Zakończenie
wizyty zamienia rezerwację w dokumenty: RW dla zużycia na koszt firmy, WZ dla
towaru sprzedanego klientowi. Odwołanie zwalnia rezerwację.

Magazyn nie jest zależnością rezerwacji: bez modułu w profilu wszystko tutaj
milczy, a import jego API jest leniwy.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import ValidationError

from saas_core.modules.shared.billing.authorization import authorize_entitled

#: Źródło rezerwacji i dokumentów magazynu wystawionych za wizytę.
SOURCE = "booking.appointment"
CONSUME = "consume"
SALE = "sale"
MODES = (CONSUME, SALE)
MAX_LINES = 50


def enabled() -> bool:
    return "shared.inventory" in settings.ACTIVE_MODULES


def authorize_change() -> None:
    """Kto zmienia produkty wizyty, musi móc brać z magazynu."""
    if not enabled():
        raise ValidationError({"materials": "Magazyn nie jest dostępny w tym produkcie."})
    from saas_core.modules.shared.inventory.api import (  # noqa: PLC0415
        INVENTORY_ENABLED,
        INVENTORY_USE,
    )

    authorize_entitled(INVENTORY_USE, INVENTORY_ENABLED)


def normalize(
    organization_id: UUID, raw: list[dict[str, Any]], *, strict: bool = True
) -> list[dict[str, Any]]:
    """Linie w jednej postaci, z nazwą i ceną sprzedaży z chwili zapisu.

    Pozycja spoza katalogu firmy (albo ukryta), którą ktoś właśnie wybrał, jest
    błędem wejścia — ma się dowiedzieć, że jej nie ma. Kopia z usługi
    (`strict=False`) pomija takie pozycje: produkt ukryty po ustawieniu usługi
    nie może blokować klientowi rezerwacji.
    """
    if not raw:
        return []
    if not enabled():
        if not strict:
            return []
        raise ValidationError({"materials": "Magazyn nie jest dostępny w tym produkcie."})
    if len(raw) > MAX_LINES:
        raise ValidationError({"materials": f"Najwyżej {MAX_LINES} pozycji."})
    from saas_core.modules.shared.inventory.api import describe_items  # noqa: PLC0415

    ids = []
    for row in raw:
        try:
            ids.append(UUID(str(row["item_id"])))
        except (KeyError, ValueError) as error:
            raise ValidationError({"materials": "Każda pozycja potrzebuje produktu."}) from error
    known = describe_items(organization_id, ids)
    lines = []
    for item_id, row in zip(ids, raw, strict=True):
        try:
            quantity = Decimal(str(row["quantity"]))
        except (KeyError, InvalidOperation) as error:
            raise ValidationError({"materials": "Podaj ilość."}) from error
        mode = row.get("mode") or CONSUME
        if quantity <= 0 or not quantity.is_finite():
            raise ValidationError({"materials": "Ilość musi być dodatnia."})
        if mode not in MODES:
            raise ValidationError({"materials": "Produkt jest zużyciem albo sprzedażą."})
        item = known.get(item_id)
        if item is None:
            if not strict:
                continue
            raise ValidationError({"materials": "Nie ma takiego produktu w magazynie firmy."})
        lines.append({
            "item_id": str(item_id),
            "name": item["name"],
            "unit": item["unit"],
            "quantity": f"{quantity.quantize(Decimal('0.001'))}",
            "mode": mode,
            # Price of the sale at the moment it was agreed; null for usage.
            "unit_price_minor": item["sale_price_net_minor"] if mode == SALE else None,
            "currency": item["currency"],
        })
    return lines


def _totals(lines: list[dict[str, Any]], mode: str | None = None) -> dict[UUID, Decimal]:
    totals: dict[UUID, Decimal] = defaultdict(Decimal)
    for line in lines:
        if mode is None or line["mode"] == mode:
            totals[UUID(line["item_id"])] += Decimal(line["quantity"])
    return totals


def reserve(organization_id: UUID, appointment_id: UUID, lines: list[dict[str, Any]]) -> None:
    """Odkłada towar dla wizyty w magazynie głównym; poprzednią rezerwację
    tej wizyty zastępuje w całości."""
    if not enabled():
        return
    from saas_core.modules.shared.inventory import api  # noqa: PLC0415

    reference = str(appointment_id)
    api.release_reservations(
        organization_id=organization_id, source=SOURCE, source_reference=reference
    )
    if not lines:
        return
    # ponytail: the main warehouse holds what visits use; a per-location or
    # per-person source comes when a business asks for it.
    warehouse = api.default_warehouse(organization_id)
    for item_id, quantity in _totals(lines).items():
        api.reserve(
            organization_id=organization_id,
            item_id=item_id,
            location_id=warehouse.id,
            quantity=quantity,
            source=SOURCE,
            source_reference=reference,
        )


def release(organization_id: UUID, appointment_id: UUID) -> None:
    if not enabled():
        return
    from saas_core.modules.shared.inventory import api  # noqa: PLC0415

    api.release_reservations(
        organization_id=organization_id, source=SOURCE, source_reference=str(appointment_id)
    )


def settle(
    organization_id: UUID, appointment_id: UUID, lines: list[dict[str, Any]], actor_id: UUID
) -> None:
    """Zakończona wizyta: rezerwacja schodzi ze stanu dokumentami RW i WZ."""
    if not enabled() or not lines:
        return
    from saas_core.modules.shared.inventory import api  # noqa: PLC0415

    reference = str(appointment_id)
    api.release_reservations(
        organization_id=organization_id, source=SOURCE, source_reference=reference
    )
    warehouse = api.default_warehouse(organization_id)
    for mode, kind in ((CONSUME, "RW"), (SALE, "WZ")):
        totals = _totals(lines, mode)
        if totals:
            api.consume(
                organization_id=organization_id,
                source=SOURCE,
                source_reference=reference,
                lines=list(totals.items()),
                location_id=warehouse.id,
                actor_id=actor_id,
                kind=kind,
            )
