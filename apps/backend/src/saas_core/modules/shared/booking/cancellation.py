"""What a booking given up gives back (ADR-072 §8, ADR-073 §8, phase 4h).

An offer carries refund thresholds — „at least N days before the start → so
many percent back” — and what they are counted on: the prepayment alone (the
default, owner decision 28a: whatever else was paid goes back whole) or
everything paid. Both are frozen in the booking's quote, so a booking is
settled by the terms its customer accepted, whatever the offer says later.

Booking works the amount out and tells commerce, which keeps the money and
works out no amount of its own. Nothing here writes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ErrorDetail, ValidationError

from .models import PaymentPolicy, RefundBasis, Service

#: The bounds of an offer's thresholds: a protective limit on their number,
#: and what a row may say. Served by `GET /booking/setup/options/`.
REFUND_THRESHOLDS: dict[str, Any] = {
    "max_rows": 6,
    "min_days_before": {"minimum": 0, "maximum": 365},
    "refund_percent": {"minimum": 0, "maximum": 100},
}
#: Why the company calls a booking off, where the reason changes what goes
#: back: the balance was not paid by its date (owner decision 29a) — the
#: prepayment is then settled by the thresholds, as when the customer gives up.
BALANCE_OVERDUE = "balance_overdue"
CANCEL_REASONS = (BALANCE_OVERDUE,)


@dataclass(frozen=True, slots=True)
class Refund:
    """What giving a booking up now gives back of what was paid."""

    paid_minor: int
    refund_minor: int
    #: The threshold's percent that applied; 100 where the offer had none.
    percent: int
    #: Whole days of the company's calendar until the booking's start.
    days_before: int


def normalized(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    """An offer's thresholds as they are stored: the longest notice first,
    one row per number of days. Refuses what makes no sense to a customer —
    more back for less notice."""
    ordered = sorted(
        (
            {
                "min_days_before": int(row["min_days_before"]),
                "refund_percent": int(row["refund_percent"]),
            }
            for row in rows
        ),
        key=lambda row: -row["min_days_before"],
    )
    days = [row["min_days_before"] for row in ordered]
    if len(set(days)) != len(days):
        raise _refused("Każdy próg ma inną liczbę dni.", "duplicate_threshold")
    percents = [row["refund_percent"] for row in ordered]
    if percents != sorted(percents, reverse=True):
        raise _refused(
            "Krótsze wyprzedzenie nie może dawać większego zwrotu niż dłuższe.",
            "thresholds_not_descending",
        )
    return ordered


def terms(service: Service, prepayment: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The offer's refund terms as a quote freezes them, or None where the
    offer has no thresholds. Without a prepayment that is a part of the price
    there is nothing but „everything paid” to count them on (ADR-072 §8)."""
    if not service.cancellation_refunds:
        return None
    partly = (
        service.payment_policy == PaymentPolicy.DEPOSIT
        and prepayment is not None
        and prepayment["kind"] == "deposit"
    )
    return {
        "applies_to": service.cancellation_applies_to if partly else RefundBasis.PAID.value,
        "refunds": list(service.cancellation_refunds),
    }


def refund(
    quote: Mapping[str, Any] | None,
    *,
    paid_minor: int,
    starts_at: datetime,
    zone: str,
    now: datetime,
) -> Refund:
    """What the booking's own terms give back when it is given up at `now`:
    the percent of the first threshold the notice reaches, counted on the
    prepayment or on everything paid; the rest of what was paid goes back
    whole. A booking without thresholds gives everything back."""
    local = ZoneInfo(zone)
    days = max((starts_at.astimezone(local).date() - now.astimezone(local).date()).days, 0)
    frozen = (quote or {}).get("cancellation")
    if not frozen or paid_minor <= 0:
        return Refund(max(paid_minor, 0), max(paid_minor, 0), 100, days)
    percent = next(
        (row["refund_percent"] for row in frozen["refunds"] if days >= row["min_days_before"]),
        0,
    )
    base = paid_minor
    if frozen["applies_to"] == RefundBasis.DEPOSIT:
        prepayment = (quote or {}).get("prepayment") or {}
        base = min(paid_minor, int(prepayment.get("amount_minor", paid_minor)))
    # Halves up to a whole minor unit, as the prepayment itself is rounded.
    back = (base * percent + 50) // 100 + (paid_minor - base)
    return Refund(paid_minor, back, percent, days)


def _refused(message: str, code: str) -> ValidationError:
    return ValidationError({"cancellation_refunds": [ErrorDetail(message, code=code)]})
