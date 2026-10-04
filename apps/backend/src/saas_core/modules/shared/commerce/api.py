"""Public use-case API of the Commerce module (ADR-073 §1, §3).

A module that sells something registers itself once, from its
`AppConfig.ready` — `register_order_source(kind, prefix)` — and then, inside
the transaction that writes what it sells, hands the priced lines over:
`place_order(...)` gives the order its number, or answers None where the
company's plan has no orders. Afterwards the source finds its order with
`order_for(source, reference)` (locked) and tells it what changed:
`reprice_order` when it priced the thing again, `cancel_order` when it took it
back. A source that first has to accept what the customer asked for places a
draft (`place_order(..., draft=True)`: no number, no payment) and calls
`accept_order` when it does. `ORDER_MODEL` is for a module's own table of details about an order.

A source that confirms only after a payment asks for it right after placing
the order — `request_prepayment(order, …)` answers until when it holds its
record — and registers a handler (`OrderHandler`) to hear which came first,
the money or the date (§5). Whether the company can be paid by a transfer at
all is `transfer_account()`; a module whose offers ask for one says so with
`register_transfer_account_use`. `orders_of(source, references)` names the
orders of a list of records for whoever may read orders,
`order_references(order, source)` the records an order stands for, and
`awaited_transfer(source, reference)` is what the buyer still has to pay and
where.

Commerce never imports a source and works out no price.
"""

from .models import Amounts, Order, OrderChannel, OrderLineKind, OrderStatus, TaxRate
from .names import COMMERCE_ENABLED
from .orders import (
    OrderLineInput,
    accept_order,
    cancel_order,
    order_for,
    order_references,
    orders_of,
    place_order,
    reprice_order,
)
from .payments import awaited_transfer, request_prepayment
from .sources import OrderHandler, register_order_source
from .transfer_account import TransferAccount, register_transfer_account_use, transfer_account

ORDER_MODEL = "commerce.Order"

__all__ = [
    "COMMERCE_ENABLED",
    "ORDER_MODEL",
    "Amounts",
    "Order",
    "OrderChannel",
    "OrderHandler",
    "OrderLineInput",
    "OrderLineKind",
    "OrderStatus",
    "TaxRate",
    "TransferAccount",
    "accept_order",
    "awaited_transfer",
    "cancel_order",
    "order_for",
    "order_references",
    "orders_of",
    "place_order",
    "register_order_source",
    "register_transfer_account_use",
    "reprice_order",
    "request_prepayment",
    "transfer_account",
]
