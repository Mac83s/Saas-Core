"""Ustawienia › Usługi i grafik: services, places and resources as the office
edits them (team phase 3c)."""

from __future__ import annotations

from datetime import time, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.booking.models import (
    Location,
    PublicBookingRoute,
    Resource,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffMember,
)
from saas_core.modules.shared.booking.services import create_appointment, list_catalog
from saas_core.modules.shared.booking.setup import (
    list_setup,
    save_location,
    save_resource,
    save_service,
)
from test_booking import membership, tenant
from test_booking_slots import at, team
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


def key() -> str:
    return str(uuid4())


def test_a_new_service_comes_with_its_people_place_and_resource() -> None:
    owner = membership("uslugi-nowa")
    configured = team(owner, people=2, hours=(time(8), time(16)), duration=60)
    first, second = configured["staff"]
    with tenant(owner):
        room = save_resource(
            resource_id=None, data={"name": "Gabinet"}, idempotency_key=key()
        ).value
        created = save_service(
            service_id=None,
            data={
                "name": "Łączenie racic",
                "duration_minutes": 90,
                "buffer_after_minutes": 15,
                "staff_count": 2,
                "public_staff_choice": "team",
                "staff_ids": [first.id, second.id, first.id],
                "location_ids": [configured["location"].id],
                "resource_ids": [room.id],
            },
            idempotency_key=key(),
        ).value
    service = created.service
    # The slug is made from the name, Polish letters folded, never asked for.
    assert service.public_slug == "laczenie-racic"
    assert (service.staff_count, service.public_staff_choice) == (2, "team")
    assert created.staff_ids == [first.id, second.id]
    assert created.location_ids == [configured["location"].id]
    assert created.resource_ids == [room.id]
    assert ServiceResource.all_objects.get(service=service).required is True
    assert PublicBookingRoute.objects.filter(public_slug=owner.organization.slug).exists()
    entry = OrganizationAuditEntry.objects.get(
        action="booking.catalog.changed", target_id=service.id
    )
    assert entry.metadata == {"created": True}


def test_editing_a_service_keeps_the_visits_booked_before() -> None:
    owner = membership("uslugi-zmiana")
    configured = team(owner, people=3, hours=(time(8), time(16)), duration=60)
    first, second, third = configured["staff"]
    day = timezone.localdate() + timedelta(days=7)
    with tenant(owner):
        visit = create_appointment(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            starts_at=at(day, 9),
            customer_data={"display_name": "Klient", "email": "klient@example.test"},
            idempotency_key="przed-zmiana",
            principal_ref=str(owner.user_id),
        ).appointment
        changed = save_service(
            service_id=configured["service"].id,
            data={
                "name": "Wizyta długa",
                "duration_minutes": 120,
                "staff_count": 2,
                "staff_ids": [second.id, third.id],
            },
            expected_version=1,
            idempotency_key=key(),
        ).value
    assert changed.staff_ids == [second.id, third.id]
    assert not ServiceStaff.all_objects.filter(service=changed.service, staff=first).exists()
    visit.refresh_from_db()
    # A visit keeps what it was booked as: its name, length and crew size.
    assert (visit.service_name, visit.staff_required) == ("Wizyta", 1)
    assert visit.ends_at - visit.starts_at == timedelta(minutes=60)
    entry = OrganizationAuditEntry.objects.get(
        action="booking.catalog.changed", target_id=changed.service.id
    )
    assert entry.metadata["changes"] == {
        "name": {"from": "Wizyta", "to": "Wizyta długa"},
        "duration_minutes": {"from": 60, "to": 120},
        "staff_count": {"from": 1, "to": 2},
        "performers": {"changed": True},
    }


