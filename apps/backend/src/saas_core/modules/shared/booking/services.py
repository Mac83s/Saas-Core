from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone, translation
from django.utils.formats import date_format
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.locales import clamp_content_locale
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
)
from saas_core.modules.core.organizations.tasks import issue_service_task_contract
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.notifications.security import decrypt_secret, encrypt_secret
from saas_core.modules.shared.notifications.services import queue_email

from . import materials as stock
from . import notify
from .availability import free_at, validate_start
from .crew import PersonUnavailable, allocate, crew_of, least_loaded, lost_slot_race, set_crew
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
    QueueReason,
    ReminderRoute,
    Resource,
    SelfServiceRoute,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffMember,
    StaffTeam,
    StaffTeamMember,
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
from .security import (
    PUBLIC_BOOKING_ROLE,
    REMINDER_PERMISSIONS,
    REMINDER_ROLE,
    issue_self_service_token,
)

BOOKING_READ = "booking.appointment.read"
BOOKING_MANAGE = "booking.appointment.manage"
BOOKING_ENABLED = "booking.enabled"


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


#: What the history keeps of a person's entry; name and phone only as "changed".
_STAFF_FIELDS = ("display_name", "phone", "active")


@transaction.atomic
def update_staff(*, staff_id: UUID, data: dict[str, Any]) -> StaffMember:
    """Renames a calendar entry, sets its phone, (de)activates it or links it to
    a team member. Management changes any of it; a person their own phone."""
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    staff = (
        StaffMember.all_objects.select_for_update()
        .filter(organization=organization, pk=staff_id)
        .first()
    )
    if staff is None:
        raise NotFound("Nie ma takiego pracownika kalendarza.")
    own = staff.membership_id is not None and staff.membership_id == context.membership_id
    if not context.has_permission(BOOKING_MANAGE) and not (own and set(data) <= {"phone"}):
        raise OrganizationPermissionDenied
    if "membership_id" in data:
        _assert_member_of(organization, data["membership_id"])
    before = audit_snapshot(staff, _STAFF_FIELDS)
    linked = staff.membership_id
    for field, value in data.items():
        setattr(staff, field, value)
    try:
        with transaction.atomic():
            staff.save()
    except IntegrityError as error:
        raise ValidationError({
            "membership_id": "Ten członek zespołu ma już swój wpis w kalendarzu."
        }) from error
    actor = User.objects.filter(pk=context.actor_id).first()
    if staff.membership_id != linked:
        record_audit(
            organization=organization,
            action=OrganizationAuditAction.BOOKING_STAFF_LINKED,
            actor=actor,
            target_type="staff",
            target_id=staff.id,
            metadata={"linked": staff.membership_id is not None},
        )
    changes = field_changes(
        before, audit_snapshot(staff, _STAFF_FIELDS), private=("display_name", "phone")
    )
    if changes:
        record_audit(
            organization=organization,
            action=OrganizationAuditAction.BOOKING_STAFF_UPDATED,
            actor=actor,
            target_type="staff",
            target_id=staff.id,
            metadata={"changes": changes},
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
    staff_id: UUID | None = None,
    mine: bool = False,
    limit: int = 500,
) -> list[Appointment]:
    """`mine`: only the visits the caller's calendar entry is on;
    `staff_id`: only the visits this person is on — leading or helping;
    `appointment_kinds`: only services of these kinds (a vertical's own visits);
    `starts_until` is exclusive, so one day is `[midnight, next midnight)`;
    `limit`: at most this many, earliest first (1 answers "is there any")."""
    # A read: it keeps working when the plan has lapsed to read-only.
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    query = Appointment.all_objects.filter(organization_id=context.organization_id)
    if starts_from:
        query = query.filter(starts_at__gte=starts_from)
    if starts_until:
        query = query.filter(starts_at__lt=starts_until)
    if appointment_kinds is not None:
        query = query.filter(service__appointment_kind__in=appointment_kinds)
    if staff_id:
        query = query.filter(_on_visit(Q(staff_allocations__staff_id=staff_id), staff_id=staff_id))
    if mine:
        query = query.filter(
            _on_visit(
                Q(staff_allocations__staff__membership_id=context.membership_id),
                membership_id=context.membership_id,
            )
        )
    limit = max(1, min(limit, 500))
    return list(with_crew(query.distinct())[:limit])


