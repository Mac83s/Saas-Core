"""What the warehouse's numbers say (warehouse plan phase 10b).

Two reports, both for whoever runs the warehouse (`inventory.manage`: they
show what the company paid, answer 43a):

- **stock value** — what lies where now, quantity × the item's average cost,
  by item, category or place;
- **usage** — what went out in a period as consumption (RW) and sales to
  customers (WZ), at the cost each movement carried when it was posted, so a
  later delivery never rewrites the past. A correction is a movement the other
  way: it nets out in the period it was made in. Grouped by item, person,
  service, customer, or visit by visit (the cost of a visit).

The warehouse does not know visits. A module that takes stock for its work
(`consume` with a `source`) says what a source reference was — which visit,
service, customer and person — through `register_usage_source`; a document
without a source is the company's own (an adjustment, a loss).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.models import User

from .models import (
    DocumentKind,
    InventoryBalance,
    InventoryMovement,
    LocationKind,
    StockDocumentLine,
)
from .services import _manage_context

STOCK_GROUPS = ("item", "category", "location")
USAGE_GROUPS = ("item", "person", "service", "customer", "visit")
#: What counts as usage: consumption at the company's cost and sales to customers.
USAGE_KINDS = (DocumentKind.RW, DocumentKind.WZ)
#: The longest period one usage report covers: a protective limit, not a
#: business rule — a report over years would read every movement at once.
MAX_PERIOD_DAYS = 366


@dataclass(frozen=True, slots=True)
class UsageContext:
    """What a source says about one of its references (e.g. an appointment)."""

    #: Groups the documents of one visit; empty: not a visit.
    visit_id: str = ""
    visit_at: datetime | None = None
    service_id: str = ""
    service_name: str = ""
    customer_id: str = ""
    #: Empty when the reader may not see whose visit it was.
    customer_name: str = ""
    #: Who did the work, when the source knows (the visit's lead).
    person_user_id: UUID | None = None


#: source → (organization_id, references) → {reference: context}. Called in the
#: reader's tenant context: a source hides what this reader may not see.
UsageSource = Callable[[UUID, Sequence[str]], Mapping[str, UsageContext]]
_sources: dict[str, UsageSource] = {}


def register_usage_source(source: str, describe: UsageSource) -> None:
    """A module's word for the references it passes to `consume`; from `ready()`."""
    _sources[source] = describe


