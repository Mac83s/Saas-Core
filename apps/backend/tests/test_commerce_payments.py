"""What a customer paid for an order (ADR-073 §4–§5, phase 4f-1): the company
marks a payment it received, the ledger says what was paid and the order's
status follows; a mark made by mistake is taken back with the opposite entry;
nothing in the ledger is ever rewritten."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.shared.billing.authorization import EntitlementRequired
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.services import (
    anonymize_customer,
    cancel_appointment,
    reschedule_appointment,
)
from saas_core.modules.shared.commerce.models import LedgerEntry, Order, Payment
from saas_core.modules.shared.commerce.orders import read_order
from saas_core.modules.shared.commerce.payments import (
    OrderVersionConflict,
    record_payment,
    void_payment,
)
from test_booking import _no_delivery, company_today, tenant
from test_booking_prices import add, key
from test_booking_quote import WARSAW
from test_booking_slots import team
from test_commerce_orders import office, order_of, visit, with_orders
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def ordered(slug: str) -> tuple[dict[str, Any], Order]:
    """A company's visit at 150 with its order, to be paid."""
    configured = office(slug)
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    with tenant(configured["owner"]):
        booked = visit(configured, starts)
        order = order_of(booked)
    assert order is not None
    configured["visit"] = booked
    return configured, order


def codes(refused: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str | None, str | None]]:
    return [(error["field"], error["code"]) for error in problem_errors(refused.value)]


def test_a_payment_at_the_desk_settles_the_order_and_is_written_in_the_ledger() -> None:
    configured, order = ordered("wplaty-calosc")
    owner: Membership = configured["owner"]

    with tenant(owner):
        seen = record_payment(
            order.id, amount_minor=15000, method="cash", expected_version=1, preview=True
        )
        untouched = (Payment.all_objects.count(), LedgerEntry.all_objects.count())
        paid = record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
        entry = LedgerEntry.all_objects.get(order_id=order.id)
        audit = OrganizationAuditEntry.objects.get(action="commerce.payment.recorded")

    # The preview says what the write then does, and writes nothing.
    assert seen == {
        "amount_minor": 15000,
        "paid_minor": 15000,
        "due_minor": 0,
        "status": "paid",
        "prepayment_met": False,
    }
    assert untouched == (0, 0)
    assert (paid["status"], paid["paid_minor"], paid["due_minor"], paid["version"]) == (
        "paid",
        15000,
        0,
        2,
    )
    (payment,) = paid["payments"]
    assert (payment["kind"], payment["method"], payment["status"], payment["amount_minor"]) == (
        "full",
        "cash",
        "succeeded",
        15000,
    )
    assert payment["recorded_by"] == owner.user.email and payment["paid_at"] is not None
    assert (entry.kind, entry.amount_minor, entry.currency, entry.payment_id) == (
        "charge",
        15000,
        "PLN",
        payment["id"],
    )
    # The history names the order and the amount, never the buyer.
    assert (audit.target_type, audit.target_id) == ("order", order.id)
    assert audit.metadata == {
        "number": order.number,
        "amount_minor": 15000,
        "currency": "PLN",
        "method": "cash",
    }


def test_a_part_and_then_the_rest_and_never_more_than_is_left() -> None:
    configured, order = ordered("wplaty-czesci")

    with tenant(configured["owner"]):
        part = record_payment(order.id, amount_minor=5000, method="transfer", expected_version=1)
        with pytest.raises(ValidationError) as too_much:
            record_payment(order.id, amount_minor=10001, method="cash", expected_version=2)
        rest = record_payment(order.id, amount_minor=10000, method="cash", expected_version=2)
        with pytest.raises(ValidationError) as nothing_left:
            record_payment(order.id, amount_minor=1, method="cash", expected_version=3)

    assert (part["status"], part["paid_minor"], part["due_minor"]) == (
        "partially_paid",
        5000,
        10000,
    )
    assert codes(too_much) == codes(nothing_left) == [("amount_minor", "amount_exceeds_due")]
    assert (rest["status"], rest["paid_minor"], rest["due_minor"]) == ("paid", 15000, 0)
    assert [(row["kind"], row["method"], row["amount_minor"]) for row in rest["payments"]] == [
        ("deposit", "transfer", 5000),
        ("balance", "cash", 10000),
    ]


def test_a_repeat_at_the_version_first_seen_marks_nothing_twice() -> None:
    configured, order = ordered("wplaty-wersja")

    with tenant(configured["owner"]):
        record_payment(order.id, amount_minor=5000, method="cash", expected_version=1)
        # The same request again — a retry, or a second person at the desk.
        with pytest.raises(OrderVersionConflict):
            record_payment(order.id, amount_minor=5000, method="cash", expected_version=1)
        with pytest.raises(OrderVersionConflict):
            record_payment(
                order.id, amount_minor=5000, method="cash", expected_version=1, preview=True
            )
        after = read_order(order.id)

    assert (after["paid_minor"], len(after["payments"])) == (5000, 1)


