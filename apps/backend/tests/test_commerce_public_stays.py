"""A stay booked on the public form carries what phase 4 built for a visit
(ADR-072, phase 5a; ADR-073 §5, §8; ADR-072 §9): the order, the prepayment by
a transfer, the company's answer where the offer is taken on request, and the
refund thresholds on the customer's own link."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.shared.booking.models import Appointment
from saas_core.modules.shared.commerce.payments import record_payment
from test_booking import _no_delivery, tenant
from test_booking_prices import key
from test_booking_public_stays import booked, form, quoted
from test_commerce_orders import order_of, with_orders
from test_commerce_prepayments import account, awaited, policy

pytestmark = pytest.mark.django_db

#: A stay of these tests begins more than thirty days ahead: everything comes
#: back; from three days before, half.
THRESHOLDS = [
    {"min_days_before": 60, "refund_percent": 100},
    {"min_days_before": 3, "refund_percent": 50},
]


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def selling(slug: str, **offer: Any) -> dict[str, Any]:
    """The cottages of `form`, at a company with orders and an account."""
    configured = form(slug)
    with_orders(configured["owner"].organization_id)
    account(configured["owner"])
    if offer:
        policy(configured, **offer)
    return configured


def test_a_stay_that_asks_for_money_first_waits_for_the_transfer() -> None:
    configured = selling(
        "pobyt-przedplata",
        payment_policy="deposit",
        deposit_percent=30,
        cancellation_refunds=THRESHOLDS,
    )
    owner = configured["owner"]
    client = APIClient()

    quote = quoted(client, configured).json()["quote"]
    # Two nights at 300, the cleaning and the tax for one person: 756.00, of
    # which 30% ahead — and what giving the stay up gives back, said before
    # the guest books.
    assert (quote["gross_minor"], quote["payment_policy"]) == (75600, "deposit")
    assert (quote["prepayment"]["kind"], quote["prepayment"]["amount_minor"]) == ("deposit", 22680)
    assert quote["cancellation"]["refunds"] == THRESHOLDS

    made = booked(client, configured, quote_digest=quote["digest"])
    assert made.status_code == 201, made.data
    stay = made.json()
    assert (stay["status"], stay["time_model"], stay["unit_name"]) == (
        "pending_payment",
        "range",
        "Domek 1",
    )
    # The transfer's details come with the booking that waits for them.
    payment = stay["payment"]
    assert (payment["kind"], payment["amount_minor"], payment["currency"]) == (
        "deposit",
        22680,
        "PLN",
    )
    assert payment["number"] and payment["due_at"] == stay["hold_expires_at"]
    with tenant(owner):
        saved = Appointment.all_objects.get(pk=stay["id"])
        order = order_of(saved)
        assert order is not None
        # The order came through the company's site, for the frozen price.
        assert (order.channel, order.gross_minor, order.number) == (
            "company_site",
            75600,
            payment["number"],
        )
        # The company marks the transfer: the stay is confirmed.
        record_payment(
            order.id,
            amount_minor=awaited(order).amount_minor,
            method="transfer",
            expected_version=order.version,
        )
    link = f"/api/v1/booking/self-service/{stay['self_service_token']}"
    read = client.get(f"{link}/").json()
    assert read["status"] == "confirmed"
    # Less than sixty days ahead: half of what was paid comes back.
    assert read["settlement"] == {"currency": "PLN", "paid_minor": 22680, "refund_minor": 11340}
    gone = client.post(f"{link}/cancel/", format="json", HTTP_IDEMPOTENCY_KEY=key())
    assert gone.status_code == 200, gone.data
    assert (gone.json()["status"], gone.json()["settlement"]["refund_minor"]) == ("canceled", 11340)
    # The cottage is free again.
    assert quoted(client, configured).status_code == 200


def test_a_stay_taken_on_request_waits_for_the_companys_answer() -> None:
    configured = selling("pobyt-prosba", confirmation="on_request", response_hours=12)
    owner = configured["owner"]
    client = APIClient()

    (listed,) = client.get(f"{configured['url']}/").json()["stays"]
    assert (listed["confirmation"], listed["response_hours"]) == ("on_request", 12)
    quote = quoted(client, configured).json()["quote"]
    made = booked(client, configured, quote_digest=quote["digest"])
    assert made.status_code == 201, made.data
    stay = made.json()
    assert (stay["status"], stay["payment"]) == ("pending_request", None)
    assert stay["hold_expires_at"] is not None
    with tenant(owner):
        saved = Appointment.all_objects.get(pk=stay["id"])
        order = order_of(saved)
        # A request's order is a draft without a number until the company says yes.
        assert order is not None and (order.status, order.number) == ("draft", "")
    # The request holds the cottage meanwhile.
    held = quoted(client, configured)
    assert (held.status_code, held.json()["code"]) == (409, "slot_unavailable")
    # A waiting booking is given up, not moved.
    link = f"/api/v1/booking/self-service/{stay['self_service_token']}"
    move = client.post(
        f"{link}/stay/preview/",
        {
            "start_date": (configured["first"] + timedelta(days=7)).isoformat(),
            "end_date": (configured["first"] + timedelta(days=9)).isoformat(),
        },
        format="json",
    )
    assert move.status_code == 404