def visible_contacts(ids: Sequence[UUID]) -> set[UUID]:
    """The visits whose customer phone and e-mail the caller sees (owner's
    decision 15.2b, ADR-067): whoever plans visits sees them all, everybody
    else only those they are on — the people going there phone the customer,
    the rest of the staff has no business with the number."""
    context = require_tenant_context()
    if not ids:
        return set()
    if context.has_permission(BOOKING_MANAGE):
        return set(ids)
    return set(
        Appointment.all_objects.filter(organization_id=context.organization_id, pk__in=ids)
        .filter(
            _on_visit(
                Q(staff_allocations__staff__membership_id=context.membership_id),
                membership_id=context.membership_id,
            )
        )
        .values_list("id", flat=True)
        .distinct()
    )


def _on_visit(
    allocated: Q, *, staff_id: UUID | None = None, membership_id: UUID | None = None
) -> Q:
    """On the visit: its lead, somebody with its time blocked, or — once it is
    called off and nobody's time is — somebody who had it. A lead taken off a
    visit that now waits for somebody else is not on it: only their name is."""
    lead = Q(staff_id=staff_id) if staff_id else Q(staff__membership_id=membership_id)
    return (
        (lead & Q(needs_assignment=False))
        | (allocated & Q(staff_allocations__active=True))
        | (allocated & Q(status=AppointmentStatus.CANCELED))
    )


def with_crew(query: QuerySet[Appointment]) -> QuerySet[Appointment]:
    """Everything a panel row of a visit reads, in a fixed number of queries."""
    return query.select_related(
        "customer", "service", "staff", "location", "resource", "requested_team"
    ).prefetch_related(
        Prefetch(
            "staff_allocations",
            queryset=AppointmentStaffAllocation.all_objects.select_related("staff").order_by("id"),
        )
    )


