"""Public use-case API of the Commerce module (ADR-073 §1, §3).

A module that sells something registers itself once, from its
`AppConfig.ready` — `register_order_source(kind, prefix)` — and then, inside
the transaction that writes what it sells, hands the priced lines over:
`place_order(...)` gives the order its number, or answers None where the
company's plan has no orders. Afterwards the source finds its order with
`order_for(source, reference)` (locked) and tells it what changed:
`reprice_order` when it priced the thing again, `cancel_order` when it took it
back. `ORDER_MODEL` is for a module's own table of details about an order.

Commerce never imports a source and works out no price.
"""

from .models import Amounts, Order, OrderChannel, OrderLineKind, OrderStatus, TaxRate
from .orders import (
    COMMERCE_ENABLED,
    OrderLineInput,
    cancel_order,
    order_for,
    place_order,
    reprice_order,
)
from .sources import register_order_source

ORDER_MODEL = "commerce.Order"

__all__ = [
    "COMMERCE_ENABLED",
    "ORDER_MODEL",
    "Amounts",
    "Order",
    "OrderChannel",
    "OrderLineInput",
    "OrderLineKind",
    "OrderStatus",
    "TaxRate",
    "cancel_order",
    "order_for",
    "place_order",
    "register_order_source",
    "reprice_order",
]
