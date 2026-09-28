"""„Do kogo?” on the public form, „Pokazuj klientom” and the customer's notes
(team phase 3d; ADR-058 §8, owner's answers 2 of 24.09 and 1A of 28.09)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.shared.booking.models import (
    Appointment,
    PublicBookingRoute,
    Service,
)
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.booking.staff import list_people, set_person_public
from saas_core.modules.shared.booking.teams import create_team
from saas_core.modules.shared.notifications.models import NotificationMessage
from saas_core.modules.shared.profiles.models import PublicProfile
from test_booking import _no_delivery, membership, tenant
from test_booking_slots import team

pytestmark = pytest.mark.django_db


def setup(slug: str, *, people: int, need: int, choice: str) -> dict[str, Any]:
    owner = membership(slug)
    configured = team(owner, people=people, hours=(time(8), time(12)), duration=60)
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(
            staff_count=need, public_staff_choice=choice
        )
    PublicBookingRoute.objects.create(public_slug=slug, organization_id=owner.organization_id)
    configured.update(
        owner=owner,
        url=f"/api/v1/booking/public/{slug}",
        day=timezone.localdate() + timedelta(days=7),
        query={
            "service_id": str(configured["service"].id),
            "location_id": str(configured["location"].id),
        },
    )
    return configured


def book(client: APIClient, configured: dict[str, Any], key: str, **extra: Any) -> Any:
    times = client.get(
        f"{configured['url']}/times/",
        {
            **configured["query"],
            "date": configured["day"].isoformat(),
            **{k: v for k, v in extra.items() if k in {"team_id", "person_id"}},
        },
    ).json()["items"]
    return client.post(
        f"{configured['url']}/appointments/",
        {
            **configured["query"],
            "starts_at": times[0]["starts_at"],
            "customer": {"display_name": "Anna", "email": f"{key}@example.test"},
            **extra,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_showing_a_person_to_customers_names_them_and_hiding_removes_the_name() -> None:
    configured = setup("publiczni-ludzie", people=1, need=1, choice="person")
    owner: Membership = configured["owner"]
    (person,) = configured["staff"]
    with tenant(owner):
        set_person_public(staff_id=person.id, shown=True, name="dr Anna Nowak")
        assert {x.staff.id: x.public_name for x in list_people()}[person.id] == "dr Anna Nowak"
        set_person_public(staff_id=person.id, shown=True, name="dr n. med. Anna Nowak")
        person.refresh_from_db()
        profile_id = person.profile_id
        assert PublicProfile.all_objects.get(pk=profile_id).display_name == "dr n. med. Anna Nowak"
        set_person_public(staff_id=person.id, shown=False)
        person.refresh_from_db()
    assert person.profile_id is None
    assert not PublicProfile.all_objects.filter(pk=profile_id).exists()
    assert [
        entry.metadata
        for entry in OrganizationAuditEntry.objects.filter(
            action="booking.staff.public_changed", target_id=person.id
        ).order_by("occurred_at")
    ] == [{"shown": True}, {"shown": False}]


def test_the_form_offers_teams_that_can_staff_the_visit_and_no_staff_list() -> None:
    configured = setup("publiczne-zespoly", people=3, need=2, choice="team")
    owner = configured["owner"]
    first, second, third = configured["staff"]
    with tenant(owner):
        north = create_team(name="Brygada Północ", member_ids=[first.id, second.id])
        create_team(name="Jednoosobowa", member_ids=[third.id])
    client = APIClient()
    listing = client.get(f"{configured['url']}/").json()
    assert listing["teams"] == [{"id": str(north.id), "name": "Brygada Północ"}]
    assert listing["people"] == []
    service = listing["services"][0]
    # A one-person team cannot staff a two-person visit: not offered.
    assert (service["staff_choice"], service["team_ids"]) == ("team", [str(north.id)])
    assert "Osoba" not in str(listing)

    # The days and times count two people at once, and only the team's.
    days = client.get(
        f"{configured['url']}/days/",
        {
            **configured["query"],
            "from": str(configured["day"]),
            "to": str(configured["day"]),
            "team_id": str(north.id),
        },
    )
    assert days.json()["items"] == [configured["day"].isoformat()]
    created = book(client, configured, "zespol-publiczny", team_id=str(north.id))
    assert created.status_code == 201, created.data
    assert created.json()["team_name"] == "Brygada Północ"
    with tenant(owner):
        visit = Appointment.all_objects.get(pk=created.json()["id"])
        assert visit.requested_team_id == north.id
        assert set(
            visit.staff_allocations.filter(active=True).values_list("staff_id", flat=True)
        ) == {
            first.id,
            second.id,
        }
    # A person where the service lets the customer choose a team is refused.
    refused = book(client, configured, "zla-osoba", person_id=str(first.id))
    assert refused.status_code == 400


def test_a_person_shown_to_customers_is_chosen_and_named_in_the_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    configured = setup("publiczna-osoba", people=2, need=1, choice="person")
    owner = configured["owner"]
    first, second = configured["staff"]
    with tenant(owner):
        set_person_public(staff_id=second.id, shown=True, name="dr Anna Nowak")
    client = APIClient()
    listing = client.get(f"{configured['url']}/").json()
    # Only the person shown to customers is offered, under their public name.
    assert listing["people"] == [{"id": str(second.id), "name": "dr Anna Nowak"}]
    assert listing["services"][0]["person_ids"] == [str(second.id)]
    created = book(
        client,
        configured,
        "osoba-publiczna",
        person_id=str(second.id),
        customer_notes="  Proszę o wizytę bez czekania.  ",
    )
    assert created.status_code == 201, created.data
    assert created.json()["person_name"] == "dr Anna Nowak"
    assert created.json()["team_name"] is None
    with tenant(owner):
        visit = Appointment.all_objects.get(pk=created.json()["id"])
    assert (visit.staff_id, visit.requested_staff_id) == (second.id, second.id)
    assert visit.customer_notes == "Proszę o wizytę bez czekania."
    # The notes are the company's: never in a mail to anybody.
    assert not [
        message
        for message in NotificationMessage.all_objects.all()
        if "bez czekania" in str(message.context)
    ]
    shown = client.get(f"/api/v1/booking/self-service/{created.json()['self_service_token']}/")
    assert shown.json()["person_name"] == "dr Anna Nowak"
    # A person the company does not show cannot be asked for.
    assert book(client, configured, "ukryta", person_id=str(first.id)).status_code == 400

    with tenant(owner):
        anonymize_customer(visit.customer_id)
        visit.refresh_from_db()
    assert visit.customer_notes == ""


def test_a_two_person_service_offers_only_starts_two_people_are_free_for() -> None:
    configured = setup("publiczne-dwie", people=2, need=2, choice="none")
    owner = configured["owner"]
    first, second = configured["staff"]
    with tenant(owner):
        # The second person only works from 10:00: before that one is not enough.
        second.availability_rules.update(local_start=time(10))
    client = APIClient()
    times = client.get(
        f"{configured['url']}/times/",
        {**configured["query"], "date": configured["day"].isoformat()},
    ).json()["items"]
    warsaw = ZoneInfo("Europe/Warsaw")
    local = [datetime.fromisoformat(item["starts_at"]).astimezone(warsaw).time() for item in times]
    assert local and min(local) >= time(10)
    created = book(client, configured, "dwie-osoby")
    assert created.status_code == 201, created.data
    with tenant(owner):
        visit = Appointment.all_objects.get(pk=created.json()["id"])
        assert visit.staff_allocations.filter(active=True).count() == 2
