"""How long an order names its buyer (ADR-073, slice 4i): an order money was
taken for keeps the buyer for five full calendar years after the year its
ledger was last written to, counted in the company's time zone. Taking a
customer out strips the customer and the visits and leaves the buyer on these
orders — by hand from the panel and by the company's removal of customers
after a time, the same way (the owner's answer of 04.10); the nightly privacy
run removes that buyer when the period ends. An order nobody paid for keeps
nothing."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.retention import cutoff_for, dry_run, run
from saas_core.modules.shared.booking import retention as booking_retention
from saas_core.modules.shared.booking.models import Appointment
from saas_core.modules.shared.booking.retention import (
    anonymization_preview,
    customers_due,
    erase_customers,
)
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.commerce import retention as buyers
from saas_core.modules.shared.commerce.api import place_order
from saas_core.modules.shared.commerce.models import LedgerEntry, Order, Refund
from saas_core.modules.shared.commerce.orders import read_order
from saas_core.modules.shared.commerce.payments import record_payment, void_payment
from saas_core.modules.shared.commerce.refunds import record_refund
from saas_core.modules.shared.commerce.retention import (
    BUYER_RETENTION_YEARS,
    buyers_due,
    erase_buyers,
    held_orders,
    kept_until,
    period_start,
)
from saas_core.modules.shared.customers.api import Customer
from saas_core.modules.shared.notifications.models import NotificationMessage
from saas_core.modules.shared.notifications.services import queue_email
from test_booking import _no_delivery, catalog, company_today, membership, tenant
from test_booking_prices import add
from test_booking_quote import WARSAW
from test_booking_slots import team
from test_commerce_orders import line, office, order_of, visit, with_orders
from test_organization_lifecycle import authenticated_member, csrf_value
from test_privacy_retention import change, customer, read_customer, switch_on
from test_team_people import bookable

pytestmark = pytest.mark.django_db

ANNA = {"display_name": "Anna Kowalska", "email": "anna@example.test", "phone": "600700800"}
PLACEHOLDER = ("Zanonimizowany klient", "", "")


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Commerce's clock reads `moment`: the period is counted from it."""
    monkeypatch.setattr(buyers, "timezone", SimpleNamespace(now=lambda: moment))


def buyer(member: Membership, order: Order) -> tuple[str, str, str]:
    with tenant(member):
        row = Order.all_objects.get(pk=order.id)
    return row.buyer_name, row.buyer_email, row.buyer_phone


def paid_visit(slug: str, **given: Any) -> tuple[dict[str, Any], Order]:
    """A company's visit at 150 with its order, paid at the desk."""
    configured = office(slug)
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    with tenant(configured["owner"]):
        booked = visit(configured, starts, customer_data=given.pop("customer_data", ANNA))
        order = order_of(booked)
        assert order is not None
        record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
    configured["visit"] = booked
    return configured, order


def test_the_period_is_five_full_calendar_years_in_the_companys_zone() -> None:
    owner = membership("okres-lata")
    assert BUYER_RETENTION_YEARS == 5

    # Through the last second of the fifth year the period reaches back to
    # the paying year's first day; a second later it no longer does.
    last = datetime(2031, 12, 31, 23, 59, 59, tzinfo=WARSAW)
    assert period_start(owner.organization_id, last) == datetime(2026, 1, 1, tzinfo=WARSAW)
    assert period_start(owner.organization_id, last + timedelta(seconds=1)) == datetime(
        2027, 1, 1, tzinfo=WARSAW
    )
    # The year is the company's, not the server's: half past midnight in
    # Warsaw on New Year's Day is still the old year in UTC.
    assert period_start(owner.organization_id, datetime(2031, 12, 31, 23, 30, tzinfo=UTC)) == (
        datetime(2027, 1, 1, tzinfo=WARSAW)
    )
    assert kept_until(datetime(2026, 6, 10, 12, tzinfo=UTC), WARSAW) == date(2031, 12, 31)
    assert kept_until(datetime(2026, 12, 31, 23, 30, tzinfo=UTC), WARSAW) == date(2032, 12, 31)

    Organization.objects.filter(pk=owner.organization_id).update(timezone="America/New_York")
    new_york = ZoneInfo("America/New_York")
    assert period_start(owner.organization_id, datetime(2032, 1, 1, 3, tzinfo=UTC)) == (
        datetime(2026, 1, 1, tzinfo=new_york)
    )