def _money(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _person(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.email


# --- stock value -----------------------------------------------------------------------


def stock_value(*, group: str = "item", location_id: UUID | None = None) -> dict[str, Any]:
    """What the stock is worth now: quantity × average cost, per currency.

    A negative stock counts as it is (the same arithmetic as a person's card):
    the total then says what the books say, and the row shows why.
    """
    context = _manage_context()
    if group not in STOCK_GROUPS:
        raise ValidationError({"group": ["Nieznane grupowanie."]}, code="invalid_choice")
    balances = InventoryBalance.all_objects.filter(
        organization_id=context.organization_id
    ).select_related("item", "item__category", "location", "location__holder")
    if location_id is not None:
        balances = balances.filter(location_id=location_id)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    totals: dict[str, Decimal] = {}
    for balance in balances:
        quantity = Decimal(balance.quantity)
        if quantity == 0:
            continue
        item = balance.item
        value = quantity * item.average_cost_minor
        totals[item.currency] = totals.get(item.currency, Decimal(0)) + value
        if group == "item":
            key, label = str(item.id), item.name
        elif group == "category":
            category = item.category
            key, label = (str(category.id), category.name) if category else ("", "")
        else:
            place = balance.location
            key = str(place.id)
            label = _person(place.holder) if place.holder is not None else place.name
        row = rows.setdefault(
            (key, item.currency),
            {
                "key": key,
                "name": label,
                "kind": balance.location.kind if group == "location" else "",
                "quantity": Decimal(0) if group == "item" else None,
                "unit": item.unit if group == "item" else "",
                "average_cost_minor": item.average_cost_minor if group == "item" else None,
                "value": Decimal(0),
                "currency": item.currency,
            },
        )
        row["value"] += value
        if group == "item":
            row["quantity"] += quantity
    items = sorted(rows.values(), key=lambda row: (-row["value"], row["name"]))
    for row in items:
        row["value_minor"] = _money(row.pop("value"))
    return {
        "group": group,
        "rows": items,
        "totals": [
            {"currency": currency, "value_minor": _money(value)}
            for currency, value in sorted(totals.items())
        ],
    }


# --- usage -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Row:
    key: str
    label: str
    currency: str
    cost: Decimal = Decimal(0)
    sold: Decimal = Decimal(0)
    quantity: Decimal = Decimal(0)
    unit: str = ""
    at: datetime | None = None
    #: The visit's service and customer, for a row of the visit list.
    detail: dict[str, str] = field(default_factory=dict)
    documents: set[UUID] = field(default_factory=set)


def _contexts(organization_id: UUID, documents: Sequence[Any]) -> dict[UUID, UsageContext]:
    """Each document's context, asked of its source once per source."""
    by_source: dict[str, set[str]] = {}
    for document in documents:
        if document.source in _sources and document.source_reference:
            by_source.setdefault(document.source, set()).add(document.source_reference)
    known = {
        source: _sources[source](organization_id, sorted(references))
        for source, references in by_source.items()
    }
    return {
        document.id: known.get(document.source, {}).get(document.source_reference, UsageContext())
        for document in documents
    }


def usage(
    *,
    first: date,
    last: date,
    group: str = "item",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """What went out between two days of the company (both included), at the
    cost of each movement; `sold_minor` is what sales to customers were
    priced at. Rows from the biggest cost, a visit list from the latest."""
    context = _manage_context()
    if group not in USAGE_GROUPS:
        raise ValidationError({"group": ["Nieznane grupowanie."]}, code="invalid_choice")
    if last < first:
        raise ValidationError({"to": ["Koniec okresu jest przed początkiem."]}, code="period")
    if (last - first).days >= MAX_PERIOD_DAYS:
        raise ValidationError(
            {"to": [f"Okres raportu to najwyżej {MAX_PERIOD_DAYS} dni."]}, code="period_too_long"
        )
    moves = list(
        InventoryMovement.all_objects.filter(
            organization_id=context.organization_id,
            kind__in=USAGE_KINDS,
            document__document_date__gte=first,
            document__document_date__lte=last,
        ).select_related("item", "document", "location", "location__holder", "created_by")
    )
    documents = list({move.document_id: move.document for move in moves}.values())
    contexts = _contexts(context.organization_id, documents)
    people = _people(moves, contexts)
    #: What each sale document was priced at, per item: its lines' prices.
    prices = _sale_prices([document.id for document in documents if document.kind == "WZ"])

    rows: dict[tuple[str, str], _Row] = {}
    totals: dict[str, list[Decimal]] = {}
    for move in moves:
        known = contexts[move.document_id]
        out = -Decimal(move.quantity)  # a correction comes back: negative usage
        cost = out * move.unit_cost_minor
        sold = out * prices.get((move.document_id, move.item_id), 0)
        currency = move.item.currency
        key, label, extra = _group_of(group, move, known, people)
        row = rows.setdefault((key, currency), _Row(key=key, label=label, currency=currency))
        row.cost += cost
        row.sold += sold
        row.documents.add(move.document_id)
        if group == "item":
            row.quantity += out
            row.unit = move.item.unit
        if group == "visit":
            row.at = known.visit_at
            row.detail = extra
        total = totals.setdefault(currency, [Decimal(0), Decimal(0)])
        total[0] += cost
        total[1] += sold
    ordered = sorted(
        rows.values(),
        key=(
            (lambda row: (-(row.at.timestamp() if row.at else 0), row.label))
            if group == "visit"
            else (lambda row: (-row.cost, row.label))
        ),
    )
    start = (page - 1) * page_size
    return {
        "group": group,
        "from": first,
        "to": last,
        "total": len(ordered),
        "page": page,
        "page_size": page_size,
        "rows": [
            {
                "key": row.key,
                "name": row.label,
                "quantity": row.quantity if group == "item" else None,
                "unit": row.unit,
                "cost_minor": _money(row.cost),
                "sold_minor": _money(row.sold),
                "currency": row.currency,
                "documents": len(row.documents),
                "at": row.at,
                "service_name": row.detail.get("service_name", ""),
                "customer_name": row.detail.get("customer_name", ""),
                "person_name": row.detail.get("person_name", ""),
            }
            for row in ordered[start : start + page_size]
        ],
        "totals": [
            {"currency": currency, "cost_minor": _money(cost), "sold_minor": _money(sold)}
            for currency, (cost, sold) in sorted(totals.items())
        ],
    }


def _sale_prices(document_ids: Sequence[UUID]) -> dict[tuple[UUID, UUID], int]:
    """(sale document, item) → the unit price on its line. A correction of a
    sale carries the original's lines, so it gives the same price back."""
    return {
        (line.document_id, line.item_id): line.unit_price_minor or 0
        for line in StockDocumentLine.all_objects.filter(document_id__in=list(document_ids))
    }


def _worker(move: InventoryMovement, known: UsageContext) -> UUID:
    """Whose usage it is: the visit's lead when the source knows, else whose
    stock it left, else whoever posted the document."""
    if known.person_user_id is not None:
        return known.person_user_id
    if move.location.kind == LocationKind.PERSON and move.location.holder_id is not None:
        return move.location.holder_id
    return move.created_by_id


def _people(
    moves: Sequence[InventoryMovement], contexts: Mapping[UUID, UsageContext]
) -> dict[UUID, str]:
    ids = {_worker(move, contexts[move.document_id]) for move in moves}
    return {user.id: _person(user) for user in User.objects.filter(pk__in=ids)}


def _group_of(
    group: str, move: InventoryMovement, known: UsageContext, people: Mapping[UUID, str]
) -> tuple[str, str, dict[str, str]]:
    """The row a movement belongs to: (key, label, the visit's details). An
    empty key is the report's „without …” row; the panel words it."""
    if group == "item":
        return str(move.item_id), move.item.name, {}
    if group == "person":
        worker = _worker(move, known)
        return str(worker), people.get(worker, ""), {}
    if group == "service":
        return known.service_id, known.service_name, {}
    if group == "customer":
        return known.customer_id, known.customer_name, {}
    return (
        known.visit_id,
        known.service_name,
        {
            "service_name": known.service_name,
            "customer_name": known.customer_name,
            "person_name": people.get(_worker(move, known), "") if known.visit_id else "",
        },
    )
