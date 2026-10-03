"""What the company's history calls the warehouse's objects (UX-055)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target

from .models import InventoryItem, StockDocument


def _documents(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        document.id: HistoryTarget(label=document.number, href="/panel/inventory/documents")
        for document in StockDocument.all_objects.filter(
            organization_id=organization_id, pk__in=ids
        )
        if document.number
    }


def _items(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        item.id: HistoryTarget(label=item.name, href="/panel/inventory/items")
        for item in InventoryItem.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("stock_document", _documents)
    register_history_target("inventory_item", _items)
