"""Who sees a customer's phone and e-mail in the calendar (decision 15.2b,
ADR-067), the visit's kind, and the flags a product puts on its card."""

from __future__ import annotations

from collections.abc import Sequence
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
def no_product_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """A product repository runs this suite with its own module registered."""
    monkeypatch.setattr(flags, "_providers", {})


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


def contacts(member: Membership) -> dict[str, tuple[Any, Any]]:
    response = authenticated_client(member).get("/api/v1/booking/appointments/")
    assert response.status_code == 200, response.content
    return {
        item["id"]: (item["customer_phone"], item["customer_email"])
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
    going = worker(owner, "jedzie@example.test")
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
    seen = ("+48 600 100 200", "jan@example.test")
    assert contacts(owner) == {str(visit.id): seen}
    assert contacts(manager) == {str(visit.id): seen}
    assert contacts(going) == {str(visit.id): seen}
    # Somebody of the same company who does not go sees the visit, not the number.
    assert contacts(staying) == {str(visit.id): (None, None)}

    with tenant(owner):
        AppointmentStaffAllocation.all_objects.filter(staff=person).update(active=False)
    assert contacts(going) == {str(visit.id): (None, None)}


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

    asked: list[list[UUID]] = []

    def farm_missing(ids: Sequence[UUID]) -> dict[UUID, list[str]]:
        asked.append(list(ids))
        return {visit.id: ["farm_missing", ""]}

    register_appointment_flags("test-farms", farm_missing)
    (item,) = client.get("/api/v1/booking/appointments/").json()["items"]
    assert item["flags"] == ["farm_missing"]
    assert len(asked) == 1
