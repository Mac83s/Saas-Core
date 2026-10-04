"""Orders (ADR-073 §1, §3, phase 4e): a priced booking is an order with a
number of its company and year, the lines its quote came to and the buyer as
they were; a move at another price writes the next revision, a cancellation
cancels it; a placed line is never rewritten; the panel reads what the
company's plan and the reader's role allow."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.currency import refuse_currency_in_use
from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import EntitlementSnapshot, Feature
from saas_core.modules.shared.booking import orders as booking_orders
from saas_core.modules.shared.booking.models import Appointment, VatCode
from saas_core.modules.shared.booking.services import (
    anonymize_customer,
    cancel_appointment,
    create_appointment,
    reschedule_appointment,
)
from saas_core.modules.shared.commerce.api import (
    COMMERCE_ENABLED,
    OrderLineInput,
    TaxRate,
    order_for,
    place_order,
    reprice_order,
)
from saas_core.modules.shared.commerce.models import Order, OrderCounter, OrderLine
from saas_core.modules.shared.commerce.orders import list_orders, read_order
from saas_core.modules.shared.commerce.sources import order_sources, register_order_source
from saas_core.modules.shared.customers.api import Customer, match_or_create
from test_booking import _no_delivery, company_today, membership, tenant
from test_booking_prices import add, key
from test_booking_public_price import first_start, priced
from test_booking_quote import WARSAW, day, priced_cottages
from test_booking_slots import team
from test_booking_stays import GUEST, stay
from test_customers_documents import approved, with_second_factor
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable

pytestmark = pytest.mark.django_db

YEAR = company_today().year


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def with_orders(organization_id: Any) -> None:
    """The company's plan has orders."""
    Feature.objects.get_or_create(
        key=COMMERCE_ENABLED, defaults={"name": "Zamówienia", "module": "shared.commerce"}
    )
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=organization_id)
    snapshot.features = {**snapshot.features, COMMERCE_ENABLED: True}
    snapshot.sources = {**snapshot.sources, COMMERCE_ENABLED: {"kind": "plan"}}
    snapshot.save(update_fields=["features", "sources"])


def form_booking(client: APIClient, configured: dict[str, Any], name: str) -> dict[str, Any]:
    """What the public form sends for the priced visit, at the price it showed."""
    body = {
        "service_id": str(configured["service"].id),
        "starts_at": first_start(client, configured),
    }
    quote = client.post(f"{configured['url']}/quote/", body, format="json").json()["quote"]
    return {
        **configured["query"],
        "starts_at": body["starts_at"],
        "customer": {
            "display_name": "Anna Kowalska",
            "email": f"{name}@example.test",
            "phone": "+48 600 100 200",
        },
        "quote_digest": quote["digest"],
    }


def send(client: APIClient, configured: dict[str, Any], body: dict[str, Any], name: str) -> Any:
    return client.post(
        f"{configured['url']}/appointments/", body, format="json", HTTP_IDEMPOTENCY_KEY=name
    )


def office(slug: str) -> dict[str, Any]:
    """A company with orders whose visit costs 150 and 180 on Tuesdays."""
    owner = membership(slug)
    with_orders(owner.organization_id)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
        add(18000, service_id=configured["service"].id, weekdays=[1])
    configured["owner"] = owner
    today = company_today()
    configured["monday"] = today + timedelta(days=7 - today.weekday())
    return configured


def visit(configured: dict[str, Any], starts_at: datetime, **given: Any) -> Appointment:
    owner: Membership = configured["owner"]
    return create_appointment(
        service_id=configured["service"].id,
        staff_id=configured["staff"][0].id,
        location_id=configured["location"].id,
        starts_at=starts_at,
        customer_data=given.pop("customer_data", GUEST),
        idempotency_key=key(),
        principal_ref=str(owner.user_id),
        **given,
    ).appointment


def order_of(appointment: Appointment) -> Order | None:
    return order_for(booking_orders.LINE_SOURCE, str(appointment.id))


