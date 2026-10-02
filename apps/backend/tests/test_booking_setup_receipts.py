"""Setup writes as the assistant and the panel make them (ADR-072 §11): a key
with a receipt, a version a change names, and a preview that saves nothing."""

from __future__ import annotations

from datetime import time
from uuid import uuid4

import pytest
from rest_framework.exceptions import ParseError, ValidationError

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.booking.models import (
    AvailabilityRule,
    BookingSetupMutation,
    Location,
    Service,
    StaffMember,
)
from saas_core.modules.shared.booking.offer_settings import OFFER_SETTINGS
from saas_core.modules.shared.booking.serializers import ServiceInputSerializer
from saas_core.modules.shared.booking.services import (
    BookingIdempotencyConflict,
    BookingVersionConflict,
)
from saas_core.modules.shared.booking.setup import save_location, save_resource, save_service
from saas_core.modules.shared.booking.staff import set_person_hours
from test_booking import membership, tenant
from test_booking_slots import team
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


def key() -> str:
    return str(uuid4())


NEW = {"name": "Strzyżenie", "duration_minutes": 45}


def test_a_repeated_key_answers_the_first_service_and_a_reused_one_is_refused() -> None:
    owner = membership("s11-klucz")
    with tenant(owner):
        first = save_service(service_id=None, data=dict(NEW), idempotency_key="k-1")
        again = save_service(service_id=None, data=dict(NEW), idempotency_key="k-1")
        assert (again.item_id, again.replayed, again.created) == (first.item_id, True, True)
        with pytest.raises(BookingIdempotencyConflict):
            save_service(
                service_id=None, data={**NEW, "duration_minutes": 60}, idempotency_key="k-1"
            )
        with pytest.raises(ParseError):
            save_service(service_id=None, data=dict(NEW))
    assert Service.all_objects.filter(organization=owner.organization).count() == 1
    receipt = BookingSetupMutation.all_objects.get(organization=owner.organization)
    assert (receipt.action, receipt.result_kind, receipt.result_id) == (
        "service.create",
        "service",
        first.item_id,
    )


def test_a_change_names_the_version_it_was_made_on() -> None:
    owner = membership("s11-wersja")
    with tenant(owner):
        place = save_location(location_id=None, data={"name": "Baza"}, idempotency_key=key())
        assert place.version == 1
        with pytest.raises(ValidationError) as missing:
            save_location(location_id=place.item_id, data={"name": "B"}, idempotency_key=key())
        assert "expected_version" in missing.value.detail
        renamed = save_location(
            location_id=place.item_id,
            data={"name": "Baza główna"},
            expected_version=1,
            idempotency_key=key(),
        )
        assert (renamed.version, renamed.changes) == (
            2,
            {"name": {"from": "Baza", "to": "Baza główna"}},
        )
        # Somebody saw version 1 and saves over a change they never saw.
        with pytest.raises(BookingVersionConflict):
            save_location(
                location_id=place.item_id,
                data={"name": "Stara nazwa"},
                expected_version=1,
                idempotency_key=key(),
            )
        # Saving what is already there moves no version: nobody else's open
        # form goes stale for nothing.
        same = save_location(
            location_id=place.item_id,
            data={"name": "Baza główna"},
            expected_version=2,
            idempotency_key=key(),
        )
        assert (same.version, same.changes) == (2, {})
    assert Location.all_objects.get(pk=place.item_id).name == "Baza główna"


def test_a_preview_saves_nothing_and_refuses_what_the_write_would() -> None:
    owner = membership("s11-podglad")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    service = configured["service"]
    with tenant(owner):
        made = save_service(service_id=None, data=dict(NEW), preview=True)
        assert (made.value.service.name, made.created) == ("Strzyżenie", True)
        changed = save_service(
            service_id=service.id,
            data={"duration_minutes": 90},
            expected_version=1,
            preview=True,
        )
        assert changed.changes == {"duration_minutes": {"from": 60, "to": 90}}
        assert changed.version == 2
        with pytest.raises(ValidationError) as refused:
            save_service(
                service_id=service.id,
                data={"staff_count": 2, "public_staff_choice": "person"},
                expected_version=1,
                preview=True,
            )
        assert "public_staff_choice" in refused.value.detail
        with pytest.raises(BookingVersionConflict):
            save_service(
                service_id=service.id, data={"name": "X"}, expected_version=7, preview=True
            )
        resource = save_resource(resource_id=None, data={"name": "Fotel"}, preview=True)
        assert resource.value.name == "Fotel"
    service.refresh_from_db()
    assert (service.duration_minutes, service.version) == (60, 1)
    assert Service.all_objects.filter(organization=owner.organization).count() == 1
    assert not BookingSetupMutation.all_objects.filter(organization=owner.organization).exists()
    assert not OrganizationAuditEntry.objects.filter(
        organization=owner.organization, action="booking.catalog.changed"
    ).exists()


