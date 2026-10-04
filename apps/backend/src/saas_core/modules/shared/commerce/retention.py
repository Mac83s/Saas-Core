"""How long an order names its buyer (ADR-073, slice 4i).

An order money was taken for is the company's sales record. It keeps its
buyer — the name, the e-mail, the phone — for `BUYER_RETENTION_YEARS` full
calendar years after the year its ledger was last written to, counted in the
company's time zone: a payment of June 2026 keeps the buyer until the end of
31 December 2031. An order nobody paid for keeps nothing.

Two things follow, and both ask the same question (`held_orders`):

- taking a customer out strips the customer and the visits and leaves the
  buyer on these orders (`orders.strip_buyer`) — by hand from the panel and
  by the company's own removal of customers after a time alike (the owner's
  answer of 04.10: the run keeps no more than a person's click does);
- when the period ends, the buyer left on an order of a customer who is
  already anonymised is removed by the nightly privacy run (`erase_buyers`).

What a strip would leave is read beforehand by `kept_of` — for the window
that asks before a removal by hand, and for the preview of the company's
retention setting.

Every write to a ledger locks its order first, so whoever decides here locks
the orders and reads the ledger afterwards: a payment in flight is waited for
and seen, one that starts later waits and finds the decision made.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import F, Max, OuterRef, Q, QuerySet, Subquery, Sum
from django.utils import timezone

from saas_core.modules.core.organizations.api import RetentionRule, RetentionSweep
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.customers.api import Customer, Kept

from .models import LedgerEntry, LedgerEntryKind, Order

#: Full calendar years an order money was taken for keeps its buyer, after
#: the year of its last ledger entry. A working value until the lawyer
#: answers (the legal list, 03.10; the owner's answer of 04.10) — the one
#: place to change it. Not a company's setting: a company cannot choose to
#: keep its sales records shorter than the law asks.
BUYER_RETENTION_YEARS = 5

#: The privacy run's sweep that removes a buyer left on an order.
SWEEP = "commerce.buyers"
#: What a kept buyer is called where a module lists what stays of a customer.
KEPT_KIND = "commerce.order_buyer"

#: Why an order still names its buyer after the customer was taken out.
WHY_BUYER_STAYS = {
    "pl": "Dane kupującego (imię i nazwisko, e-mail, telefon) zostają w zamówieniu z wpłatą: "
    f"to zapis sprzedaży firmy, przechowywany przez {BUYER_RETENTION_YEARS} pełnych lat "
    "kalendarzowych po roku ostatniej wpłaty albo zwrotu. Po tym dniu system usunie je sam.",
    "en": "The buyer's details (name, e-mail, phone) stay on an order that was paid for: it "
    f"is the company's sales record, kept for {BUYER_RETENTION_YEARS} full calendar years "
    "after the year of its last payment or refund. After that day the system removes them "
    "by itself.",
}


def _zone(organization_id: UUID) -> ZoneInfo:
    return ZoneInfo(Organization.objects.values_list("timezone", flat=True).get(pk=organization_id))


def period_start(organization_id: UUID, now: datetime | None = None) -> datetime:
    """The moment the period reaches back to at `now`: the first instant, in
    the company's time zone, of the year `BUYER_RETENTION_YEARS` before the
    current one. A ledger last written to before it has had its full years."""
    zone = _zone(organization_id)
    local = (now or timezone.now()).astimezone(zone)
    return datetime(local.year - BUYER_RETENTION_YEARS, 1, 1, tzinfo=zone)


def kept_until(last_entry: datetime, zone: ZoneInfo) -> date:
    """The last day an order whose ledger was last written to at `last_entry`
    names its buyer, as the company reads its calendar."""
    return date(last_entry.astimezone(zone).year + BUYER_RETENTION_YEARS, 12, 31)


def _sales(organization_id: UUID, **scope: Any) -> QuerySet[LedgerEntry, dict[str, Any]]:
    """The ledgers of orders money was really taken for, one row an order:
    the charges come to more than nothing — a payment marked by mistake and
    taken back is no sale — with when the ledger was last written to. Both of
    an entry's dates are read and the later one counts: an entry added late
    for something that happened earlier keeps the buyer from when it was
    added."""
    return (
        LedgerEntry.all_objects.filter(organization_id=organization_id, **scope)
        .order_by()
        .values("order_id", customer_id=F("order__customer_id"))
        .annotate(
            charged=Sum("amount_minor", filter=Q(kind=LedgerEntryKind.CHARGE)),
            occurred=Max("occurred_at"),
            written=Max("created_at"),
        )
        .filter(charged__gt=0)
    )


def held_orders(
    organization_id: UUID, order_ids: Collection[UUID], start: datetime | None = None
) -> dict[UUID, date]:
    """Which of these orders keep their buyer, with the last day each does:
    sales records whose ledger was written to at `start` or later — now's
    `period_start` unless a run names its own. The caller that decides by it
    holds the orders' locks."""
    if not order_ids:
        return {}
    start = start or period_start(organization_id)
    zone = _zone(organization_id)
    held = {}
    for row in _sales(organization_id, order_id__in=list(order_ids)):
        last = max(row["occurred"], row["written"])
        if last >= start:
            held[row["order_id"]] = kept_until(last, zone)
    return held