def test_taking_a_customer_out_leaves_the_buyer_on_the_paid_order_only() -> None:
    """A customer with two orders: the one money was taken for keeps its
    buyer, the one nobody paid for does not."""
    configured, paid = paid_visit("okres-dwa-zamowienia")
    owner: Membership = configured["owner"]
    year = timezone.now().astimezone(WARSAW).year
    with tenant(owner):
        second = visit(
            configured,
            datetime.combine(configured["monday"], time(12), WARSAW),
            customer_data=ANNA,
        )
        unpaid = order_of(second)
        assert unpaid is not None and unpaid.customer_id == paid.customer_id
        # Given back in part, with the company's own words about it.
        record_refund(
            paid.id, amount_minor=5000, method="cash", expected_version=2, reason="Anna, kolano"
        )
        Appointment.all_objects.filter(pk=second.id).update(customer_notes="Boli mnie kolano")
        queue_email(
            recipient_email=ANNA["email"],
            template_key="booking.confirmation",
            template_version=1,
            locale="pl",
            template_context={"organization_name": "Studio", "starts_at": "12.10 10:00"},
            idempotency_key="mail-paid",
            causation_id=f"commerce-order:{paid.id}",
        )

        before = anonymization_preview(paid.customer_id)
        anonymize_customer(paid.customer_id)
        after = anonymization_preview(paid.customer_id)
        shown, bare = read_order(paid.id), read_order(unpaid.id)
        person = Customer.all_objects.get(pk=paid.customer_id)
        notes = Appointment.all_objects.get(pk=second.id).customer_notes
        reasons = list(Refund.all_objects.values_list("reason", flat=True))
        mails = list(
            NotificationMessage.all_objects.filter(
                causation_id=f"commerce-order:{paid.id}"
            ).values_list("recipient_email", flat=True)
        )

    # Asked before anybody decides: what stays, until when and why.
    (kept,) = before["kept"]
    assert before["anonymized_at"] is None
    assert (kept["kind"], kept["label"], kept["reference"]) == (
        "commerce.order_buyer",
        paid.number,
        str(paid.id),
    )
    assert kept["until"] == date(year + 5, 12, 31)
    assert "5 pełnych lat" in kept["why"]["pl"] and "5 full calendar years" in kept["why"]["en"]
    assert after["anonymized_at"] is not None and after["kept"] == []

    # The customer and the visits are stripped as they always were…
    assert (person.display_name, person.email, person.phone) == PLACEHOLDER
    assert person.anonymized_at is not None and notes == ""
    # …the mails' copies and the company's words about the refund go too…
    assert reasons == [""]
    assert mails and all(address.endswith("@invalid.local") for address in mails)
    # …the sales record names its buyer until the period ends, and says so…
    assert buyer(owner, paid) == (ANNA["display_name"], ANNA["email"], ANNA["phone"])
    assert shown["customer_anonymized_at"] is not None
    assert shown["buyer_kept_until"] == date(year + 5, 12, 31)
    # …and the order nobody paid for keeps nothing.
    assert buyer(owner, unpaid) == PLACEHOLDER
    assert bare["customer_anonymized_at"] is not None and bare["buyer_kept_until"] is None


def test_an_order_of_a_named_customer_says_nothing_about_keeping() -> None:
    configured, paid = paid_visit("okres-nazwany")
    with tenant(configured["owner"]):
        shown = read_order(paid.id)
    assert (shown["customer_anonymized_at"], shown["buyer_kept_until"]) == (None, None)


def test_the_run_removes_the_buyer_on_the_first_day_after_the_fifth_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, paid = paid_visit("okres-granica")
    owner: Membership = configured["owner"]
    year = timezone.now().astimezone(WARSAW).year
    with tenant(owner):
        anonymize_customer(paid.customer_id)
    assert buyer(owner, paid)[0] == ANNA["display_name"]

    # The last second of the fifth calendar year: nothing is due.
    last = datetime(year + 5, 12, 31, 23, 59, 59, tzinfo=WARSAW)
    assert [item for item in dry_run(last) if item.sweep == "commerce.buyers"] == []
    assert [item for item in run(last).removed if item.sweep == "commerce.buyers"] == []
    assert buyer(owner, paid)[0] == ANNA["display_name"]

    # Midnight in the company's zone: the period has ended.
    first = last + timedelta(seconds=1)
    (due,) = [item for item in dry_run(first) if item.sweep == "commerce.buyers"]
    assert (due.count, due.period, due.waits_until) == (1, "5 lat", None)
    assert due.cutoff == datetime(year + 1, 1, 1, tzinfo=WARSAW)
    (removed,) = [item for item in run(first).removed if item.sweep == "commerce.buyers"]
    assert (removed.organization_id, removed.count) == (owner.organization_id, 1)
    assert buyer(owner, paid) == PLACEHOLDER
    # The order itself stays: its number, its lines and its money.
    with tenant(owner):
        at(monkeypatch, first)
        shown = read_order(paid.id)
        audit = OrganizationAuditEntry.objects.get(
            organization_id=owner.organization_id, action="privacy.retention.run"
        )
    assert (shown["number"], shown["paid_minor"], shown["buyer_kept_until"]) == (
        paid.number,
        15000,
        None,
    )
    # One history row for the run: counts, never a person.
    assert audit.metadata == {"sweep": "commerce.buyers", "period": "5 lat", "removed": 1}
    # Running it again removes nothing.
    assert run(first).removed == ()


