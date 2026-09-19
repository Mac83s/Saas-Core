"""A team member as a person: permissions, name, and their own calendar entry.

The panel hides what a member cannot use by permission (roles differ per
organization type, ADR-050), greets them by name, and shows "my visits" from
the calendar entry linked to their membership.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import AccountAuditEvent, AccountAuditEventType
from saas_core.modules.core.organizations.models import Membership, Role
from saas_core.modules.shared.booking.models import Service, StaffMember
from test_booking import catalog, create, membership, tenant
from test_organization_api import (
    CURRENT_URL,
    active_user,
    clear_session_cache,  # noqa: F401 - autouse: a cached session outlives the test
    csrf_value,
    login,
    membership_for,
)

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/auth/me/"
MEMBERS_URL = "/api/v1/organizations/current/members/"


def test_the_organization_summary_carries_the_members_permissions() -> None:
    client = APIClient()
    viewer = active_user(email="podglad@example.com")
    membership_for(viewer, role_key="viewer")
    login(client, viewer)

    summary = client.get(CURRENT_URL)
    assert summary.status_code == 200
    permissions = set(summary.data["permissions"])
    assert permissions == set(
        Role.objects.get(key="viewer", organization=None, organization_type="").permissions
    )
    assert "organization.read" in permissions
    assert "organization.members.manage" not in permissions
    listed = client.get("/api/v1/organizations/")
    assert listed.data[0]["permissions"] == summary.data["permissions"]


def test_a_person_names_themselves_once_and_the_team_sees_it() -> None:
    client = APIClient(enforce_csrf_checks=True)
    owner = active_user()
    membership_for(owner)
    login(client, owner)
    headers = {"HTTP_X_CSRFTOKEN": csrf_value(client)}

    assert client.patch(ME_URL, {"first_name": "Marcin"}, format="json").status_code == 403
    changed = client.patch(
        ME_URL, {"first_name": " Marcin ", "last_name": "Nowak"}, format="json", **headers
    )
    assert changed.status_code == 200
    assert (changed.data["first_name"], changed.data["last_name"]) == ("Marcin", "Nowak")
    assert client.get(ME_URL).data["first_name"] == "Marcin"

    # The same values again change nothing and leave no second audit event.
    client.patch(ME_URL, {"first_name": "Marcin"}, format="json", **headers)
    events = AccountAuditEvent.objects.filter(
        subject_user=owner, event_type=AccountAuditEventType.PROFILE_UPDATED
    )
    assert events.count() == 1

    team = client.get(MEMBERS_URL).data
    assert [(m["first_name"], m["last_name"]) for m in team] == [("Marcin", "Nowak")]


@pytest.mark.django_db(transaction=True)
def test_a_calendar_entry_stands_for_one_member_of_its_own_organization() -> None:
    from saas_core.modules.shared.booking.services import (  # noqa: PLC0415
        create_catalog_item,
        list_appointments,
        update_staff,
    )

    owner = membership("zespol")
    configured = catalog(owner)
    other = membership("obcy")
    staff: Any = configured["staff"]

    with tenant(owner):
        linked = update_staff(staff_id=staff.id, data={"membership_id": owner.id})
        assert linked.membership_id == owner.id
        with pytest.raises(ValidationError, match="ma już swój wpis"):
            create_catalog_item(
                kind="staff",
                data={"display_name": "Drugi", "public_slug": "drugi", "membership_id": owner.id},
            )
        with pytest.raises(ValidationError, match="aktywnego członka"):
            update_staff(staff_id=staff.id, data={"membership_id": other.id})

    create(owner, configured)
    with tenant(owner):
        assert len(list_appointments(mine=True)) == 1
        update_staff(staff_id=staff.id, data={"membership_id": None})
        assert list_appointments(mine=True) == []
        assert len(list_appointments()) == 1

    # The database guard is the second line: an entry pointing at another
    # organization's member is refused even when the service is bypassed.
    with pytest.raises(IntegrityError), transaction.atomic():
        StaffMember.all_objects.create(
            organization_id=other.organization_id,
            display_name="Podrzut",
            public_slug="podrzut",
            membership_id=owner.id,
        )


@pytest.mark.django_db(transaction=True)
def test_the_catalog_names_a_services_visit_kind_but_not_who_has_an_account() -> None:
    from saas_core.modules.shared.booking.services import (  # noqa: PLC0415
        list_catalog,
        update_staff,
    )
    from saas_core.modules.shared.booking.views import _catalog_payload  # noqa: PLC0415

    owner: Membership = membership("katalog")
    configured = catalog(owner)
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(appointment_kind="x.visit")
        update_staff(staff_id=configured["staff"].id, data={"membership_id": owner.id})
        value = list_catalog()
    panel = _catalog_payload(value)
    public = _catalog_payload(value, public=True)
    assert panel["services"][0]["appointment_kind"] == "x.visit"
    assert panel["staff"][0]["membership_id"] == owner.id
    assert public["staff"][0]["membership_id"] is None