def kept_of(customers: Sequence[Customer]) -> list[Kept]:
    """What taking these customers of one company out now would leave: the
    buyer on each of their orders inside the period, and until when. A read."""
    if not customers:
        return []
    organization_id = customers[0].organization_id
    orders = dict(
        Order.all_objects.filter(
            organization_id=organization_id,
            customer_id__in=[customer.id for customer in customers],
        ).values_list("id", "number")
    )
    held = held_orders(organization_id, list(orders))
    return [
        Kept(
            kind=KEPT_KIND,
            label=orders[order_id],
            reference=str(order_id),
            until=until,
            why=WHY_BUYER_STAYS,
        )
        for order_id, until in sorted(held.items(), key=lambda item: orders[item[0]])
    ]


def _named(organization_id: UUID) -> QuerySet[Order]:
    """The orders that still name a buyer whose customer was taken out: what
    `strip_buyer` left because the order was a sales record inside its period.
    A stripped order carries its customer's placeholder and nothing else."""
    return Order.all_objects.filter(
        organization_id=organization_id, customer__anonymized_at__isnull=False
    ).exclude(Q(buyer_name=F("customer__display_name")) & Q(buyer_email="") & Q(buyer_phone=""))


def buyers_due(organization_id: UUID, start: datetime | None = None) -> list[UUID]:
    """The orders whose kept buyer a run would remove, in id order: the
    ledger was last written to before `start`, so the period has ended — or
    the order is no sales record any more (its only payment was taken back as
    a mistake after the customer was taken out)."""
    named = list(_named(organization_id).order_by("id").values_list("id", flat=True))
    held = held_orders(organization_id, named, start)
    return [order_id for order_id in named if order_id not in held]


def clear_buyers(organization_id: UUID, order_ids: Collection[UUID]) -> None:
    """The buyer's name, e-mail and phone go from these orders; what is left
    is the anonymised customer's placeholder. Numbers, lines and money stay."""
    Order.all_objects.filter(organization_id=organization_id, id__in=list(order_ids)).update(
        buyer_name=Subquery(
            Customer.all_objects.filter(
                organization_id=organization_id, pk=OuterRef("customer_id")
            ).values("display_name")[:1]
        ),
        buyer_email="",
        buyer_phone="",
        updated_at=timezone.now(),
    )


def erase_buyers(organization_id: UUID, start: datetime, limit: int) -> int:
    """Removes up to `limit` buyers whose time has come, inside the company's
    tenant and the run's transaction. The orders are locked in id order and
    the ledger is read again from under the locks: an entry written between
    finding the order and locking it — a refund marked years later — starts
    the period again and keeps the buyer."""
    found = buyers_due(organization_id, start)[:limit]
    if not found:
        return 0
    locked = list(
        Order.all_objects.select_for_update(no_key=True)
        .filter(organization_id=organization_id, id__in=found)
        .order_by("id")
        .values_list("id", flat=True)
    )
    held = held_orders(organization_id, locked, start)
    still_named = set(_named(organization_id).filter(id__in=locked).values_list("id", flat=True))
    due = [order_id for order_id in locked if order_id in still_named and order_id not in held]
    clear_buyers(organization_id, due)
    return len(due)


def _rule(organization_id: UUID, now: datetime) -> RetentionRule:
    """The same in every company and with no grace period: it is the law's
    period, not a company's click. The cutoff is the company's own — its
    years are counted in its time zone."""
    return RetentionRule(
        cutoff=period_start(organization_id, now), period=f"{BUYER_RETENTION_YEARS} lat"
    )


BUYERS = RetentionSweep(
    key=SWEEP,
    rule=_rule,
    due=lambda organization_id, start: len(buyers_due(organization_id, start)),
    erase=erase_buyers,
)
