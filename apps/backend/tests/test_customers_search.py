"""The panel's search for a customer (ADR-073, „Uzupełnienie 2026-10-04: po
plastrze 4i” — a place to remove one customer's data on request): by what a
person typed, answering only with the customers the caller sees elsewhere in
the panel, and with as much of each as they see there.

Stands on booking alone — the calendar is where every profile shows its
customers — so it runs wherever customers do."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from uuid import uuid7
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    StaffMember,
)
from saas_core.modules.shared.customers.api import Customer, strip_customer
from saas_core.modules.shared.notifications.security import encrypt_secret
from test_booking import catalog, tenant
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable

pytestmark = pytest.mark.django_db

URL = "/api/v1/customers/search/"
WARSAW = ZoneInfo("Europe/Warsaw")
KSAWERY = ("Ksawery Kowalski", "ksawery.kowalski@poczta.test", "+48 601 234 567")
BONIFACY = ("Bonifacy Kowalski", "bonifacy@inna-poczta.test", "512 345 678")
ZENOBIA = ("Zenobia Brzęczyszczykiewicz", "zenobia.b@skrzynka.test", "+48 22 765 43 21")


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def company(slug: str) -> tuple[APIClient, Membership, dict[str, Customer], StaffMember]:
    """A company whose calendar holds three customers: Ksawery and Zenobia on
    Alex's visits, Bonifacy on Iga's."""
    _, owner, client = authenticated_member(
        email=f"{slug}@example.test", role_key="owner", slug=slug
    )
    bookable(owner.organization)
    configured = catalog(owner)
    day = timezone.localdate(timezone=WARSAW) + timedelta(days=1)
    with tenant(owner):
        iga = StaffMember.all_objects.create(
            organization=owner.organization, display_name="Iga", public_slug="iga"
        )
        customers = {}
        for hour, (name, email, phone), staff in (
            (9, KSAWERY, configured["staff"]),
            (10, ZENOBIA, configured["staff"]),
            (11, BONIFACY, iga),
        ):
            person = Customer.all_objects.create(
                organization=owner.organization,
                display_name=name,
                email=email,
                phone=phone,
                contact_hash=uuid7().hex,
            )
            starts = datetime.combine(day, time(hour), tzinfo=WARSAW)
            ends = starts + timedelta(minutes=30)
            visit = Appointment.all_objects.create(
                organization=owner.organization,
                customer=person,
                service=configured["service"],
                staff=staff,
                location=configured["location"],
                starts_at=starts,
                ends_at=ends,
                occupied_from=starts,
                occupied_until=ends,
                timezone="Europe/Warsaw",
                service_name=configured["service"].name,
                status="confirmed",
                self_service_token_ciphertext=encrypt_secret(uuid7().hex),
                self_service_expires_at=starts,
            )
            AppointmentStaffAllocation.all_objects.create(
                organization=owner.organization,
                appointment=visit,
                staff=staff,
                occupied_range=(starts, ends),
            )
            customers[name] = person
    return client, owner, customers, iga


def found(client: APIClient, q: str) -> dict[str, Any]:
    answer = client.get(URL, {"q": q})
    assert answer.status_code == 200, answer.data
    body: dict[str, Any] = answer.json()
    return body


def test_the_owner_finds_a_customer_by_name_e_mail_or_phone() -> None:
    client, _, customers, _ = company("szukaj-wlasciciel")

    by_name = found(client, "kowalski")
    by_mail = found(client, ZENOBIA[1])
    by_phone = found(client, "601 234 567")

    assert by_name["total"] == 2
    assert {item["name"] for item in by_name["items"]} == {KSAWERY[0], BONIFACY[0]}
    (zenobia,) = by_mail["items"]
    assert zenobia == {
        "customer_id": str(customers[ZENOBIA[0]].id),
        "name": ZENOBIA[0],
        "email": ZENOBIA[1],
        "phone": ZENOBIA[2],
        "links": zenobia["links"],
        "matched": ["email"],
        "seen_in": ["bookings"],
    }
    assert zenobia["links"][0]["href"].startswith("/panel/calendar?view=day&date=")
    assert [(item["name"], item["matched"]) for item in by_phone["items"]] == [
        (KSAWERY[0], ["phone"])
    ]
    assert found(client, "Nikt Taki") == {"total": 0, "items": []}
    # Nobody's name is one letter, and a search needs words.
    assert client.get(URL, {"q": "k"}).status_code == 400
    assert client.get(URL).status_code == 400


def test_a_reader_finds_only_whom_the_panel_shows_them_and_a_removed_customer_is_gone() -> None:
    client, owner, customers, iga = company("szukaj-pracownik")
    # Staff: reads the calendar, plans nothing — on Bonifacy's visit, not on
    # Zenobia's.
    _, colleague, worker = authenticated_member(
        email="szukaj-pracownik-iga@example.test",
        role_key="staff",
        organization=owner.organization,
    )
    with tenant(owner):
        StaffMember.all_objects.filter(pk=iga.pk).update(membership=colleague)

    kowalscy = found(worker, "Kowalski")
    zenobia = found(worker, "Zenobia")

    # Her own visit: the contact the calendar gives the people going there.
    assert (BONIFACY[0], BONIFACY[1]) in [
        (item["name"], item["email"]) for item in kowalscy["items"]
    ]
    # A visit of somebody else: at most the name the calendar shows, no contact.
    assert all(
        (item["email"], item["phone"]) == (None, None)
        for item in [*zenobia["items"], *kowalscy["items"]]
        if item["name"] != BONIFACY[0]
    )

    with tenant(owner):
        strip_customer(Customer.all_objects.select_for_update().get(pk=customers[BONIFACY[0]].pk))
    assert found(client, "Bonifacy") == {"total": 0, "items": []}

    # Another company's customers are never found.
    _, _, stranger = authenticated_member(
        email="szukaj-obcy@example.test", role_key="owner", slug="szukaj-obcy"
    )
    assert found(stranger, "Kowalski") == {"total": 0, "items": []}