def test_the_settings_refuse_what_cannot_be_booked_or_is_not_the_companys() -> None:
    owner = membership("uslugi-odmowy")
    stranger = membership("uslugi-obcy")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    foreign = team(stranger, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        # A person is chosen only for a one-person service (answer 2, 24.09).
        with pytest.raises(ValidationError):
            save_service(
                service_id=configured["service"].id,
                data={"staff_count": 2, "public_staff_choice": "person"},
                expected_version=1,
                idempotency_key=key(),
            )
        for field, target in (
            ("staff_ids", foreign["staff"][0].id),
            ("location_ids", foreign["location"].id),
        ):
            with pytest.raises(ValidationError) as refused:
                save_service(
                    service_id=configured["service"].id,
                    data={field: [target]},
                    expected_version=1,
                    idempotency_key=key(),
                )
            assert field in refused.value.detail
        with pytest.raises(NotFound):
            save_service(
                service_id=foreign["service"].id,
                data={"name": "Cudza"},
                expected_version=1,
                idempotency_key=key(),
            )
        with pytest.raises(NotFound):
            save_location(
                location_id=foreign["location"].id,
                data={"name": "Cudze"},
                expected_version=1,
                idempotency_key=key(),
            )
    assert Service.all_objects.get(pk=configured["service"].id).staff_count == 1


def test_a_switched_off_service_or_place_leaves_the_calendar_but_not_the_settings() -> None:
    owner = membership("uslugi-wylacz")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        second = save_location(
            location_id=None,
            data={"name": "Filia Łódź", "address": "ul. 1"},
            idempotency_key=key(),
        ).value
        assert second.public_slug == "filia-lodz"
        save_service(
            service_id=configured["service"].id,
            data={"active": False},
            expected_version=1,
            idempotency_key=key(),
        )
        save_location(
            location_id=second.id, data={"active": False}, expected_version=1, idempotency_key=key()
        )
        calendar = list_catalog()
        setup = list_setup()
    assert not [x for x in calendar["services"] if x.active]
    assert {x.id for x in setup.locations} == {configured["location"].id, second.id}
    assert [item.service.active for item in setup.services] == [False]
    assert Location.all_objects.get(pk=second.id).active is False


def test_the_settings_api_answers_management_and_refuses_the_others() -> None:
    _, owner, client = authenticated_member(
        email="uslugi-api@example.test", role_key="owner", slug="uslugi-api"
    )
    bookable(owner.organization)
    configured = team(owner, people=2, hours=(time(8), time(16)), duration=60)
    first, _second = configured["staff"]
    csrf = csrf_value(client)

    def headers() -> dict[str, str]:
        return {"HTTP_X_CSRFTOKEN": csrf, "HTTP_IDEMPOTENCY_KEY": key()}

    place = client.post(
        "/api/v1/booking/setup/locations/", {"name": "Baza"}, format="json", **headers()
    )
    assert place.status_code == 201, place.data
    thing = client.post(
        "/api/v1/booking/setup/resources/", {"name": "Poskrom"}, format="json", **headers()
    )
    assert thing.status_code == 201, thing.data
    made = client.post(
        "/api/v1/booking/setup/services/",
        {
            "name": "Korekcja",
            "duration_minutes": 180,
            "staff_ids": [str(first.id)],
            "location_ids": [place.json()["id"]],
            "resource_ids": [thing.json()["id"]],
        },
        format="json",
        **headers(),
    )
    assert made.status_code == 201, made.data
    service = made.json()
    assert (service["staff_count"], service["public_staff_choice"]) == (1, "none")
    changed = client.patch(
        f"/api/v1/booking/setup/services/{service['id']}/",
        {"public_staff_choice": "person", "resource_ids": [], "expected_version": 1},
        format="json",
        **headers(),
    )
    assert changed.status_code == 200, changed.data
    assert changed.json()["resource_ids"] == []
    assert changed.json()["public_staff_choice"] == "person"
    renamed = client.patch(
        f"/api/v1/booking/setup/locations/{place.json()['id']}/",
        {"address": "Radziejów 1", "expected_version": 1},
        format="json",
        **headers(),
    )
    assert renamed.json()["address"] == "Radziejów 1"
    listed = client.get("/api/v1/booking/setup/").json()
    assert {item["name"] for item in listed["services"]} == {"Wizyta", "Korekcja"}
    people = {x.display_name for x in configured["staff"]}
    assert {item["name"] for item in listed["staff"]} == people
    assert not ServiceResource.all_objects.filter(service_id=service["id"]).exists()
    assert ServiceLocation.all_objects.filter(service_id=service["id"]).count() == 1
    assert Resource.all_objects.filter(organization=owner.organization).count() == 1

    worker = member_of(owner, "uslugi-pracownik@example.test", "staff")
    worker_client = authenticated_client(worker)
    worker_client.get("/api/v1/auth/csrf/")
    assert worker_client.get("/api/v1/booking/setup/").status_code == 403
    refused = worker_client.patch(
        f"/api/v1/booking/setup/services/{service['id']}/",
        {"name": "Moja", "expected_version": 2},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(worker_client),
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert refused.status_code == 403
    assert StaffMember.all_objects.filter(organization=owner.organization).count() == 2
