"""An appointment's end of life: done, and not called off afterwards (HC-ADR-002, C2/C4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from saas_core.modules.shared.booking.api import (
    AppointmentNotChangeable,
    AppointmentStatus,
    appointment_for_tenant,
    cancel_appointment,
    complete_appointment,
    list_appointments,
)
from saas_core.modules.shared.booking.models import Appointment, SelfServiceRoute, Service
from saas_core.modules.shared.booking.security import public_booking_context
from test_booking import catalog, create, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)


def test_a_completed_visit_closes_the_customers_link_and_stays_done() -> None:
    member = membership("zakonczone")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    with tenant(member) as context:
        found = appointment_for_tenant(context.organization_id, appointment.id)
        assert found is not None and found.service.id == configured["service"].id
        done = complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
        again = complete_appointment(
            appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
        )
        assert done.status == again.status == AppointmentStatus.COMPLETED
        assert SelfServiceRoute.objects.get(appointment_id=appointment.id).revoked_at is not None
        with pytest.raises(AppointmentNotChangeable):
            cancel_appointment(
                appointment_id=appointment.id, idempotency_key="c", principal_ref="t"
            )


def test_the_customer_cannot_move_or_call_off_a_visit_that_started() -> None:
    member = membership("po-starcie")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    Appointment.all_objects.filter(pk=appointment.id).update(
        starts_at=timezone.now() - timedelta(minutes=5)
    )
    with (
        public_booking_context(member.organization_id),
        pytest.raises(AppointmentNotChangeable),
    ):
        cancel_appointment(appointment_id=appointment.id, idempotency_key="k", principal_ref="x")
    # The provider still can: a visit called off on the spot is theirs to record.
    with tenant(member):
        canceled = cancel_appointment(
            appointment_id=appointment.id, idempotency_key="k", principal_ref="staff"
        )
        assert canceled.status == AppointmentStatus.CANCELED


def test_a_vertical_lists_one_day_of_its_own_kind_of_visit() -> None:
    member = membership("dzien")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    with tenant(member):
        Service.all_objects.filter(pk=configured["service"].id).update(appointment_kind="x.visit")
        day = appointment.starts_at.replace(hour=0, minute=0, second=0, microsecond=0)
        window = {"starts_from": day, "starts_until": day + timedelta(days=1)}
        assert [a.id for a in list_appointments(**window, appointment_kinds={"x.visit"})] == [
            appointment.id
        ]
        assert list_appointments(**window, appointment_kinds={"y.visit"}) == []
        assert list_appointments(starts_from=day + timedelta(days=1)) == []
