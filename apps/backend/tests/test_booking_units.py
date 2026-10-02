"""Units, groups and blocks (ADR-072 §3–§4, phase 2a): a unit's block holds
its time under the same exclusion constraint as a booking."""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from rest_framework.exceptions import ValidationError

from saas_core.modules.shared.booking.models import (
    AppointmentResourceAllocation,
    BookingSetupMutation,
    Resource,
    TimeOff,
)
from saas_core.modules.shared.booking.services import configure_schedule
from saas_core.modules.shared.booking.setup import list_setup, save_group, save_resource
from saas_core.modules.shared.booking.units import (
    UnitBusy,
    add_unit_block,
    list_unit_blocks,
    remove_unit_block,
)
from test_booking import catalog, create, membership, tenant
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    # Logins are throttled per client address, and the API tests log in.
    cache.clear()


def key() -> str:
    return str(uuid4())


def test_units_join_a_group_and_a_place_of_the_company() -> None:
    owner = membership("jednostki-grupy")
    stranger = membership("jednostki-obcy")
    configured = catalog(owner)
    foreign = catalog(stranger)
    with tenant(stranger):
        theirs = save_group(group_id=None, data={"name": "Cudza"}, idempotency_key=key()).value
    with tenant(owner):
        group = save_group(group_id=None, data={"name": "Domek 6-os."}, idempotency_key=key()).value
        cottage = save_resource(
            resource_id=None,
            data={
                "name": "Domek 1",
                "group_id": group.id,
                "location_id": configured["location"].id,
                "capacity": 6,
                "description": "Dwie sypialnie, kominek.",
            },
            idempotency_key=key(),
        ).value
        assert (cottage.group_id, cottage.capacity) == (group.id, 6)
        # Another company's group or place is nobody's to join.
        for field, target in (("group_id", theirs.id), ("location_id", foreign["location"].id)):
            with pytest.raises(ValidationError) as refused:
                save_resource(
                    resource_id=cottage.id,
                    data={field: target},
                    expected_version=1,
                    idempotency_key=key(),
                )
            assert field in refused.value.detail
        with pytest.raises(ValidationError) as taken:
            save_group(group_id=None, data={"name": "domek 6-OS."}, idempotency_key=key())
        assert taken.value.get_codes() == {"name": "name_taken"}
        # Out of the group: null, at the version read.
        out = save_resource(
            resource_id=cottage.id,
            data={"group_id": None},
            expected_version=1,
            idempotency_key=key(),
        )
        assert (out.value.group_id, out.version) == (None, 2)
        assert out.changes == {"group_id": {"from": str(group.id), "to": None}}
        setup = list_setup()
    assert [item.name for item in setup.groups] == ["Domek 6-os."]


def test_a_block_holds_the_unit_and_refuses_what_overlaps() -> None:
    owner = membership("jednostki-blokada")
    configured = catalog(owner)
    visit = create(owner, configured).appointment
    resource: Resource = configured["resource"]
    later = visit.ends_at + timedelta(days=1)
    with tenant(owner):
        # Over the booking: refused, nothing kept.
        with pytest.raises(UnitBusy):
            add_unit_block(
                resource_id=resource.id,
                starts_at=visit.starts_at - timedelta(hours=1),
                ends_at=visit.ends_at,
                idempotency_key=key(),
            )
        preview = add_unit_block(
            resource_id=resource.id,
            starts_at=later,
            ends_at=later + timedelta(days=2),
            reason="remont",
            preview=True,
        )
        assert preview.value.holds is True
        assert not TimeOff.all_objects.filter(resource=resource).exists()
        block = add_unit_block(
            resource_id=resource.id,
            starts_at=later,
            ends_at=later + timedelta(days=2),
            reason="remont",
            idempotency_key="blokada-1",
        ).value.block
        allocation = AppointmentResourceAllocation.all_objects.get(time_off=block)
        assert (allocation.appointment_id, allocation.active) == (None, True)
        with pytest.raises(UnitBusy):
            add_unit_block(
                resource_id=resource.id,
                starts_at=later + timedelta(days=1),
                ends_at=later + timedelta(days=3),
                idempotency_key=key(),
            )
        # A booking racing the block loses in the database, whatever Python saw.
        with pytest.raises(IntegrityError), transaction.atomic():
            AppointmentResourceAllocation.all_objects.create(
                organization_id=owner.organization_id,
                appointment=visit,
                resource=resource,
                occupied_range=(later, later + timedelta(hours=2)),
            )
        listed = list_unit_blocks(
            resource_id=resource.id, starts_from=later, starts_until=later + timedelta(days=9)
        )
        assert [(item.block.id, item.holds) for item in listed] == [(block.id, True)]
        remove_unit_block(time_off_id=block.id, idempotency_key="zdjecie-1")
        remove_unit_block(time_off_id=block.id, idempotency_key="zdjecie-1")
        assert not AppointmentResourceAllocation.all_objects.filter(
            resource=resource, appointment__isnull=True
        ).exists()
    receipts = BookingSetupMutation.all_objects.filter(organization_id=owner.organization_id)
    assert sorted(receipts.values_list("action", flat=True)) == ["unit.block", "unit.unblock"]


