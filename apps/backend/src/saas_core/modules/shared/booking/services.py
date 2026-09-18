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
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
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
from .security import issue_self_service_token

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


@transaction.atomic
def create_catalog_item(*, kind: str, data: dict[str, Any]) -> Any:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    if kind == "location":
        item: Any = Location.all_objects.create(organization=organization, **data)
    elif kind == "staff":
        item = StaffMember.all_objects.create(organization=organization, **data)
    elif kind == "service":
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


def list_appointments(*, starts_from: datetime | None = None) -> list[Appointment]:
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED)
    query = Appointment.all_objects.filter(organization_id=context.organization_id)
    if starts_from:
        query = query.filter(starts_at__gte=starts_from)
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
) -> CreatedAppointment:
    context = require_tenant_context()
    request_hash = _hash({
        "service_id": str(service_id),
        "staff_id": str(staff_id),
        "location_id": str(location_id),
        "resource_id": str(resource_id),
        "starts_at": starts_at.isoformat(),
        "customer": customer_data,
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
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    occupied_from = starts_at - timedelta(minutes=service.buffer_before_minutes)
    occupied_until = ends_at + timedelta(minutes=service.buffer_after_minutes)
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
        reminder_due_at=max(
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
    signed = issue_tenant_task_contract(causation_id=f"booking:{appointment.id}")
    reminder_due_at = appointment.reminder_due_at
    assert reminder_due_at is not None
    ReminderRoute.objects.create(
        appointment_id=appointment.id,
        organization_id=organization.id,
        signed_tenant_context=encrypt_secret(signed),
        due_at=reminder_due_at,
    )
    if email:
        queue_email(
            recipient_email=email,
            template_key="booking.confirmation",
            template_version=1,
            locale=customer.locale,
            template_context={
                "organization_name": organization.name,
                "starts_at": starts_at.isoformat(),
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
    return CreatedAppointment(appointment, token, True)


@transaction.atomic
def reschedule_appointment(
    *, appointment_id: UUID, starts_at: datetime, idempotency_key: str, principal_ref: str
) -> Appointment:
    context = require_tenant_context()
    appointment = Appointment.all_objects.select_for_update().filter(pk=appointment_id).first()
    if not appointment or appointment.status != AppointmentStatus.CONFIRMED:
        raise NotFound("Aktywna rezerwacja nie istnieje.")
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
    BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="reschedule",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.appointment.rescheduled",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        metadata={"starts_at": starts_at.isoformat()},
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


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
