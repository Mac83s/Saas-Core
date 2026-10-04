"""The price on the public booking form and in the customer's own link
(ADR-072 §7–§8, phase 3d): a customer reads the gross price in their language,
books at the price they saw, and is told how they pay."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.shared.booking.models import Appointment, Service
from saas_core.modules.shared.booking.offer_settings import offer_options
from saas_core.modules.shared.booking.prices import save_price
from saas_core.modules.shared.booking.quote import quote_visit
from saas_core.modules.shared.booking.setup import save_service
from test_booking import _no_delivery, tenant
from test_booking_extras import extra
from test_booking_prices import add, key
from test_booking_public_choice import setup

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def first_start(client: APIClient, configured: dict[str, Any]) -> str:
    times = client.get(
        f"{configured['url']}/times/",
        {**configured["query"], "date": configured["day"].isoformat()},
    ).json()["items"]
    return str(times[0]["starts_at"])


def priced(slug: str) -> dict[str, Any]:
    """A visit at 150 with travel on every booking and photos to pick, paid
    on site."""
    configured = setup(slug, people=1, need=1, choice="none")
    service = configured["service"]
    with tenant(configured["owner"]):
        save_service(
            service_id=service.id,
            data={"payment_policy": "on_site"},
            expected_version=Service.all_objects.get(pk=service.id).version,
            idempotency_key=key(),
        )
        add(15000, service_id=service.id)
        configured["travel"] = extra(service.id, "Dojazd", 5000, mandatory=True)
        configured["photos"] = extra(service.id, "Zdjęcia", 2000, max_quantity=3)
    return configured


def test_how_the_customer_pays_is_the_offers_setting_and_part_of_the_price_shown() -> None:
    configured = setup("cena-platnosc", people=1, need=1, choice="none")
    service = configured["service"]
    starts = configured["day"]
    with tenant(configured["owner"]):
        at = datetime.combine(starts, time(9), ZoneInfo("Europe/Warsaw"))
        add(15000, service_id=service.id)
        before = quote_visit(service=service, starts_at=at)
        changed = save_service(
            service_id=service.id,
            data={"payment_policy": "on_site"},
            expected_version=Service.all_objects.get(pk=service.id).version,
            idempotency_key=key(),
        )
        after = quote_visit(service=changed.value.service, starts_at=at)
        option = next(
            item for item in offer_options() if item["key"] == "booking.offer.payment_policy"
        )
    assert changed.changes == {"payment_policy": {"from": "none", "to": "on_site"}}
    assert (before.payment_policy, after.payment_policy) == ("none", "on_site")
    assert before.digest != after.digest
    assert [value["value"] for value in option["values"]] == [
        "none",
        "on_site",
        "transfer",
        "deposit",
        "full",
    ]
    assert option["default"] == "none"


def test_the_form_shows_the_gross_price_and_books_at_the_price_shown() -> None:
    configured = priced("cena-formularz")
    client = APIClient()
    starts_at = first_start(client, configured)
    body = {
        "service_id": str(configured["service"].id),
        "starts_at": starts_at,
        "extras": [{"extra_id": str(configured["photos"].id), "quantity": 2}],
    }
    # The form lists the service's extras with what one of each comes to.
    listing = client.get(f"{configured['url']}/").json()
    assert listing["currency"] == "PLN"
    listed = listing["extras"]
    assert [
        (item["name"], item["mandatory"], item["max_quantity"], item["unit_gross_minor"])
        for item in listed
    ] == [("Dojazd", True, 1, 5000), ("Zdjęcia", False, 3, 2000)]
    answer = client.post(f"{configured['url']}/quote/", body, format="json")
    assert answer.status_code == 200, answer.data
    quote = answer.json()["quote"]
    # Gross, by name, and nothing of the company's own: no net, no tax, no ids.
    assert quote == {
        "currency": "PLN",
        "lines": [
            {"kind": "price", "name": "Wizyta", "quantity": 1, "gross_minor": 15000},
            {"kind": "extra", "name": "Dojazd", "quantity": 1, "gross_minor": 5000},
            {"kind": "extra", "name": "Zdjęcia", "quantity": 2, "gross_minor": 4000},
        ],
        "gross_minor": 24000,
        "security_deposit_minor": 0,
        "payment_policy": "on_site",
        # Nothing is paid before the booking is confirmed.
        "prepayment": None,
        # The offer has no refund thresholds: everything paid goes back.
        "cancellation": None,
        "digest": quote["digest"],
    }

    booking = {
        **configured["query"],
        "starts_at": starts_at,
        "customer": {"display_name": "Anna", "email": "anna-cena@example.test"},
        "extras": body["extras"],
    }
    # The price went up between the look and the booking.
    with tenant(configured["owner"]):
        rule = configured["service"].price_rules.get()
        save_price(
            price_id=rule.id,
            data={"amount_minor": 16000},
            expected_version=1,
            idempotency_key=key(),
        )
    # A customer never books at a price they were not shown: a form that
    # sends no digest is answered with the price, not with a booking.
    unseen = client.post(
        f"{configured['url']}/appointments/",
        booking,
        format="json",
        HTTP_IDEMPOTENCY_KEY="cena-niewidziana",
    )
    assert (unseen.status_code, unseen.json()["code"]) == (409, "quote_changed")
    assert unseen.json()["detail"]["quote"]["gross_minor"] == 25000
    stale = client.post(
        f"{configured['url']}/appointments/",
        {**booking, "quote_digest": quote["digest"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="cena-stara",
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "quote_changed")
    fresh = stale.json()["detail"]["quote"]
    assert (fresh["gross_minor"], set(fresh)) == (25000, set(quote))
    assert not Appointment.all_objects.filter(
        organization_id=configured["owner"].organization_id
    ).exists()

    made = client.post(
        f"{configured['url']}/appointments/",
        {**booking, "quote_digest": fresh["digest"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="cena-nowa",
    )
    assert made.status_code == 201, made.data
    assert made.json()["quote"] == fresh
    own = client.get(f"/api/v1/booking/self-service/{made.json()['self_service_token']}/")
    assert own.json()["quote"]["gross_minor"] == 25000


def test_a_service_without_a_price_shows_none_and_one_off_the_form_is_not_priced() -> None:
    configured = setup("cena-brak", people=1, need=1, choice="none")
    client = APIClient()
    body = {
        "service_id": str(configured["service"].id),
        "starts_at": first_start(client, configured),
    }
    unpriced = client.post(f"{configured['url']}/quote/", body, format="json")
    assert unpriced.json() == {"quote": None}
    booked = client.post(
        f"{configured['url']}/appointments/",
        {
            **configured["query"],
            "starts_at": body["starts_at"],
            "customer": {"display_name": "Jan", "email": "jan-cena@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="cena-brak",
    )
    assert (booked.status_code, booked.json()["quote"]) == (201, None)

    with tenant(configured["owner"]):
        Service.all_objects.filter(pk=configured["service"].id).update(online=False)
    hidden = client.post(f"{configured['url']}/quote/", body, format="json")
    assert hidden.status_code == 404


def test_a_customer_moving_their_visit_sees_the_new_price_before_it_is_theirs() -> None:
    configured = priced("cena-przelozenie")
    with tenant(configured["owner"]):
        # From ten the visit costs more.
        add(
            20000,
            service_id=configured["service"].id,
            local_from=time(10),
            local_to=time(12),
        )
    client = APIClient()
    starts = [
        item["starts_at"]
        for item in client.get(
            f"{configured['url']}/times/",
            {**configured["query"], "date": configured["day"].isoformat()},
        ).json()["items"]
    ]
    # The company's clock: the starts at eight, nine and ten in Warsaw.
    local = {
        datetime.fromisoformat(item).astimezone(ZoneInfo("Europe/Warsaw")).time(): item
        for item in starts
    }
    at_eight, at_nine, at_ten = local[time(8)], local[time(9)], local[time(10)]
    shown = client.post(
        f"{configured['url']}/quote/",
        {"service_id": str(configured["service"].id), "starts_at": at_eight},
        format="json",
    ).json()["quote"]
    made = client.post(
        f"{configured['url']}/appointments/",
        {
            **configured["query"],
            "starts_at": at_eight,
            "customer": {"display_name": "Anna", "email": "anna-ruch@example.test"},
            "quote_digest": shown["digest"],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="ruch-1",
    )
    assert (made.status_code, made.json()["quote"]["gross_minor"]) == (201, 20000)
    link = f"/api/v1/booking/self-service/{made.json()['self_service_token']}/reschedule/"

    # The same price at nine: the move needs no asking.
    same = client.post(link, {"starts_at": at_nine}, format="json", HTTP_IDEMPOTENCY_KEY="ruch-2")
    assert (same.status_code, same.json()["quote"]["gross_minor"]) == (200, 20000)
    # Another one at ten: the customer is shown it, and nothing has moved.
    dearer = client.post(link, {"starts_at": at_ten}, format="json", HTTP_IDEMPOTENCY_KEY="ruch-3")
    assert (dearer.status_code, dearer.json()["code"]) == (409, "quote_changed")
    fresh = dearer.json()["detail"]["quote"]
    assert (fresh["gross_minor"], set(fresh)) == (25000, set(shown))
    with tenant(configured["owner"]):
        visit = Appointment.all_objects.get(pk=made.json()["id"])
        assert (visit.starts_at, visit.quote["gross_minor"]) == (
            datetime.fromisoformat(at_nine),
            20000,
        )
    # Having seen it, they take it.
    moved = client.post(
        link,
        {"starts_at": at_ten, "quote_digest": fresh["digest"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ruch-4",
    )
    assert (moved.status_code, moved.json()["quote"]["gross_minor"]) == (200, 25000)