def test_a_ledger_entry_added_late_starts_the_period_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, paid = paid_visit("okres-pozny-wpis")
    owner: Membership = configured["owner"]
    year = timezone.now().astimezone(WARSAW).year
    with tenant(owner):
        anonymize_customer(paid.customer_id)
        # Three years on the company gives a part back: the ledger is written
        # to again, so the five years are counted from that year.
        LedgerEntry.all_objects.create(
            organization_id=owner.organization_id,
            order=paid,
            kind="refund",
            amount_minor=-5000,
            currency="PLN",
            occurred_at=datetime(year + 3, 3, 1, 12, tzinfo=WARSAW),
        )
        until = held_orders(owner.organization_id, [paid.id])[paid.id]
    assert until == date(year + 8, 12, 31)

    after_first_period = datetime(year + 6, 1, 1, tzinfo=WARSAW)
    assert run(after_first_period).removed == ()
    assert buyer(owner, paid)[0] == ANNA["display_name"]
    assert run(datetime(year + 8, 12, 31, 23, 59, tzinfo=WARSAW)).removed == ()
    (removed,) = run(datetime(year + 9, 1, 1, tzinfo=WARSAW)).removed
    assert (removed.sweep, removed.count) == ("commerce.buyers", 1)
    assert buyer(owner, paid) == PLACEHOLDER


def test_an_entry_written_later_than_it_occurred_counts_from_when_it_was_written() -> None:
    """Both of an entry's dates are read, and the later one decides."""
    owner = membership("okres-wpis-wsteczny")
    with_orders(owner.organization_id)
    with tenant(owner):
        person = Customer.all_objects.create(
            organization_id=owner.organization_id,
            display_name="Jan Dawny",
            email="jan@example.test",
            contact_hash="d" * 64,
        )
        order = place_order(
            source="booking",
            customer=person,
            currency="PLN",
            amounts="gross",
            lines=[line(10000)],
            channel="office",
        )
        assert order is not None
        # Money that came in 2020, written down only now.
        LedgerEntry.all_objects.create(
            organization_id=owner.organization_id,
            order=order,
            kind="charge",
            amount_minor=10000,
            currency="PLN",
            occurred_at=datetime(2020, 5, 1, 12, tzinfo=WARSAW),
        )
        held = held_orders(owner.organization_id, [order.id])
    year = timezone.now().astimezone(WARSAW).year
    assert held == {order.id: date(year + 5, 12, 31)}


