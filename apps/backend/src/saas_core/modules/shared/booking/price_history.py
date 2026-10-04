"""What a price was (ADR-072 §6; ADR-073, slice 4i).

Every write of a `PriceRule` appends a line to `PriceHistoryEntry` in the
write's own transaction: the whole rule as the write left it, the amount
before and after, who wrote it and when. Nothing here is ever changed, so
the price list of a past moment is read back exactly — the latest line of
each price up to that moment, without the deleted ones — and `prices.price_for`
answers over it as it does over today's list.

The record begins with the migration that made the table: it wrote one
`baseline` line for every price that existed then. Before a company's first
line nothing is known, and the reads say so (`recorded_since`) instead of
guessing. How the amounts are read (gross or net, `pricing.entry.amounts`)
is a company setting with its own history (ADR-078); a line holds the rule,
not the setting.

Whoever writes a price calls `record` — `prices.save_price`, `delete_price`,
`copy_prices_to_next_year`, and the draft offer's removal in `setup`. A write
that runs as a preview is rolled back with its line. The panel's reads are
`prices.price_list_on` and `prices.list_price_changes`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import ForeignKey, Min
from django.utils import timezone

from saas_core.modules.core.organizations.audit import audit_snapshot
from saas_core.modules.core.organizations.context import TenantContext

from .models import PriceChange, PriceHistoryEntry, PriceRule

#: Every column of a price, by the name its value is stored under.
_COLUMNS = tuple(field.attname for field in PriceRule._meta.concrete_fields)


def record(
    context: TenantContext | None,
    rule: PriceRule,
    change: str,
    *,
    previous_amount: int | None = None,
) -> PriceHistoryEntry:
    """One line for a write of `rule`, in the caller's transaction and tenant.
    For a deletion `rule` is the row as it last was, before it goes."""
    return PriceHistoryEntry.all_objects.create(
        organization_id=rule.organization_id,
        rule_id=rule.id,
        change=change,
        state=audit_snapshot(rule, _COLUMNS),
        amount_minor=rule.amount_minor,
        previous_amount_minor=previous_amount,
        currency=rule.currency,
        actor_id=context.actor_id if context is not None else None,
        acting_via=context.acting_via if context is not None else "",
        recorded_at=timezone.now(),
    )


def rule_of(line: PriceHistoryEntry) -> PriceRule:
    """The price a line describes, as an object `price_for` and the panel's
    serializer read — never saved."""
    values: dict[str, Any] = {}
    for field in PriceRule._meta.concrete_fields:
        if field.attname in line.state:
            # A relation's column holds the other row's key.
            column = field.target_field if isinstance(field, ForeignKey) else field
            values[field.attname] = column.to_python(line.state[field.attname])
    values.update(id=line.rule_id, organization_id=line.organization_id)
    return PriceRule(**values)


def _lines_at(organization_id: UUID, moment: datetime) -> list[PriceHistoryEntry]:
    """The latest line of each price up to `moment`."""
    return list(
        PriceHistoryEntry.all_objects.filter(
            organization_id=organization_id, recorded_at__lte=moment
        )
        .order_by("rule_id", "-recorded_at", "-id")
        .distinct("rule_id")
    )


def rules_at(organization_id: UUID, moment: datetime) -> list[PriceRule]:
    """The company's price list as it stood at `moment`, read from the
    record: pass it to `prices.price_for` for the price of a day then. Inside
    the company's tenant. Empty before the record began — ask
    `recorded_since` whether `moment` is one the record can answer for."""
    return [
        rule_of(line)
        for line in _lines_at(organization_id, moment)
        if line.change != PriceChange.DELETED
    ]


def recorded_since(organization_id: UUID) -> datetime | None:
    """The company's first line: from then on the record is complete."""
    found: datetime | None = PriceHistoryEntry.all_objects.filter(
        organization_id=organization_id
    ).aggregate(first=Min("recorded_at"))["first"]
    return found
