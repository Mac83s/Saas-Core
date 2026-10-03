"""Who sees a customer's phone and e-mail in the calendar (decision 15.2b,
ADR-067), the visit's kind, and the flags a product puts on its card."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import Membership, Role, RoleScope
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.booking import flags
from saas_core.modules.shared.booking.api import register_appointment_flags
from saas_core.modules.shared.booking.models import (
    AppointmentStaffAllocation,
    ServiceStaff,
    StaffMember,
)
from test_booking import _no_delivery, catalog, create, membership, tenant
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def no_product_flags(monkeypatch: pytest.MonkeyPatch, settings: Any) -> None:
    """A product repository runs this suite with its own module registered —
    and MedPlano with its permission for other people's visits (UX-023): the
    contacts rule is core's, read where everybody sees every visit."""
    monkeypatch.setattr(flags, "_providers", {})
    settings.BOOKING_OTHERS_PERMISSION = None


def worker(member: Membership, email: str, *, role: str = "staff") -> Membership:
    user = User.objects.create_user(email=email)
    user.status = UserStatus.ACTIVE
    user.save()
    system, _ = Role.objects.get_or_create(
        key=role,
        organization=None,
        organization_type="",
        defaults={
            "name": role,
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS[role]),
            "is_immutable": True,
        },
    )
    return Membership.objects.create(organization=member.organization, user=user, role=system)


def contacts(member: Membership) -> dict[str, tuple[Any, Any, Any]]:
    response = authenticated_client(member).get("/api/v1/booking/appointments/")
    assert response.status_code == 200, response.content
    return {
        item["id"]: (item["customer_phone"], item["customer_email"], item["place_address"])
        for item in response.json()["items"]
    }


def test_the_phone_is_for_whoever_plans_and_whoever_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    owner = membership("kontakt-widok")
    configured = catalog(owner)
    visit = create(owner, configured).appointment
    with tenant(owner):
        visit.customer.phone = "+48 600 100 200"
        visit.customer.save(update_fields=["phone"])
        visit.place_town, visit.place_address = "Wólka", "Polna 3"
        visit.save(update_fields=["place_town", "place_address"])
    going = worker(owner, "jedzie@example.test")
    leading = worker(owner, "prowadzi@example.test")
    staying = worker(owner, "zostaje@example.test")
    manager = worker(owner, "biuro@example.test", role="manager")
    with tenant(owner):
        # „going” helps on this visit: time blocked like the lead's.
        person = StaffMember.all_objects.create(
            organization=owner.organization, display_name="Bea", membership_id=going.id
        )
        ServiceStaff.all_objects.create(
            organization=owner.organization, service=configured["service"], staff=person
        )
        AppointmentStaffAllocation.all_objects.create(
            organization=owner.organization,
            appointment=visit,
            staff=person,
            occupied_range=(visit.occupied_from, visit.occupied_until),
        )
        # „leading” is the visit's lead, with no vacancy on it.
        configured["staff"].membership_id = leading.id
        configured["staff"].save(update_fields=["membership_id"])
    seen = ("+48 600 100 200", "jan@example.test", "Polna 3")
    hidden = (None, None, "")
    assert contacts(owner) == {str(visit.id): seen}
    assert contacts(manager) == {str(visit.id): seen}
    assert contacts(going) == {str(visit.id): seen}
    assert contacts(leading) == {str(visit.id): seen}
    # Somebody of the same company who does not go sees the visit and its town,
    # not the number or the street.
    assert contacts(staying) == {str(visit.id): hidden}
    response = authenticated_client(staying).get("/api/v1/booking/appointments/")
    assert response.json()["items"][0]["place"] == "Wólka"

    with tenant(owner):
        AppointmentStaffAllocation.all_objects.filter(staff=person).update(active=False)
    assert contacts(going) == {str(visit.id): hidden}

    # A called-off visit: whoever was on it still sees whom to tell.
    with tenant(owner):
        AppointmentStaffAllocation.all_objects.filter(staff=person).update(active=True)
    cancel = authenticated_client(owner).post(
        f"/api/v1/booking/appointments/{visit.id}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="kontakt-odwolanie",
    )
    assert cancel.status_code == 200, cancel.content
    assert contacts(going) == {str(visit.id): seen}
    assert contacts(staying) == {str(visit.id): hidden}


def test_a_visit_says_its_kind_and_the_flags_a_product_puts_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    owner = membership("kontakt-znaczniki")
    configured = catalog(owner)
    visit = create(owner, configured).appointment
    client = authenticated_client(owner)
    (item,) = client.get("/api/v1/booking/appointments/").json()["items"]
    assert (item["appointment_kind"], item["flags"]) == ("", [])

    asked: list[dict[UUID, str]] = []

    def farm_missing(kinds: Mapping[UUID, str]) -> dict[UUID, list[str]]:
        asked.append(dict(kinds))
        return {visit.id: ["farm_missing", ""]}

    register_appointment_flags("test-farms", farm_missing)
    (item,) = client.get("/api/v1/booking/appointments/").json()["items"]
    assert item["flags"] == ["farm_missing"]
    # One question for the list, each visit with its kind.
    assert asked == [{visit.id: ""}]

    # A provider that fails costs its own flags, never the list or a change.
    def broken(kinds: Mapping[UUID, str]) -> dict[UUID, list[str]]:
        raise RuntimeError("module down")

    register_appointment_flags("test-broken", broken)
    response = client.get("/api/v1/booking/appointments/")
    assert response.status_code == 200
    assert response.json()["items"][0]["flags"] == ["farm_missing"]
    canceled = client.post(
        f"/api/v1/booking/appointments/{visit.id}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="znaczniki-odwolanie",
    )
    assert canceled.status_code == 200, canceled.content
    assert canceled.json()["status"] == "canceled"
