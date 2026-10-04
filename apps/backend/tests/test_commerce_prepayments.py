"""A transfer with a date (ADR-073 §5, ADR-072 §8–§9, phase 4f-2): the
company's bank account, an offer that asks for money before it confirms, the
booking that waits for it, and which comes first — the payment the company
marks, or the date the deadlines' task keeps."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.identity.step_up import StepUpMfaSetupRequired, activate_step_up
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    require_tenant_context,
)
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking import orders as booking_orders
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    AppointmentStatusHistory,
    ReminderRoute,
    SelfServiceRoute,
    Service,
)
from saas_core.modules.shared.booking.services import anonymize_customer, cancel_appointment
from saas_core.modules.shared.booking.setup import save_service
from saas_core.modules.shared.commerce.api import COMMERCE_ENABLED, transfer_account
from saas_core.modules.shared.commerce.models import Order, Payment, PaymentRoute
from saas_core.modules.shared.commerce.orders import options, read_order
from saas_core.modules.shared.commerce.payments import record_payment, void_payment
from saas_core.modules.shared.commerce.tasks import expire_due_payments
from saas_core.modules.shared.commerce.transfer_account import normalized, valid
from saas_core.modules.shared.notifications.models import NotificationMessage
from test_booking import _no_delivery, company_today, mails, membership, tenant, watching
from test_booking_prices import add, key
from test_booking_public_price import priced
from test_booking_quote import WARSAW, day, priced_cottages
from test_booking_slots import team
from test_booking_stays import stay
from test_commerce_orders import form_booking, office, order_of, send, visit, with_orders
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable

pytestmark = pytest.mark.django_db

ACCOUNT = "61 1090 1014 0000 0712 1981 2874"


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def codes(refused: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str | None, str | None]]:
    return [(error["field"], error["code"]) for error in problem_errors(refused.value)]


def account(owner: Membership, **changes: Any) -> None:
    """The company gives (or changes) its account, with the code a change asks for."""
    values = {"account_holder": "Gabinet Anna Nowak", "account_number": ACCOUNT, **changes}
    with tenant(owner), activate_step_up(int(timezone.now().timestamp())):
        change_settings(
            "commerce.transfer",
            changes=values,
            expected_version=read_group("commerce.transfer").version,
            idempotency_key=key(),
        )


def policy(configured: dict[str, Any], **data: Any) -> Service:
    """The offer's way of paying, set as the panel sets it."""
    service = configured["service"]
    with tenant(configured["owner"]):
        saved = save_service(
            service_id=service.id,
            data=data,
            expected_version=Service.all_objects.get(pk=service.id).version,
            idempotency_key=key(),
        )
    return saved.value.service


def prepaid(slug: str, **data: Any) -> dict[str, Any]:
    """A company with orders and an account whose visit at 150 asks for 30%
    ahead, within three days."""
    configured = office(slug)
    account(configured["owner"])
    policy(configured, **(data or {"payment_policy": "deposit", "deposit_percent": 30}))
    return configured


def at(configured: dict[str, Any], hour: int = 10) -> datetime:
    """The Monday after the coming one: always more than a transfer's three
    days ahead, whatever day the tests run on."""
    return datetime.combine(configured["monday"] + timedelta(days=7), time(hour), WARSAW)


def awaited(order: Order) -> Payment:
    return Payment.all_objects.get(order=order, status="requires_payment")


def past_due(order: Order) -> None:
    """The date of the order's awaited payment has passed."""
    earlier = timezone.now() - timedelta(minutes=1)
    Payment.all_objects.filter(order=order, status="requires_payment").update(due_at=earlier)
    PaymentRoute.objects.filter(
        payment_id__in=Payment.all_objects.filter(order=order).values("id")
    ).update(due_at=earlier)


