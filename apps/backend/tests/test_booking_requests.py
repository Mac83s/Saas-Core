"""Bookings „on request” (ADR-072 §8–§9, ADR-073, phase 4g): a customer's
booking of such an offer holds its time and waits for the company's answer;
accepted, it is confirmed — or waits for its payment; declined or unanswered,
it lets its time go. Its order is a draft without a number until then."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    AppointmentStatusHistory,
    ReminderRoute,
    RequestRoute,
)
from saas_core.modules.shared.booking.services import (
    AppointmentNotChangeable,
    answer_request,
)
from saas_core.modules.shared.booking.tasks import expire_pending_requests
from saas_core.modules.shared.commerce.models import Order, OrderCounter, Payment
from saas_core.modules.shared.commerce.orders import list_orders, read_order
from saas_core.modules.shared.commerce.payments import record_payment
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from saas_core.modules.shared.notifications.templates import render_template
from test_booking import _no_delivery, company_today, mails, tenant, watching
from test_booking_prices import key
from test_booking_public_price import priced
from test_booking_quote import WARSAW
from test_commerce_orders import form_booking, order_of, send, visit, with_orders
from test_commerce_prepayments import account, policy
from test_organization_lifecycle import authenticated_member, csrf_value

pytestmark = pytest.mark.django_db

YEAR = company_today().year


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def on_request(slug: str, *, orders: bool = True, **data: Any) -> dict[str, Any]:
    """A company whose priced visit (150 and 50 for the travel, paid on site)
    is booked on request, with twelve hours to answer."""
    configured = priced(slug)
    if orders:
        with_orders(configured["owner"].organization_id)
    policy(configured, confirmation="on_request", response_hours=12, **data)
    return configured


def asked(configured: dict[str, Any], name: str) -> tuple[Any, Appointment]:
    """A customer asks for the visit on the public form."""
    client = APIClient()
    made = send(client, configured, form_booking(client, configured, name), name)
    assert made.status_code == 201, made.data
    with tenant(configured["owner"]):
        appointment = Appointment.all_objects.get(pk=made.json()["id"])
    return made, appointment


def answer(configured: dict[str, Any], appointment: Appointment, accept: bool) -> Appointment:
    owner: Membership = configured["owner"]
    with tenant(owner):
        return answer_request(
            appointment_id=appointment.id,
            accept=accept,
            idempotency_key=key(),
            principal_ref=str(owner.user_id),
        )


def past_due(appointment: Appointment) -> None:
    earlier = timezone.now() - timedelta(minutes=1)
    Appointment.all_objects.filter(pk=appointment.id).update(hold_expires_at=earlier)
    RequestRoute.objects.filter(appointment_id=appointment.id).update(due_at=earlier)


def test_a_customers_request_holds_its_time_and_waits_for_the_company(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosba-czeka")
    owner: Membership = configured["owner"]

    with watching() as seen, django_capture_on_commit_callbacks(execute=True):
        made, appointment = asked(configured, "prosba-anna")
    answer_json = made.json()
    with tenant(owner):
        order = order_of(appointment)
        assert order is not None
        route = RequestRoute.objects.get(appointment_id=appointment.id)
        history = list(AppointmentStatusHistory.all_objects.filter(appointment=appointment))
        (mail,) = mails(appointment.id, "booking.request_received")
        drafted = OrganizationAuditEntry.objects.get(action="commerce.order.drafted")
        listed = list_orders()["items"]

    # Twelve hours to answer; the time is taken meanwhile.
    assert (answer_json["status"], appointment.status) == ("pending_request", "pending_request")
    assert appointment.hold_expires_at is not None
    assert timedelta(hours=11, minutes=59) < appointment.hold_expires_at - timezone.now()
    assert appointment.hold_expires_at - timezone.now() <= timedelta(hours=12)
    assert (route.due_at, route.dispatched_at) == (appointment.hold_expires_at, None)
    assert AppointmentStaffAllocation.all_objects.filter(
        appointment=appointment, active=True
    ).exists()
    assert [(row.from_status, row.to_status) for row in history] == [("", "pending_request")]
    # A request can be withdrawn, never moved; nothing is to be paid yet.
    assert answer_json["self_service"]["cancel"] is True
    assert answer_json["self_service"]["reschedule"] is False
    assert answer_json["payment"] is None
    # The order is a draft: no number, and the counter has not moved.
    assert (order.status, order.number, order.gross_minor) == ("draft", "", 20000)
    assert not OrderCounter.all_objects.filter(organization_id=owner.organization_id).exists()
    assert drafted.target_id == order.id
    assert [(row["number"], row["status"]) for row in listed] == [("", "draft")]
    # The customer is told what happens next; nothing of a confirmed booking yet.
    assert mail.recipient_email == "prosba-anna@example.test"
    assert set(mail.context) == {"organization_name", "starts_at", "answer_by", "manage_url"}
    assert mails(appointment.id, "booking.confirmation") == []
    assert not ReminderRoute.objects.filter(appointment_id=appointment.id).exists()
    assert seen == []
    # Whoever manages bookings hears of it, whatever the notices' switch says.
    assert {
        notice.user_id
        for notice in AppNotification.all_objects.filter(kind="booking.office_request")
    } == {owner.user_id}


def test_the_teams_own_booking_of_such_an_offer_never_waits_for_an_answer() -> None:
    configured = on_request("prosba-biuro")
    owner: Membership = configured["owner"]

    with tenant(owner):
        booked = visit(configured, datetime.combine(configured["day"], time(9), WARSAW))
        order = order_of(booked)
    assert booked.status == "confirmed"
    assert order is not None and (order.status, order.number) == (
        "awaiting_payment",
        f"R/{YEAR}/0001",
    )


def test_accepting_confirms_the_booking_and_gives_the_order_its_number(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosba-przyjeta")
    owner: Membership = configured["owner"]
    _, appointment = asked(configured, "prosba-anna")

    with watching() as seen, django_capture_on_commit_callbacks(execute=True), tenant(owner):
        same_key = key()
        first = answer_request(
            appointment_id=appointment.id,
            accept=True,
            idempotency_key=same_key,
            principal_ref=str(owner.user_id),
        )
        # The same key again answers what the first call did, and does nothing.
        again = answer_request(
            appointment_id=appointment.id,
            accept=True,
            idempotency_key=same_key,
            principal_ref=str(owner.user_id),
        )
        # Answered: neither a second acceptance nor a refusal changes it.
        with pytest.raises(AppointmentNotChangeable):
            answer_request(
                appointment_id=appointment.id,
                accept=False,
                idempotency_key=key(),
                principal_ref=str(owner.user_id),
            )
        order = order_of(appointment)
        assert order is not None
        history = list(
            AppointmentStatusHistory.all_objects.filter(appointment=appointment).order_by(
                "occurred_at"
            )
        )
        placed = OrganizationAuditEntry.objects.get(action="commerce.order.placed")
        accepted = OrganizationAuditEntry.objects.get(action="booking.appointment.accepted")

    assert (first.status, first.hold_expires_at, again.id) == ("confirmed", None, first.id)
    assert (order.status, order.number) == ("awaiting_payment", f"R/{YEAR}/0001")
    assert [(row.from_status, row.to_status, row.reason) for row in history] == [
        ("", "pending_request", ""),
        ("pending_request", "confirmed", "accepted"),
    ]
    assert placed.metadata["number"] == f"R/{YEAR}/0001" and accepted.target_id == appointment.id
    assert not RequestRoute.objects.filter(appointment_id=appointment.id).exists()
    # Now everything a confirmed booking gets.
    assert len(mails(appointment.id, "booking.confirmation")) == 1
    assert mails(appointment.id, "booking.request_accepted") == []
    assert ReminderRoute.objects.filter(appointment_id=appointment.id).exists()
    assert [(change.change, change.status) for change in seen] == [("created", "confirmed")]


def test_an_accepted_request_of_an_offer_with_a_prepayment_waits_for_its_payment() -> None:
    configured = priced("prosba-przedplata")
    owner: Membership = configured["owner"]
    with_orders(owner.organization_id)
    account(owner)
    policy(
        configured,
        confirmation="on_request",
        response_hours=12,
        payment_policy="deposit",
        deposit_percent=50,
    )
    made, appointment = asked(configured, "prosba-anna")

    with tenant(owner):
        order = order_of(appointment)
        assert order is not None
        # A draft takes no payment: the company answers first.
        with pytest.raises(ValidationError) as early:
            record_payment(order.id, amount_minor=10000, method="transfer", expected_version=1)
        waiting = Payment.all_objects.filter(order=order).count()
    accepted = answer(configured, appointment, True)
    with tenant(owner):
        payment = Payment.all_objects.get(order=order, status="requires_payment")
        order.refresh_from_db()
        history = AppointmentStatusHistory.all_objects.filter(appointment=appointment).latest(
            "occurred_at"
        )
        told = mails(appointment.id, "booking.request_accepted")
        details = NotificationMessage.all_objects.filter(template_key="commerce.transfer_details")
        paid = record_payment(
            order.id, amount_minor=10000, method="transfer", expected_version=order.version
        )
        appointment.refresh_from_db()

    # The request promised the terms; nothing was asked for before the answer.
    assert made.json()["quote"]["prepayment"]["amount_minor"] == 10000
    assert [(error["field"], error["code"]) for error in problem_errors(early.value)] == [
        ("order", "order_not_placed")
    ]
    assert waiting == 0
    # Accepted: the order has its number and the booking waits for half of 200.
    assert (accepted.status, accepted.hold_expires_at) == ("pending_payment", payment.due_at)
    assert (order.number, order.status, payment.amount_minor) == (
        f"R/{YEAR}/0001",
        "awaiting_payment",
        10000,
    )
    assert (history.from_status, history.to_status, history.reason) == (
        "pending_request",
        "pending_payment",
        "accepted",
    )
    assert len(told) == 1 and details.count() == 1
    assert "/booking/bk_" in details.get().context["manage_url"]
    assert mails(appointment.id, "booking.confirmation") != []  # after the payment below
    assert (paid["status"], appointment.status) == ("partially_paid", "confirmed")


def test_declining_lets_the_time_go_and_tells_the_customer(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosba-odmowa")
    owner: Membership = configured["owner"]
    _, appointment = asked(configured, "prosba-anna")

    with watching() as seen, django_capture_on_commit_callbacks(execute=True):
        declined = answer(configured, appointment, False)
    with tenant(owner):
        order = order_of(appointment)
        assert order is not None
        history = AppointmentStatusHistory.all_objects.filter(appointment=appointment).latest(
            "occurred_at"
        )
        read = read_order(order.id)
    # The same time can be asked for again.
    _, other = asked(configured, "prosba-ewa")

    assert (declined.status, declined.hold_expires_at) == ("canceled", None)
    assert (history.from_status, history.to_status, history.reason) == (
        "pending_request",
        "canceled",
        "declined",
    )
    # The draft is canceled and never got a number.
    assert (read["status"], read["number"]) == ("canceled", "")
    assert not RequestRoute.objects.filter(appointment_id=appointment.id).exists()
    assert len(mails(appointment.id, "booking.request_declined")) == 1
    assert mails(appointment.id, "booking.canceled") == []
    assert seen == []
    assert other.starts_at == appointment.starts_at and other.status == "pending_request"


def test_the_company_may_say_why_and_its_words_reach_the_customer_without_a_link(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosba-powod")
    owner: Membership = configured["owner"]
    _, appointment = asked(configured, "prosba-anna")

    def decline(reason: str) -> Appointment:
        with tenant(owner):
            return answer_request(
                appointment_id=appointment.id,
                accept=False,
                idempotency_key=key(),
                principal_ref=str(owner.user_id),
                reason=reason,
            )

    with pytest.raises(ValidationError) as linked:
        decline("Zapisy tylko przez www.inna-strona.example")
    with pytest.raises(ValidationError) as long:
        decline("x" * 301)
    with tenant(owner):
        still = Appointment.all_objects.get(pk=appointment.id).status
    with django_capture_on_commit_callbacks(execute=True):
        declined = decline("  W tym tygodniu <b>nie</b> przyjmujemy.\n Zapraszamy w listopadzie.  ")
    with tenant(owner):
        history = AppointmentStatusHistory.all_objects.filter(appointment=appointment).latest(
            "occurred_at"
        )
        audit = OrganizationAuditEntry.objects.filter(action="booking.appointment.declined").latest(
            "occurred_at"
        )

    assert [(item["field"], item["code"]) for item in problem_errors(linked.value)] == [
        ("reason", "links")
    ]
    assert [(item["field"], item["code"]) for item in problem_errors(long.value)] == [
        ("reason", "max_length")
    ]
    assert still == "pending_request" and declined.status == "canceled"
    (mail,) = mails(appointment.id, "booking.request_declined")
    # The words go out as the company's, on one line, and as text: a tag is
    # shown, never run.
    assert mail.template_version == 2
    assert (
        mail.context["reason"] == "W tym tygodniu <b>nie</b> przyjmujemy. Zapraszamy w listopadzie."
    )
    _, body = render_template(
        key="booking.request_declined", version=2, locale="pl", context=mail.context
    )
    assert "Wiadomość od prosba-powod: W tym tygodniu &lt;b&gt;nie&lt;/b&gt; przyjmujemy." in body
    # They are kept in that mail only: neither the booking's history nor the
    # company's has them.
    assert history.reason == "declined"
    assert "tygodniu" not in str(audit.metadata)


def test_the_requests_that_wait_are_listed_for_whoever_answers_them() -> None:
    configured = on_request("prosba-lista")
    owner: Membership = configured["owner"]
    _, first = asked(configured, "prosba-anna")
    configured["day"] += timedelta(days=1)
    _, second = asked(configured, "prosba-ewa")
    # The second one's time to answer runs out first.
    Appointment.all_objects.filter(pk=second.id).update(
        hold_expires_at=timezone.now() + timedelta(hours=1)
    )
    _, _, staff = authenticated_member(
        email="lista-pracownik@example.test", role_key="staff", organization=owner.organization
    )
    _, _, manager = authenticated_member(
        email="lista-kierownik@example.test", role_key="admin", organization=owner.organization
    )

    listed = manager.get("/api/v1/booking/requests/")
    overview = manager.get("/api/v1/booking/overview/").json()
    answer(configured, second, True)
    answer(configured, first, False)
    after = manager.get("/api/v1/booking/requests/").json()
    still_offered = manager.get("/api/v1/booking/overview/").json()

    assert staff.get("/api/v1/booking/requests/").status_code == 403
    assert staff.get("/api/v1/booking/overview/").json()["requests"] is None
    assert listed.status_code == 200, listed.data
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [str(second.id), str(first.id)]
    assert {item["status"] for item in items} == {"pending_request"}
    assert items[0]["customer_email"] == "prosba-ewa@example.test" and items[0]["hold_expires_at"]
    assert overview["requests"] == 2
    # Answered, they leave the list; the company still takes requests, so the
    # list stays in the menu with nothing in it.
    assert after["items"] == [] and still_offered["requests"] == 0

    # A company that takes nothing on request has no such list.
    plain = priced("prosba-lista-bez")
    _, _, other = authenticated_member(
        email="lista-inna@example.test", role_key="admin", organization=plain["owner"].organization
    )
    assert other.get("/api/v1/booking/overview/").json()["requests"] is None
    assert other.get("/api/v1/booking/requests/").json()["items"] == []


def test_an_unanswered_request_expires_and_everybody_is_told(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosba-wygasla")
    owner: Membership = configured["owner"]
    _, appointment = asked(configured, "prosba-anna")

    with watching() as seen, django_capture_on_commit_callbacks(execute=True):
        # Not due yet: the task leaves it alone.
        assert expire_pending_requests() == 0
        with tenant(owner):
            past_due(appointment)
        assert expire_pending_requests() == 1
        assert expire_pending_requests() == 0
    with tenant(owner):
        appointment.refresh_from_db()
        order = order_of(appointment)
        assert order is not None
        history = AppointmentStatusHistory.all_objects.filter(appointment=appointment).latest(
            "occurred_at"
        )
        expired = OrganizationAuditEntry.objects.get(action="booking.appointment.expired")

    assert (appointment.status, order.status, order.number) == ("canceled", "canceled", "")
    assert (history.reason, history.actor_kind) == ("request_expired", "service")
    assert expired.metadata == {"reason": "request_expired"}
    assert len(mails(appointment.id, "booking.request_expired")) == 1
    assert AppNotification.all_objects.filter(kind="booking.office_request_expired").exists()
    assert seen == []


def test_a_request_answered_in_time_is_not_expired_by_a_late_route() -> None:
    configured = on_request("prosba-zdazyla")
    owner: Membership = configured["owner"]
    _, appointment = asked(configured, "prosba-anna")
    with tenant(owner):
        route = RequestRoute.objects.get(appointment_id=appointment.id)
    answer(configured, appointment, True)
    # The route as the task would have read it a moment before the answer.
    RequestRoute.objects.create(
        appointment_id=appointment.id,
        organization_id=route.organization_id,
        signed_tenant_context=route.signed_tenant_context,
        due_at=timezone.now() - timedelta(minutes=1),
    )

    assert expire_pending_requests() == 0
    with tenant(owner):
        appointment.refresh_from_db()
    assert appointment.status == "confirmed"
    assert RequestRoute.objects.get(appointment_id=appointment.id).dispatched_at is not None


def test_a_customer_withdraws_a_request_through_their_link() -> None:
    configured = on_request("prosba-rezygnacja")
    owner: Membership = configured["owner"]
    made, appointment = asked(configured, "prosba-anna")
    client = APIClient()
    token = made.json()["self_service_token"]

    seen = client.get(f"/api/v1/booking/self-service/{token}/")
    gone = client.post(
        f"/api/v1/booking/self-service/{token}/cancel/",
        format="json",
        HTTP_IDEMPOTENCY_KEY="prosba-cancel",
    )

    assert seen.status_code == 200 and seen.json()["status"] == "pending_request"
    assert gone.status_code == 200, gone.data
    with tenant(owner):
        appointment.refresh_from_db()
        order = order_of(appointment)
    assert appointment.status == "canceled"
    assert order is not None and (order.status, order.number) == ("canceled", "")
    assert not RequestRoute.objects.filter(appointment_id=appointment.id).exists()
    assert expire_pending_requests() == 0


def test_a_request_works_without_orders_and_the_form_says_the_offer_is_on_request() -> None:
    configured = on_request("prosba-bez-zamowien", orders=False)
    owner: Membership = configured["owner"]
    client = APIClient()

    catalogue = client.get(f"{configured['url']}/").json()
    _, appointment = asked(configured, "prosba-anna")
    accepted = answer(configured, appointment, True)

    (offer,) = catalogue["services"]
    assert (offer["confirmation"], offer["response_hours"]) == ("on_request", 12)
    with tenant(owner):
        assert not Order.all_objects.filter(organization_id=owner.organization_id).exists()
    assert accepted.status == "confirmed"


def test_the_panel_accepts_and_declines_over_the_api_and_only_who_manages_bookings() -> None:
    configured = on_request("prosba-api")
    owner: Membership = configured["owner"]
    _, first = asked(configured, "prosba-anna")
    configured["day"] += timedelta(days=1)
    _, second = asked(configured, "prosba-ewa")
    _, _, staff = authenticated_member(
        email="prosba-pracownik@example.test",
        role_key="staff",
        organization=owner.organization,
    )
    _, _, manager = authenticated_member(
        email="prosba-kierownik@example.test",
        role_key="admin",
        organization=owner.organization,
    )

    def post(client: APIClient, visit_id: Any, action: str, name: str) -> Any:
        return client.post(
            f"/api/v1/booking/appointments/{visit_id}/{action}/",
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=name,
        )

    refused = post(staff, first.id, "accept", "api-0")
    accepted = post(manager, first.id, "accept", "api-1")
    replayed = post(manager, first.id, "accept", "api-1")
    too_late = post(manager, first.id, "decline", "api-2")
    declined = post(manager, second.id, "decline", "api-3")

    assert refused.status_code == 403
    assert accepted.status_code == 200, accepted.data
    assert (accepted.json()["status"], accepted.json()["order"]["number"]) == (
        "confirmed",
        f"R/{YEAR}/0001",
    )
    assert replayed.status_code == 200 and replayed.json()["status"] == "confirmed"
    assert too_late.status_code == 409 and too_late.json()["code"] == "appointment_not_changeable"
    assert declined.status_code == 200 and declined.json()["status"] == "canceled"