def line(gross: int, **given: Any) -> OrderLineInput:
    values = {
        "kind": "product",
        "name": "Kubek",
        "customer_name": "Mug",
        "quantity": 1,
        "unit_amount_minor": gross,
        "net_minor": gross,
        "vat_minor": 0,
        "gross_minor": gross,
        "tax_rate": "zw",
        "source": "test.item",
        "source_reference": "1",
    }
    return OrderLineInput(**{**values, **given})


def test_a_priced_booking_on_the_form_is_an_order_with_the_lines_of_its_quote() -> None:
    configured = priced("zamowienie-formularz")
    owner: Membership = configured["owner"]
    with_orders(owner.organization_id)
    client = APIClient()

    # The company has a privacy policy: the form shows it and the buyer accepts it.
    approved(with_second_factor(owner))
    (document,) = client.get(f"{configured['url']}/consents/").json()["documents"]
    body = {
        **form_booking(client, configured, "zamowienie-anna"),
        "consents": {"documents": [document["text_id"]]},
    }
    made = send(client, configured, body, "zamowienie-anna")
    # The same request again answers the first booking and places nothing.
    again = send(client, configured, body, "zamowienie-anna")

    assert made.status_code == 201, made.data
    assert again.json()["id"] == made.json()["id"]
    with tenant(owner):
        appointment = Appointment.all_objects.get(organization_id=owner.organization_id)
        (order,) = Order.all_objects.filter(organization_id=owner.organization_id)
        lines = list(OrderLine.all_objects.filter(order=order).order_by("position"))
        audit = OrganizationAuditEntry.objects.get(action="commerce.order.placed")
        consents = read_order(order.id)["consents"]
    assert (order.number, order.source, order.channel) == (
        f"R/{YEAR}/0001",
        "booking",
        "company_site",
    )
    assert (order.status, order.currency, order.amounts) == ("awaiting_payment", "PLN", "gross")
    assert (order.buyer_name, order.buyer_email, order.buyer_phone) == (
        "Anna Kowalska",
        "zamowienie-anna@example.test",
        "+48 600 100 200",
    )
    assert order.customer_id == appointment.customer_id
    # The visit at 150 and the travel every booking pays for, as the quote froze them.
    assert [
        (row.kind, row.name, row.quantity, row.unit_amount_minor, row.gross_minor, row.tax_rate)
        for row in lines
    ] == [("booking", "Wizyta", 1, 15000, 15000, "23"), ("extra", "Dojazd", 1, 5000, 5000, "23")]
    assert {(row.source, row.source_reference, row.revision) for row in lines} == {
        ("booking.appointment", str(appointment.id), 1)
    }
    quote = appointment.quote
    assert (order.net_minor, order.vat_minor, order.gross_minor) == (
        quote["net_minor"],
        quote["vat_minor"],
        20000,
    )
    # The order says what its buyer accepted, from the consent journal.
    assert [{**consent, "created_at": None} for consent in consents] == [
        {
            "kind": "document",
            "document_kind": "privacy_policy",
            "version": 1,
            "locale": "pl",
            "granted": True,
            "created_at": None,
        }
    ]
    # The history names the order, never the buyer.
    assert (audit.target_type, audit.target_id) == ("order", order.id)
    assert audit.metadata == {
        "number": order.number,
        "source": "booking",
        "channel": "company_site",
        "gross_minor": 20000,
    }


def test_the_offices_bookings_are_numbered_one_after_another_in_each_company() -> None:
    first, other = office("zamowienia-biuro"), office("zamowienia-inna-firma")
    starts = datetime.combine(first["monday"], time(10), WARSAW)

    with tenant(first["owner"]):
        orders = [order_of(visit(first, starts + timedelta(hours=hour))) for hour in (0, 2)]
    with tenant(other["owner"]):
        elsewhere = order_of(visit(other, starts))

    assert [(order.number, order.channel) for order in orders if order] == [
        (f"R/{YEAR}/0001", "office"),
        (f"R/{YEAR}/0002", "office"),
    ]
    assert elsewhere is not None and elsewhere.number == f"R/{YEAR}/0001"