def test_an_account_number_is_checked_and_read_back_as_people_write_it() -> None:
    assert normalized(" 61 1090-1014 0000 0712 1981 2874 ") == "PL61109010140000071219812874"
    assert valid("PL61109010140000071219812874") and valid("DE89370400440532013000")
    assert not valid("PL61109010140000071219812875") and not valid("PL61")

    configured = office("rachunek-numer")
    owner: Membership = configured["owner"]
    with tenant(owner):
        assert transfer_account() is None and options()["transfer_account_set"] is False
    with pytest.raises(ValidationError) as wrong:
        account(owner, account_number="61 1090 1014 0000 0712 1981 2875")
    with pytest.raises(ValidationError) as nobody:
        account(owner, account_holder="")
    account(owner, bank_name="Bank Testowy")

    with tenant(owner):
        given = transfer_account()
        assert options()["transfer_account_set"] is True
        audit = OrganizationAuditEntry.objects.filter(
            action="organization.settings_changed"
        ).latest("occurred_at")
    assert codes(wrong) == [("account_number", "invalid_account_number")]
    assert codes(nobody) == [("account_holder", "required")]
    assert given is not None
    assert (given.holder, given.number, given.bank) == (
        "Gabinet Anna Nowak",
        "PL61 1090 1014 0000 0712 1981 2874",
        "Bank Testowy",
    )
    assert audit.target_type == "commerce.transfer"


def test_the_bank_or_the_holder_changes_while_a_transfer_is_awaited_and_the_number_stays() -> None:
    configured = prepaid("rachunek-czeka")
    owner: Membership = configured["owner"]
    with tenant(owner):
        visit(configured, at(configured))

    # Only the bank's name: the number is no part of the change.
    account(owner, account_holder=None, account_number=None, bank_name="Bank Nowy")
    with pytest.raises(ValidationError) as cleared:
        account(owner, account_holder=None, account_number="")

    with tenant(owner):
        given = transfer_account()
    assert given is not None and (given.bank, given.holder) == ("Bank Nowy", "Gabinet Anna Nowak")
    assert codes(cleared) == [("account_number", "transfer_account_in_use")]


def test_changing_the_account_asks_for_a_code_and_a_plan_without_orders_has_none() -> None:
    configured = office("rachunek-kod")
    owner: Membership = configured["owner"]

    with tenant(owner), pytest.raises(StepUpMfaSetupRequired):
        change_settings(
            "commerce.transfer",
            changes={"account_holder": "Ktoś", "account_number": ACCOUNT},
            expected_version=read_group("commerce.transfer").version,
        )
    with tenant(owner):
        # A preview asks for no code: it writes nothing.
        seen = change_settings(
            "commerce.transfer",
            changes={"account_holder": "Ktoś", "account_number": ACCOUNT},
            expected_version=read_group("commerce.transfer").version,
            preview=True,
        )
        snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
        snapshot.features = {**snapshot.features, COMMERCE_ENABLED: False}
        snapshot.save(update_fields=["features"])
        locked = read_group("commerce.transfer")

    assert set(seen.changes) == {"account_holder", "account_number"}
    assert locked.can_change is False and locked.locked


def test_an_offer_takes_money_ahead_only_where_it_can_be_paid() -> None:
    configured = office("oferta-przelew")
    owner: Membership = configured["owner"]

    with pytest.raises(ValidationError) as no_account:
        policy(configured, payment_policy="transfer")
    # A prepayment without an account is allowed: it is then paid on site.
    # Nobody said how much: the offer's default, 30%.
    default = policy(configured, payment_policy="deposit")
    saved = policy(configured, deposit_percent=40, transfer_due_days=5)
    account(owner)
    whole = policy(configured, payment_policy="transfer")
    # The account stays while an offer asks for a transfer.
    with pytest.raises(ValidationError) as in_use:
        account(owner, account_number="", account_holder="")
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    snapshot.features = {**snapshot.features, COMMERCE_ENABLED: False}
    snapshot.save(update_fields=["features"])
    cache.clear()
    # An offer set up earlier still saves its other fields without orders…
    renamed = policy(configured, name="Wizyta domowa")
    # …and asks for no new payment ahead.
    with pytest.raises(ValidationError) as no_orders:
        policy(configured, payment_policy="full")

    assert codes(no_account) == [("payment_policy", "transfer_account_missing")]
    assert (default.payment_policy, default.deposit_percent, default.transfer_due_days) == (
        "deposit",
        30,
        3,
    )
    assert (saved.payment_policy, saved.deposit_percent, saved.transfer_due_days) == (
        "deposit",
        40,
        5,
    )
    assert whole.payment_policy == "transfer"
    assert codes(in_use) == [("account_number", "transfer_account_in_use")]
    assert renamed.name == "Wizyta domowa"
    assert codes(no_orders) == [("payment_policy", "orders_required")]


