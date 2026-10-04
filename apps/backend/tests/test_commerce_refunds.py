"""Refund thresholds, refunds marked by hand and the balance due by a transfer
(ADR-072 §8, ADR-073 §5 and §8, phase 4h): an offer's thresholds frozen in the
booking, what giving a booking up gives back, the refund the company marks in
the ledger, and the rest of a price that is reminded of and reported late but
cancels nothing."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.billing.authorization import EntitlementRequired
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking import orders as booking_orders
from saas_core.modules.shared.booking.cancellation import refund
from saas_core.modules.shared.booking.models import Appointment, AppointmentStatusHistory, Service
from saas_core.modules.shared.booking.presets import _catalogue, _refund_terms, apply_preset
from saas_core.modules.shared.booking.security import public_booking_context
from saas_core.modules.shared.booking.services import (
    anonymize_customer,
    cancel_appointment,
    reschedule_appointment,
)
from saas_core.modules.shared.booking.setup import save_service
from saas_core.modules.shared.commerce.models import LedgerEntry, Payment, PaymentRoute, Refund
from saas_core.modules.shared.commerce.orders import read_order
from saas_core.modules.shared.commerce.payments import OrderVersionConflict, record_payment
from saas_core.modules.shared.commerce.refunds import record_refund, void_refund
from saas_core.modules.shared.commerce.tasks import expire_due_payments
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from test_booking import _no_delivery, company_today, tenant
from test_booking_prices import add, key
from test_booking_slots import team
from test_commerce_orders import order_of, visit, with_orders
from test_commerce_prepayments import account, at, awaited, codes, policy, prepaid
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db

WARSAW = ZoneInfo("Europe/Warsaw")
#: A booking of these tests starts 8–14 days ahead (`at`): half comes back.
THRESHOLDS = [
    {"min_days_before": 30, "refund_percent": 100},
    {"min_days_before": 3, "refund_percent": 50},
]


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def with_terms(slug: str, **data: Any) -> dict[str, Any]:
    """A company whose visit at 150 asks for 30% ahead and gives half of it
    back to whoever gives the booking up between 3 and 29 days before."""
    return prepaid(
        slug,
        **{
            "payment_policy": "deposit",
            "deposit_percent": 30,
            "cancellation_refunds": THRESHOLDS,
            **data,
        },
    )


def confirmed(configured: dict[str, Any], *, amount: int = 4500) -> Appointment:
    """A booking whose prepayment the company marked, inside the tenant."""
    booked = visit(configured, at(configured))
    order = order_of(booked)
    assert order is not None
    record_payment(order.id, amount_minor=amount, method="transfer", expected_version=2)
    booked.refresh_from_db()
    assert booked.status == "confirmed"
    return booked


def given_up(owner: Membership, booked: Appointment) -> Appointment:
    """The customer gives the booking up from their link."""
    with public_booking_context(owner.organization_id):
        return cancel_appointment(
            appointment_id=booked.id, idempotency_key=key(), principal_ref="guest"
        )


def mail(template: str) -> list[NotificationMessage]:
    return list(NotificationMessage.all_objects.filter(template_key=template).order_by("id"))


def moved_to(order_id: Any, when: datetime, *, payment: bool = False) -> None:
    """The deadlines' task is to look at the order's awaited payment at
    `when`; with `payment`, that is the payment's own date too."""
    waiting = Payment.all_objects.filter(order_id=order_id, status="requires_payment")
    PaymentRoute.objects.filter(payment_id__in=waiting.values("id")).update(due_at=when)
    if payment:
        waiting.update(due_at=when)