def test_a_payment_marked_by_mistake_is_taken_back_and_stays_in_the_history() -> None:
    configured, order = ordered("wplaty-wycofanie")

    with tenant(configured["owner"]):
        paid = record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
        payment_id = paid["payments"][0]["id"]
        with pytest.raises(OrderVersionConflict):
            void_payment(order.id, payment_id, expected_version=1)
        back = void_payment(order.id, payment_id, expected_version=2)
        with pytest.raises(ValidationError) as twice:
            void_payment(order.id, payment_id, expected_version=3)
        with pytest.raises(NotFound):
            void_payment(order.id, order.id, expected_version=3)
        entries = list(
            LedgerEntry.all_objects.filter(order_id=order.id).order_by("created_at", "id")
        )
        again = record_payment(order.id, amount_minor=15000, method="transfer", expected_version=3)
        audit = OrganizationAuditEntry.objects.get(action="commerce.payment.voided")

    assert (back["status"], back["paid_minor"], back["due_minor"]) == ("awaiting_payment", 0, 15000)
    assert [(row["status"], row["amount_minor"]) for row in back["payments"]] == [
        ("canceled", 15000)
    ]
    # The ledger keeps both entries; their sum is what was paid.
    assert [(entry.kind, entry.amount_minor) for entry in entries] == [
        ("charge", 15000),
        ("charge", -15000),
    ]
    assert codes(twice) == [("payment", "payment_not_voidable")]
    assert (again["status"], [row["status"] for row in again["payments"]]) == (
        "paid",
        ["canceled", "succeeded"],
    )
    assert audit.metadata["amount_minor"] == 15000


def test_what_was_paid_stays_paid_when_the_booking_moves_or_is_canceled() -> None:
    configured, order = ordered("wplaty-przeniesienie")
    booked = configured["visit"]
    monday = booked.starts_at

    with tenant(configured["owner"]):
        record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
        # Tuesday costs 180: the order is no longer paid in full.
        reschedule_appointment(
            appointment_id=booked.id,
            starts_at=monday + timedelta(days=1),
            idempotency_key=key(),
            principal_ref="test",
        )
        dearer = read_order(order.id)
        # Back to Monday's 150.
        reschedule_appointment(
            appointment_id=booked.id,
            starts_at=monday + timedelta(hours=2),
            idempotency_key=key(),
            principal_ref="test",
        )
        cheaper = read_order(order.id)
        cancel_appointment(appointment_id=booked.id, idempotency_key=key(), principal_ref="test")
        canceled = read_order(order.id)
        with pytest.raises(ValidationError) as refused:
            record_payment(
                order.id, amount_minor=1, method="cash", expected_version=canceled["version"]
            )

    assert (dearer["status"], dearer["gross_minor"], dearer["paid_minor"], dearer["due_minor"]) == (
        "partially_paid",
        18000,
        15000,
        3000,
    )
    assert (cheaper["status"], cheaper["due_minor"]) == ("paid", 0)
    # A canceled order keeps what was paid for it — to be given back — and takes no more.
    assert (canceled["status"], canceled["paid_minor"], canceled["due_minor"]) == (
        "canceled",
        15000,
        0,
    )
    assert codes(refused) == [("order", "order_canceled")]


def test_only_a_payment_the_company_marks_itself_and_only_whoever_may() -> None:
    configured, order = ordered("wplaty-kto")
    owner: Membership = configured["owner"]
    other, foreign = ordered("wplaty-kto-obca")

    with tenant(owner):
        with pytest.raises(ValidationError) as online:
            record_payment(order.id, amount_minor=15000, method="online", expected_version=1)
        # Another company's order is not there.
        with pytest.raises(NotFound):
            record_payment(foreign.id, amount_minor=15000, method="cash", expected_version=1)
    assert codes(online) == [("method", "method_not_manual")]

    # A plan from before orders.
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    snapshot.features = {"booking.enabled": True}
    snapshot.save(update_fields=["features"])
    with tenant(owner), pytest.raises(EntitlementRequired):
        record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
    with_orders(owner.organization_id)

    # Somebody who works in the calendar does not mark payments.
    Membership.objects.filter(pk=owner.pk).update(
        role=Role.objects.get(key="staff", organization=None, organization_type="")
    )
    owner.refresh_from_db()
    with tenant(owner):
        for attempt in (
            lambda: record_payment(order.id, amount_minor=15000, method="cash", expected_version=1),
            lambda: void_payment(order.id, order.id, expected_version=1),
        ):
            with pytest.raises(OrganizationPermissionDenied):
                attempt()
    assert not Payment.all_objects.exists() and not LedgerEntry.all_objects.exists()
    assert other["owner"].organization_id != owner.organization_id