def test_a_number_comes_from_a_locked_counter_and_from_the_companys_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = office("zamowienia-rok")
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    # Half past midnight in Warsaw on New Year's Day is still last year in UTC.
    new_year = datetime(YEAR, 12, 31, 23, 30, tzinfo=UTC)
    with tenant(configured["owner"]):
        # Only the clock commerce reads: the booking itself is next week's.
        monkeypatch.setattr(
            "saas_core.modules.shared.commerce.orders.timezone",
            SimpleNamespace(now=lambda: new_year),
        )
        with CaptureQueriesContext(connection) as queries:
            order = order_of(visit(configured, starts))
        counter = OrderCounter.all_objects.get(organization_id=configured["owner"].organization_id)

    assert order is not None and order.number == f"R/{YEAR + 1}/0001"
    assert (counter.prefix, counter.year, counter.last) == ("R", YEAR + 1, 1)
    assert any(
        "commerce_ordercounter" in query["sql"] and "FOR UPDATE" in query["sql"]
        for query in queries.captured_queries
    )


def test_a_booking_without_a_price_or_without_orders_has_no_order(settings: Any) -> None:
    # No price list: nothing was sold for an amount.
    unpriced = membership("zamowienia-bez-ceny")
    with_orders(unpriced.organization_id)
    free = team(unpriced, people=1, hours=(time(8), time(16)), duration=60)
    free["owner"] = unpriced
    # A price, but a plan from before orders.
    earlier = office("zamowienia-stary-plan")
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=earlier["owner"].organization_id)
    snapshot.features = {"booking.enabled": True}
    snapshot.save(update_fields=["features"])
    # A product that leaves commerce out.
    without = office("zamowienia-bez-modulu")
    starts = datetime.combine(earlier["monday"], time(10), WARSAW)

    with tenant(unpriced):
        visit(free, starts)
    with tenant(earlier["owner"]):
        kept = visit(earlier, starts)
        moved = reschedule_appointment(
            appointment_id=kept.id,
            starts_at=starts + timedelta(days=1),
            idempotency_key=key(),
            principal_ref="test",
        )
        cancel_appointment(appointment_id=kept.id, idempotency_key=key(), principal_ref="test")
    settings.ACTIVE_MODULES = [m for m in settings.ACTIVE_MODULES if m != "shared.commerce"]
    with tenant(without["owner"]):
        visit(without, starts)

    assert moved.quote["gross_minor"] == 18000
    assert not Order.all_objects.exists()


def test_a_move_at_another_price_writes_the_next_revision_and_keeps_the_earlier_lines() -> None:
    configured = office("zamowienia-przeniesienie")
    owner: Membership = configured["owner"]
    monday = datetime.combine(configured["monday"], time(10), WARSAW)

    def move(appointment: Appointment, starts_at: datetime) -> None:
        reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=starts_at,
            idempotency_key=key(),
            principal_ref=str(owner.user_id),
        )

    with tenant(owner):
        booked = visit(configured, monday)
        # Another hour of the same day costs the same: nothing changes.
        move(booked, monday + timedelta(hours=2))
        same = order_of(booked)
        assert same is not None and (same.revision, same.version, same.gross_minor) == (1, 1, 15000)
        # Tuesday is dearer.
        move(booked, monday + timedelta(days=1))
        order = order_of(booked)
        assert order is not None
        read = read_order(order.id)
        rows = list(OrderLine.all_objects.filter(order=order).order_by("revision", "position"))
        audit = OrganizationAuditEntry.objects.get(action="commerce.order.repriced")

    assert (order.revision, order.version, order.gross_minor, order.status) == (
        2,
        2,
        18000,
        "awaiting_payment",
    )
    assert [(row.revision, row.gross_minor) for row in rows] == [(1, 15000), (2, 18000)]
    assert [item["gross_minor"] for item in read["lines"]] == [18000]
    assert read["revisions"] == [
        {"revision": 1, "gross_minor": 15000},
        {"revision": 2, "gross_minor": 18000},
    ]
    assert audit.metadata["changes"] == {"gross_minor": {"from": 15000, "to": 18000}}