def test_whole_days_of_the_companys_calendar_pick_the_threshold() -> None:
    starts = datetime(2027, 6, 30, 16, 0, tzinfo=WARSAW)
    quote = {
        "prepayment": {"kind": "deposit", "amount_minor": 3000},
        "cancellation": {
            "applies_to": "deposit",
            "refunds": [
                {"min_days_before": 30, "refund_percent": 100},
                {"min_days_before": 14, "refund_percent": 50},
            ],
        },
    }

    def back(day: int, month: int = 6, *, paid: int = 3000, **changes: Any) -> tuple[int, int, int]:
        # Late in the evening: a day of the calendar, not 24 hours.
        now = datetime(2027, month, day, 23, 30, tzinfo=WARSAW)
        frozen = {**quote, "cancellation": {**quote["cancellation"], **changes}}
        result = refund(frozen, paid_minor=paid, starts_at=starts, zone="Europe/Warsaw", now=now)
        return result.refund_minor, result.percent, result.days_before

    assert back(31, 5) == (3000, 100, 30)
    assert back(1) == (1500, 50, 29)
    assert back(16) == (1500, 50, 14)
    # Less notice than the last threshold gives nothing back.
    assert back(17) == (0, 0, 13)
    # The thresholds cover the prepayment; the rest the customer paid comes
    # back whole (owner decision 28a) — unless the offer said „everything”.
    assert back(16, paid=10000) == (1500 + 7000, 50, 14)
    assert back(16, paid=10000, applies_to="paid") == (5000, 50, 14)
    assert back(17, paid=10000) == (7000, 0, 13)
    # Halves go up, as the prepayment itself is rounded.
    assert back(16, paid=10001, applies_to="paid")[0] == 5001
    # No thresholds: everything paid goes back.
    assert refund(
        {"prepayment": None}, paid_minor=4500, starts_at=starts, zone="Europe/Warsaw", now=starts
    ) == refund(None, paid_minor=4500, starts_at=starts, zone="Europe/Warsaw", now=starts)


def test_an_offers_thresholds_are_kept_in_order_and_frozen_in_the_booking() -> None:
    configured = with_terms("progi-oferta")
    owner: Membership = configured["owner"]
    service: Service = configured["service"]

    def save(**data: Any) -> Service:
        with tenant(owner):
            return save_service(
                service_id=service.id,
                data=data,
                expected_version=Service.all_objects.get(pk=service.id).version,
                idempotency_key=key(),
            ).value.service

    with pytest.raises(ValidationError) as rising:
        save(
            cancellation_refunds=[
                {"min_days_before": 30, "refund_percent": 50},
                {"min_days_before": 14, "refund_percent": 80},
            ]
        )
    with pytest.raises(ValidationError) as twice:
        save(
            cancellation_refunds=[
                {"min_days_before": 14, "refund_percent": 50},
                {"min_days_before": 14, "refund_percent": 40},
            ]
        )
    # Given in any order, kept with the longest notice first.
    saved = save(cancellation_refunds=list(reversed(THRESHOLDS)))

    assert codes(rising) == [("cancellation_refunds", "thresholds_not_descending")]
    assert codes(twice) == [("cancellation_refunds", "duplicate_threshold")]
    assert saved.cancellation_refunds == THRESHOLDS
    assert saved.cancellation_applies_to == "deposit"

    with tenant(owner):
        booked = visit(configured, at(configured))
    # The terms the customer books under travel with the booking.
    assert booked.quote["cancellation"] == {"applies_to": "deposit", "refunds": THRESHOLDS}

    # Without a part paid ahead there is only „everything paid” to count on;
    # an offer without thresholds freezes none and keeps its quote's digest.
    whole = save(payment_policy="full")
    with tenant(owner):
        other = visit(configured, at(configured, hour=12))
        plain = save(cancellation_refunds=[])
        bare = visit(configured, at(configured, hour=14))
    assert whole.cancellation_applies_to == "deposit"
    assert other.quote["cancellation"]["applies_to"] == "paid"
    assert plain.cancellation_refunds == [] and bare.quote["cancellation"] is None