def test_a_booking_that_asks_for_a_prepayment_waits_for_it(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = prepaid("przedplata-czeka")
    owner: Membership = configured["owner"]

    with watching() as seen, django_capture_on_commit_callbacks(execute=True), tenant(owner):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        payment = awaited(order)
        route = PaymentRoute.objects.get(payment_id=payment.id)
        history = list(AppointmentStatusHistory.all_objects.filter(appointment=booked))
        (mail,) = NotificationMessage.all_objects.filter(template_key="commerce.transfer_details")
        audit = OrganizationAuditEntry.objects.get(action="commerce.payment.requested")
        read = read_order(order.id)

    # 30% of 150, by a transfer, within three days; the booking holds its time.
    assert (booked.status, booked.hold_expires_at) == ("pending_payment", payment.due_at)
    assert (payment.kind, payment.method, payment.amount_minor) == ("deposit", "transfer", 4500)
    assert timedelta(days=2, hours=23) < payment.due_at - timezone.now() <= timedelta(days=3)
    assert (route.organization_id, route.due_at, route.dispatched_at) == (
        owner.organization_id,
        payment.due_at,
        None,
    )
    assert booked.quote["prepayment"] == {
        "kind": "deposit",
        "amount_minor": 4500,
        "transfer_due_days": 3,
    }
    assert [(row.from_status, row.to_status) for row in history] == [("", "pending_payment")]
    assert AppointmentStaffAllocation.all_objects.filter(appointment=booked, active=True).exists()
    # What comes with a confirmed booking has not come: no confirmation, no
    # reminder, and the observers heard nothing.
    assert mails(booked.id, "booking.confirmation") == []
    assert not ReminderRoute.objects.filter(appointment_id=booked.id).exists()
    assert seen == []
    # The buyer was told where to pay, how much and what to write in the title.
    assert mail.recipient_email == "gosc@example.test"
    assert mail.context["number"] == order.number
    assert mail.context["amount"] == "45,00 PLN"
    assert mail.context["account_number"] == "PL61 1090 1014 0000 0712 1981 2874"
    assert mail.context["account_holder"] == "Gabinet Anna Nowak"
    assert mail.context["subject"] == "Wizyta"
    assert audit.metadata["amount_minor"] == 4500 and "gosc" not in str(audit.metadata)
    # The order waits with it.
    assert (read["status"], read["due_minor"]) == ("awaiting_payment", 15000)
    assert [(row["status"], row["amount_minor"], row["due_at"]) for row in read["payments"]] == [
        ("requires_payment", 4500, payment.due_at)
    ]


def test_marking_the_awaited_payment_confirms_the_booking(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = prepaid("przedplata-wplata")
    owner: Membership = configured["owner"]

    with watching() as seen, django_capture_on_commit_callbacks(execute=True), tenant(owner):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        first = awaited(order)
        preview = record_payment(
            order.id, amount_minor=4500, method="transfer", expected_version=2, preview=True
        )
        assert Appointment.all_objects.get(pk=booked.id).status == "pending_payment"
        paid = record_payment(order.id, amount_minor=4500, method="transfer", expected_version=2)
        booked.refresh_from_db()
        history = list(
            AppointmentStatusHistory.all_objects.filter(appointment=booked).order_by("occurred_at")
        )

    assert preview["prepayment_met"] is True and preview["status"] == "partially_paid"
    # The row that waited is the payment: no second one beside it.
    (row,) = paid["payments"]
    assert (row["id"], row["status"], row["kind"], row["amount_minor"]) == (
        first.id,
        "succeeded",
        "deposit",
        4500,
    )
    assert (paid["status"], paid["paid_minor"], paid["due_minor"]) == (
        "partially_paid",
        4500,
        10500,
    )
    assert not PaymentRoute.objects.filter(payment_id=first.id).exists()
    assert (booked.status, booked.hold_expires_at) == ("confirmed", None)
    assert [(item.from_status, item.to_status, item.reason) for item in history] == [
        ("", "pending_payment", ""),
        ("pending_payment", "confirmed", "paid"),
    ]
    # Now everything a confirmed booking gets: the confirmation, the reminder
    # and the observers' CREATED.
    assert len(mails(booked.id, "booking.confirmation")) == 1
    assert ReminderRoute.objects.filter(appointment_id=booked.id).exists()
    assert [(change.change, change.status) for change in seen] == [("created", "confirmed")]


def test_a_part_of_the_prepayment_leaves_the_rest_awaited() -> None:
    configured = prepaid("przedplata-czesc")

    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        part = record_payment(order.id, amount_minor=2000, method="transfer", expected_version=2)
        still = Appointment.all_objects.get(pk=booked.id).status
        rest_awaited = awaited(order).amount_minor
        # The part marked by mistake: the whole prepayment is awaited again.
        taken_back = void_payment(order.id, part["payments"][-1]["id"], expected_version=3)
        again = awaited(order).amount_minor
        # More than was asked for covers it: the customer paid everything.
        paid = record_payment(order.id, amount_minor=15000, method="cash", expected_version=4)
        booked.refresh_from_db()

    assert part["status"] == "partially_paid" and still == "pending_payment"
    assert rest_awaited == 2500
    assert taken_back["paid_minor"] == 0 and again == 4500
    assert (paid["status"], booked.status) == ("paid", "confirmed")
    assert [(row["status"], row["method"], row["amount_minor"]) for row in paid["payments"]] == [
        ("succeeded", "cash", 15000),
        ("canceled", "transfer", 2000),
    ]


def test_the_date_comes_first_and_the_booking_lets_its_time_go(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = prepaid("przedplata-wygasla")
    owner: Membership = configured["owner"]

    with watching() as seen, django_capture_on_commit_callbacks(execute=True):
        with tenant(owner):
            booked = visit(configured, at(configured))
            order = order_of(booked)
            assert order is not None
        # Not due yet: the task leaves it alone.
        assert expire_due_payments() == 0
        with tenant(owner):
            past_due(order)
        assert expire_due_payments() == 1
        # A second run finds nothing left to do.
        assert expire_due_payments() == 0

    with tenant(owner):
        booked.refresh_from_db()
        order.refresh_from_db()
        payment = Payment.all_objects.get(order=order)
        history = AppointmentStatusHistory.all_objects.filter(appointment=booked).latest(
            "occurred_at"
        )
        canceled = OrganizationAuditEntry.objects.get(action="commerce.order.canceled")
        expired = OrganizationAuditEntry.objects.get(action="booking.appointment.expired")
        # The time is free again: the same visit can be booked.
        other = visit(
            configured,
            at(configured),
            customer_data={"display_name": "Ewa Nowa", "email": "ewa@example.test"},
        )
    assert (booked.status, booked.hold_expires_at) == ("canceled", None)
    assert (order.status, payment.status) == ("canceled", "expired")
    assert (history.from_status, history.to_status, history.reason, history.actor_kind) == (
        "pending_payment",
        "canceled",
        "payment_expired",
        "service",
    )
    assert canceled.metadata["reason"] == "payment_expired" and canceled.actor_user_id is None
    assert expired.target_id == booked.id
    assert PaymentRoute.objects.filter(dispatched_at__isnull=True).count() == 1  # the new one
    assert SelfServiceRoute.objects.get(appointment_id=booked.id).revoked_at is not None
    # The customer is told; nobody who never heard of the booking hears now.
    assert len(mails(booked.id, "booking.pending_expired")) == 1
    assert mails(booked.id, "booking.canceled") == []
    assert seen == []
    assert other.status == "pending_payment"


def test_a_payment_marked_in_time_is_not_expired_by_a_late_route() -> None:
    configured = prepaid("przedplata-zdazyla")
    owner: Membership = configured["owner"]

    with tenant(owner):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        payment = awaited(order)
        route = PaymentRoute.objects.get(payment_id=payment.id)
        record_payment(order.id, amount_minor=4500, method="transfer", expected_version=2)
        # The route as the task would have read it a moment before the mark.
        PaymentRoute.objects.create(
            payment_id=payment.id,
            organization_id=route.organization_id,
            signed_tenant_context=route.signed_tenant_context,
            due_at=timezone.now() - timedelta(minutes=1),
        )
    assert expire_due_payments() == 0
    with tenant(owner):
        booked.refresh_from_db()
        order.refresh_from_db()
    assert (booked.status, order.status) == ("confirmed", "partially_paid")
    assert PaymentRoute.objects.get(payment_id=payment.id).dispatched_at is not None


def test_a_pending_booking_given_up_cancels_its_order_and_tells_no_observer(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = prepaid("przedplata-rezygnacja")
    owner: Membership = configured["owner"]

    with watching() as seen, django_capture_on_commit_callbacks(execute=True), tenant(owner):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        cancel_appointment(
            appointment_id=booked.id, idempotency_key=key(), principal_ref=str(owner.user_id)
        )
        order.refresh_from_db()
        payment = Payment.all_objects.get(order=order)
    assert (order.status, payment.status) == ("canceled", "canceled")
    assert not PaymentRoute.objects.filter(payment_id=payment.id).exists()
    assert seen == []
    assert expire_due_payments() == 0


def test_anonymising_the_buyer_scrubs_the_transfers_details_they_were_sent() -> None:
    configured = prepaid("przedplata-anonimizacja")

    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        (mail,) = NotificationMessage.all_objects.filter(template_key="commerce.transfer_details")
        assert mail.recipient_email == "gosc@example.test"
        anonymize_customer(booked.customer_id)
        mail.refresh_from_db()
    assert mail.recipient_email.startswith("redacted+") and mail.context == {}


def test_a_payment_taken_back_after_confirming_leaves_the_booking_confirmed() -> None:
    configured = prepaid("przedplata-wycofana")

    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        paid = record_payment(order.id, amount_minor=4500, method="transfer", expected_version=2)
        back = void_payment(order.id, paid["payments"][0]["id"], expected_version=3)
        booked.refresh_from_db()
    assert (back["status"], back["paid_minor"]) == ("awaiting_payment", 0)
    assert booked.status == "confirmed"


def test_without_an_account_the_prepayment_is_paid_on_site_and_the_booking_confirmed() -> None:
    configured = office("przedplata-bez-rachunku")
    policy(configured, payment_policy="deposit", deposit_percent=30)

    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
    assert booked.status == "confirmed" and booked.hold_expires_at is None
    # The quote never promises a transfer nobody can make.
    assert (booked.quote["payment_policy"], booked.quote["prepayment"]) == ("on_site", None)
    assert not Payment.all_objects.filter(order=order).exists()
    assert len(mails(booked.id, "booking.confirmation")) == 1


def test_the_whole_by_transfer_and_a_visit_under_way_never_waits() -> None:
    configured = prepaid("przedplata-calosc", payment_policy="transfer", transfer_due_days=30)

    with tenant(configured["owner"]):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        payment = awaited(order)
        now = visit(
            configured,
            timezone.now(),
            walk_in_minutes=30,
            customer_data={"display_name": "Ewa Nowa", "email": "ewa@example.test"},
        )
    assert (payment.kind, payment.amount_minor) == ("full", 15000)
    # Thirty days to pay, but never past the visit's start.
    assert payment.due_at == booked.starts_at == booked.hold_expires_at
    assert now.status == "confirmed"


def test_a_stay_waits_for_its_prepayment_like_a_visit() -> None:
    owner = membership("przedplata-pobyt")
    with_orders(owner.organization_id)
    setup = priced_cottages(owner)
    account(owner)
    policy({"service": setup["service"], "owner": owner}, payment_policy="full")

    with tenant(owner):
        booked = stay(setup, day(6, 1), day(6, 4)).appointment
        order = order_of(booked)
        assert order is not None
        payment = awaited(order)
        record_payment(order.id, amount_minor=90000, method="transfer", expected_version=2)
        booked.refresh_from_db()
        order.refresh_from_db()
    assert (payment.kind, payment.amount_minor) == ("full", 90000)
    assert (booked.status, order.status) == ("confirmed", "paid")


def test_the_form_shows_the_prepayment_and_the_customer_gets_the_transfers_details() -> None:
    configured = priced("przedplata-formularz")
    owner: Membership = configured["owner"]
    with_orders(owner.organization_id)
    account(owner)
    policy(configured, payment_policy="deposit", deposit_percent=50)
    client = APIClient()

    body = form_booking(client, configured, "przedplata-anna")
    quote = client.post(
        f"{configured['url']}/quote/",
        {"service_id": body["service_id"], "starts_at": body["starts_at"]},
        format="json",
    ).json()["quote"]
    made = send(client, configured, body, "przedplata-anna")

    assert made.status_code == 201, made.data
    answer = made.json()
    # The visit at 150 and the travel at 50: half of 200 ahead.
    assert (quote["payment_policy"], quote["prepayment"]) == (
        "deposit",
        {"kind": "deposit", "amount_minor": 10000, "transfer_due_days": 3},
    )
    assert answer["status"] == "pending_payment" and answer["hold_expires_at"]
    assert answer["payment"]["amount_minor"] == 10000
    assert answer["payment"]["account_number"] == "PL61 1090 1014 0000 0712 1981 2874"
    assert answer["payment"]["number"].startswith("R/")
    # A booking that waits can be given up, never moved.
    assert answer["self_service"]["cancel"] is True
    assert answer["self_service"]["reschedule"] is False
    token = answer["self_service_token"]
    seen = client.get(f"/api/v1/booking/self-service/{token}/")
    assert seen.status_code == 200 and seen.json()["payment"]["amount_minor"] == 10000
    moved = client.post(
        f"/api/v1/booking/self-service/{token}/reschedule/",
        {"starts_at": body["starts_at"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="przedplata-move",
    )
    assert moved.status_code == 404, moved.data
    gone = client.post(
        f"/api/v1/booking/self-service/{token}/cancel/",
        format="json",
        HTTP_IDEMPOTENCY_KEY="przedplata-cancel",
    )
    assert gone.status_code == 200, gone.data
    with tenant(owner):
        (order,) = Order.all_objects.filter(organization_id=owner.organization_id)
    assert order.status == "canceled"


def test_the_calendar_links_a_visit_to_its_order_for_whoever_reads_orders() -> None:
    _, owner, client = authenticated_member(
        email="kalendarz-zamowienie@example.test", role_key="owner", slug="kalendarz-zamowienie"
    )
    bookable(owner.organization)
    with_orders(owner.organization_id)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    configured["owner"] = owner
    today = company_today()
    configured["monday"] = today + timedelta(days=7 - today.weekday())
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
    account(owner)
    policy(configured, payment_policy="deposit", deposit_percent=30)
    with tenant(owner):
        booked = visit(configured, at(configured))
        order = order_of(booked)
        assert order is not None
        links = booking_orders.links([booked.id])
        # Somebody who sees the calendar and may not read orders gets no link.
        staff = replace(
            require_tenant_context(),
            permissions=frozenset({"booking.appointment.read"}),
        )
    with activate_tenant_context(staff):
        hidden = booking_orders.links([booked.id])
    listed = client.get(
        "/api/v1/booking/appointments/",
        {
            "from": at(configured, 0).isoformat(),
            "to": at(configured, 23).isoformat(),
        },
    )

    assert links == {booked.id: {"id": order.id, "number": order.number}}
    assert hidden == {}
    assert listed.status_code == 200, listed.data
    (item,) = listed.json()["items"]
    assert item["order"] == {"id": str(order.id), "number": order.number}
    assert item["status"] == "pending_payment" and item["hold_expires_at"]
