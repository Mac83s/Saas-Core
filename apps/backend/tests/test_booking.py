from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    Feature,
    SubscriptionState,
)
from saas_core.modules.shared.booking.availability import _valid_instants, available_slots
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentResourceAllocation,
    AppointmentStaffAllocation,
    AvailabilityRule,
    Customer,
    Location,
    Resource,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffMember,
)
from saas_core.modules.shared.booking.security import public_booking_context
from saas_core.modules.shared.booking.services import (
    SlotUnavailable,
    anonymize_customer,
    cancel_appointment,
    create_appointment,
    create_catalog_item,
    reschedule_appointment,
)

pytestmark = pytest.mark.django_db(transaction=True)


def membership(slug: str) -> Membership:
    Feature.objects.get_or_create(
        key="booking.enabled",
        defaults={"name": "Rezerwacje", "module": "shared.booking"},
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug,
        slug=slug,
        status=OrganizationStatus.ACTIVE,
        timezone="Europe/Warsaw",
    )
    role, _ = Role.objects.get_or_create(
        key="owner",
        organization=None,
        defaults={
            "name": "Owner",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["owner"]),
            "is_immutable": True,
        },
    )
    member = Membership.objects.create(
        organization=organization,
        user=user,
        role=role,
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"booking.enabled": True},
        quotas={},
        sources={"booking.enabled": {"kind": "plan"}},
    )
    return member


@contextmanager
def tenant(member: Membership):
    context = context_from_membership(member)
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        yield context


def catalog(member: Membership) -> dict[str, Any]:
    with tenant(member):
        organization = member.organization
        location = Location.all_objects.create(
            organization=organization, name="Centrum", public_slug="centrum"
        )
        staff = StaffMember.all_objects.create(
            organization=organization, display_name="Alex", public_slug="alex"
        )
        resource = Resource.all_objects.create(
            organization=organization, name="Gabinet 1", kind="room"
        )
        service = Service.all_objects.create(
            organization=organization,
            name="Konsultacja",
            public_slug="konsultacja",
            duration_minutes=30,
            buffer_before_minutes=5,
            buffer_after_minutes=10,
            minimum_notice_minutes=0,
        )
        ServiceStaff.all_objects.create(organization=organization, service=service, staff=staff)
        ServiceLocation.all_objects.create(
            organization=organization, service=service, location=location
        )
        ServiceResource.all_objects.create(
            organization=organization, service=service, resource=resource
        )
        future = timezone.localdate() + timedelta(days=7)
        AvailabilityRule.all_objects.create(
            organization=organization,
            staff=staff,
            location=location,
            weekday=future.weekday(),
            local_start=time(9),
            local_end=time(12),
        )
    return {
        "location": location,
        "staff": staff,
        "resource": resource,
        "service": service,
        "date": future,
    }


def create(member: Membership, configured: dict[str, Any], key: str = "create-1"):
    with tenant(member):
        slots = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"],
        )
        if "starts_at" not in configured:
            assert slots
            configured["starts_at"] = slots[0].starts_at
        return create_appointment(
            service_id=configured["service"].id,
            staff_id=configured["staff"].id,
            location_id=configured["location"].id,
            resource_id=configured["resource"].id,
            starts_at=configured["starts_at"],
            customer_data={
                "display_name": "Jan Kowalski",
                "email": "jan@example.test",
                "phone": "",
                "locale": "pl",
            },
            idempotency_key=key,
            principal_ref=str(member.user_id),
        )


def test_dst_nonexistent_time_is_skipped_and_ambiguous_time_has_two_instants() -> None:
    zone = ZoneInfo("Europe/Warsaw")
    assert _valid_instants(date(2026, 3, 29), time(2, 30), zone) == []
    ambiguous = _valid_instants(date(2026, 10, 25), time(2, 30), zone)
    assert len(ambiguous) == 2
    assert ambiguous[1] - ambiguous[0] == timedelta(hours=1)


def test_availability_query_count_is_bounded_for_long_horizon(
    django_assert_max_num_queries: Any,
) -> None:
    member = membership("booking-performance")
    configured = catalog(member)
    with tenant(member), django_assert_max_num_queries(10):
        slots = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"] + timedelta(days=30),
            limit=500,
        )
    assert slots


def test_create_retry_returns_same_appointment_and_same_self_service_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-idempotency")
    configured = catalog(member)
    first = create(member, configured)
    second = create(member, configured)
    assert first.created and not second.created
    assert first.appointment.id == second.appointment.id
    assert first.token == second.token
    assert first.token and "jan@example.test" not in first.token
    assert Customer._meta.get_field("id") and not hasattr(first.appointment.customer, "user")


