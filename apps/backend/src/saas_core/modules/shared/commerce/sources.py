"""Who places orders (ADR-073 §1). A module that sells something says so from
its `AppConfig.ready`: `register_order_source(kind, prefix)` — bookings are
`R`, the shop is `Z` — and the prefix starts every number of its orders."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

from saas_core.modules.core.organizations.history import HistoryTarget

from .models import Order

_PREFIX = re.compile(r"^[A-Z]{1,4}$")

#: What the records a source's lines stand for are called, and where the panel
#: shows them: (organization, a line's `source`, references) -> reference ->
#: its name. A record that is gone, or one the source does not name, is left
#: out. Never a customer's name: the order says who bought.
type LineTargets = Callable[[UUID, str, Sequence[str]], Mapping[str, HistoryTarget]]


@dataclass(frozen=True, slots=True)
class OrderHandler:
    """What commerce tells a source about the money of its orders (ADR-073
    §1, §5). Each runs inside the transaction and the tenant of the change
    that caused it, so the order and the source's record move together."""

    #: The payment the source waited for before confirming has come whole.
    prepaid: Callable[[Order], None]
    #: It has not come by its date: the order is canceled, and the source
    #: lets go of what it held for it.
    expired: Callable[[Order], None]
    #: The buyer's own address of what the order is for — where they see it
    #: and can give it up — for a mail commerce sends later than the order
    #: (a balance's reminder). Empty when the source has none.
    link: Callable[[Order], str] | None = None


@dataclass(frozen=True, slots=True)
class OrderSource:
    kind: str
    prefix: str
    targets: LineTargets | None = None
    handler: OrderHandler | None = None


_sources: dict[str, OrderSource] = {}


def register_order_source(
    kind: str,
    prefix: str,
    *,
    targets: LineTargets | None = None,
    handler: OrderHandler | None = None,
) -> None:
    """`kind` names the source on every order it places; `prefix` is its own:
    two sources never number into one sequence. `targets` names what its
    lines stand for — a visit with its time — for whoever reads the order.
    `handler` is for a source that asks for a payment before it confirms
    (`request_prepayment`): it hears when the payment came and when it did
    not."""
    if not _PREFIX.fullmatch(prefix):
        raise ImproperlyConfigured(f"Order prefix {prefix!r} is not one to four capital letters.")
    owner = next((source.kind for source in _sources.values() if source.prefix == prefix), kind)
    if owner != kind:
        raise ImproperlyConfigured(f"Order prefix {prefix!r} belongs to {owner!r}.")
    _sources[kind] = OrderSource(kind, prefix, targets, handler)


def order_source(kind: str) -> OrderSource:
    try:
        return _sources[kind]
    except KeyError:
        raise LookupError(f"No order source {kind!r} is registered.") from None


def order_sources() -> list[OrderSource]:
    return sorted(_sources.values(), key=lambda source: source.kind)