def test_a_stay_is_an_order_and_its_move_prices_the_order_again() -> None:
    owner = membership("zamowienia-pobyt")
    with_orders(owner.organization_id)
    setup = priced_cottages(owner)

    with tenant(owner):
        booked = stay(setup, day(6, 1), day(6, 4)).appointment
        order = order_of(booked)
        assert order is not None
        before = (order.number, order.gross_minor, order.revision)
        lines = list(OrderLine.all_objects.filter(order=order))

    # Three nights at 300, at 8%.
    assert before == (f"R/{YEAR}/0001", 90000, 1)
    assert [(row.kind, row.quantity, row.unit_amount_minor, row.tax_rate) for row in lines] == [
        ("booking", 3, 30000, "8")
    ]
    assert order.net_minor + order.vat_minor == order.gross_minor


def test_a_canceled_booking_cancels_its_order_and_a_canceled_order_takes_no_lines() -> None:
    configured = office("zamowienia-anulowanie")
    starts = datetime.combine(configured["monday"], time(10), WARSAW)

    with tenant(configured["owner"]):
        booked = visit(configured, starts)
        for _ in range(2):  # The second cancellation finds it canceled already.
            cancel_appointment(
                appointment_id=booked.id, idempotency_key=key(), principal_ref="test"
            )
        order = order_of(booked)
        assert order is not None
        audits = OrganizationAuditEntry.objects.filter(action="commerce.order.canceled").count()
        with pytest.raises(ValueError, match="canceled"):
            reprice_order(order, amounts="gross", lines=[line(100)])

    assert (order.status, order.version) == ("canceled", 2)
    assert audits == 1


