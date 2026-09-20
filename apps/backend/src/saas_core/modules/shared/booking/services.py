from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.utils import timezone, translation
from django.utils.formats import date_format
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
)
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.notifications.security import decrypt_secret, encrypt_secret
from saas_core.modules.shared.notifications.services import queue_email

from .availability import available_slots
from .models import (
    Appointment,
    AppointmentResourceAllocation,
    AppointmentStaffAllocation,
    AppointmentStatus,
    AppointmentStatusHistory,
    AvailabilityRule,
    BookingMutation,
    Customer,
    Location,
    PublicBookingRoute,
    ReminderRoute,
    Resource,
    SelfServiceRoute,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffMember,
    TimeOff,
)
from .observers import (
    CANCELED,
    COMPLETED,
    CREATED,
    RESCHEDULED,
    AppointmentChange,
    notify_appointment_change,
)
from .security import PUBLIC_BOOKING_ROLE, issue_self_service_token

BOOKING_READ = "booking.appointment.read"
BOOKING_MANAGE = "booking.appointment.manage"
BOOKING_ENABLED = "booking.enabled"


#: SQLSTATE of a deadlock. Two bookings racing for one slot insert their
#: allocations at the same moment, and each exclusion check then waits for the
#: other's uncommitted row; PostgreSQL breaks the cycle by aborting one of them.
#: For that one it is the same outcome as the exclusion violation it would have
#: hit a millisecond later, so it must reach the caller as a slot conflict, not
#: as a 500.
_DEADLOCK_DETECTED = "40P01"


def _lost_slot_race(error: DatabaseError) -> bool:
    return isinstance(error, IntegrityError) or (
        getattr(error.__cause__, "sqlstate", None) == _DEADLOCK_DETECTED
    )


class AppointmentNotChangeable(APIException):
    status_code = 409
    default_detail = "Tej wizyty nie można już zmienić."
    default_code = "appointment_not_changeable"


class SlotUnavailable(APIException):
    status_code = 409
    default_detail = "Wybrany termin nie jest już dostępny."
    default_code = "slot_unavailable"


class BookingIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inne żądanie."
    default_code = "booking_idempotency_conflict"


@dataclass(frozen=True, slots=True)
class CreatedAppointment:
    appointment: Appointment
    token: str | None
    created: bool


def list_catalog() -> dict[str, list[Any]]:
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED)
    org = context.organization_id
    return {
        "locations": list(Location.all_objects.filter(organization_id=org)),
        "staff": list(StaffMember.all_objects.filter(organization_id=org)),
        "services": list(Service.all_objects.filter(organization_id=org)),
        "resources": list(Resource.all_objects.filter(organization_id=org)),
    }


def _assert_appointment_kind_available(organization: Organization, kind: str) -> None:
    """A service may sell a kind of visit only a module of the organization's
    type provides (ADR-050): a farm cannot sell a trimming company's visit."""
    if not kind:
        return
    organization_type = settings.ORGANIZATION_TYPES.get(organization.organization_type)
    allowed = organization_type.modules if organization_type is not None else frozenset()
    owners = [
        module_id
        for module_id, descriptor in settings.MODULE_CATALOG.items()
        if kind in (descriptor.appointment_kinds or {})
    ]
    if kind not in settings.APPOINTMENT_KINDS or not any(owner in allowed for owner in owners):
        raise ValidationError({"appointment_kind": "Ten typ wizyty nie jest dostępny."})


@transaction.atomic
def create_catalog_item(*, kind: str, data: dict[str, Any]) -> Any:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    if kind == "location":
        item: Any = Location.all_objects.create(organization=organization, **data)
    elif kind == "staff":
        _assert_member_of(organization, data.get("membership_id"))
        try:
            with transaction.atomic():
                item = StaffMember.all_objects.create(organization=organization, **data)
        except IntegrityError as error:
            raise ValidationError({
                "membership_id": "Ten członek zespołu ma już swój wpis w kalendarzu."
            }) from error
    elif kind == "service":
        _assert_appointment_kind_available(organization, data.get("appointment_kind", ""))
        item = Service.all_objects.create(organization=organization, **data)
    elif kind == "resource":
        item = Resource.all_objects.create(organization=organization, **data)
    else:
        raise ValidationError("Nieznany typ katalogu.")
    PublicBookingRoute.objects.get_or_create(
        public_slug=organization.slug, defaults={"organization_id": organization.id}
    )
    record_audit(
        organization=organization,
        action="booking.catalog.changed",
        actor=User.objects.get(pk=context.actor_id),
        target_type=kind,
        target_id=item.id,
    )
    return item


