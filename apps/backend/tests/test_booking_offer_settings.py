"""The company's word on its customers' links and on what it offers online
(R3a B4, B2, B6; ADR-078): self-service terms frozen into each booking, a
service or place kept off the site's form, and the start grid of a service."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.booking.availability import available_slots
from saas_core.modules.shared.booking.models import (
    Appointment,
    Location,
    PublicBookingRoute,
    Service,
)
from test_booking import _no_delivery, catalog, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)

SELF_SERVICE = "booking.self_service"


@pytest.fixture(autouse=True)
def _fresh_throttle() -> Any:
    # The public form is throttled per client address.
    cache.clear()
    yield
    cache.clear()


def _change(group: str, key: str, **changes: Any) -> Any:
    return change_settings(
        group, changes=changes, expected_version=read_group(group).version, idempotency_key=key
    )


def _public(member: Any, slug: str) -> tuple[APIClient, str, dict[str, Any]]:
    configured = catalog(member)
    PublicBookingRoute.objects.create(public_slug=slug, organization_id=member.organization_id)
    configured["query"] = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    return APIClient(), f"/api/v1/booking/public/{slug}", configured


def _book(client: APIClient, url: str, configured: dict[str, Any], who: str, index: int = 0) -> Any:
    day = str(configured["date"])
    times = client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day})
    return client.post(
        f"{url}/appointments/",
        {
            **configured["query"],
            "starts_at": times.json()["items"][index]["starts_at"],
            "customer": {"display_name": who, "email": f"{who}@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"book-{who}",
    )


def test_a_booking_keeps_the_self_service_terms_it_was_made_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("self-service-terms")
    client, url, configured = _public(member, "warunki")

    before = _book(client, url, configured, "przed")
    with tenant(member):
        _change(SELF_SERVICE, "s-1", mode="cancel_only")
    after = _book(client, url, configured, "po", index=4)
    assert before.json()["self_service"]["reschedule"] is True
    assert after.json()["self_service"] == {
        "reschedule": False,
        "cancel": True,
        "until": after.json()["starts_at"],
    }

    # The company changes its mind: neither booking changes its terms.
    with tenant(member):
        _change(SELF_SERVICE, "s-2", mode="none")
    day = str(configured["date"])
    free = client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day})
    later = free.json()["items"][-1]["starts_at"]
    moved = client.post(
        f"/api/v1/booking/self-service/{before.json()['self_service_token']}/reschedule/",
        {"starts_at": later},
        format="json",
        HTTP_IDEMPOTENCY_KEY="warunki-przed",
    )
    refused = client.post(
        f"/api/v1/booking/self-service/{after.json()['self_service_token']}/reschedule/",
        {"starts_at": later},
        format="json",
        HTTP_IDEMPOTENCY_KEY="warunki-po",
    )
    canceled = client.post(
        f"/api/v1/booking/self-service/{after.json()['self_service_token']}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="warunki-po-odwolanie",
    )

    assert moved.status_code == 200, moved.json()
    assert (refused.status_code, refused.json()["code"]) == (409, "appointment_not_changeable")
    assert canceled.status_code == 200
    terms = dict(Appointment.all_objects.values_list("customer__display_name", "self_service_mode"))
    assert terms == {"przed": "change_and_cancel", "po": "cancel_only"}


def test_the_link_stops_the_given_hours_before_the_visit(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    member = membership("self-service-cutoff")
    client, url, configured = _public(member, "prog")
    with tenant(member):
        _change(SELF_SERVICE, "c-1", cutoff_hours=24)
    # The visit is a week away: a day's threshold leaves the link open.
    booked = _book(client, url, configured, "prog")
    assert booked.json()["self_service"]["cancel"] is True

    # Eight days' threshold has passed already.
    with tenant(member):
        Appointment.all_objects.update(self_service_cutoff_hours=8 * 24)
    refused = client.post(
        f"/api/v1/booking/self-service/{booked.json()['self_service_token']}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="prog-odwolanie",
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "appointment_not_changeable")


def test_a_service_or_place_kept_off_the_site_is_not_on_its_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("offline-offer")
    client, url, configured = _public(member, "poza-strona")
    day = str(configured["date"])
    times = client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day})
    starts_at = times.json()["items"][0]["starts_at"]

    with tenant(member):
        Service.all_objects.update(online=False)
    listing = client.get(f"{url}/").json()
    refused = client.post(
        f"{url}/appointments/",
        {
            **configured["query"],
            "starts_at": starts_at,
            "customer": {"display_name": "Anna", "email": "anna@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="poza-strona-1",
    )
    assert listing["services"] == []
    assert refused.status_code == 404

    with tenant(member):
        Service.all_objects.update(online=True)
        Location.all_objects.update(online=False)
    assert client.get(f"{url}/").json()["locations"] == []


def test_a_service_starts_on_its_own_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    member = membership("slot-step")
    configured = catalog(member)
    with tenant(member):
        every_five = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"],
        )
        Service.all_objects.update(slot_step_minutes=15)
        every_fifteen = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"],
        )
    steps = {
        (b.starts_at - a.starts_at) for a, b in zip(every_fifteen, every_fifteen[1:], strict=False)
    }
    assert every_five[1].starts_at - every_five[0].starts_at == timedelta(minutes=5)
    assert steps == {timedelta(minutes=15)}
    assert {slot.starts_at.minute % 15 for slot in every_fifteen} == {0}
