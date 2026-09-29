"""The warehouse's facts about a person (team plan, phase 5, board 4).

What a person took from the warehouse, used and gave back, valued at the cost
each movement carried when it was posted, and what they hold now. Registered
with booking's staff facts only where booking is composed; the warehouse
alone has no people's cards. Warehouse phase 10 reads the same numbers.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from rest_framework.exceptions import APIException

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    DocumentKind,
    InventoryBalance,
    InventoryMovement,
    LocationKind,
    StockLocation,
)
from .permissions import INVENTORY_MANAGE, INVENTORY_READ

if TYPE_CHECKING:
    from saas_core.modules.shared.booking.facts import Event, Metric, Period, StaffSubject

INVENTORY_ENABLED = "inventory.enabled"


def _entitled(subject: StaffSubject) -> bool:
    """The warehouse is in the plan and the viewer may read this person's stock."""
    try:
        authorize_entitled(
            INVENTORY_READ if subject.own else INVENTORY_MANAGE,
            INVENTORY_ENABLED,
            operation=FeatureOperation.READ,
        )
    except APIException:
        return False
    return True


def _place(subject: StaffSubject) -> StockLocation | None:
    """The person's own stock; none until somebody gives them something."""
    return StockLocation.all_objects.filter(
        organization_id=subject.organization_id,
        kind=LocationKind.PERSON,
        holder_id=subject.user_id,
    ).first()


def _money(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _moves(place: StockLocation, span: Period) -> list[InventoryMovement]:
    return list(
        InventoryMovement.all_objects.filter(
            organization_id=place.organization_id,
            location=place,
            document__document_date__gte=span.first,
            document__document_date__lte=span.last,
        ).select_related("document", "item")
    )


def _kind(move: InventoryMovement) -> str:
    if move.kind == DocumentKind.MM:
        return "taken" if move.quantity > 0 else "returned"
    if move.kind == DocumentKind.RW and move.quantity < 0:
        return "used"
    return "other"


def metrics(subject: StaffSubject, span: Period) -> list[Metric]:
    from saas_core.modules.shared.booking.facts import Metric  # noqa: PLC0415

    # A person without an account holds no stock; no warehouse, no group.
    if subject.user_id is None or not _entitled(subject):
        return []
    place = _place(subject)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for move in _moves(place, span) if place else []:
        totals[_kind(move)] += abs(move.quantity) * move.unit_cost_minor
    held = sum(
        (
            balance.quantity * balance.item.average_cost_minor
            for balance in InventoryBalance.all_objects.filter(
                organization_id=subject.organization_id, location=place
            ).select_related("item")
        )
        if place
        else (),
        Decimal(0),
    )
    return [
        Metric("taken", _money(totals["taken"]), unit="money"),
        Metric("used", _money(totals["used"]), unit="money"),
        Metric("returned", _money(totals["returned"]), unit="money"),
        # Today's stock, whatever the period: a number without a comparison.
        Metric("on_hand", _money(held), unit="money", comparable=False),
    ]


def history(subject: StaffSubject, span: Period) -> list[Event]:
    from saas_core.modules.shared.booking.facts import Event  # noqa: PLC0415

    if subject.user_id is None or not _entitled(subject):
        return []
    place = _place(subject)
    if place is None:
        return []
    documents: dict[Any, list[InventoryMovement]] = defaultdict(list)
    for move in _moves(place, span):
        documents[move.document].append(move)
    events = []
    for document, moves in documents.items():
        kind = _kind(moves[0])
        events.append(
            Event(
                document.posted_at or document.created_at,
                kind,
                {
                    "number": document.number,
                    "lines": [
                        {
                            "name": move.item.name,
                            "quantity": str(abs(move.quantity).normalize()),
                            "unit": move.item.unit,
                        }
                        for move in moves
                    ],
                },
                value=_money(
                    sum((abs(move.quantity) * move.unit_cost_minor for move in moves), Decimal(0))
                ),
                unit="money",
            )
        )
    return events


def register() -> None:
    from saas_core.modules.shared.booking.api import (  # noqa: PLC0415
        StaffFacts,
        register_staff_facts,
    )

    register_staff_facts(
        StaffFacts(
            "inventory",
            metrics,
            history,
            own_permission=INVENTORY_READ,
            others_permission=INVENTORY_MANAGE,
            order=50,
        )
    )