def _assert_member_of(organization: Organization, membership_id: UUID | None) -> None:
    """A calendar entry may stand for an active member of this organization only.

    Read under the tenant, so another organization's membership is simply not
    found; the database guard on `booking_staffmember` is the second line.
    """
    if membership_id is None:
        return
    if not Membership.objects.filter(
        pk=membership_id, organization=organization, status=MembershipStatus.ACTIVE
    ).exists():
        raise ValidationError({"membership_id": "Nie ma takiego aktywnego członka zespołu."})


@transaction.atomic
def update_staff(*, staff_id: UUID, data: dict[str, Any]) -> StaffMember:
    """Renames, (de)activates or links a calendar entry to a team member."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    staff = (
        StaffMember.all_objects.select_for_update()
        .filter(organization=organization, pk=staff_id)
        .first()
    )
    if staff is None:
        raise NotFound("Nie ma takiego pracownika kalendarza.")
    if "membership_id" in data:
        _assert_member_of(organization, data["membership_id"])
    for field, value in data.items():
        setattr(staff, field, value)
    try:
        with transaction.atomic():
            staff.save()
    except IntegrityError as error:
        raise ValidationError({
            "membership_id": "Ten członek zespołu ma już swój wpis w kalendarzu."
        }) from error
    record_audit(
        organization=organization,
        action="booking.catalog.changed",
        actor=User.objects.get(pk=context.actor_id),
        target_type="staff",
        target_id=staff.id,
    )
    return staff


@transaction.atomic
def configure_schedule(*, kind: str, data: dict[str, Any]) -> Any:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    item: Any
    if kind == "availability":
        item = AvailabilityRule.all_objects.create(organization=organization, **data)
    elif kind == "time_off":
        item = TimeOff.all_objects.create(organization=organization, **data)
    elif kind == "service_staff":
        item = ServiceStaff.all_objects.create(organization=organization, **data)
    elif kind == "service_location":
        item = ServiceLocation.all_objects.create(organization=organization, **data)
    elif kind == "service_resource":
        item = ServiceResource.all_objects.create(organization=organization, **data)
    else:
        raise ValidationError("Nieznany typ grafiku.")
    record_audit(
        organization=organization,
        action="booking.schedule.changed",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type=kind,
        target_id=item.id,
    )
    return item


def list_appointments(
    *,
    starts_from: datetime | None = None,
    starts_until: datetime | None = None,
    appointment_kinds: frozenset[str] | set[str] | None = None,
    mine: bool = False,
) -> list[Appointment]:
    """`mine`: only the calendar entries linked to the caller's membership;
    `appointment_kinds`: only services of these kinds (a vertical's own visits);
    `starts_until` is exclusive, so one day is `[midnight, next midnight)`."""
    # A read: it keeps working when the plan has lapsed to read-only.
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    query = Appointment.all_objects.filter(organization_id=context.organization_id)
    if starts_from:
        query = query.filter(starts_at__gte=starts_from)
    if starts_until:
        query = query.filter(starts_at__lt=starts_until)
    if appointment_kinds is not None:
        query = query.filter(service__appointment_kind__in=appointment_kinds)
    if mine:
        query = query.filter(staff__membership_id=context.membership_id)
    return list(query.select_related("customer", "service", "staff", "location", "resource")[:500])


@transaction.atomic
def create_appointment(
    *,
    service_id: UUID,
    staff_id: UUID,
    location_id: UUID,
    resource_id: UUID | None,
    starts_at: datetime,
    customer_data: dict[str, str],
    idempotency_key: str,
    principal_ref: str,
    walk_in_minutes: int | None = None,
) -> CreatedAppointment:
    """Books a free slot, or — with `walk_in_minutes` — records work already under way.

    A walk-in is the same appointment, entered from the other end: somebody is
    standing at the customer already, so the calendar's job is to record that
    the time is gone, not to decide whether it may be given away. The schedule
    is therefore not consulted and the caller states how long to block, because
    the service's nominal duration says nothing about a visit nobody planned.

    What a walk-in still does: takes the staff and resource allocations, so the
    window shows busy and the next search cannot resell it. What it skips: the
    reminder (the visit is happening now) and the confirmation mail (the
    customer is watching the person who would send it).
    """
    context = require_tenant_context()
    request_hash = _hash({
        "service_id": str(service_id),
        "staff_id": str(staff_id),
        "location_id": str(location_id),
        "resource_id": str(resource_id),
        "starts_at": starts_at.isoformat(),
        "customer": customer_data,
        "walk_in_minutes": walk_in_minutes,
    })
    existing = (
        BookingMutation.all_objects.filter(
            organization_id=context.organization_id,
            action="create",
            principal_ref=principal_ref,
            idempotency_key=idempotency_key,
        )
        .select_related("appointment")
        .first()
    )
    if existing:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return CreatedAppointment(
            existing.appointment,
            decrypt_secret(existing.appointment.self_service_token_ciphertext),
            False,
        )
    service = Service.all_objects.filter(pk=service_id, active=True).first()
    staff = StaffMember.all_objects.filter(pk=staff_id, active=True).first()
    location = Location.all_objects.filter(pk=location_id, active=True).first()
    resource = (
        Resource.all_objects.filter(pk=resource_id, active=True).first() if resource_id else None
    )
    if not service or not staff or not location:
        raise NotFound("Konfiguracja rezerwacji nie istnieje.")
    if (
        not ServiceStaff.all_objects.filter(service=service, staff=staff).exists()
        or not ServiceLocation.all_objects.filter(service=service, location=location).exists()
    ):
        raise SlotUnavailable
    required = ServiceResource.all_objects.filter(service=service, required=True).values_list(
        "resource_id", flat=True
    )
    if required and (resource is None or resource.id not in required):
        raise SlotUnavailable
    organization = Organization.objects.get(pk=context.organization_id)
    if walk_in_minutes is None:
        local_date = starts_at.astimezone(ZoneInfo(organization.timezone)).date()
        slots = available_slots(
            service_id=service.id,
            location_id=location.id,
            from_date=local_date,
            to_date=local_date,
        )
        if not any(
            slot.starts_at == starts_at
            and slot.staff_id == staff.id
            and slot.resource_id == (resource.id if resource else None)
            for slot in slots
        ):
            raise SlotUnavailable
    elif walk_in_minutes <= 0:
        raise ValidationError({"walk_in_minutes": "Podaj, na jak długo zająć okno."})
    email = customer_data.get("email", "").strip().lower()
    phone = customer_data.get("phone", "").strip()
    if not email and not phone:
        raise ValidationError("Wymagany jest e-mail albo telefon.")
    contact_hash = hashlib.sha256(f"{email}|{phone}".encode()).hexdigest()
    customer = Customer.all_objects.filter(
        contact_hash=contact_hash, anonymized_at__isnull=True
    ).first()
    if customer is None:
        customer = Customer.all_objects.create(
            organization=organization,
            display_name=customer_data["display_name"].strip(),
            email=email,
            phone=phone,
            contact_hash=contact_hash,
            locale=customer_data.get("locale", organization.default_locale),
        )
    ends_at = starts_at + timedelta(minutes=walk_in_minutes or service.duration_minutes)
    # A walk-in takes no buffers: they exist to protect a plan, and there is none.
    before = 0 if walk_in_minutes else service.buffer_before_minutes
    after = 0 if walk_in_minutes else service.buffer_after_minutes
    occupied_from = starts_at - timedelta(minutes=before)
    occupied_until = ends_at + timedelta(minutes=after)
    token, digest = issue_self_service_token()
    expires = timezone.now() + timedelta(days=settings.BOOKING_SELF_SERVICE_TTL_DAYS)
    appointment = Appointment.all_objects.create(
        organization=organization,
        customer=customer,
        service=service,
        staff=staff,
        location=location,
        resource=resource,
        starts_at=starts_at,
        ends_at=ends_at,
        occupied_from=occupied_from,
        occupied_until=occupied_until,
        timezone=organization.timezone,
        service_name=service.name,
        self_service_token_ciphertext=encrypt_secret(token),
        self_service_expires_at=expires,
        # Nothing to remind anybody about when the visit is already happening.
        reminder_due_at=None
        if walk_in_minutes
        else max(
            timezone.now(), starts_at - timedelta(hours=settings.BOOKING_REMINDER_LEAD_HOURS)
        ),
    )
    try:
        AppointmentStaffAllocation.all_objects.create(
            organization=organization,
            appointment=appointment,
            staff=staff,
            occupied_range=(occupied_from, occupied_until),
        )
        if resource:
            AppointmentResourceAllocation.all_objects.create(
                organization=organization,
                appointment=appointment,
                resource=resource,
                occupied_range=(occupied_from, occupied_until),
            )
    except (IntegrityError, OperationalError) as error:
        if not _lost_slot_race(error):
            raise
        raise SlotUnavailable from error
    AppointmentStatusHistory.all_objects.create(
        organization=organization,
        appointment=appointment,
        to_status=AppointmentStatus.CONFIRMED,
        actor_kind=context.principal_kind,
    )
    BookingMutation.all_objects.create(
        organization=organization,
        appointment=appointment,
        action="create",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    SelfServiceRoute.objects.create(
        token_digest=digest,
        organization_id=organization.id,
        appointment_id=appointment.id,
        expires_at=expires,
    )
    if walk_in_minutes is None:
        signed = issue_tenant_task_contract(causation_id=f"booking:{appointment.id}")
        reminder_due_at = appointment.reminder_due_at
        assert reminder_due_at is not None
        ReminderRoute.objects.create(
            appointment_id=appointment.id,
            organization_id=organization.id,
            signed_tenant_context=encrypt_secret(signed),
            due_at=reminder_due_at,
        )
    if email and walk_in_minutes is None:
        queue_email(
            recipient_email=email,
            template_key="booking.confirmation",
            template_version=1,
            locale=customer.locale,
            template_context={
                "organization_name": organization.name,
                "starts_at": local_time(starts_at, appointment.timezone, customer.locale),
            },
            idempotency_key=f"booking-confirm:{appointment.id}",
            causation_id=f"booking:{appointment.id}",
        )
    record_audit(
        organization=organization,
        action="booking.appointment.created",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        metadata={"starts_at": starts_at.isoformat()},
    )
    _announce(
        AppointmentChange(
            change=CREATED,
            organization_id=organization.id,
            appointment_id=appointment.id,
            previous_starts_at=None,
            starts_at=starts_at,
            previous_status="",
            status=appointment.status,
            timezone=appointment.timezone,
        )
    )
    return CreatedAppointment(appointment, token, True)


@transaction.atomic
def reschedule_appointment(
    *, appointment_id: UUID, starts_at: datetime, idempotency_key: str, principal_ref: str
) -> Appointment:
    context = require_tenant_context()
    appointment = Appointment.all_objects.select_for_update().filter(pk=appointment_id).first()
    if not appointment or appointment.status != AppointmentStatus.CONFIRMED:
        raise NotFound("Aktywna rezerwacja nie istnieje.")
    _refuse_customer_after_start(context.role_key, appointment)
    request_hash = _hash({"starts_at": starts_at.isoformat()})
    existing = BookingMutation.all_objects.filter(
        action="reschedule", principal_ref=principal_ref, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return appointment
    AppointmentStaffAllocation.all_objects.filter(appointment=appointment, active=True).update(
        active=False
    )
    AppointmentResourceAllocation.all_objects.filter(appointment=appointment, active=True).update(
        active=False
    )
    local_date = starts_at.astimezone(ZoneInfo(appointment.timezone)).date()
    slots = available_slots(
        service_id=appointment.service_id,
        location_id=appointment.location_id,
        from_date=local_date,
        to_date=local_date,
    )
    if not any(
        slot.starts_at == starts_at
        and slot.staff_id == appointment.staff_id
        and slot.resource_id == appointment.resource_id
        for slot in slots
    ):
        raise SlotUnavailable
    service = appointment.service
    ends = starts_at + timedelta(minutes=service.duration_minutes)
    occupied_from = starts_at - timedelta(minutes=service.buffer_before_minutes)
    occupied_until = ends + timedelta(minutes=service.buffer_after_minutes)
    try:
        AppointmentStaffAllocation.all_objects.create(
            organization_id=context.organization_id,
            appointment=appointment,
            staff=appointment.staff,
            occupied_range=(occupied_from, occupied_until),
        )
        if appointment.resource_id:
            resource = appointment.resource
            assert resource is not None
            AppointmentResourceAllocation.all_objects.create(
                organization_id=context.organization_id,
                appointment=appointment,
                resource=resource,
                occupied_range=(occupied_from, occupied_until),
            )
    except (IntegrityError, OperationalError) as error:
        if not _lost_slot_race(error):
            raise
        raise SlotUnavailable from error
    previous = appointment.starts_at
    appointment.starts_at, appointment.ends_at = starts_at, ends
    appointment.occupied_from, appointment.occupied_until = occupied_from, occupied_until
    appointment.save(
        update_fields=["starts_at", "ends_at", "occupied_from", "occupied_until", "updated_at"]
    )
    AppointmentStatusHistory.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        from_status=appointment.status,
        to_status=appointment.status,
        reason=f"rescheduled:{previous.isoformat()}",
        actor_kind=context.principal_kind,
    )
    mutation = BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="reschedule",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    organization = Organization.objects.get(pk=context.organization_id)
    customer = appointment.customer
    if customer.email:
        queue_email(
            recipient_email=customer.email,
            template_key="booking.rescheduled",
            template_version=1,
            locale=customer.locale,
            template_context={
                "organization_name": organization.name,
                "previous_starts_at": local_time(previous, appointment.timezone, customer.locale),
                "starts_at": local_time(starts_at, appointment.timezone, customer.locale),
            },
            # The mutation row is this move's identity. A retry of the same
            # request returned above, so a row here always means a move that
            # really happened — while `appointment.id` alone would swallow every
            # move after the first, and the old time repeats as soon as a visit
            # is moved back to where it was.
            idempotency_key=f"booking-reschedule:{mutation.id}",
            causation_id=f"booking:{appointment.id}",
        )
    record_audit(
        organization=organization,
        action="booking.appointment.rescheduled",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        metadata={"starts_at": starts_at.isoformat()},
    )
    _announce(
        AppointmentChange(
            change=RESCHEDULED,
            organization_id=organization.id,
            appointment_id=appointment.id,
            previous_starts_at=previous,
            starts_at=starts_at,
            previous_status=appointment.status,
            status=appointment.status,
            timezone=appointment.timezone,
        )
    )
    return appointment


@transaction.atomic
def cancel_appointment(
    *, appointment_id: UUID, idempotency_key: str, principal_ref: str
) -> Appointment:
    context = require_tenant_context()
    appointment = Appointment.all_objects.select_for_update().filter(pk=appointment_id).first()
    if not appointment:
        raise NotFound("Rezerwacja nie istnieje.")
    request_hash = _hash({"cancel": True})
    existing = BookingMutation.all_objects.filter(
        action="cancel", principal_ref=principal_ref, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return appointment
    if appointment.status in {AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}:
        # A visit that took place is not called off afterwards.
        raise AppointmentNotChangeable
    _refuse_customer_after_start(context.role_key, appointment)
    if appointment.status != AppointmentStatus.CANCELED:
        old = appointment.status
        appointment.status = AppointmentStatus.CANCELED
        appointment.save(update_fields=["status", "updated_at"])
        AppointmentStaffAllocation.all_objects.filter(appointment=appointment).update(active=False)
        AppointmentResourceAllocation.all_objects.filter(appointment=appointment).update(
            active=False
        )
        SelfServiceRoute.objects.filter(appointment_id=appointment.id).update(
            revoked_at=timezone.now()
        )
        AppointmentStatusHistory.all_objects.create(
            organization_id=context.organization_id,
            appointment=appointment,
            from_status=old,
            to_status=AppointmentStatus.CANCELED,
            actor_kind=context.principal_kind,
        )
        customer = appointment.customer
        if customer.email:
            queue_email(
                recipient_email=customer.email,
                template_key="booking.canceled",
                template_version=1,
                locale=customer.locale,
                template_context={
                    "organization_name": Organization.objects.get(
                        pk=context.organization_id
                    ).name,
                    "starts_at": local_time(
                        appointment.starts_at, appointment.timezone, customer.locale
                    ),
                },
                # A booking is called off once, so the appointment identifies the
                # mail. This block runs on the real transition only; a second
                # cancellation under another idempotency key finds the booking
                # already canceled and never gets here.
                idempotency_key=f"booking-cancel:{appointment.id}",
                causation_id=f"booking:{appointment.id}",
            )
        _announce(
            AppointmentChange(
                change=CANCELED,
                organization_id=context.organization_id,
                appointment_id=appointment.id,
                previous_starts_at=appointment.starts_at,
                starts_at=appointment.starts_at,
                previous_status=old,
                status=AppointmentStatus.CANCELED,
                timezone=appointment.timezone,
            )
        )
    BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="cancel",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.appointment.canceled",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
    )
    return appointment


def _refuse_customer_after_start(role_key: str, appointment: Appointment) -> None:
    """A customer's self-service link moves or calls off a visit only before it
    starts; once the provider is on site, changes go through the provider."""
    if role_key == PUBLIC_BOOKING_ROLE and appointment.starts_at <= timezone.now():
        raise AppointmentNotChangeable


def staff_for_membership(organization_id: UUID, membership_id: UUID) -> StaffMember | None:
    """The calendar entry of a team member, if their account has one."""
    return StaffMember.all_objects.filter(
        organization_id=organization_id, membership_id=membership_id
    ).first()


def appointment_for_tenant(organization_id: UUID, appointment_id: UUID) -> Appointment | None:
    """The appointment if it belongs to this organization; None otherwise."""
    return (
        Appointment.all_objects.filter(organization_id=organization_id, pk=appointment_id)
        .select_related("customer", "service", "staff", "location", "resource")
        .first()
    )


@transaction.atomic
def complete_appointment(
    *, appointment_id: UUID, idempotency_key: str, principal_ref: str
) -> Appointment:
    """Marks a confirmed appointment as done; the customer's self-service link
    stops working, because there is nothing left to move or call off."""
    context = require_tenant_context()
    appointment = Appointment.all_objects.select_for_update().filter(pk=appointment_id).first()
    if not appointment:
        raise NotFound("Rezerwacja nie istnieje.")
    request_hash = _hash({"complete": True})
    existing = BookingMutation.all_objects.filter(
        action="complete", principal_ref=principal_ref, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return appointment
    if appointment.status != AppointmentStatus.COMPLETED:
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise AppointmentNotChangeable
        appointment.status = AppointmentStatus.COMPLETED
        appointment.save(update_fields=["status", "updated_at"])
        SelfServiceRoute.objects.filter(appointment_id=appointment.id).update(
            revoked_at=timezone.now()
        )
        AppointmentStatusHistory.all_objects.create(
            organization_id=context.organization_id,
            appointment=appointment,
            from_status=AppointmentStatus.CONFIRMED,
            to_status=AppointmentStatus.COMPLETED,
            actor_kind=context.principal_kind,
        )
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action="booking.appointment.completed",
            actor=User.objects.filter(pk=context.actor_id).first(),
            target_type="appointment",
            target_id=appointment.id,
        )
        _announce(
            AppointmentChange(
                change=COMPLETED,
                organization_id=context.organization_id,
                appointment_id=appointment.id,
                previous_starts_at=appointment.starts_at,
                starts_at=appointment.starts_at,
                previous_status=AppointmentStatus.CONFIRMED,
                status=AppointmentStatus.COMPLETED,
                timezone=appointment.timezone,
            )
        )
    BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="complete",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return appointment


@transaction.atomic
def anonymize_customer(customer_id: UUID) -> Customer:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    customer = Customer.all_objects.select_for_update().filter(pk=customer_id).first()
    if not customer:
        raise NotFound("Klient nie istnieje.")
    customer.display_name = "Zanonimizowany klient"
    customer.email = ""
    customer.phone = ""
    customer.contact_hash = hashlib.sha256(f"anon:{customer.id}".encode()).hexdigest()
    customer.anonymized_at = timezone.now()
    customer.save()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.customer.anonymized",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="customer",
        target_id=customer.id,
    )
    return customer


def local_time(value: datetime, zone: str, locale: str) -> str:
    """The wall clock a customer reads, not the instant a database stores.

    An email template is `str.format_map` over strings — it cannot format a
    datetime, so an ISO stamp handed to it reaches the customer as an ISO stamp.
    The appointment carries its own `timezone` snapshot; Django's own
    localisation turns it into a date the recipient's locale writes normally.

    `Customer.locale` is pl or en by field choices, the same two the templates
    carry; an unknown one would fail in `render_template` before reaching here.
    """
    with translation.override(locale):
        return date_format(value.astimezone(ZoneInfo(zone)), "DATETIME_FORMAT")


def _announce(change: AppointmentChange) -> None:
    """Observers run after commit, never inside the mutation's transaction.

    Two reasons, both hard. An observer writes into another tenant through the
    registry door, which means another `SET LOCAL organization_id` — doing that
    inside this transaction would leave the wrong tenant set for everything
    after it. And a failure has to be swallowed, which is impossible inside an
    atomic block: Django marks the block broken on the first database error, so
    a swallowed one would turn the next query into a TransactionManagementError
    and take the booking down with it.
    """
    transaction.on_commit(lambda: notify_appointment_change(change))


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
