"""The assistant's commands for orders and what was paid for them (ADR-076 §1;
ADR-073 §4, §5 and §11).

Thin adapters over the services the panel's „Zamówienia” calls: the list, one
order with its payments and refunds, a payment the company marks as received
and a payment marked by mistake taken back.

Three rules decide how they look:

- **No buyer.** An order is named by its number and by what it is for. The
  buyer's name, e-mail and phone never reach a model: a command that returns
  `personal` fields needs the audited read ADR-076 §1 describes, and nobody
  has built it. A search still takes the words the person said (`q`), and
  the answer says which orders matched, not whose they are.
- **Money is never guessed.** The amount and how it came are the person's
  own words; the words the person agrees to are written here from the
  service's own preview — the amount, the order, what is paid afterwards and
  what is left — so a model cannot swap an amount between what it said and
  what is written.
- **Each on its own click, as a step nobody takes back.** The ledger is
  append-only: a payment marked stays in the order's history, and a mistake
  is corrected by the opposite entry, never removed. A payment that covers
  the prepayment an order waits for also confirms the booking and writes to
  the customer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command

from .emails import money
from .ledger import MANUAL_METHODS, paid_by_order
from .models import Order, OrderLine, OrderStatus
from .names import COMMERCE_ENABLED, ORDERS_READ, PAYMENTS_MANAGE
from .orders import list_orders, read_order
from .payments import record_payment, void_payment

_MODULE = "shared.commerce"
_PUBLIC = "public"
#: Orders a read returns at once: enough to answer „which wait for a payment”,
#: small enough that every later call of the model does not pay for a long list.
PAGE_SIZE = 20
#: How a payment marked by hand came, as the panel's „Zamówienia” words it.
_METHOD = {
    "cash": ("na miejscu", "at the desk"),
    "transfer": ("przelewem", "by a transfer"),
}
_STATUSES = list(OrderStatus.values)


def _nullable(kind: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], "description": description, **extra}


def _id(arguments: Mapping[str, Any], field: str) -> UUID:
    try:
        return UUID(str(arguments[field]))
    except ValueError:
        raise ValidationError({field: ["Nieprawidłowy identyfikator."]}) from None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _effect(kind: str, order_id: UUID, pl: str, en: str) -> Effect:
    return Effect(
        kind=kind,
        resource="commerce.order",
        resource_id=str(order_id),
        summary={"pl": pl, "en": en},
    )


def _subjects(organization_id: UUID, orders: Mapping[UUID, int]) -> dict[UUID, str]:
    """What each order is for, in the company's language: the first line of
    the revision in force."""
    found: dict[UUID, str] = {}
    for order_id, revision, name in (
        OrderLine.all_objects.filter(organization_id=organization_id, order_id__in=list(orders))
        .order_by("order_id", "revision", "position")
        .values_list("order_id", "revision", "name")
    ):
        if revision == orders[order_id]:
            found.setdefault(order_id, name)
    return found


# --- commerce.orders.read@1 ------------------------------------------------------------


def _read_orders(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    listed = list_orders(
        page=arguments["page"] or 1,
        page_size=PAGE_SIZE,
        status=arguments["status"] or "",
        query=arguments["q"] or "",
    )
    organization_id = call.context.organization_id
    ids = [item["id"] for item in listed["items"]]
    revisions = dict(
        Order.all_objects.filter(organization_id=organization_id, pk__in=ids).values_list(
            "id", "revision"
        )
    )
    subjects = _subjects(organization_id, revisions)
    paid = paid_by_order(organization_id, ids)
    return {
        "total": listed["total"],
        "page": listed["page"],
        "page_size": listed["page_size"],
        "orders": [
            {
                "order_id": str(item["id"]),
                # Empty for a draft: a booking request nobody has answered yet.
                "number": item["number"],
                "status": item["status"],
                "source": item["source"],
                "placed_at": _iso(item["placed_at"]),
                "for": subjects.get(item["id"], ""),
                "currency": item["currency"],
                "gross_minor": item["gross_minor"],
                "paid_minor": paid.get(item["id"], 0),
                "due_minor": item["gross_minor"] - paid.get(item["id"], 0),
            }
            for item in listed["items"]
        ],
    }


ORDERS_READ_COMMAND = CommandSpec(
    name="commerce.orders.read",
    version=1,
    module=_MODULE,
    title={"pl": "Odczytaj zamówienia", "en": "Read the orders"},
    summary={
        "pl": "Zamówienia klientów firmy: numer, stan, za co, kwota, ile wpłacono i ile zostało.",
        "en": "The customers' orders: number, status, what for, amount, paid and left to pay.",
    },
    model_description=(
        "Returns the company's orders, newest first, twenty at a time: each with its "
        "order_id, its number (R/2026/0007; empty for a draft — a booking request nobody "
        "answered yet), status, what it is for, and in minor units of its currency what it "
        "comes to (gross_minor), what was paid (paid_minor) and what is left (due_minor). "
        "status: awaiting_payment, partially_paid, paid, canceled, refunded (canceled and the "
        "money given back), draft. Filter with status, or search with q — a part of an "
        "order's number, or of the buyer's name or e-mail exactly as the person said it. "
        "The buyer is never in the answer: name an order by its number and what it is for. "
        "Use it to find an order the person talks about before commerce.order.read; an "
        "amount is said as money (4500 minor units of PLN is 45,00 zł)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "q", "page"],
        "properties": {
            "status": {
                "type": ["string", "null"],
                "enum": [*_STATUSES, None],
                "description": "Only orders in this status; null for all.",
            },
            "q": _nullable(
                "string",
                "A part of a number, or of the buyer's name or e-mail as the person said it; "
                "null for no search.",
                maxLength=120,
            ),
            "page": _nullable("integer", "Which twenty; null for the newest.", minimum=1),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "total": {"type": "integer"},
            "page": {"type": "integer"},
            "page_size": {"type": "integer"},
            "orders": {"type": "array"},
        },
    },
    permission=ORDERS_READ,
    entitlement=COMMERCE_ENABLED,
    risk="read",
    run=_read_orders,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- commerce.order.read@1 -------------------------------------------------------------


def _order_id(arguments: Mapping[str, Any]) -> UUID:
    """The order the caller means: by its id, or by its number as people
    write it."""
    if arguments["order_id"] is not None:
        return _id(arguments, "order_id")
    number = (arguments["number"] or "").strip()
    if not number:
        raise ValidationError({"order_id": ["Podaj identyfikator albo numer zamówienia."]})
    for item in list_orders(query=number, page_size=PAGE_SIZE)["items"]:
        if item["number"].casefold() == number.casefold():
            return UUID(str(item["id"]))
    raise NotFound("Nie ma takiego zamówienia.")


def _read_order(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    order = read_order(_order_id(arguments))
    return {
        "order_id": str(order["id"]),
        "number": order["number"],
        "status": order["status"],
        "source": order["source"],
        "placed_at": _iso(order["placed_at"]),
        "currency": order["currency"],
        # Whether the company's prices were entered net or gross.
        "amounts": order["amounts"],
        "gross_minor": order["gross_minor"],
        "paid_minor": order["paid_minor"],
        "due_minor": order["due_minor"],
        "refunded_minor": order["refunded_minor"],
        "refund_owed_minor": order["refund_owed_minor"],
        "version": order["version"],
        "lines": [
            {
                "name": line["name"],
                "kind": line["kind"],
                "quantity": line["quantity"],
                "gross_minor": line["gross_minor"],
                "for": line["target"]["label"] if line["target"] else None,
                "at": _iso(line["target"]["at"]) if line["target"] else None,
            }
            for line in order["lines"]
        ],
        # Who marked each is a person of the company: not the model's to know.
        "payments": [
            {
                "payment_id": str(payment["id"]),
                "kind": payment["kind"],
                "method": payment["method"],
                "status": payment["status"],
                "amount_minor": payment["amount_minor"],
                "due_at": _iso(payment["due_at"]),
                "paid_at": _iso(payment["paid_at"]),
            }
            for payment in order["payments"]
        ],
        # Without the company's reason: its own words, which may name somebody.
        "refunds": [
            {
                "refund_id": str(refund["id"]),
                "method": refund["method"],
                "status": refund["status"],
                "amount_minor": refund["amount_minor"],
                "refunded_at": _iso(refund["refunded_at"]),
            }
            for refund in order["refunds"]
        ],
    }


ORDER_READ_COMMAND = CommandSpec(
    name="commerce.order.read",
    version=1,
    module=_MODULE,
    title={"pl": "Odczytaj zamówienie", "en": "Read an order"},
    summary={
        "pl": "Jedno zamówienie: pozycje, wpłaty, zwroty, ile wpłacono i ile zostało.",
        "en": "One order: its lines, payments, refunds, what was paid and what is left.",
    },
    model_description=(
        "Returns one order by its order_id (from commerce.orders.read) or by its number as "
        "the person wrote it (R/2026/0007) — pass the one you have and null for the other. "
        "The answer has its lines with what each is for and when, and in minor units of its "
        "currency: gross_minor, paid_minor, due_minor (left to pay), refunded_minor (given "
        "back) and refund_owed_minor (what its terms still owe the customer after a "
        "cancellation). payments: each with its payment_id, kind (deposit, full, balance), "
        "method (cash — at the desk; transfer; online), status (requires_payment — awaited "
        "until due_at; succeeded; canceled — taken back; expired) and amount. refunds: what "
        "the company marked as given back. The buyer is never in the answer. Read it before "
        "marking a payment or taking one back: both need the order_id, and taking back the "
        "payment_id."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["order_id", "number"],
        "properties": {
            "order_id": _nullable("string", "The order's id; null when you pass its number."),
            "number": _nullable(
                "string", "The order's number as the person wrote it; null when you pass the id."
            ),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "order_id": {"type": "string"},
            "number": {"type": "string"},
            "status": {"type": "string"},
            "source": {"type": "string"},
            "placed_at": {"type": ["string", "null"]},
            "currency": {"type": "string"},
            "amounts": {"type": "string"},
            "gross_minor": {"type": "integer"},
            "paid_minor": {"type": "integer"},
            "due_minor": {"type": "integer"},
            "refunded_minor": {"type": "integer"},
            "refund_owed_minor": {"type": "integer"},
            "version": {"type": "integer"},
            "lines": {"type": "array"},
            "payments": {"type": "array"},
            "refunds": {"type": "array"},
        },
    },
    permission=ORDERS_READ,
    entitlement=COMMERCE_ENABLED,
    risk="read",
    run=_read_order,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- commerce.payment.record@1 and commerce.payment.void@1 -----------------------------


def _current(arguments: Mapping[str, Any], call: Any) -> tuple[Order, str]:
    """The order as it is now and what it is for; its version is what the
    consent binds."""
    order = Order.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "order_id")
    ).first()
    if order is None:
        raise NotFound("Nie ma takiego zamówienia.")
    subject = _subjects(order.organization_id, {order.id: order.revision}).get(order.id, "")
    return order, subject


def _named(order: Order, subject: str, at: int) -> str:
    """An order as a person knows it: its number and what it is for."""
    number = order.number or ("bez numeru", "without a number")[at]
    if not subject:
        return number
    return f"{number} — „{subject}”" if at == 0 else f"{number} — “{subject}”"


def _after(order: Order, effect: Mapping[str, Any], at: int) -> str:
    """What the order's money is after the step, in the reader's language."""
    locale = ("pl", "en")[at]
    paid = money(effect["paid_minor"], order.currency, locale)
    gross = money(order.gross_minor, order.currency, locale)
    due = money(effect["due_minor"], order.currency, locale)
    if effect["due_minor"] <= 0:
        return (
            f"Po tym zamówienie jest opłacone w całości ({gross}).",
            f"After it the order is paid in full ({gross}).",
        )[at]
    return (
        f"Po tym wpłacono {paid} z {gross}; do zapłaty zostaje {due}.",
        f"After it {paid} of {gross} is paid; {due} is left to pay.",
    )[at]


def _version(call: Any, order_id: UUID) -> int:
    return int(call.preview.observed_versions[f"commerce.order:{order_id}"])


def _preview_record(arguments: Mapping[str, Any], call: Any) -> Preview:
    order, subject = _current(arguments, call)
    effect = record_payment(
        order.id,
        amount_minor=arguments["amount_minor"],
        method=arguments["method"],
        expected_version=order.version,
        preview=True,
    )
    how = _METHOD[arguments["method"]]
    words = []
    for at, locale in enumerate(("pl", "en")):
        amount = money(arguments["amount_minor"], order.currency, locale)
        text = (
            f"Wpłata {amount} ({how[0]}) do zamówienia {_named(order, subject, 0)}.",
            f"A payment of {amount} ({how[1]}) for order {_named(order, subject, 1)}.",
        )[at]
        text += " " + _after(order, effect, at)
        if effect["prepayment_met"]:
            text += (
                " Pokrywa przedpłatę, na którą czeka rezerwacja: rezerwacja zostanie "
                "potwierdzona, a klient dostanie potwierdzenie.",
                " It covers the prepayment the booking waits for: the booking will be "
                "confirmed and the customer gets the confirmation.",
            )[at]
        text += (
            " Wpis zostaje w historii zamówienia; pomyłkę koryguje wpis przeciwny "
            "(„Wycofaj wpłatę”), a nie usunięcie.",
            " The entry stays in the order's history; a mistake is corrected by the "
            "opposite entry (“Take the payment back”), never removed.",
        )[at]
        words.append(text)
    return Preview(
        effects=(_effect("updated", order.id, words[0], words[1]),),
        observed_versions={f"commerce.order:{order.id}": order.version},
    )


def _paid(order: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(order["id"]),
        "number": order["number"],
        "status": order["status"],
        "paid_minor": order["paid_minor"],
        "due_minor": order["due_minor"],
        "version": order["version"],
    }


def _record(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    order_id = _id(arguments, "order_id")
    return _paid(
        record_payment(
            order_id,
            amount_minor=arguments["amount_minor"],
            method=arguments["method"],
            expected_version=_version(call, order_id),
        )
    )


_PAID_OUTPUT = {
    "type": "object",
    "x-data-class": _PUBLIC,
    "properties": {
        "order_id": {"type": "string"},
        "number": {"type": "string"},
        "status": {"type": "string"},
        "paid_minor": {"type": "integer"},
        "due_minor": {"type": "integer"},
        "version": {"type": "integer"},
    },
}

PAYMENT_RECORD = CommandSpec(
    name="commerce.payment.record",
    version=1,
    module=_MODULE,
    title={"pl": "Oznacz wpłatę", "en": "Mark a payment"},
    summary={
        "pl": "Firma dostała pieniądze za zamówienie: na miejscu albo przelewem.",
        "en": "The company received money for an order: at the desk or by a transfer.",
    },
    model_description=(
        "Marks money the company received for an order: writes the payment and moves the "
        "order's status. It moves no money — it records what the person says happened. "
        "amount_minor and method are the person's own words: never work an amount out, "
        "never assume one. When the person said \"the rest\" or \"everything\", that is the "
        "order's due_minor from commerce.order.read — say the amount in your answer. When "
        "no amount or no way of paying was said, ask; do not call. method: cash — at the "
        "desk, in cash or by card on the company's terminal; transfer — a transfer the "
        "company saw on its account. More than what is left to pay is refused, so is a "
        "payment for a canceled order or for a draft (a booking request must be answered "
        "first). Where the order waits for a prepayment, an amount that covers it confirms "
        "the booking and the customer is written to. The person agrees to every payment by "
        "its own click, with the amount in front of them; a mistake is taken back with "
        "commerce.payment.void, never by marking a negative amount."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["order_id", "amount_minor", "method"],
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The order's id from commerce.orders.read or commerce.order.read.",
            },
            "amount_minor": {
                "type": "integer",
                "minimum": 1,
                "description": "What the company received, in minor units of the order's "
                "currency (45,00 zł is 4500), as the person said it.",
            },
            "method": {
                "type": "string",
                "enum": list(MANUAL_METHODS),
                "description": "How it came, as the person said it: cash (at the desk) or "
                "transfer.",
            },
        },
    },
    output_schema=_PAID_OUTPUT,
    permission=PAYMENTS_MANAGE,
    entitlement=COMMERCE_ENABLED,
    risk="irreversible",
    run=_record,
    undo="compensation:the opposite ledger entry, commerce.payment.void@1; a booking the "
    "payment confirmed stays confirmed",
    preview=_preview_record,
    version_field="expected_version",
)


def _preview_void(arguments: Mapping[str, Any], call: Any) -> Preview:
    order, subject = _current(arguments, call)
    effect = void_payment(
        order.id, _id(arguments, "payment_id"), expected_version=order.version, preview=True
    )
    how = _METHOD.get(effect["method"], (effect["method"], effect["method"]))
    words = []
    for at, locale in enumerate(("pl", "en")):
        amount = money(effect["amount_minor"], order.currency, locale)
        text = (
            f"Wycofanie wpłaty {amount} ({how[0]}) z zamówienia {_named(order, subject, 0)} — "
            "oznaczonej przez pomyłkę.",
            f"Taking back the payment of {amount} ({how[1]}) for order "
            f"{_named(order, subject, 1)} — marked by mistake.",
        )[at]
        text += " " + _after(order, effect, at)
        text += (
            " To nie jest zwrot: żadne pieniądze nie wracają do klienta. Rezerwacja, którą "
            "ta wpłata potwierdziła, zostaje potwierdzona. Wpis zostaje w historii zamówienia.",
            " It is not a refund: no money goes back to the customer. A booking this "
            "payment confirmed stays confirmed. The entry stays in the order's history.",
        )[at]
        words.append(text)
    return Preview(
        effects=(_effect("updated", order.id, words[0], words[1]),),
        observed_versions={f"commerce.order:{order.id}": order.version},
    )


def _void(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    order_id = _id(arguments, "order_id")
    return _paid(
        void_payment(
            order_id, _id(arguments, "payment_id"), expected_version=_version(call, order_id)
        )
    )


PAYMENT_VOID = CommandSpec(
    name="commerce.payment.void",
    version=1,
    module=_MODULE,
    title={"pl": "Wycofaj wpłatę", "en": "Take a payment back"},
    summary={
        "pl": "Wpłata oznaczona przez pomyłkę: zamówienie znów czeka na tę kwotę.",
        "en": "A payment marked by mistake: the order owes that amount again.",
    },
    model_description=(
        "Takes back a payment that was marked by mistake: it stays in the order's history "
        "as canceled and the order owes that amount again. It is not a refund — no money "
        "goes back to the customer; when the company gave money back, that is marked in the "
        "panel, on the order's page („Oznacz zwrot”), not here. Only a payment marked by "
        "hand (cash or transfer) that was not taken back yet can be. A booking the payment "
        "confirmed stays confirmed: calling it off is the person's own decision in the "
        "calendar. Take order_id and payment_id from commerce.order.read; when the order "
        "has several payments and the person did not say which, ask."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["order_id", "payment_id"],
        "properties": {
            "order_id": {"type": "string", "description": "The order's id."},
            "payment_id": {
                "type": "string",
                "description": "The payment to take back, from commerce.order.read.",
            },
        },
    },
    output_schema=_PAID_OUTPUT,
    permission=PAYMENTS_MANAGE,
    entitlement=COMMERCE_ENABLED,
    risk="irreversible",
    run=_void,
    undo="compensation:the payment is marked again with commerce.payment.record@1",
    preview=_preview_void,
    version_field="expected_version",
)


def register_commerce_commands() -> None:
    for spec in (ORDERS_READ_COMMAND, ORDER_READ_COMMAND, PAYMENT_RECORD, PAYMENT_VOID):
        register_command(spec)