def test_the_run_asks_the_ledger_again_under_the_orders_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry written between finding the order and locking it keeps the
    buyer: what the first read found is asked again."""
    configured, paid = paid_visit("okres-wyscig")
    owner: Membership = configured["owner"]
    year = timezone.now().astimezone(WARSAW).year
    with tenant(owner):
        anonymize_customer(paid.customer_id)
    start = datetime(year + 1, 1, 1, tzinfo=WARSAW)
    found = buyers.buyers_due

    def then_refunded(organization_id: Any, cutoff: Any) -> list[Any]:
        due = found(organization_id, cutoff)
        LedgerEntry.all_objects.create(
            organization_id=owner.organization_id,
            order=paid,
            kind="refund",
            amount_minor=-1000,
            currency="PLN",
            occurred_at=start + timedelta(days=1),
        )
        return due

    with tenant(owner):
        assert found(owner.organization_id, start) == [paid.id]
        monkeypatch.setattr(buyers, "buyers_due", then_refunded)
        assert erase_buyers(owner.organization_id, start, 10) == 0
    assert buyer(owner, paid)[0] == ANNA["display_name"]


def test_a_payment_taken_back_as_a_mistake_is_no_sale(monkeypatch: pytest.MonkeyPatch) -> None:
    configured, paid = paid_visit("okres-pomylka")
    owner: Membership = configured["owner"]
    with tenant(owner):
        other = visit(
            configured,
            datetime.combine(configured["monday"], time(13), WARSAW),
            customer_data={"display_name": "Ewa Nowa", "email": "ewa@example.test", "phone": ""},
        )
        mistaken = order_of(other)
        assert mistaken is not None
        marked = record_payment(mistaken.id, amount_minor=15000, method="cash", expected_version=1)
        void_payment(mistaken.id, marked["payments"][0]["id"], expected_version=2)
        # Marked and taken back before the customer goes: nothing was sold.
        assert anonymization_preview(mistaken.customer_id)["kept"] == []
        anonymize_customer(mistaken.customer_id)

        # Taken back after the customer went: the buyer was kept, and the
        # next run removes it without waiting five years.
        anonymize_customer(paid.customer_id)
        payment_id = read_order(paid.id)["payments"][0]["id"]
        void_payment(paid.id, payment_id, expected_version=2)
        due = buyers_due(owner.organization_id)

    assert buyer(owner, mistaken) == PLACEHOLDER
    assert due == [paid.id]
    assert [(item.sweep, item.count) for item in run().removed] == [("commerce.buyers", 1)]
    assert buyer(owner, paid) == PLACEHOLDER


def test_a_payment_marked_after_the_customer_went_finds_the_buyer_gone() -> None:
    """The order was not paid for when the customer was taken out, so its
    buyer went; money marked afterwards cannot bring a name back."""
    configured = office("okres-pozna-wplata")
    owner: Membership = configured["owner"]
    with tenant(owner):
        booked = visit(
            configured,
            datetime.combine(configured["monday"], time(10), WARSAW),
            customer_data=ANNA,
        )
        order = order_of(booked)
        assert order is not None
        anonymize_customer(order.customer_id)
        record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
        shown = read_order(order.id)
        due = buyers_due(owner.organization_id)

    assert buyer(owner, order) == PLACEHOLDER
    assert (shown["paid_minor"], shown["buyer_kept_until"]) == (15000, None)
    # Nothing is left for the run either.
    assert due == []


def sold(member: Membership, person: Any, gross: int = 12000) -> Order:
    """An order of `person` money was taken for now."""
    with tenant(member):
        order = place_order(
            source="booking",
            customer=Customer.all_objects.get(pk=person.id),
            currency="PLN",
            amounts="gross",
            lines=[line(gross)],
            channel="office",
        )
        assert order is not None
        record_payment(order.id, amount_minor=gross, method="transfer", expected_version=1)
    return order


def test_the_companys_removal_strips_a_buyer_and_leaves_the_paid_order_named() -> None:
    """The run keeps no more than a person's click does: the customer and
    the visits go at the company's period, the buyer stays on the sales
    record until its own."""
    owner = membership("okres-przebieg")
    with_orders(owner.organization_id)
    configured = catalog(owner)
    bought = customer(owner, configured, "kupila", ended=40)
    asked = customer(owner, configured, "pytal", ended=40)
    order = sold(owner, bought)
    year = timezone.now().astimezone(WARSAW).year
    with tenant(owner):
        # An order nobody paid for keeps nothing.
        unpaid = place_order(
            source="booking",
            customer=Customer.all_objects.get(pk=asked.id),
            currency="PLN",
            amounts="gross",
            lines=[line(9000)],
            channel="office",
        )
        assert unpaid is not None
        due = set(customers_due(owner.organization_id, cutoff_for(24)).values_list("id", flat=True))
    # Having bought something holds nobody back.
    assert due == {asked.id, bought.id}

    # The preview says what stays, until when and why, before anybody saves —
    # in the words of the module that keeps it, not as customers who stay.
    (effect,) = change(owner, "booking.retention", preview=True, customers="24").effects
    assert "dotyczy teraz: 2." in effect.summary["pl"]
    assert "którzy na razie zostają" not in effect.summary["pl"]
    assert (
        "Dane kupującego (imię i nazwisko, e-mail, telefon) zostają w zamówieniu z wpłatą"
        in effect.summary["pl"]
    )
    assert (
        f"U klientów, których dotyczy teraz, zostaje tak: 1 — najdłużej do {year + 5}-12-31."
        in effect.summary["pl"]
    )
    assert (
        f"For the customers affected now this keeps: 1 — the longest until {year + 5}-12-31."
        in effect.summary["en"]
    )

    switch_on(owner)
    assert [(item.sweep, item.count) for item in run().removed] == [("booking.customers", 2)]
    assert read_customer(owner, asked).anonymized_at is not None
    gone = read_customer(owner, bought)
    assert (gone.display_name, gone.email, gone.phone) == PLACEHOLDER
    assert gone.anonymized_at is not None
    with tenant(owner):
        assert Appointment.all_objects.get(pk=bought.visit_id).customer_notes == ""
        shown = read_order(order.id)
    # The sales record names its buyer, and says until when…
    assert buyer(owner, order) == ("kupila", "kupila@example.test", "+48500100200")
    assert shown["buyer_kept_until"] == date(year + 5, 12, 31)
    # …the order nobody paid for does not.
    assert buyer(owner, unpaid) == PLACEHOLDER

    # The first day after the fifth year the other sweep removes the buyer.
    last = datetime(year + 5, 12, 31, 23, 59, 59, tzinfo=WARSAW)
    assert [item for item in run(last).removed if item.sweep == "commerce.buyers"] == []
    assert buyer(owner, order)[0] == "kupila"
    first = last + timedelta(seconds=1)
    assert [item.count for item in run(first).removed if item.sweep == "commerce.buyers"] == [1]
    assert buyer(owner, order) == PLACEHOLDER


def test_a_payment_marked_while_the_run_was_looking_keeps_the_buyer_on_the_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run chose its customers before the payment was marked: the strip
    locks the customer's orders and reads the ledger from under the lock, so
    the order paid for meanwhile keeps its buyer — the customer goes."""
    owner = membership("okres-przebieg-wyscig")
    with_orders(owner.organization_id)
    configured = catalog(owner)
    paying = customer(owner, configured, "placi", ended=40)
    free = customer(owner, configured, "wolny", ended=40)
    with tenant(owner):
        candidates = Customer.all_objects.filter(
            organization_id=owner.organization_id, id__in=[paying.id, free.id]
        )
        monkeypatch.setattr(
            booking_retention, "customers_due", lambda organization_id, cutoff: candidates
        )
    # Committed after the run chose its candidates: the order is paid for.
    order = sold(owner, paying)
    with tenant(owner):
        assert erase_customers(owner.organization_id, cutoff_for(24), 10) == 2

    assert read_customer(owner, paying).anonymized_at is not None
    assert read_customer(owner, free).anonymized_at is not None
    assert buyer(owner, order) == ("placi", "placi@example.test", "+48500100200")