def test_the_schedule_door_blocks_a_resource_the_same_way() -> None:
    owner = membership("jednostki-grafik")
    configured = catalog(owner)
    visit = create(owner, configured).appointment
    with tenant(owner), pytest.raises(UnitBusy):
        configure_schedule(
            kind="time_off",
            data={
                "resource": configured["resource"],
                "starts_at": visit.starts_at,
                "ends_at": visit.ends_at,
            },
        )


def test_the_migration_holds_old_blocks_and_reports_the_overlapping_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = membership("jednostki-migracja")
    configured = catalog(owner)
    visit = create(owner, configured).appointment
    resource = configured["resource"]
    later = visit.ends_at + timedelta(days=1)
    with tenant(owner):
        # Blocks from before the constraint covered them: one free, one over
        # the booking, one over the free one.
        rows = [
            TimeOff.all_objects.create(
                organization=owner.organization, resource=resource, starts_at=a, ends_at=b
            )
            for a, b in (
                (later, later + timedelta(hours=3)),
                (visit.starts_at, visit.ends_at),
                (later + timedelta(hours=1), later + timedelta(hours=2)),
            )
        ]
    migration: Any = importlib.import_module(
        "saas_core.modules.shared.booking.migrations.0016_units_groups_and_blocks"
    )

    class Editor:
        pass

    editor = Editor()
    editor.connection = connection  # type: ignore[attr-defined]
    migration.hold_blocks(None, editor)
    held = {
        allocation.time_off_id: allocation.active
        for allocation in AppointmentResourceAllocation.all_objects.filter(time_off__in=rows)
    }
    assert held == {rows[0].id: True, rows[1].id: False, rows[2].id: False}
    assert "3 blokad zasobów z alokacją, w tym 2 nieaktywnych" in capsys.readouterr().out


def test_the_units_api_answers_management_and_refuses_the_others() -> None:
    _, owner, client = authenticated_member(
        email="jednostki-api@example.test", role_key="owner", slug="jednostki-api"
    )
    bookable(owner.organization)
    configured = catalog(owner)
    csrf = csrf_value(client)

    def headers() -> dict[str, str]:
        return {"HTTP_X_CSRFTOKEN": csrf, "HTTP_IDEMPOTENCY_KEY": key()}

    group = client.post(
        "/api/v1/booking/setup/groups/", {"name": "Kajak 2-os."}, format="json", **headers()
    )
    assert group.status_code == 201, group.data
    renamed = client.patch(
        f"/api/v1/booking/setup/groups/{group.json()['id']}/",
        {"name": "Kajak dwuosobowy", "expected_version": 1},
        format="json",
        **headers(),
    )
    assert (renamed.status_code, renamed.json()["version"]) == (200, 2)
    unit = client.patch(
        f"/api/v1/booking/setup/resources/{configured['resource'].id}/",
        {"group_id": group.json()["id"], "capacity": 2, "expected_version": 1},
        format="json",
        **headers(),
    )
    assert unit.status_code == 200, unit.data
    assert (unit.json()["group_id"], unit.json()["capacity"]) == (group.json()["id"], 2)
    starts = configured["date"] + timedelta(days=30)
    window = {"starts_at": f"{starts}T08:00:00+02:00", "ends_at": f"{starts}T18:00:00+02:00"}
    blocks = f"/api/v1/booking/setup/resources/{configured['resource'].id}/blocks/"
    made = client.post(blocks, window, format="json", **headers())
    assert made.status_code == 201, made.data
    busy = client.post(f"{blocks}preview/", window, format="json", HTTP_X_CSRFTOKEN=csrf)
    assert (busy.status_code, busy.json()["code"]) == (409, "unit_busy")
    listed = client.get(
        blocks, {"from": f"{starts}T00:00:00+02:00", "to": f"{starts}T23:59:00+02:00"}
    )
    assert [item["id"] for item in listed.json()["items"]] == [made.json()["id"]]
    assert client.get("/api/v1/booking/setup/").json()["groups"][0]["name"] == "Kajak dwuosobowy"
    gone = client.delete(f"/api/v1/booking/setup/blocks/{made.json()['id']}/", **headers())
    assert gone.status_code == 204

    worker = member_of(owner, "jednostki-pracownik@example.test", "staff")
    worker_client = authenticated_client(worker)
    worker_client.get("/api/v1/auth/csrf/")
    refused = worker_client.post(
        blocks,
        window,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(worker_client),
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert refused.status_code == 403
