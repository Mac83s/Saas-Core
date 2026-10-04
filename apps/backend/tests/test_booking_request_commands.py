"""What is particular to the assistant's commands for bookings made on request
(`shared/booking/request_commands.py`): the requests are read without the
customer; an answer is agreed to with what the customer gets — a confirmation,
or the transfer's details where the offer asks for money first; the company's
own words to a customer it declines are refused with a link, as the panel
refuses them; and a request somebody answered already is refused before a
click."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.shared.booking.models import Appointment
from test_booking import _no_delivery, mails
from test_booking_pricing_commands import refused, run, shown
from test_booking_public_price import priced
from test_booking_requests import asked, on_request
from test_command_evals import assistant, invocation
from test_commerce_orders import with_orders
from test_commerce_prepayments import account, policy

pytestmark = pytest.mark.django_db

READ = "booking.requests.read@1"
ACCEPT = "booking.request.accept@1"
DECLINE = "booking.request.decline@1"


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache.clear()
    _no_delivery(monkeypatch)
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def accept(appointment: Appointment) -> list[Any]:
    return [invocation(ACCEPT, {"request_id": str(appointment.id)})]


def decline(appointment: Appointment, reason: str | None) -> list[Any]:
    return [invocation(DECLINE, {"request_id": str(appointment.id), "reason": reason})]


def test_the_requests_are_read_without_the_customer() -> None:
    configured = on_request("prosby-odczyt")
    _, appointment = asked(configured, "prosba-anna")
    person = context_from_membership(configured["owner"])

    with activate_tenant_context(assistant(person)):
        (result,) = execute_plan([invocation(READ, {})])

    assert result.status == "done", result
    (request,) = result.output["requests"]
    assert (request["request_id"], request["service"]) == (
        str(appointment.id),
        appointment.service_name,
    )
    # 150 and 50 for the travel, paid on site: nothing is asked for ahead.
    assert (request["gross_minor"], request["currency"], request["prepayment_minor"]) == (
        20000,
        "PLN",
        None,
    )
    assert request["answer_by"] and request["starts_at"] < request["ends_at"]
    said = json.dumps(result.output, ensure_ascii=False)
    assert "Anna" not in said and "example.test" not in said and "600 100 200" not in said


def test_accepting_is_agreed_to_with_what_the_customer_gets_and_answers_once() -> None:
    configured = on_request("prosby-przyjecie")
    _, appointment = asked(configured, "prosba-anna")
    person = context_from_membership(configured["owner"])

    risk, words = shown(person, accept(appointment))

    # A message to somebody outside the company: its own click, never taken back.
    assert risk == "irreversible"
    assert words.startswith(f"Przyjęcie prośby o rezerwację: „{appointment.service_name}”, ")
    assert words.endswith("Rezerwacja zostanie potwierdzona. Klient dostanie e-mail od razu.")

    result = run(person, accept(appointment))

    assert result.status == "done", result
    assert (result.output["request_id"], result.output["status"]) == (
        str(appointment.id),
        "confirmed",
    )
    assert Appointment.all_objects.get(pk=appointment.id).status == "confirmed"
    # Answered: neither answer is offered for a click any more.
    with activate_tenant_context(assistant(person)):
        (late,) = preview_plan(decline(appointment, None)).refusals
    assert (late.status, late.code) == (409, "appointment_not_changeable")


def test_an_offer_that_asks_for_money_first_says_so_before_the_click() -> None:
    configured = priced("prosby-przedplata")
    owner = configured["owner"]
    with_orders(owner.organization_id)
    account(owner)
    policy(
        configured,
        confirmation="on_request",
        response_hours=12,
        payment_policy="deposit",
        deposit_percent=50,
    )
    _, appointment = asked(configured, "prosba-anna")
    person = context_from_membership(owner)

    _, words = shown(person, accept(appointment))

    assert (
        "Oferta wymaga przedpłaty 100,00 PLN: klient dostanie dane do przelewu, a rezerwacja "
        "będzie potwierdzona po wpłacie."
    ) in words

    result = run(person, accept(appointment))

    assert (result.status, result.output["status"]) == ("done", "pending_payment")
    assert result.output["hold_expires_at"]


def test_declining_carries_the_persons_own_words_and_no_link(
    django_capture_on_commit_callbacks: Any,
) -> None:
    configured = on_request("prosby-odmowa")
    _, appointment = asked(configured, "prosba-anna")
    person = context_from_membership(configured["owner"])

    assert refused(person, decline(appointment, "Zapisy przez www.inna-strona.example")) == (
        "reason",
        "links",
    )
    risk, words = shown(person, decline(appointment, "W tym terminie mamy remont."))
    assert risk == "irreversible"
    assert words.startswith(f"Odmowa prośby o rezerwację: „{appointment.service_name}”, ")
    assert words.endswith(
        "Termin zostaje zwolniony. Klient dostanie e-mail od razu. W e-mailu będą Twoje słowa: "
        "„W tym terminie mamy remont.”."
    )
    # Without a reason nothing is said about one.
    assert "Twoje słowa" not in shown(person, decline(appointment, None))[1]

    with django_capture_on_commit_callbacks(execute=True):
        result = run(person, decline(appointment, "W tym terminie mamy remont."))

    assert (result.status, result.output["status"]) == ("done", "canceled")
    (mail,) = mails(appointment.id, "booking.request_declined")
    assert (mail.template_version, mail.context["reason"]) == (
        2,
        "W tym terminie mamy remont.",
    )