def _left_behind(way: str) -> dict[str, Any]:
    """What is left of a customer with a paid order, an unpaid one, a refund
    with the company's words, a visit's notes and stored mails — taken out
    `by_hand` (the panel) or by the `run` (the company's period)."""
    owner = membership(f"okres-oba-{way.replace('_', '-')}")
    with_orders(owner.organization_id)
    configured = catalog(owner)
    # The helpers' keys are the name's: one name per company, read back as „anna”.
    name = f"anna-{way.replace('_', '-')}"
    person = customer(owner, configured, name, ended=40)
    paid = sold(owner, person)
    with tenant(owner):
        unpaid = place_order(
            source="booking",
            customer=Customer.all_objects.get(pk=person.id),
            currency="PLN",
            amounts="gross",
            lines=[line(9000)],
            channel="office",
        )
        assert unpaid is not None
        record_refund(
            paid.id, amount_minor=5000, method="cash", expected_version=2, reason="Anna, kolano"
        )
        queue_email(
            recipient_email=person.email,
            template_key="booking.confirmation",
            template_version=1,
            locale="pl",
            template_context={"organization_name": "Studio", "starts_at": "12.10 10:00"},
            idempotency_key=f"mail-paid-{way}",
            causation_id=f"commerce-order:{paid.id}",
        )
        foretold = anonymization_preview(person.id)["kept"]
    if way == "by_hand":
        with tenant(owner):
            anonymize_customer(person.id)
    else:
        switch_on(owner)
        assert [(item.sweep, item.count) for item in run().removed] == [("booking.customers", 1)]
    with tenant(owner):
        row = Customer.all_objects.get(pk=person.id)
        visit_row = Appointment.all_objects.get(pk=person.visit_id)
        return {
            "customer": (row.display_name, row.email, row.phone, row.anonymized_at is not None),
            "visit": (visit_row.customer_notes, visit_row.place_address, visit_row.place_town),
            "paid_order": tuple(text.replace(name, "anna") for text in buyer(owner, paid)),
            "paid_order_kept_until": read_order(paid.id)["buyer_kept_until"],
            "unpaid_order": buyer(owner, unpaid),
            "unpaid_order_kept_until": read_order(unpaid.id)["buyer_kept_until"],
            "refund_reasons": list(
                Refund.all_objects.filter(order_id=paid.id).values_list("reason", flat=True)
            ),
            "mails": sorted(
                (template, address.endswith("@invalid.local"))
                for template, address in NotificationMessage.all_objects.filter(
                    causation_id__in=[f"commerce-order:{paid.id}", f"booking:{person.visit_id}"]
                ).values_list("template_key", "recipient_email")
            ),
            "foretold": [(item["kind"], item["until"]) for item in foretold],
            "left_after": len(anonymization_preview(person.id)["kept"]),
        }