def test_the_options_say_what_a_threshold_may_be_and_a_preset_brings_its_own() -> None:
    _, owner, client = authenticated_member(
        email="progi-opcje@example.test", role_key="owner", slug="progi-opcje"
    )
    bookable(owner.organization)
    options = client.get("/api/v1/booking/setup/options/").json()
    keys = {item["key"]: item for item in options["keys"]}

    assert options["refund_thresholds"] == {
        "max_rows": 6,
        "min_days_before": {"minimum": 0, "maximum": 365},
        "refund_percent": {"minimum": 0, "maximum": 100},
    }
    assert options["cancel_reasons"] == ["balance_overdue"]
    assert keys["booking.offer.balance_due_days_before"]["default"] is None
    assert keys["booking.offer.cancellation_applies_to"]["default"] == "deposit"
    assert keys["booking.offer.cancellation_applies_to"]["depends_on"] == (
        "booking.offer.payment_policy == 'deposit'"
    )

    # A preset that names refund terms brings them to the offer it starts —
    # the first lodging preset does (30 days: all, 14: half, then nothing).
    first_lodging = dict(_catalogue())["core.lodging"][1]
    assert _refund_terms(first_lodging) == {
        "cancellation_applies_to": "deposit",
        "cancellation_refunds": [
            {"min_days_before": 30, "refund_percent": 100},
            {"min_days_before": 14, "refund_percent": 50},
            {"min_days_before": 0, "refund_percent": 0},
        ],
    }
    # The one in use today names none: its offer starts without thresholds.
    with tenant(owner):
        lodging = apply_preset(
            preset_id="core.lodging", name="Domek", idempotency_key=key()
        ).value.service
    assert lodging.cancellation_refunds == [] and lodging.balance_due_days_before is None