def test_the_ledger_is_never_rewritten_and_goes_only_with_the_company() -> None:
    configured, order = ordered("wplaty-ksiega")
    owner: Membership = configured["owner"]
    other, foreign = ordered("wplaty-ksiega-obca")
    organization_id = owner.organization_id
    with tenant(owner):
        paid = record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
        entry = LedgerEntry.all_objects.get(order_id=order.id)
        payment = Payment.all_objects.get(pk=paid["payments"][0]["id"])
        # The customer goes; what they paid stays, without them.
        anonymize_customer(order.customer_id)
        kept = read_order(order.id)

    for change in (
        lambda: LedgerEntry.all_objects.filter(pk=entry.pk).update(amount_minor=1),
        lambda: LedgerEntry.all_objects.filter(pk=entry.pk).delete(),
        # An entry or a payment that points into another company.
        lambda: LedgerEntry.all_objects.create(
            organization=other["owner"].organization,
            order=order,
            kind="charge",
            amount_minor=1,
            currency="PLN",
            occurred_at=entry.occurred_at,
        ),
        lambda: LedgerEntry.all_objects.create(
            organization=other["owner"].organization,
            order=foreign,
            payment=payment,
            kind="charge",
            amount_minor=1,
            currency="PLN",
            occurred_at=entry.occurred_at,
        ),
        lambda: Payment.all_objects.filter(pk=payment.pk).update(order=foreign),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            change()
    assert (kept["buyer_name"], kept["paid_minor"]) == ("Zanonimizowany klient", 15000)

    erase_organization(organization=owner.organization, requested_by=None, reason="test")

    for model in (Payment, LedgerEntry, Order):
        assert not model.all_objects.filter(organization_id=organization_id).exists()


def test_the_panel_marks_and_takes_back_a_payment_over_the_api() -> None:
    _, owner, client = authenticated_member(
        email="wplaty-api@example.test", role_key="owner", slug="wplaty-api"
    )
    bookable(owner.organization)
    with_orders(owner.organization_id)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    configured["owner"] = owner
    today = company_today()
    starts = datetime.combine(today + timedelta(days=7 - today.weekday()), time(9), WARSAW)
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
        order = order_of(visit(configured, starts))
    assert order is not None
    url = f"/api/v1/commerce/orders/{order.id}/payments/"

    def send(path: str, body: dict[str, Any]) -> Any:
        return client.post(path, body, format="json", HTTP_X_CSRFTOKEN=csrf_value(client))

    options = client.get("/api/v1/commerce/options/").json()
    assert options["manual_methods"] == ["cash", "transfer"]
    body = {"amount_minor": 5000, "method": "transfer", "expected_version": 1}
    assert client.post(url, body, format="json").status_code == 403  # No CSRF token.
    preview = send(f"{url}preview/", body)
    assert (preview.status_code, preview.json()) == (
        200,
        {
            "amount_minor": 5000,
            "paid_minor": 5000,
            "due_minor": 10000,
            "status": "partially_paid",
            "prepayment_met": False,
        },
    )
    made = send(url, body)
    assert made.status_code == 201, made.data
    paid = made.json()
    assert (paid["status"], paid["paid_minor"], paid["due_minor"], paid["version"]) == (
        "partially_paid",
        5000,
        10000,
        2,
    )
    assert client.get(f"/api/v1/commerce/orders/{order.id}/").json() == paid
    listed = client.get("/api/v1/commerce/orders/").json()["items"]
    assert [item["status"] for item in listed] == ["partially_paid"]

    stale = send(url, body)
    assert (stale.status_code, stale.json()["code"]) == (409, "order_version_conflict")
    wrong = send(url, {"amount_minor": 0, "method": "online", "expected_version": 2})
    assert wrong.status_code == 400
    assert {error["field"] for error in wrong.json()["errors"]} == {"amount_minor", "method"}
    too_much = send(url, {"amount_minor": 10001, "method": "cash", "expected_version": 2})
    assert (too_much.status_code, too_much.json()["errors"][0]["code"]) == (
        400,
        "amount_exceeds_due",
    )

    void = f"{url}{paid['payments'][0]['id']}/void/"
    back = send(void, {"expected_version": 2})
    assert back.status_code == 200, back.data
    assert (back.json()["status"], back.json()["due_minor"]) == ("awaiting_payment", 15000)
    assert [row["status"] for row in back.json()["payments"]] == ["canceled"]
    assert send(void, {"expected_version": 2}).status_code == 409
    unknown = "/api/v1/commerce/orders/00000000-0000-7000-8000-000000000000/payments/"
    assert send(unknown, {**body, "expected_version": 1}).status_code == 404