def test_the_hand_and_the_run_leave_exactly_the_same() -> None:
    """The owner's answer of 04.10 (variant b): the company's removal after a
    time strips a customer with a paid order as the hand anonymisation does —
    the card and the visits go, only the buyer's snapshot stays in the order
    for its period."""
    year = timezone.now().astimezone(WARSAW).year
    by_hand, by_run = _left_behind("by_hand"), _left_behind("run")

    assert by_hand == by_run
    assert by_run == {
        "customer": (*PLACEHOLDER, True),
        "visit": ("", "", "Olsztyn"),
        "paid_order": ("anna", "anna@example.test", "+48500100200"),
        "paid_order_kept_until": date(year + 5, 12, 31),
        "unpaid_order": PLACEHOLDER,
        "unpaid_order_kept_until": None,
        "refund_reasons": [""],
        "mails": [
            ("booking.confirmation", True),
            ("booking.confirmation", True),
            ("booking.confirmation", True),
            ("commerce.refund_marked", True),
        ],
        "foretold": [("commerce.order_buyer", date(year + 5, 12, 31))],
        "left_after": 0,
    }


def test_the_panel_reads_what_stays_over_the_api_and_only_in_its_own_company() -> None:
    _, owner, client = authenticated_member(
        email="okres-api@example.test", role_key="owner", slug="okres-api"
    )
    bookable(owner.organization)
    with_orders(owner.organization_id)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    today = company_today()
    starts = datetime.combine(today + timedelta(days=7 - today.weekday()), time(9), WARSAW)
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
        configured["owner"] = owner
        order = order_of(visit(configured, starts, customer_data=ANNA))
        assert order is not None
        record_payment(order.id, amount_minor=15000, method="cash", expected_version=1)
    url = f"/api/v1/booking/customers/{order.customer_id}/anonymize/"

    seen = client.get(f"{url}preview/")
    assert seen.status_code == 200, seen.data
    (kept,) = seen.json()["kept"]
    year = timezone.now().astimezone(WARSAW).year
    assert (kept["label"], kept["until"]) == (order.number, f"{year + 5}-12-31")
    assert set(kept["why"]) == {"pl", "en"}
    done = client.post(url, {}, format="json", HTTP_X_CSRFTOKEN=csrf_value(client))
    assert done.status_code == 200, done.data
    shown = client.get(f"/api/v1/commerce/orders/{order.id}/").json()
    assert shown["buyer_name"] == ANNA["display_name"]
    assert shown["buyer_kept_until"] == f"{year + 5}-12-31"
    assert shown["customer_anonymized_at"] is not None
    assert client.get(f"{url}preview/").json()["kept"] == []

    # Another company's customer is not there at all.
    _, stranger, other = authenticated_member(
        email="okres-obcy@example.test", role_key="owner", slug="okres-obcy"
    )
    bookable(stranger.organization)
    assert other.get(f"{url}preview/").status_code == 404
    # Whoever may not anonymise is not told what would stay either.
    viewer = Role.objects.create(
        key="widz",
        organization=owner.organization,
        name="Widz",
        scope=RoleScope.ORGANIZATION,
        permissions=["booking.appointment.read"],
    )
    Membership.objects.filter(pk=owner.pk).update(role=viewer)
    reader = Membership.objects.select_related("role", "organization", "user").get(pk=owner.pk)
    with tenant(reader), pytest.raises(OrganizationPermissionDenied):
        anonymization_preview(order.customer_id)