@transaction.atomic
def create_appointment(
    *,
    service_id: UUID,
    staff_id: UUID | None = None,
    staff_ids: Sequence[UUID] | None = None,
    team_id: UUID | None = None,
    requested_staff_id: UUID | None = None,
    location_id: UUID,
    resource_id: UUID | None = None,
    starts_at: datetime,
    customer_data: dict[str, str],
    idempotency_key: str,
    principal_ref: str,
    walk_in_minutes: int | None = None,
    materials: list[dict[str, Any]] | None = None,
    customer_notes: str = "",
    place_town: str = "",
    place_address: str = "",
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

    The people: `staff_ids` (the lead first) or `staff_id` name them;
    `requested_staff_id` is the person a customer chose on the public form;
    `team_id` limits the choice to a team. Without names the server picks as
    many of the least loaded free people as the service needs (ADR-058 §2–§4)
    — the browser never decides who gets the visit. Fewer named people than the
    service needs make a vacancy the office staffs from „Do przydzielenia”.

    `place_town` and `place_address`: „Miejsce wizyty” (ADR-066), where the
    visit takes place when that is not the company's location.
    """
    place_town, place_address = place_town.strip(), place_address.strip()
    context = require_tenant_context()
    named = list(
        dict.fromkeys(
            staff_ids
            or ([staff_id] if staff_id else [])
            or ([requested_staff_id] if requested_staff_id else [])
        )
    )
    request_hash = _hash({
        "service_id": str(service_id),
        # The request, not the pick: a retry of "anybody" finds its booking.
        "staff_id": str(named[0]) if len(named) == 1 else None,
        "location_id": str(location_id),
        "resource_id": str(resource_id),
        "starts_at": starts_at.isoformat(),
        "customer": customer_data,
        "walk_in_minutes": walk_in_minutes,
        **({"materials": materials} if materials is not None else {}),
        **({"staff_ids": [str(person) for person in named]} if len(named) > 1 else {}),
        **({"team_id": str(team_id)} if team_id else {}),
        **({"requested": True} if requested_staff_id else {}),
        **({"notes": customer_notes} if customer_notes else {}),
        **({"place": [place_town, place_address]} if place_town or place_address else {}),
    })
    with connection.cursor() as cursor:
        # One key at a time: a retry sent while the first request still runs
        # waits for it and finds its booking, instead of losing the first
        # person to it, booking the next one and failing on the key's index.
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"booking-create:{context.organization_id}:{principal_ref}:{idempotency_key}"],
        )
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
    people = {
        person.id: person for person in StaffMember.all_objects.filter(pk__in=named, active=True)
    }
    location = Location.all_objects.filter(pk=location_id, active=True).first()
    resource = (
        Resource.all_objects.filter(pk=resource_id, active=True).first() if resource_id else None
    )
    team = StaffTeam.all_objects.filter(pk=team_id).first() if team_id else None
    # A walk-in is entered by whoever is doing the work, so it always names them.
    if (
        not service
        or not location
        or len(people) != len(named)
        or (team_id and team is None)
        or (walk_in_minutes is not None and len(named) != 1)
    ):
        raise NotFound("Konfiguracja rezerwacji nie istnieje.")
    if (
        named
        and ServiceStaff.all_objects.filter(service=service, staff_id__in=named).count()
        != len(named)
    ) or not ServiceLocation.all_objects.filter(service=service, location=location).exists():
        raise SlotUnavailable
    required = list(
        ServiceResource.all_objects.filter(service=service, required=True).values_list(
            "resource_id", flat=True
        )
    )
    if walk_in_minutes and resource is None and len(required) == 1:
        # A walk-in is entered by whoever is doing the work, and the slot search
        # that normally names the resource was never run. With one possible
        # answer there is nothing to ask about — and the resource still has to
        # be taken, or the calendar would offer the only crush to somebody else.
        resource = Resource.all_objects.filter(pk=required[0], active=True).first()
    if required and (
        (resource is not None and resource.id not in required)
        # Nobody named: the pick below takes a required resource along, but
        # never instead of one the caller named and that is gone.
        or (resource is None and (named or resource_id))
    ):
        raise SlotUnavailable
    organization = Organization.objects.get(pk=context.organization_id)
    need = 1 if walk_in_minutes is not None else service.staff_count
    resources: list[UUID | None] = [resource.id if resource else None]
    candidates = list(named)
    chose = False
    if walk_in_minutes is None:
        if named:
            for person in named:
                if not validate_start(
                    service=service,
                    location=location,
                    starts_at=starts_at,
                    staff_id=person,
                    resource_id=resources[0],
                ):
                    raise SlotUnavailable
        else:
            eligible = (
                list(
                    StaffTeamMember.all_objects.filter(team=team).values_list("staff_id", flat=True)
                )
                if team
                else None
            )
            pairs = free_at(
                service=service,
                location=location,
                starts_at=starts_at,
                staff_ids=eligible,
                resource_ids=[resource.id] if resource else None,
            )
            free = list(dict.fromkeys(person for person, _ in pairs))
            if len(free) < need:
                raise SlotUnavailable
            candidates = least_loaded(organization, starts_at, free)
            if resource is None:
                resources = list(dict.fromkeys(item for _, item in pairs))
            # Worth a look by the office only when there was a choice to make.
            chose = len(free) > need
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
            locale=clamp_content_locale(
                str(customer_data.get("locale") or "").strip().lower() or None,
                organization=organization,
            ),
        )
    if materials is not None:
        # Hand-picked products: whoever types them must be allowed to take stock.
        if materials:
            stock.refuse_own(service.appointment_kind)
        if materials or stock.enabled():
            stock.authorize_change()
        lines = stock.normalize(organization.id, materials)
    elif stock.takes_materials(service.appointment_kind):
        lines = stock.normalize(organization.id, service.materials, strict=False)
    else:
        lines = []
    ends_at = starts_at + timedelta(minutes=walk_in_minutes or service.duration_minutes)
    # A walk-in takes no buffers: they exist to protect a plan, and there is none.
    before = 0 if walk_in_minutes else service.buffer_before_minutes
    after = 0 if walk_in_minutes else service.buffer_after_minutes
    occupied_from = starts_at - timedelta(minutes=before)
    occupied_until = ends_at + timedelta(minutes=after)
    token, digest = issue_self_service_token()
    expires = timezone.now() + timedelta(days=settings.BOOKING_SELF_SERVICE_TTL_DAYS)
    lookup = {
        person.id: person
        for person in StaffMember.all_objects.filter(pk__in=candidates, active=True)
    }
    # One savepoint for the visit; inside it, one per person and per resource.
    # Losing a person to a concurrent booking (the exclusion constraint, or a
    # deadlock over it) leaves the next one; a named person is not replaced.
    try:
        with transaction.atomic():
            appointment = Appointment.all_objects.create(
                organization=organization,
                customer=customer,
                service=service,
                staff_id=candidates[0],
                location=location,
                starts_at=starts_at,
                ends_at=ends_at,
                occupied_from=occupied_from,
                occupied_until=occupied_until,
                timezone=organization.timezone,
                service_name=service.name,
                materials=lines,
                self_service_token_ciphertext=encrypt_secret(token),
                self_service_expires_at=expires,
                staff_required=max(need, 1),
                requested_team=team,
                requested_staff_id=requested_staff_id,
                customer_notes=customer_notes.strip()[:500],
                place_town=place_town[:120],
                place_address=place_address[:240],
            )
            taken: list[UUID] = []
            for person_id in candidates:
                if len(taken) >= need and not named:
                    break
                try:
                    allocate(appointment, lookup[person_id])
                except PersonUnavailable:
                    if named:
                        raise
                    continue
                taken.append(person_id)
            if not taken or (not named and len(taken) < need):
                raise SlotUnavailable
            for resource_option in resources:
                if resource_option is None:
                    break
                try:
                    with transaction.atomic():
                        AppointmentResourceAllocation.all_objects.create(
                            organization=organization,
                            appointment=appointment,
                            resource_id=resource_option,
                            occupied_range=(occupied_from, occupied_until),
                        )
                except (IntegrityError, OperationalError) as error:
                    if not lost_slot_race(error):
                        raise
                    continue
                appointment.resource_id = resource_option
                break
            else:
                if resources and resources[0] is not None:
                    raise SlotUnavailable
    except PersonUnavailable as error:
        raise SlotUnavailable from error
    vacancy = len(taken) < appointment.staff_required
    auto = chose and not vacancy and context.principal_kind != "membership"
    appointment.staff_id = taken[0]
    appointment.needs_assignment = vacancy
    appointment.auto_assigned = auto
    appointment.crew_version = 1
    if vacancy or auto:
        appointment.queue_reason = QueueReason.PUBLIC if auto else QueueReason.SHORT
        appointment.queued_at = timezone.now()
    appointment.save(
        update_fields=[
            "staff",
            "resource",
            "needs_assignment",
            "auto_assigned",
            "crew_version",
            "queue_reason",
            "queued_at",
        ]
    )
    AppointmentStatusHistory.all_objects.create(
        organization=organization,
        appointment=appointment,
        to_status=AppointmentStatus.CONFIRMED,
        actor_kind=context.principal_kind,
    )
    stock.reserve(organization.id, appointment.id, lines)
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
        # Nothing to remind anybody about when the visit is already happening.
        _arm_reminder(appointment)
    if email and walk_in_minutes is None:
        queue_email(
            recipient_email=email,
            template_key="booking.confirmation",
            template_version=2,
            locale=customer.locale,
            template_context={
                "organization_name": organization.name,
                "starts_at": local_time(starts_at, appointment.timezone, customer.locale),
                "manage_url": notify.manage_url(token, customer.locale),
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
        metadata={
            "starts_at": starts_at.isoformat(),
            "staff": [str(person) for person in taken],
        },
    )
    notify.staff_assigned(appointment, taken)
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
    """Moves a visit with its people.

    From the panel the whole crew has to be free at the new time, or the move
    names who is not. A customer moving their own visit gets the times their
    choice allows; when they chose nobody, whoever cannot come is replaced by
    the least loaded free person and the office sees it in „Do przydzielenia”.
    """
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
    service = appointment.service
    crew = crew_of(appointment)
    customer_move = context.principal_kind != "membership"

    def free(person: UUID) -> bool:
        return validate_start(
            service=service,
            location=appointment.location,
            starts_at=starts_at,
            staff_id=person,
            resource_id=appointment.resource_id,
            ignore_appointment_id=appointment.id,
        )

    kept = [person for person in crew if free(person)]
    dropped = [person for person in crew if person not in kept]
    if dropped and not customer_move:
        names = StaffMember.all_objects.filter(pk__in=dropped).order_by("display_name")
        raise PersonUnavailable(", ".join(person.display_name for person in names))
    if appointment.requested_staff_id is not None and customer_move and dropped:
        # The customer chose this person; the move follows them or does not happen.
        raise SlotUnavailable
    AppointmentStaffAllocation.all_objects.filter(appointment=appointment, active=True).update(
        active=False
    )
    AppointmentResourceAllocation.all_objects.filter(appointment=appointment, active=True).update(
        active=False
    )
    ends = starts_at + timedelta(minutes=service.duration_minutes)
    occupied_from = starts_at - timedelta(minutes=service.buffer_before_minutes)
    occupied_until = ends + timedelta(minutes=service.buffer_after_minutes)
    previous = appointment.starts_at
    appointment.starts_at, appointment.ends_at = starts_at, ends
    appointment.occupied_from, appointment.occupied_until = occupied_from, occupied_until
    appointment.save(
        update_fields=["starts_at", "ends_at", "occupied_from", "occupied_until", "updated_at"]
    )
    try:
        for person in StaffMember.all_objects.filter(pk__in=kept):
            allocate(appointment, person)
        if appointment.resource_id:
            resource = appointment.resource
            assert resource is not None
            with transaction.atomic():
                AppointmentResourceAllocation.all_objects.create(
                    organization_id=context.organization_id,
                    appointment=appointment,
                    resource=resource,
                    occupied_range=(occupied_from, occupied_until),
                )
    except PersonUnavailable as error:
        raise SlotUnavailable from error
    except (IntegrityError, OperationalError) as error:
        if not lost_slot_race(error):
            raise
        raise SlotUnavailable from error
    mutation = BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="reschedule",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    # A visit nobody is on yet moves as it is from the panel; the office staffs
    # it. A customer's move fills it: they were offered times with people free.
    missing = appointment.staff_required - len(kept)
    if customer_move and missing > 0:
        eligible = (
            list(
                StaffTeamMember.all_objects.filter(
                    team_id=appointment.requested_team_id
                ).values_list("staff_id", flat=True)
            )
            if appointment.requested_team_id
            else None
        )
        pairs = free_at(
            service=service,
            location=appointment.location,
            starts_at=starts_at,
            staff_ids=eligible,
            resource_ids=[appointment.resource_id],
            ignore_appointment_id=appointment.id,
        )
        free_now = [person for person, _ in pairs if person not in kept]
        organization = Organization.objects.get(pk=context.organization_id)
        picked = least_loaded(organization, starts_at, free_now)[: max(missing, 0)]
        if len(picked) < missing:
            raise SlotUnavailable
        lead = appointment.staff_id if appointment.staff_id in kept else None
        set_crew(
            appointment,
            [*([lead] if lead else []), *[p for p in kept if p != lead], *picked],
            lead_id=lead,
            reason=QueueReason.MOVED,
            auto=True,
            check=False,
            notify_staff=True,
        )
        if dropped:
            notify.staff_unassigned(appointment, dropped)
    _arm_reminder(appointment)
    AppointmentStatusHistory.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        from_status=appointment.status,
        to_status=appointment.status,
        reason=f"rescheduled:{previous.isoformat()}",
        actor_kind=context.principal_kind,
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
    notify.staff_moved(appointment, kept, previous_starts_at=previous, mutation_id=mutation.id)
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
        crew = crew_of(appointment)
        appointment.status = AppointmentStatus.CANCELED
        # Nothing left to staff: a called-off visit leaves the queue.
        appointment.needs_assignment = appointment.auto_assigned = False
        appointment.queue_reason, appointment.queued_at = "", None
        appointment.save(
            update_fields=[
                "status",
                "needs_assignment",
                "auto_assigned",
                "queue_reason",
                "queued_at",
                "updated_at",
            ]
        )
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
        stock.release(context.organization_id, appointment.id)
        customer = appointment.customer
        if customer.email:
            queue_email(
                recipient_email=customer.email,
                template_key="booking.canceled",
                template_version=1,
                locale=customer.locale,
                template_context={
                    "organization_name": Organization.objects.get(pk=context.organization_id).name,
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
        notify.staff_canceled(appointment, crew)
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


def _arm_reminder(appointment: Appointment) -> None:
    """Schedules the customer's reminder for the appointment's current time.

    A move re-arms it: the reminder follows the new time, even when the old
    one was already sent. The route is signed as the organization's own
    service, not as whoever booked, so it outlives that person's membership
    (ADR-058 §7).
    """
    due_at = max(
        timezone.now(),
        appointment.starts_at - timedelta(hours=settings.BOOKING_REMINDER_LEAD_HOURS),
    )
    appointment.reminder_due_at, appointment.reminder_sent_at = due_at, None
    appointment.save(update_fields=["reminder_due_at", "reminder_sent_at", "updated_at"])
    signed = issue_service_task_contract(
        organization_id=appointment.organization_id,
        role_key=REMINDER_ROLE,
        permissions=REMINDER_PERMISSIONS,
        causation_id=f"booking:{appointment.id}",
    )
    ReminderRoute.objects.update_or_create(
        appointment_id=appointment.id,
        defaults={
            "organization_id": appointment.organization_id,
            "signed_tenant_context": encrypt_secret(signed),
            "due_at": due_at,
            "dispatched_at": None,
        },
    )


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
def set_service_materials(*, service_id: UUID, materials: list[dict[str, Any]]) -> Service:
    """Produkty, które każda wizyta tej usługi zabiera z magazynu."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    if materials:
        stock.authorize_change()
    service = Service.all_objects.select_for_update().filter(pk=service_id).first()
    if service is None:
        raise NotFound("Usługa nie istnieje.")
    if materials:
        stock.refuse_own(service.appointment_kind)
    lines = stock.normalize(context.organization_id, materials)
    service.materials = [
        {"item_id": line["item_id"], "quantity": line["quantity"], "mode": line["mode"]}
        for line in lines
    ]
    service.save(update_fields=["materials", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.catalog.changed",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="service",
        target_id=service.id,
        metadata={"materials": len(lines)},
    )
    return service


@transaction.atomic
def set_appointment_materials(
    *, appointment_id: UUID, materials: list[dict[str, Any]]
) -> Appointment:
    """Produkty jednej wizyty, wpisane ręcznie — rezerwacja idzie za nimi."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    stock.authorize_change()
    appointment = (
        Appointment.all_objects.select_for_update(of=("self",))
        .select_related("service")
        .filter(pk=appointment_id)
        .first()
    )
    if appointment is None:
        raise NotFound("Rezerwacja nie istnieje.")
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise AppointmentNotChangeable
    if materials:
        stock.refuse_own(appointment.service.appointment_kind)
    before = appointment.materials
    appointment.materials = stock.normalize(context.organization_id, materials)
    appointment.save(update_fields=["materials", "updated_at"])
    stock.reserve(context.organization_id, appointment.id, appointment.materials)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.appointment.materials_changed",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        metadata={
            "changes": {
                "materials": {
                    "from": [f"{x['name']} × {x['quantity']}" for x in before],
                    "to": [f"{x['name']} × {x['quantity']}" for x in appointment.materials],
                }
            }
        },
    )
    return appointment


@transaction.atomic
def set_appointment_place(*, appointment_id: UUID, town: str, address: str = "") -> Appointment:
    """„Miejsce wizyty” of a booked visit (ADR-066): its town and, optionally,
    a street and number; both empty give the place back to the module that
    knows it. Setting the same place again changes nothing, so a retry is safe.
    A called-off visit keeps the place it had."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    appointment = (
        Appointment.all_objects.select_for_update(of=("self",))
        .filter(organization_id=context.organization_id, pk=appointment_id)
        .first()
    )
    if appointment is None:
        raise NotFound("Rezerwacja nie istnieje.")
    if appointment.status == AppointmentStatus.CANCELED:
        raise AppointmentNotChangeable
    town, address = town.strip()[:120], address.strip()[:240]
    if (appointment.place_town, appointment.place_address) == (town, address):
        return appointment
    before = appointment.place_town
    address_changed = appointment.place_address != address
    appointment.place_town, appointment.place_address = town, address
    appointment.save(update_fields=["place_town", "place_address", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action="booking.appointment.place_changed",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        # The street may be a customer's home: the history says it changed,
        # never what it is.
        metadata={
            "changes": {"place_town": {"from": before, "to": town}},
            **({"address_changed": True} if address_changed else {}),
        },
    )
    return appointment


@transaction.atomic
def complete_appointment(
    *,
    appointment_id: UUID,
    idempotency_key: str,
    principal_ref: str,
    ended_at: datetime | None = None,
) -> Appointment:
    """Marks a confirmed appointment as done; the customer's self-service link
    stops working, because there is nothing left to move or call off.

    The people and the resource are busy until `ended_at` (now by default; a
    product may pass its own, such as when the trimmer left the farm) plus the
    buffer the booking took after the visit, so a walk-in blocked for the whole
    day frees them when the work ends (ADR-058 §6). A trim only shortens, so
    it cannot collide with anybody; the planned times stay as booked.
    """
    context = require_tenant_context()
    appointment = Appointment.all_objects.select_for_update().filter(pk=appointment_id).first()
    if not appointment:
        raise NotFound("Rezerwacja nie istnieje.")
    request_hash = _hash({
        "complete": True,
        **({"ended_at": ended_at.isoformat()} if ended_at else {}),
    })
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
        # The booking's own after-buffer, not the catalogue's today: none for a
        # walk-in, which is booked without buffers.
        until = (ended_at or timezone.now()) + (appointment.occupied_until - appointment.ends_at)
        for model in (AppointmentStaffAllocation, AppointmentResourceAllocation):
            for allocation in model.all_objects.filter(
                appointment=appointment, active=True, occupied_range__endswith__gt=until
            ):
                start = allocation.occupied_range.lower
                # Ended before it began: an empty range, which overlaps nothing.
                allocation.occupied_range = (start, max(start, until))
                allocation.save(update_fields=["occupied_range"])
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
        # A kind whose module accounts for its own material (HoofCare) never
        # settles here: its stock already went per cow (ADR-055). A reservation
        # it held from before its module said so is let go, not left behind.
        if not stock.takes_materials(appointment.service.appointment_kind):
            stock.release(context.organization_id, appointment.id)
        elif context.actor_id is not None:
            stock.settle(
                context.organization_id, appointment.id, appointment.materials, context.actor_id
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
    # What the customer wrote about the visit goes too (answer 1A, 28.09):
    # in a clinic it can be about their health.
    Appointment.all_objects.filter(customer=customer).exclude(customer_notes="").update(
        customer_notes=""
    )
    # So does the street of a visit at the customer's (ADR-066); the town stays,
    # it names nobody.
    Appointment.all_objects.filter(customer=customer).exclude(place_address="").update(
        place_address=""
    )
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
