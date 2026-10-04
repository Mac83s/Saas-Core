"""What is particular to the assistant's commands for orders and payments
(`shared/commerce/command_declarations.py`): an order is read by its number
and by what it is for, never by who bought; the words a person agrees to
carry the amount, the order and what is left; a payment that covers the
prepayment a booking waits for says what it confirms; and a payment taken
back is not a refund."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache

from command_evals.commerce import _order, _payment
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.shared.booking.models import Appointment
from saas_core.modules.shared.commerce.models import LedgerEntry, Payment
from test_booking import _no_delivery, tenant
from test_booking_pricing_commands import refused, run, shown
from test_command_evals import assistant, invocation, owner
from test_commerce_orders import order_of, visit
from test_commerce_prepayments import at, prepaid

pytestmark = pytest.mark.django_db

ORDERS = "commerce.orders.read@1"
ORDER = "commerce.order.read@1"
RECORD = "commerce.payment.record@1"
VOID = "commerce.payment.void@1"


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache.clear()
    _no_delivery(monkeypatch)
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def read(person: TenantContext, key: str, arguments: dict[str, Any]) -> Any:
    with activate_tenant_context(assistant(person)):
        (result,) = execute_plan([invocation(key, arguments)])
    return result


def payment(person: TenantContext, amount: int, method: str = "cash") -> list[Any]:
    return [
        invocation(
            RECORD,
            {"order_id": str(_order(person).id), "amount_minor": amount, "method": method},
        )
    ]


def test_orders_are_read_by_number_and_money_and_never_by_buyer() -> None:
    person = owner("orders-read", ORDERS)

    listed = read(person, ORDERS, {"status": None, "q": None, "page": None})

    assert listed.status == "done", listed
    (order,) = listed.output["orders"]
    assert (order["number"], order["status"], order["for"]) == (
        "R/2026/0001",
        "partially_paid",
        "Konsultacja",
    )
    assert (order["gross_minor"], order["paid_minor"], order["due_minor"]) == (15000, 5000, 10000)
    # The person may search by the buyer they named; the answer still does not name them.
    by_buyer = read(person, ORDERS, {"status": None, "q": "kowalska", "page": None})
    nobody = read(person, ORDERS, {"status": "paid", "q": None, "page": None})
    assert (by_buyer.output["total"], nobody.output["total"]) == (1, 0)

    one = read(person, ORDER, {"order_id": None, "number": "r/2026/0001"})

    assert one.status == "done", one
    assert (one.output["paid_minor"], one.output["due_minor"], one.output["version"]) == (
        5000,
        10000,
        3,
    )
    (line,) = one.output["lines"]
    assert (line["name"], line["gross_minor"]) == ("Konsultacja", 15000)
    (marked,) = one.output["payments"]
    assert (marked["payment_id"], marked["method"], marked["status"], marked["amount_minor"]) == (
        str(_payment(person).id),
        "cash",
        "succeeded",
        5000,
    )
    # Neither the buyer nor the person of the company who marked the payment.
    said = json.dumps([listed.output, by_buyer.output, one.output], ensure_ascii=False)
    assert "Anna" not in said and "Kowalska" not in said and "buyer" not in said
    assert "recorded_by" not in said

    missing = read(person, ORDER, {"order_id": None, "number": "R/2026/0099"})
    unnamed = read(person, ORDER, {"order_id": None, "number": None})
    assert (missing.status, missing.code) == ("refused", "not_found")
    assert (unnamed.status, [error["field"] for error in unnamed.errors]) == (
        "refused",
        ["order_id"],
    )


def test_a_payment_is_agreed_to_with_its_amount_and_what_is_left() -> None:
    person = owner("payment-words", RECORD)

    risk, words = shown(person, payment(person, 4000, "transfer"))

    # Money takes its own click, as a step nobody takes back: the ledger only grows.
    assert risk == "irreversible"
    assert words == (
        "Wpłata 40,00 PLN (przelewem) do zamówienia R/2026/0001 — „Konsultacja”. Po tym "
        "wpłacono 90,00 PLN z 150,00 PLN; do zapłaty zostaje 60,00 PLN. Wpis zostaje w "
        "historii zamówienia; pomyłkę koryguje wpis przeciwny („Wycofaj wpłatę”), a nie "
        "usunięcie."
    )
    assert "opłacone w całości (150,00 PLN)" in shown(person, payment(person, 10000))[1]
    # More than what is left is refused before anybody is asked to click.
    assert refused(person, payment(person, 10001)) == ("amount_minor", "amount_exceeds_due")

    result = run(person, payment(person, 4000, "transfer"))

    assert result.status == "done", result
    assert result.output == {
        "order_id": str(_order(person).id),
        "number": "R/2026/0001",
        "status": "partially_paid",
        "paid_minor": 9000,
        "due_minor": 6000,
        "version": 4,
    }
    assert sorted(
        LedgerEntry.all_objects.filter(order=_order(person)).values_list("kind", "amount_minor")
    ) == [("charge", 4000), ("charge", 5000)]


def test_a_payment_that_covers_the_awaited_prepayment_says_what_it_confirms() -> None:
    configured = prepaid("payment-confirms")
    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None and booked.status == "pending_payment"
    person = context_from_membership(configured["owner"])
    plan = [
        invocation(RECORD, {"order_id": str(order.id), "amount_minor": 4500, "method": "cash"})
    ]

    risk, words = shown(person, plan)

    assert risk == "irreversible"
    assert (
        "Pokrywa przedpłatę, na którą czeka rezerwacja: rezerwacja zostanie potwierdzona, a "
        "klient dostanie potwierdzenie."
    ) in words
    # A part of it confirms nothing, and the words do not say it would.
    part = [
        invocation(RECORD, {"order_id": str(order.id), "amount_minor": 2000, "method": "cash"})
    ]
    assert "potwierdzona" not in shown(person, part)[1]

    result = run(person, plan)

    assert result.status == "done", result
    assert Appointment.all_objects.get(pk=booked.id).status == "confirmed"


def test_a_payment_marked_by_mistake_is_taken_back_and_that_is_not_a_refund() -> None:
    person = owner("payment-void", VOID)
    plan = [
        invocation(
            VOID, {"order_id": str(_order(person).id), "payment_id": str(_payment(person).id)}
        )
    ]

    risk, words = shown(person, plan)

    assert risk == "irreversible"
    assert words == (
        "Wycofanie wpłaty 50,00 PLN (na miejscu) z zamówienia R/2026/0001 — „Konsultacja” — "
        "oznaczonej przez pomyłkę. Po tym wpłacono 0,00 PLN z 150,00 PLN; do zapłaty zostaje "
        "150,00 PLN. To nie jest zwrot: żadne pieniądze nie wracają do klienta. Rezerwacja, "
        "którą ta wpłata potwierdziła, zostaje potwierdzona. Wpis zostaje w historii "
        "zamówienia."
    )

    result = run(person, plan)

    assert result.status == "done", result
    assert (result.output["status"], result.output["paid_minor"], result.output["due_minor"]) == (
        "awaiting_payment",
        0,
        15000,
    )
    assert Payment.all_objects.get(pk=_payment(person).id).status == "canceled"
    assert sorted(
        LedgerEntry.all_objects.filter(order=_order(person)).values_list("kind", "amount_minor")
    ) == [("charge", -5000), ("charge", 5000)]
    # Taken back once: a second try is refused before a click.
    again = [
        invocation(
            VOID, {"order_id": str(_order(person).id), "payment_id": str(_payment(person).id)}
        )
    ]
    assert refused(person, again) == ("payment", "payment_not_voidable")
