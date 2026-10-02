"""„Miejsce wizyty” (ADR-066): a visit's own town and address, before the
place a module knows, and the company's places offered in the visit form."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.booking import places, titles
from saas_core.modules.shared.booking.api import (
    PlaceSuggestion,
    register_appointment_place,
    register_appointment_title,
    register_place_search,
)
from saas_core.modules.shared.booking.availability import available_slots
from saas_core.modules.shared.booking.models import Appointment
from test_booking import _no_delivery, catalog, membership, tenant
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def no_product_places(monkeypatch: pytest.MonkeyPatch) -> None:
    """A product repository runs this suite with its own module registered."""
    monkeypatch.setattr(places, "_providers", {})
    monkeypatch.setattr(places, "_searches", {})
    monkeypatch.setattr(titles, "_providers", {})


def worker_of(member: Membership, email: str) -> Membership:
    """Somebody who takes visits but does not book them."""
    user = User.objects.create_user(email=email)
    user.status = UserStatus.ACTIVE
    user.save()
    role, _ = Role.objects.get_or_create(
        key="staff",
        organization=None,
        organization_type="",
        defaults={
            "name": "Staff",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["staff"]),
            "is_immutable": True,
        },
    )
    return Membership.objects.create(organization=member.organization, user=user, role=role)


def book(client: APIClient, configured: dict[str, Any], key: str, **place: str) -> Any:
    """The first free slot, remembered per key: a retry asks for the same one."""
    slots = configured.setdefault("slots", {})
    if key not in slots:
        with tenant(configured["member"]):
            slots[key] = available_slots(
                service_id=configured["service"].id,
                location_id=configured["location"].id,
                from_date=configured["date"],
                to_date=configured["date"],
            )[0]
    slot = slots[key]
    return client.post(
        "/api/v1/booking/appointments/",
        {
            "service_id": str(configured["service"].id),
            "location_id": str(configured["location"].id),
            "staff_id": str(slot.staff_id),
            "resource_id": str(configured["resource"].id),
            "starts_at": slot.starts_at.isoformat(),
            "customer": {"display_name": "Jan Nowak", "email": f"{key}@example.test"},
            **place,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_a_visit_keeps_its_own_place_before_the_one_a_module_knows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("miejsce-wlasne")
    configured = {**catalog(member), "member": member}
    client = authenticated_client(member)

    created = book(client, configured, "m-1", place_town=" Piątnica ", place_address="Polna 3")
    assert created.status_code == 201, created.content
    visit = created.json()
    assert (visit["place"], visit["place_town"], visit["place_address"]) == (
        "Piątnica",
        "Piątnica",
        "Polna 3",
    )
    # The same request again is the same booking; another place is another request.
    retry = book(client, configured, "m-1", place_town="Piątnica", place_address="Polna 3")
    assert retry.status_code == 200
    assert book(client, configured, "m-1", place_town="Łomża").status_code == 409

    def herds(ids: Sequence[UUID]) -> dict[UUID, str]:
        return dict.fromkeys(ids, "Testowo")

    register_appointment_place("test-herds", herds)
    try:
        listed = client.get("/api/v1/booking/appointments/").json()["items"]
        assert [item["place"] for item in listed] == ["Piątnica"]

        url = f"/api/v1/booking/appointments/{visit['id']}/place/"
        cleared = client.put(url, {"town": "", "address": ""}, format="json")
        assert cleared.status_code == 200, cleared.content
        # Without its own place the visit shows what the module knows.
        assert (cleared.json()["place"], cleared.json()["place_town"]) == ("Testowo", "")
    finally:
        places._providers.pop("test-herds", None)

    moved = client.put(url, {"town": "Zambrów", "address": "Długa 7"}, format="json")
    assert moved.json()["place"] == "Zambrów"
    again = client.put(url, {"town": "Zambrów", "address": "Długa 7"}, format="json")
    assert again.status_code == 200
    changes = OrganizationAuditEntry.objects.filter(
        organization=member.organization, action="booking.appointment.place_changed"
    ).order_by("occurred_at", "id")
    # Two changes, not three; the street is never in the history.
    assert [entry.metadata["changes"]["place_town"]["to"] for entry in changes] == [
        "",
        "Zambrów",
    ]
    assert "Długa" not in str([entry.metadata for entry in changes])


def test_only_whoever_books_visits_sets_the_place_and_never_on_a_called_off_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("miejsce-prawa")
    configured = {**catalog(member), "member": member}
    client = authenticated_client(member)
    visit = book(client, configured, "p-1").json()
    url = f"/api/v1/booking/appointments/{visit['id']}/place/"

    assert APIClient().put(url, {"town": "X"}, format="json").status_code in {401, 403}
    worker = authenticated_client(worker_of(member, "korektor@example.test"))
    assert worker.put(url, {"town": "X"}, format="json").status_code == 403
    stranger = authenticated_client(membership("miejsce-obcy"))
    assert stranger.put(url, {"town": "X"}, format="json").status_code == 404
    too_long = client.put(url, {"town": "x" * 121}, format="json")
    assert too_long.status_code == 400
    # A street needs its town; the answer names the field.
    street_only = client.put(url, {"town": "", "address": "Polna 3"}, format="json")
    assert street_only.status_code == 400
    assert "town" in street_only.json()["detail"]
    assert book(client, configured, "p-2", place_address="Polna 3").status_code == 400

    client.post(
        f"/api/v1/booking/appointments/{visit['id']}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="p-cancel",
    )
    refused = client.put(url, {"town": "Łomża"}, format="json")
    assert refused.status_code == 409
    assert refused.json()["code"] == "appointment_not_changeable"


def test_the_form_offers_the_places_a_module_keeps(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    member = membership("miejsce-lista")
    catalog(member)
    client = authenticated_client(member)
    # No module keeps places: the form has nothing to offer.
    assert client.get("/api/v1/booking/catalog/").json()["place_search"] is False
    assert client.get("/api/v1/booking/places/").json() == {"items": []}

    asked: list[tuple[str, int]] = []

    def farms(query: str, limit: int) -> list[PlaceSuggestion]:
        asked.append((query, limit))
        return [PlaceSuggestion("Gospodarstwo Kowalski", "Testowo", "Testowo 12")]

    register_place_search("test-farms", farms)
    try:
        assert client.get("/api/v1/booking/catalog/").json()["place_search"] is True
        found = client.get("/api/v1/booking/places/", {"q": " kowal ", "limit": 5})
        assert found.status_code == 200
        assert found.json() == {
            "items": [{"name": "Gospodarstwo Kowalski", "town": "Testowo", "address": "Testowo 12"}]
        }
        assert asked == [("kowal", 5)]
        worker = authenticated_client(worker_of(member, "biuro-nie@example.test"))
        assert worker.get("/api/v1/booking/places/").status_code == 403
        assert client.get("/api/v1/booking/places/", {"limit": "dużo"}).status_code == 400
    finally:
        places._searches.pop("test-farms", None)


def test_anonymizing_the_customer_takes_the_street_and_keeps_the_town(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("miejsce-rodo")
    configured = {**catalog(member), "member": member}
    client = authenticated_client(member)
    visit = book(client, configured, "r-1", place_town="Piątnica", place_address="Polna 3").json()
    with tenant(member):
        customer_id = Appointment.all_objects.get(pk=visit["id"]).customer_id
    response = client.post(f"/api/v1/booking/customers/{customer_id}/anonymize/", format="json")
    assert response.status_code == 200, response.content
    with tenant(member):
        stored = Appointment.all_objects.get(pk=visit["id"])
    assert (stored.place_town, stored.place_address) == ("Piątnica", "")


def test_a_module_names_its_visits_and_a_failing_one_names_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("nazwa-wizyty")
    configured = {**catalog(member), "member": member}
    client = authenticated_client(member)
    visit = book(client, configured, "t-1").json()
    # Without a module the customer is the visit's name.
    assert (visit["title"], visit["customer_name"]) == ("", "Jan Nowak")

    def farms(ids: Sequence[UUID]) -> dict[UUID, str]:
        return dict.fromkeys(ids, "Gospodarstwo Nowak")

    def broken(ids: Sequence[UUID]) -> dict[UUID, str]:
        raise RuntimeError("provider down")

    register_appointment_title("test-broken", broken)
    register_appointment_title("test-farms", farms)
    (listed,) = client.get("/api/v1/booking/appointments/").json()["items"]
    # The farm first, the person who answers the phone still there (UX plan W2).
    assert (listed["title"], listed["customer_name"]) == ("Gospodarstwo Nowak", "Jan Nowak")