def test_a_placed_line_is_never_rewritten_and_nothing_points_into_another_company() -> None:
    configured, other = office("zamowienia-wiersze"), office("zamowienia-wiersze-obce")
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    with tenant(configured["owner"]):
        order = order_of(visit(configured, starts))
        assert order is not None
        placed = OrderLine.all_objects.get(order=order)
    with tenant(other["owner"]):
        stranger, _email = match_or_create(other["owner"].organization, GUEST)

    for change in (
        lambda: OrderLine.all_objects.filter(pk=placed.pk).update(gross_minor=1),
        lambda: OrderLine.all_objects.filter(pk=placed.pk).delete(),
        # A line in another company's order, an order for another company's customer.
        lambda: OrderLine.all_objects.create(
            organization=other["owner"].organization,
            order=order,
            revision=1,
            position=9,
            kind="fee",
            name="x",
            customer_name="x",
            quantity=1,
            unit_amount_minor=1,
            net_minor=1,
            vat_minor=0,
            gross_minor=1,
            tax_rate="zw",
            source="test",
            source_reference="1",
        ),
        lambda: Order.all_objects.filter(pk=order.pk).update(customer=stranger),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            change()
    assert OrderLine.all_objects.get(pk=placed.pk).gross_minor == 15000


def test_anonymising_the_customer_clears_the_buyer_and_keeps_the_amounts() -> None:
    configured = office("zamowienia-anonimizacja")
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    guest = {"display_name": "Jan Nowak", "email": "jan@example.test", "phone": "600700800"}

    with tenant(configured["owner"]):
        booked = visit(configured, starts, customer_data=guest)
        anonymize_customer(booked.customer_id)
        order = order_of(booked)

    assert order is not None
    assert (order.buyer_name, order.buyer_email, order.buyer_phone) == (
        "Zanonimizowany klient",
        "",
        "",
    )
    assert (order.number, order.gross_minor) == (f"R/{YEAR}/0001", 15000)
    assert OrderLine.all_objects.filter(order=order).count() == 1


def test_a_company_with_orders_keeps_its_currency_and_its_erasure_takes_them() -> None:
    owner = membership("zamowienia-waluta")
    with_orders(owner.organization_id)
    organization_id = owner.organization_id
    with tenant(owner):
        customer: Customer = match_or_create(owner.organization, GUEST)[0]
        refuse_currency_in_use(organization_id)  # No amounts yet: the currency may change.
        order = place_order(
            source="booking",
            customer=customer,
            currency="PLN",
            amounts="gross",
            lines=[line(0)],
            channel="office",
        )
        with pytest.raises(ValidationError) as refused:
            refuse_currency_in_use(organization_id)
        # Another currency than the company's is the source's mistake.
        with pytest.raises(ValueError, match="currency"):
            place_order(
                source="booking",
                customer=customer,
                currency="EUR",
                amounts="gross",
                lines=[line(100)],
                channel="office",
            )

    # Nothing to pay is paid.
    assert order is not None and (order.status, order.gross_minor) == ("paid", 0)
    assert refused.value.detail["currency"][0].code == "currency_in_use"

    erase_organization(organization=owner.organization, requested_by=None, reason="test")

    for model in (Order, OrderLine, OrderCounter):
        assert not model.all_objects.filter(organization_id=organization_id).exists()


def test_two_sources_never_number_into_one_sequence() -> None:
    assert [(source.kind, source.prefix) for source in order_sources()] == [("booking", "R")]
    with pytest.raises(ImproperlyConfigured, match="belongs to 'booking'"):
        register_order_source("shop", "R")
    with pytest.raises(ImproperlyConfigured, match="capital letters"):
        register_order_source("shop", "z1")
    with tenant(membership("zamowienia-zrodlo")), pytest.raises(LookupError):
        with_orders(Organization.objects.get(slug="zamowienia-zrodlo").id)
        place_order(
            source="shop",
            customer=Customer(),
            currency="PLN",
            amounts="gross",
            lines=[line(100)],
            channel="office",
        )


def test_a_bookings_tax_codes_are_an_orders_tax_rates() -> None:
    assert set(VatCode.values) == set(TaxRate.values)


def test_the_panel_lists_filters_and_reads_orders_over_the_api() -> None:
    _, owner, client = authenticated_member(
        email="zamowienia-api@example.test", role_key="owner", slug="zamowienia-api"
    )
    bookable(owner.organization)
    with_orders(owner.organization_id)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    configured["owner"] = owner
    today = company_today()
    starts = datetime.combine(today + timedelta(days=7 - today.weekday()), time(9), WARSAW)
    with tenant(owner):
        add(15000, service_id=configured["service"].id)
        anna = visit(
            configured,
            starts,
            customer_data={"display_name": "Anna Lis", "email": "lis@example.test"},
        )
        jan = visit(
            configured,
            starts + timedelta(hours=2),
            customer_data={"display_name": "Jan Kot", "email": "kot@example.test"},
        )
        cancel_appointment(appointment_id=jan.id, idempotency_key=key(), principal_ref="test")
    stranger = office("zamowienia-api-obce")
    with tenant(stranger["owner"]):
        foreign = order_of(visit(stranger, starts))
        assert foreign is not None

    def numbers(**query: Any) -> list[str]:
        answer = client.get("/api/v1/commerce/orders/", query)
        assert answer.status_code == 200, answer.data
        return [item["number"] for item in answer.json()["items"]]

    listed = client.get("/api/v1/commerce/orders/").json()
    assert (listed["total"], listed["page"], listed["page_size"]) == (2, 1, 25)
    # Newest first, and only this company's.
    assert [item["number"] for item in listed["items"]] == [f"R/{YEAR}/0002", f"R/{YEAR}/0001"]
    assert listed["items"][1] == {
        "id": listed["items"][1]["id"],
        "number": f"R/{YEAR}/0001",
        "status": "awaiting_payment",
        "channel": "office",
        "source": "booking",
        "placed_at": listed["items"][1]["placed_at"],
        "buyer_name": "Anna Lis",
        "currency": "PLN",
        "gross_minor": 15000,
    }
    assert numbers(status="canceled") == [f"R/{YEAR}/0002"]
    assert numbers(q="lis@") == [f"R/{YEAR}/0001"]
    assert numbers(q="0002") == [f"R/{YEAR}/0002"]
    assert numbers(channel="company_site") == numbers(source="shop") == []
    assert numbers(customer_id=str(anna.customer_id)) == [f"R/{YEAR}/0001"]
    assert numbers(page=2, page_size=1) == [f"R/{YEAR}/0001"]
    wrong = client.get("/api/v1/commerce/orders/", {"status": "lost", "page_size": 500})
    assert wrong.status_code == 400
    assert {error["field"] for error in wrong.json()["errors"]} == {"status", "page_size"}

    read = client.get(f"/api/v1/commerce/orders/{listed['items'][1]['id']}/").json()
    assert (read["buyer_email"], read["customer_id"]) == ("lis@example.test", str(anna.customer_id))
    assert (read["amounts"], read["revision"], read["version"]) == ("gross", 1, 1)
    assert read["net_minor"] + read["vat_minor"] == read["gross_minor"] == 15000
    assert read["lines"] == [
        {
            "position": 1,
            "kind": "booking",
            "name": read["lines"][0]["name"],
            "customer_name": read["lines"][0]["customer_name"],
            "quantity": 1,
            "unit_amount_minor": 15000,
            "net_minor": read["net_minor"],
            "vat_minor": read["vat_minor"],
            "gross_minor": 15000,
            "tax_rate": "23",
            "source": "booking.appointment",
            "source_reference": str(anna.id),
            "target": read["lines"][0]["target"],
        }
    ]
    # The line names the visit it stands for and its day in the calendar.
    assert read["lines"][0]["target"]["label"] == configured["service"].name
    assert read["lines"][0]["target"]["href"] == (
        f"/panel/calendar?view=day&date={starts.date().isoformat()}"
    )
    assert read["revisions"] == [{"revision": 1, "gross_minor": 15000}]
    # The office wrote this one down: nobody was shown a document.
    assert read["consents"] == []
    # Another company's order is not there to be read.
    assert client.get(f"/api/v1/commerce/orders/{foreign.id}/").status_code == 404
    assert client.get(f"/api/v1/commerce/orders/{uuid7()}/").status_code == 404

    options = client.get("/api/v1/commerce/options/").json()
    assert options["currency"] == "PLN"
    assert options["sources"] == [{"kind": "booking", "prefix": "R"}]
    assert options["statuses"][:2] == ["draft", "awaiting_payment"]
    assert options["channels"] == ["company_site", "catalog", "office"]
    assert (options["tax_rates"], options["max_page_size"]) == (
        ["23", "8", "5", "0", "zw", "np"],
        100,
    )


@pytest.mark.parametrize("path", ["orders/", "options/", f"orders/{uuid7()}/"])
def test_orders_are_read_by_whoever_runs_the_company_on_a_plan_with_orders(path: str) -> None:
    _, staff, client = authenticated_member(
        email="zamowienia-pracownik@example.test", role_key="staff", slug="zamowienia-rola"
    )
    bookable(staff.organization)
    with_orders(staff.organization_id)
    url = f"/api/v1/commerce/{path}"

    assert APIClient().get(url).status_code in {401, 403}
    refused = client.get(url)
    assert (refused.status_code, refused.json()["code"]) == (
        403,
        "organization_permission_denied",
    )

    Membership.objects.filter(pk=staff.pk).update(
        role=Role.objects.get(key="manager", organization=None, organization_type="")
    )
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=staff.organization_id)
    snapshot.features = {"booking.enabled": True}
    snapshot.save(update_fields=["features"])
    without_plan = client.get(url)
    assert (without_plan.status_code, without_plan.json()["code"]) == (403, "entitlement_required")

    with_orders(staff.organization_id)
    assert client.get(url).status_code == (404 if path.count("/") == 2 else 200)

    # A suspended company reads nothing, nor does somebody who left it.
    Organization.objects.filter(pk=staff.organization_id).update(
        status=OrganizationStatus.SUSPENDED
    )
    assert client.get(url).status_code == 409
    Organization.objects.filter(pk=staff.organization_id).update(status=OrganizationStatus.ACTIVE)
    Membership.objects.filter(pk=staff.pk).delete()
    assert client.get(url).status_code == 409


def test_a_reader_of_orders_runs_inside_its_tenant() -> None:
    configured = office("zamowienia-lista-serwis")
    starts = datetime.combine(configured["monday"], time(10), WARSAW)
    with tenant(configured["owner"]):
        visit(configured, starts)
        page = list_orders(query="gosc@")
    other = office("zamowienia-lista-serwis-obca")
    with tenant(other["owner"]):
        empty = list_orders()

    assert [item["buyer_name"] for item in page["items"]] == ["Gość"]
    assert (empty["total"], empty["items"]) == (0, [])