def test_a_week_has_its_own_version_receipt_and_preview() -> None:
    owner = membership("s11-tydzien")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60, weekdays=[0])
    staff: StaffMember = configured["staff"][0]
    week = [
        {
            "weekday": 1,
            "local_start": time(9),
            "local_end": time(17),
            "location_id": configured["location"].id,
        }
    ]
    with tenant(owner):
        preview = set_person_hours(staff_id=staff.id, rules=week, expected_version=1, preview=True)
        assert preview.version == 2
        assert preview.changes["hours"]["to"] == [
            [1, "09:00", "17:00", str(configured["location"].id)]
        ]
        assert AvailabilityRule.all_objects.get(staff=staff, active=True).weekday == 0
        saved = set_person_hours(
            staff_id=staff.id, rules=week, expected_version=1, idempotency_key="tydzien"
        )
        again = set_person_hours(
            staff_id=staff.id, rules=week, expected_version=1, idempotency_key="tydzien"
        )
        assert (saved.version, again.version, again.replayed) == (2, 2, True)
        with pytest.raises(BookingVersionConflict):
            set_person_hours(staff_id=staff.id, rules=[], expected_version=1, idempotency_key=key())
    assert AvailabilityRule.all_objects.filter(staff=staff, active=True).count() == 1
    assert (
        OrganizationAuditEntry.objects.filter(
            target_id=staff.id, action="booking.staff.hours_changed"
        ).count()
        == 1
    )


def test_the_offer_options_declare_what_the_input_accepts() -> None:
    fields = ServiceInputSerializer().fields
    for setting in OFFER_SETTINGS:
        if setting.type == "int":
            field = fields[setting.field]
            assert (field.min_value, field.max_value) == (setting.minimum, setting.maximum)
            assert setting.minimum <= setting.default <= setting.maximum
        assert setting.key == f"booking.offer.{setting.field}"
        assert set(setting.label) == {"pl", "en"}


def test_the_setup_api_takes_a_key_and_a_version_and_previews() -> None:
    _, owner, client = authenticated_member(
        email="s11-api@example.test", role_key="owner", slug="s11-api"
    )
    bookable(owner.organization)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    service = configured["service"]
    staff: StaffMember = configured["staff"][0]
    csrf = csrf_value(client)
    url = f"/api/v1/booking/setup/services/{service.id}/"

    keyless = client.patch(
        url, {"name": "A", "expected_version": 1}, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert keyless.status_code == 400
    unversioned = client.patch(
        url, {"name": "A"}, format="json", HTTP_X_CSRFTOKEN=csrf, HTTP_IDEMPOTENCY_KEY=key()
    )
    assert unversioned.status_code == 400
    assert [error["field"] for error in unversioned.json()["errors"]] == ["expected_version"]

    preview = client.post(
        f"{url}preview/",
        {"duration_minutes": 90, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert preview.status_code == 200, preview.data
    assert preview.json()["changes"] == {"duration_minutes": {"from": 60, "to": 90}}
    assert preview.json()["version"] == 2
    service.refresh_from_db()
    assert service.duration_minutes == 60

    changed = client.patch(
        url,
        {"duration_minutes": 90, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert (changed.status_code, changed.json()["version"]) == (200, 2)
    stale = client.patch(
        url,
        {"duration_minutes": 30, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "booking_version_conflict")

    hours = client.post(
        f"/api/v1/booking/staff/{staff.id}/hours/preview/",
        {
            "rules": [
                {
                    "weekday": 0,
                    "local_start": "10:00",
                    "local_end": "09:00",
                    "location_id": str(configured["location"].id),
                }
            ],
            "expected_version": 1,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert hours.status_code == 400
    assert hours.json()["errors"][0]["field"] == "rules.0.local_end"

    listed = client.get("/api/v1/booking/setup/").json()
    assert listed["services"][0]["version"] == 2
    assert listed["staff"][0]["hours_version"] == 1
    options = client.get("/api/v1/booking/setup/options/")
    assert options.status_code == 200
    entry = next(
        item for item in options.json()["keys"] if item["key"] == "booking.offer.duration_minutes"
    )
    assert (entry["minimum"], entry["maximum"], entry["unit"], entry["default"]) == (
        5,
        1440,
        "minute",
        30,
    )

    worker = member_of(owner, "s11-pracownik@example.test", "staff")
    worker_client = authenticated_client(worker)
    worker_client.get("/api/v1/auth/csrf/")
    assert worker_client.get("/api/v1/booking/setup/options/").status_code == 403
    refused = worker_client.post(
        f"{url}preview/",
        {"name": "Moja", "expected_version": 2},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(worker_client),
    )
    assert refused.status_code == 403
