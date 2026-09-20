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
from saas_core.modules.shared.booking.observers import (
    AppointmentChange,
    _observers,
    register_appointment_observer,
)
from saas_core.modules.shared.booking.security import public_booking_context
from saas_core.modules.shared.booking.services import (
    SlotUnavailable,
    anonymize_customer,
    cancel_appointment,
    complete_appointment,
    create_appointment,
    create_catalog_item,
    reschedule_appointment,
)
from saas_core.modules.shared.notifications.models import NotificationMessage

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
        organization_type="",
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


def _no_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )


@contextmanager
def watching():
    """Registers an observer for the duration of one test and takes it back."""
    seen: list[AppointmentChange] = []
    name = f"test-{len(_observers)}"
    register_appointment_observer(name, seen.append)
    try:
        yield seen
    finally:
        _observers.pop(name, None)


def mails(appointment_id: Any, key: str) -> list[NotificationMessage]:
    return list(
        NotificationMessage.all_objects.filter(
            causation_id=f"booking:{appointment_id}", template_key=key
        ).order_by("created_at")
    )


def test_a_moved_booking_mails_the_customer_both_times_with_both_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-mail-move")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    first_time = appointment.starts_at
    with tenant(member):
        second_time = first_time + timedelta(minutes=60)
        reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=second_time,
            idempotency_key="move-1",
            principal_ref=str(member.user_id),
        )
        third_time = first_time + timedelta(minutes=120)
        reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=third_time,
            idempotency_key="move-2",
            principal_ref=str(member.user_id),
        )
        # A retry of the second move must not produce a third mail.
        reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=third_time,
            idempotency_key="move-2",
            principal_ref=str(member.user_id),
        )
        sent = mails(appointment.id, "booking.rescheduled")
        assert len(sent) == 2
        assert sent[0].context["previous_starts_at"] != sent[0].context["starts_at"]
        assert sent[0].context["starts_at"] == sent[1].context["previous_starts_at"]
        # The customer reads a local wall clock, never the stored instant.
        local = first_time.astimezone(ZoneInfo(appointment.timezone))
        assert first_time.isoformat() not in sent[0].context["previous_starts_at"]
        assert f"{local.hour:02d}:{local.minute:02d}" in sent[0].context["previous_starts_at"]
        assert str(local.year) in sent[0].context["previous_starts_at"]