def test_database_exclusion_blocks_staff_and_shared_resource_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-conflict")
    configured = catalog(member)
    booked = create(member, configured).appointment
    with tenant(member):
        with pytest.raises(IntegrityError), transaction.atomic():
            AppointmentStaffAllocation.all_objects.create(
                organization=member.organization,
                appointment=booked,
                staff=configured["staff"],
                occupied_range=(booked.occupied_from, booked.occupied_until),
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            AppointmentResourceAllocation.all_objects.create(
                organization=member.organization,
                appointment=booked,
                resource=configured["resource"],
                occupied_range=(booked.occupied_from, booked.occupied_until),
            )
        with pytest.raises(SlotUnavailable):
            create_appointment(
                service_id=configured["service"].id,
                staff_id=configured["staff"].id,
                location_id=configured["location"].id,
                resource_id=configured["resource"].id,
                starts_at=booked.starts_at,
                customer_data={"display_name": "Anna", "email": "anna@example.test"},
                idempotency_key="second-client",
                principal_ref="public",
            )


def test_two_concurrent_transactions_create_only_one_appointment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-concurrent")
    configured = catalog(member)
    with tenant(member):
        slot = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"],
        )[0]

    def attempt(number: int) -> str:
        close_old_connections()
        try:
            with public_booking_context(member.organization_id):
                create_appointment(
                    service_id=configured["service"].id,
                    staff_id=configured["staff"].id,
                    location_id=configured["location"].id,
                    resource_id=configured["resource"].id,
                    starts_at=slot.starts_at,
                    customer_data={
                        "display_name": f"Klient {number}",
                        "email": f"client-{number}@example.test",
                    },
                    idempotency_key=f"concurrent-{number}",
                    principal_ref=f"public-{number}",
                )
            return "created"
        except SlotUnavailable:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, (1, 2)))
    assert sorted(outcomes) == ["conflict", "created"]
    with tenant(member):
        assert Appointment.objects.count() == 1


def test_a_deadlock_between_two_racing_bookings_is_a_slot_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race above can end in a deadlock instead of an exclusion violation.

    Both transactions insert their allocation, and each exclusion check waits
    for the other's uncommitted row; PostgreSQL aborts one of them with SQLSTATE
    40P01. Seen under load on 2026-09-18 as a 500 where a 409 belongs. Forced
    here, because the real interleaving cannot be produced on demand.
    """
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-deadlock")
    configured = catalog(member)

    def deadlock(*_args: Any, **_kwargs: Any) -> None:
        try:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        except psycopg.errors.DeadlockDetected as cause:
            raise OperationalError("deadlock detected") from cause

    monkeypatch.setattr(AppointmentStaffAllocation.all_objects, "create", deadlock)
    with pytest.raises(SlotUnavailable):
        create(member, configured)

    def unrelated(*_args: Any, **_kwargs: Any) -> None:
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(AppointmentStaffAllocation.all_objects, "create", unrelated)
    with pytest.raises(OperationalError):
        create(member, configured, key="create-2")


def test_reschedule_cancel_are_idempotent_and_schedule_change_preserves_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-lifecycle")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    original_name = appointment.service_name
    with tenant(member):
        configured["service"].name = "Nowa nazwa"
        configured["service"].save(update_fields=["name", "updated_at"])
        appointment.refresh_from_db()
        assert appointment.service_name == original_name
        moved = appointment.starts_at + timedelta(minutes=60)
        first = reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=moved,
            idempotency_key="move-1",
            principal_ref=str(member.user_id),
        )
        retry = reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=moved,
            idempotency_key="move-1",
            principal_ref=str(member.user_id),
        )
        assert first.starts_at == retry.starts_at == moved
        AvailabilityRule.all_objects.all().delete()
        canceled = cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key="cancel-1",
            principal_ref=str(member.user_id),
        )
        retry_cancel = cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key="cancel-1",
            principal_ref=str(member.user_id),
        )
        assert canceled.status == retry_cancel.status == "canceled"


def test_customer_anonymization_and_cross_tenant_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    first = membership("booking-first")
    second = membership("booking-second")
    booked = create(first, catalog(first)).appointment
    with tenant(second):
        assert Appointment.objects.filter(pk=booked.id).count() == 0
        assert Customer.objects.filter(pk=booked.customer_id).count() == 0
    with tenant(first):
        customer = anonymize_customer(booked.customer_id)
        assert customer.email == "" and customer.phone == ""
        assert customer.anonymized_at is not None


def test_unknown_or_revoked_self_service_token_is_non_enumerable() -> None:
    client = APIClient()
    unknown = client.get("/api/v1/booking/self-service/bk_unknown/")
    assert unknown.status_code == 404
    assert "appointment" not in str(unknown.data).lower()


def test_canceled_self_service_token_returns_same_non_enumerable_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership("booking-revoked-token")
    created = create(member, catalog(member))
    assert created.token
    with tenant(member):
        cancel_appointment(
            appointment_id=created.appointment.id,
            idempotency_key="cancel-token",
            principal_ref=str(member.user_id),
        )
    response = APIClient().get(f"/api/v1/booking/self-service/{created.token}/")
    assert response.status_code == 404
    assert "appointment" not in str(response.data).lower()


def test_booking_tables_force_rls_and_cross_tenant_relations_fail_at_database() -> None:
    first = membership("booking-rls-first")
    second = membership("booking-rls-second")
    configured = catalog(first)
    with tenant(second), pytest.raises(IntegrityError), transaction.atomic():
        ServiceStaff.all_objects.create(
            organization=second.organization,
            service=configured["service"],
            staff=configured["staff"],
        )
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('booking_customer', 'booking_appointment') ORDER BY relname"
        )
        assert cursor.fetchall() == [(True, True), (True, True)]


def test_a_service_sells_only_a_visit_kind_its_organization_type_has() -> None:
    """ADR-050: a kind of visit belongs to a module, and the module to a type."""
    member = membership("booking-kind")
    with tenant(member), pytest.raises(ValidationError):
        create_catalog_item(
            kind="service",
            data={"name": "Cudza wizyta", "duration_minutes": 30, "appointment_kind": "x.visit"},
        )