def test_a_customer_who_gives_up_gets_back_what_the_thresholds_give(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = with_terms("progi-rezygnacja")
    owner: Membership = configured["owner"]

    with django_capture_on_commit_callbacks(execute=True):
        with tenant(owner):
            booked = confirmed(configured)
            order = order_of(booked)
            assert order is not None
            before = booking_orders.settlement(booked)
        given_up(owner, booked)
        with tenant(owner):
            after = read_order(order.id)
            audit = OrganizationAuditEntry.objects.get(action="commerce.order.canceled")
            settled = booking_orders.settlement(Appointment.all_objects.get(pk=booked.id))

    # Asked before anybody decides: half of the prepayment would come back.
    assert before is not None and before["paid_minor"] == 4500
    assert (before["by_terms"]["refund_minor"], before["by_terms"]["percent"]) == (2250, 50)
    assert 8 <= before["by_terms"]["days_before"] <= 14
    assert before["balance_overdue"] is False and before["refund_owed_minor"] == 0
    # The order remembers what is owed; the money stays paid until the
    # company gives it back.
    assert (after["status"], after["paid_minor"]) == ("canceled", 4500)
    assert (after["refund_owed_minor"], after["refunded_minor"], after["refunds"]) == (2250, 0, [])
    assert (audit.metadata["paid_minor"], audit.metadata["refund_minor"]) == (4500, 2250)
    assert settled is not None and settled["refund_owed_minor"] == 2250
    # The customer is told both numbers.
    (told,) = mail("commerce.refund_settled")
    assert told.recipient_email == "gosc@example.test"
    assert (told.context["paid"], told.context["refund"]) == ("45,00 PLN", "22,50 PLN")


def test_the_company_calling_off_gives_everything_back_and_a_waiting_booking_too() -> None:
    configured = with_terms("progi-firma")
    owner: Membership = configured["owner"]

    with tenant(owner):
        booked = confirmed(configured)
        order = order_of(booked)
        assert order is not None
        with pytest.raises(ValidationError) as early:
            cancel_appointment(
                appointment_id=booked.id,
                idempotency_key=key(),
                principal_ref="office",
                reason="balance_overdue",
            )
        cancel_appointment(appointment_id=booked.id, idempotency_key=key(), principal_ref="office")
        called_off = read_order(order.id)
        # A booking that still waits for the rest of its prepayment was never
        # confirmed: a customer who gives it up gets the part they paid back.
        waiting = visit(configured, at(configured, hour=12))
        second = order_of(waiting)
        assert second is not None
        record_payment(second.id, amount_minor=2000, method="transfer", expected_version=2)
    given_up(owner, waiting)
    with tenant(owner):
        never_confirmed = read_order(second.id)

    assert codes(early) == [("reason", "balance_not_overdue")]
    assert (called_off["paid_minor"], called_off["refund_owed_minor"]) == (4500, 4500)
    assert (never_confirmed["paid_minor"], never_confirmed["refund_owed_minor"]) == (2000, 2000)


def test_the_company_marks_the_refund_and_takes_a_mistake_back() -> None:
    configured = with_terms("zwrot-reczny")
    owner: Membership = configured["owner"]

    with tenant(owner):
        booked = confirmed(configured)
        order = order_of(booked)
        assert order is not None
    given_up(owner, booked)
    with tenant(owner):
        version = read_order(order.id)["version"]
        preview = record_refund(
            order.id, amount_minor=2250, method="transfer", expected_version=version, preview=True
        )
        assert not Refund.all_objects.exists()
        with pytest.raises(ValidationError) as too_much:
            record_refund(order.id, amount_minor=4501, method="cash", expected_version=version)
        with pytest.raises(ValidationError) as unexplained:
            record_refund(order.id, amount_minor=3000, method="cash", expected_version=version)
        with pytest.raises(ValidationError) as online:
            record_refund(order.id, amount_minor=2250, method="online", expected_version=version)
        back = record_refund(
            order.id, amount_minor=2250, method="transfer", expected_version=version
        )
        with pytest.raises(OrderVersionConflict):
            record_refund(order.id, amount_minor=2250, method="transfer", expected_version=version)
        entries = list(
            LedgerEntry.all_objects.filter(order=order)
            .order_by("occurred_at", "id")
            .values_list("kind", "amount_minor")
        )
        # Beyond the terms the company says why, in its own words.
        kind = record_refund(
            order.id,
            amount_minor=1000,
            method="cash",
            reason="  Stały klient  ",
            expected_version=back["version"],
        )
        undone = void_refund(order.id, kind["refunds"][-1]["id"], expected_version=kind["version"])
        with pytest.raises(ValidationError) as again:
            void_refund(order.id, kind["refunds"][-1]["id"], expected_version=undone["version"])
        with pytest.raises(NotFound):
            void_refund(order.id, order.id, expected_version=undone["version"])
        audits = list(
            OrganizationAuditEntry.objects.filter(action__startswith="commerce.refund.")
            .order_by("occurred_at", "id")
            .values_list("action", "metadata")
        )

    assert preview == {
        "amount_minor": 2250,
        "paid_minor": 2250,
        "refund_owed_minor": 0,
        "status": "canceled",
        "reason_required": False,
    }
    assert codes(too_much) == [("amount_minor", "refund_exceeds_paid")]
    assert codes(unexplained) == [("reason", "reason_required")]
    assert codes(online) == [("method", "method_not_manual")]
    assert (back["paid_minor"], back["refunded_minor"], back["refund_owed_minor"]) == (
        2250,
        2250,
        0,
    )
    assert entries == [("charge", 4500), ("refund", -2250)]
    (first,) = back["refunds"]
    assert (first["status"], first["method"], first["amount_minor"], first["reason"]) == (
        "succeeded",
        "transfer",
        2250,
        "",
    )
    assert first["recorded_by"]
    assert (kind["paid_minor"], kind["refunds"][-1]["reason"]) == (1250, "Stały klient")
    # Taken back, it stays in the history and the money is the order's again.
    assert (undone["paid_minor"], undone["refunded_minor"]) == (2250, 2250)
    assert [row["status"] for row in undone["refunds"]] == ["succeeded", "canceled"]
    assert codes(again) == [("refund", "refund_not_voidable")]
    assert [action for action, _ in audits] == [
        "commerce.refund.recorded",
        "commerce.refund.recorded",
        "commerce.refund.voided",
    ]
    # The company's words stay on the order's page: the history has none.
    assert all("klient" not in str(metadata) for _, metadata in audits)

    # They may name the customer, so they go when the customer does; the
    # amounts stay.
    with tenant(owner):
        anonymize_customer(booked.customer_id)
        kept = list(Refund.all_objects.filter(order=order).values_list("reason", "amount_minor"))
    assert sorted(kept) == [("", 1000), ("", 2250)]


def test_only_whoever_marks_payments_marks_refunds_and_only_of_their_own_orders() -> None:
    configured = with_terms("zwrot-kto")
    owner: Membership = configured["owner"]
    other = with_terms("zwrot-kto-obca")

    with tenant(other["owner"]):
        foreign = order_of(confirmed(other))
        assert foreign is not None
    with tenant(owner):
        order = order_of(confirmed(configured))
        assert order is not None
        version = read_order(order.id)["version"]
        # Another company's order is not there.
        with pytest.raises(NotFound):
            record_refund(foreign.id, amount_minor=100, method="cash", expected_version=version)

    # A plan from before orders.
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    features = dict(snapshot.features)
    snapshot.features = {"booking.enabled": True}
    snapshot.save(update_fields=["features"])
    with tenant(owner), pytest.raises(EntitlementRequired):
        record_refund(order.id, amount_minor=100, method="cash", expected_version=version)
    snapshot.features = features
    snapshot.save(update_fields=["features"])

    # Somebody who works in the calendar marks no refunds.
    Membership.objects.filter(pk=owner.pk).update(
        role=Role.objects.get(key="staff", organization=None, organization_type="")
    )
    owner.refresh_from_db()
    with tenant(owner):
        for attempt in (
            lambda: record_refund(
                order.id, amount_minor=100, method="cash", reason="x", expected_version=version
            ),
            lambda: void_refund(order.id, order.id, expected_version=version),
        ):
            with pytest.raises(OrganizationPermissionDenied):
                attempt()
    assert not Refund.all_objects.exists()


def test_the_rest_due_by_a_transfer_is_planned_reminded_of_and_reported_late(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = with_terms("doplata-termin", balance_due_days_before=2)
    owner: Membership = configured["owner"]

    with django_capture_on_commit_callbacks(execute=True), tenant(owner):
        booked = confirmed(configured)
        order = order_of(booked)
        assert order is not None
        balance = awaited(order)
        route = PaymentRoute.objects.get(payment_id=balance.id)
        planned = read_order(order.id)

    # The prepayment came: the rest waits for a transfer two days before the
    # start, and the task first looks three days before that, to remind.
    assert booked.quote["prepayment"]["balance_due_days_before"] == 2
    assert (balance.kind, balance.method, balance.amount_minor) == ("balance", "transfer", 10500)
    assert balance.due_at == booked.starts_at - timedelta(days=2)
    assert route.due_at == balance.due_at - timedelta(days=3)
    assert (planned["status"], planned["due_minor"]) == ("partially_paid", 10500)
    (details,) = mail("commerce.balance_details")
    assert details.recipient_email == "gosc@example.test"
    assert details.context["amount"] == "105,00 PLN"
    assert "/booking/bk_" in details.context["manage_url"]

    # The reminder's day: the same details once more, and the task comes back
    # at the date itself.
    moved_to(order.id, timezone.now() - timedelta(minutes=1))
    with django_capture_on_commit_callbacks(execute=True):
        assert expire_due_payments() == 0
    route.refresh_from_db()
    assert (route.due_at, route.dispatched_at) == (balance.due_at, None)
    assert len(mail("commerce.balance_details")) == 2

    # The date passes unpaid: the customer and the company are told, and
    # nothing is called off (owner decision 29a).
    moved_to(order.id, timezone.now() - timedelta(minutes=1), payment=True)
    with django_capture_on_commit_callbacks(execute=True):
        assert expire_due_payments() == 0
        assert expire_due_payments() == 0
    route.refresh_from_db()
    booked.refresh_from_db()
    with tenant(owner):
        late = read_order(order.id)
        money = booking_orders.settlement(booked)
        notices = list(AppNotification.all_objects.filter(kind="commerce.balance_overdue"))
        audit = OrganizationAuditEntry.objects.get(action="commerce.balance.overdue")
    assert route.dispatched_at is not None
    assert (booked.status, late["status"]) == ("confirmed", "partially_paid")
    assert [row["status"] for row in late["payments"]] == ["succeeded", "requires_payment"]
    assert len(mail("commerce.balance_overdue")) == 1
    (office_mail,) = mail("commerce.office_balance_overdue")
    assert office_mail.recipient_email == owner.user.email
    assert f"/panel/orders/{order.id}" in office_mail.context["panel_url"]
    (notice,) = notices
    assert (notice.user_id, notice.payload["number"], notice.payload["amount_minor"]) == (
        owner.user_id,
        late["number"],
        10500,
    )
    assert "gosc" not in str(notice.payload) and "gosc" not in str(audit.metadata)
    assert money is not None and money["balance_overdue"] is True

    # Only now may the company call the booking off for it — and the
    # prepayment is then settled by the thresholds, as if the customer had
    # given up.
    with django_capture_on_commit_callbacks(execute=True), tenant(owner):
        cancel_appointment(
            appointment_id=booked.id,
            idempotency_key=key(),
            principal_ref="office",
            reason="balance_overdue",
        )
        settled = read_order(order.id)
        history = AppointmentStatusHistory.all_objects.filter(
            appointment=booked, to_status="canceled"
        ).get()
    assert (settled["status"], settled["refund_owed_minor"]) == ("canceled", 2250)
    assert [row["status"] for row in settled["payments"]] == ["succeeded", "canceled"]
    assert history.reason == "balance_overdue"
    assert not PaymentRoute.objects.filter(payment_id=balance.id).exists()


def test_the_balance_is_the_payment_the_company_marks_and_follows_a_moved_booking() -> None:
    configured = with_terms("doplata-wplata", balance_due_days_before=2)
    owner: Membership = configured["owner"]

    with tenant(owner):
        booked = confirmed(configured)
        order = order_of(booked)
        assert order is not None
        first = awaited(order)
        # Moved to the next day, a Tuesday at 180: the rest and its date follow.
        reschedule_appointment(
            appointment_id=booked.id,
            starts_at=booked.starts_at + timedelta(days=1),
            idempotency_key=key(),
            principal_ref="office",
        )
        moved = awaited(order)
        route = PaymentRoute.objects.get(payment_id=moved.id)
        # A part of it leaves the rest awaited; the rest marks the row that waited.
        part = record_payment(
            order.id,
            amount_minor=3500,
            method="transfer",
            expected_version=read_order(order.id)["version"],
        )
        rest = awaited(order).amount_minor
        paid = record_payment(
            order.id, amount_minor=10000, method="transfer", expected_version=part["version"]
        )
        booked.refresh_from_db()

    assert moved.id == first.id
    assert (moved.amount_minor, moved.due_at) == (13500, booked.starts_at - timedelta(days=2))
    assert route.due_at == moved.due_at - timedelta(days=3) and route.dispatched_at is None
    assert rest == 10000
    assert (paid["status"], paid["due_minor"], booked.status) == ("paid", 0, "confirmed")
    assert not Payment.all_objects.filter(order=order, status="requires_payment").exists()
    assert not PaymentRoute.objects.filter(payment_id=first.id).exists()
    assert len(mail("commerce.balance_details")) == 2


def test_the_company_sets_the_reminder_and_a_rest_due_on_site_plans_nothing() -> None:
    configured = with_terms("doplata-ustawienie", balance_due_days_before=2)
    owner: Membership = configured["owner"]
    with tenant(owner):
        change_settings(
            "commerce.balance",
            changes={"remind_days_before": 0},
            expected_version=read_group("commerce.balance").version,
            idempotency_key=key(),
        )
        order = order_of(confirmed(configured))
        assert order is not None
        balance = awaited(order)
        route = PaymentRoute.objects.get(payment_id=balance.id)
    # The task looks at the date itself only.
    assert route.due_at == balance.due_at

    # An offer whose rest is due on site plans nothing — as before 4h.
    plain = with_terms("doplata-na-miejscu")
    with tenant(plain["owner"]):
        order = order_of(confirmed(plain))
        assert order is not None
    assert not Payment.all_objects.filter(order=order, status="requires_payment").exists()


def test_the_panel_settles_and_refunds_over_the_api() -> None:
    _, owner, client = authenticated_member(
        email="zwrot-api@example.test", role_key="owner", slug="zwrot-api"
    )
    configured = office_of(owner)
    with_orders(owner.organization_id)
    account(owner)
    policy(
        configured,
        payment_policy="deposit",
        deposit_percent=30,
        cancellation_refunds=THRESHOLDS,
    )
    with tenant(owner):
        booked = confirmed(configured)
        order = order_of(booked)
        assert order is not None

    def send(path: str, body: dict[str, Any] | None = None) -> Any:
        return client.post(
            path,
            body or {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=key(),
        )

    service = client.get("/api/v1/booking/setup/").json()["services"][0]
    assert service["cancellation_refunds"] == THRESHOLDS
    assert (service["cancellation_applies_to"], service["balance_due_days_before"]) == (
        "deposit",
        None,
    )
    settlement = client.get(f"/api/v1/booking/appointments/{booked.id}/settlement/").json()
    assert settlement["settlement"]["by_terms"]["refund_minor"] == 2250
    wrong = send(f"/api/v1/booking/appointments/{booked.id}/cancel/", {"reason": "weather"})
    assert wrong.status_code == 400
    early = send(f"/api/v1/booking/appointments/{booked.id}/cancel/", {"reason": "balance_overdue"})
    assert (early.status_code, early.json()["errors"][0]["code"]) == (400, "balance_not_overdue")
    gone = send(f"/api/v1/booking/appointments/{booked.id}/cancel/")
    assert gone.status_code == 200, gone.data

    read = client.get(f"/api/v1/commerce/orders/{order.id}/").json()
    assert (read["refund_owed_minor"], read["refunded_minor"]) == (4500, 0)
    url = f"/api/v1/commerce/orders/{order.id}/refunds/"
    body = {"amount_minor": 4500, "method": "transfer", "expected_version": read["version"]}
    assert client.post(url, body, format="json").status_code == 403  # No CSRF token.
    preview = send(f"{url}preview/", body)
    assert (preview.status_code, preview.json()["reason_required"]) == (200, False)
    made = send(url, body)
    assert made.status_code == 201, made.data
    answer = made.json()
    assert (answer["paid_minor"], answer["refund_owed_minor"]) == (0, 0)
    stale = send(url, body)
    assert (stale.status_code, stale.json()["code"]) == (409, "order_version_conflict")
    void = f"{url}{answer['refunds'][0]['id']}/void/"
    back = send(void, {"expected_version": answer["version"]})
    assert back.status_code == 200, back.data
    assert (back.json()["paid_minor"], back.json()["refund_owed_minor"]) == (4500, 4500)


def test_the_customers_link_says_what_giving_up_gives_back() -> None:
    configured = with_terms("progi-link")
    owner: Membership = configured["owner"]
    client = APIClient()

    with tenant(owner):
        booked = confirmed(configured)
        link = booking_orders._link(order_of(booked))
    token = link.rsplit("/", 1)[1]

    seen = client.get(f"/api/v1/booking/self-service/{token}/").json()
    assert seen["quote"]["cancellation"] == {"applies_to": "deposit", "refunds": THRESHOLDS}
    assert seen["settlement"] == {"currency": "PLN", "paid_minor": 4500, "refund_minor": 2250}
    gone = client.post(
        f"/api/v1/booking/self-service/{token}/cancel/", format="json", HTTP_IDEMPOTENCY_KEY=key()
    )
    assert gone.status_code == 200, gone.data
    # Afterwards: what the company is still to give back.
    assert gone.json()["settlement"] == {
        "currency": "PLN",
        "paid_minor": 4500,
        "refund_minor": 2250,
    }
    assert gone.json()["payment"] is None


def office_of(owner: Membership) -> dict[str, Any]:
    """`office()` for a member who already has a session."""
    bookable(owner.organization)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
        add(18000, service_id=configured["service"].id, weekdays=[1])
    configured["owner"] = owner
    today = company_today()
    configured["monday"] = today + timedelta(days=7 - today.weekday())
    return configured