def test_the_confirmation_mail_reads_as_a_wall_clock_not_a_stored_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The oldest booking mail had the same defect the new ones were written to avoid.

    Confirmation goes to the person the visit is for — in HoofCare that is the
    farm's keeper — and it used to hand them the raw ISO instant the database
    keeps. Containers run in UTC, so that is the wrong hour as well as an
    unreadable one.
    """
    _no_delivery(monkeypatch)
    member = membership("booking-mail-confirm")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    sent = mails(appointment.id, "booking.confirmation")
    assert len(sent) == 1
    local = appointment.starts_at.astimezone(ZoneInfo(appointment.timezone))
    assert appointment.starts_at.isoformat() not in sent[0].context["starts_at"]
    assert f"{local.hour:02d}:{local.minute:02d}" in sent[0].context["starts_at"]
    assert str(local.year) in sent[0].context["starts_at"]


def test_a_canceled_booking_mails_once_even_when_canceled_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-mail-cancel")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    with tenant(member):
        cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key="cancel-1",
            principal_ref=str(member.user_id),
        )
        cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key="cancel-2",
            principal_ref=str(member.user_id),
        )
        sent = mails(appointment.id, "booking.canceled")
        assert len(sent) == 1
        assert appointment.starts_at.isoformat() not in sent[0].context["starts_at"]


def test_a_booking_without_an_email_address_changes_without_queueing_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-mail-phone")
    configured = catalog(member)
    with tenant(member):
        slots = available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=configured["date"],
            to_date=configured["date"],
        )
        appointment = create_appointment(
            service_id=configured["service"].id,
            staff_id=configured["staff"].id,
            location_id=configured["location"].id,
            resource_id=configured["resource"].id,
            starts_at=slots[0].starts_at,
            customer_data={
                "display_name": "Bez maila",
                "email": "",
                "phone": "+48123123123",
                "locale": "pl",
            },
            idempotency_key="phone-only",
            principal_ref=str(member.user_id),
        ).appointment
        reschedule_appointment(
            appointment_id=appointment.id,
            starts_at=appointment.starts_at + timedelta(minutes=60),
            idempotency_key="move-phone",
            principal_ref=str(member.user_id),
        )
        cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key="cancel-phone",
            principal_ref=str(member.user_id),
        )
        assert NotificationMessage.all_objects.filter(
            causation_id=f"booking:{appointment.id}"
        ).count() == 0


def test_every_appointment_transition_reaches_a_registered_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-observer")
    configured = catalog(member)
    with watching() as seen:
        appointment = create(member, configured).appointment
        assert [event.change for event in seen] == ["created"]
        assert seen[0].previous_starts_at is None
        assert seen[0].starts_at == appointment.starts_at
        assert seen[0].status == "confirmed" and seen[0].organization_id == member.organization_id
        moved = appointment.starts_at + timedelta(minutes=60)
        with tenant(member):
            reschedule_appointment(
                appointment_id=appointment.id,
                starts_at=moved,
                idempotency_key="move-1",
                principal_ref=str(member.user_id),
            )
        assert seen[1].change == "rescheduled"
        assert seen[1].previous_starts_at == appointment.starts_at and seen[1].starts_at == moved
        assert seen[1].previous_status == seen[1].status == "confirmed"
        with tenant(member):
            complete_appointment(
                appointment_id=appointment.id, idempotency_key="done-1", principal_ref="t"
            )
        assert seen[2].change == "completed"
        assert seen[2].previous_status == "confirmed" and seen[2].status == "completed"


def test_a_canceled_appointment_reaches_a_registered_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Its own test: `create` books the same guest in every organization, and the
    # test database bypasses RLS, so two tenants in one test share a customer.
    _no_delivery(monkeypatch)
    member = membership("booking-observer-cancel")
    configured = catalog(member)
    with watching() as seen:
        appointment = create(member, configured).appointment
        with tenant(member):
            cancel_appointment(
                appointment_id=appointment.id,
                idempotency_key="cancel-1",
                principal_ref=str(member.user_id),
            )
        assert [event.change for event in seen] == ["created", "canceled"]
        assert seen[1].previous_status == "confirmed" and seen[1].status == "canceled"
        assert seen[1].previous_starts_at == seen[1].starts_at == appointment.starts_at


def test_an_observer_that_raises_does_not_break_the_reschedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-observer-broken")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    register_appointment_observer("broken", _explode)
    try:
        with watching() as seen, tenant(member):
            moved = appointment.starts_at + timedelta(minutes=60)
            value = reschedule_appointment(
                appointment_id=appointment.id,
                starts_at=moved,
                idempotency_key="move-1",
                principal_ref=str(member.user_id),
            )
            assert value.starts_at == moved
    finally:
        _observers.pop("broken", None)
    appointment.refresh_from_db()
    assert appointment.starts_at == moved
    # The healthy observer still ran, after the broken one.
    assert [event.change for event in seen] == ["rescheduled"]


def _explode(change: AppointmentChange) -> None:
    raise RuntimeError("obserwator padł")


def test_the_customers_own_link_notifies_observers_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("booking-observer-self-service")
    configured = catalog(member)
    created = create(member, configured)
    moved = created.appointment.starts_at + timedelta(minutes=60)
    with watching() as seen:
        response = APIClient().post(
            f"/api/v1/booking/self-service/{created.token}/reschedule/",
            {"starts_at": moved.isoformat()},
            format="json",
            HTTP_IDEMPOTENCY_KEY="self-move-1",
        )
    assert response.status_code == 200
    assert [event.change for event in seen] == ["rescheduled"]
    assert seen[0].starts_at == moved
