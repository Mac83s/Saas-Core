"""The office's side of who does which visit (ADR-058 §3, §9): the queue of
visits to look at, who is free for one of them, and the assignment itself."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.models import MembershipStatus
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .availability import WindowStatus, available_days, available_times, window_status
from .crew import CrewChanged, crew_of, last_crew_actor, set_crew
from .models import (
    Appointment,
    AppointmentStaffAllocation,
    AppointmentStatus,
    AvailabilityRule,
    BookingMutation,
    ServiceStaff,
    StaffMember,
    StaffTeam,
    StaffTeamMember,
)
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BOOKING_READ,
    AppointmentNotChangeable,
    BookingIdempotencyConflict,
    _hash,
    with_crew,
)

#: How far „najbliższy wolny termin” looks for a person who is not free.
_NEXT_FREE_DAYS = 14


def queue() -> list[Appointment]:
    """Planned visits the office should look at: vacancies and people the
    system chose on its own, earliest first."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    return list(
        with_crew(
            Appointment.all_objects.filter(
                organization_id=context.organization_id,
                status=AppointmentStatus.CONFIRMED,
                ends_at__gt=timezone.now(),
            ).filter(Q(needs_assignment=True) | Q(auto_assigned=True))
        ).order_by("starts_at", "id")[:500]
    )


@dataclass(frozen=True, slots=True)
class Overview:
    #: People who take visits: an active entry with a service and hours.
    bookable_staff: int
    teams: int
    #: Visits waiting in „Do przydzielenia”; None for whoever may not assign.
    waiting: int | None


def overview() -> Overview:
    """What the menu needs to show or hide the dispatch pages: with one person
    taking visits there is nobody to choose between (ADR-058, MedPlano)."""
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    bookable = (
        StaffMember.all_objects.filter(organization_id=context.organization_id, active=True)
        .filter(
            pk__in=ServiceStaff.all_objects.filter(
                organization_id=context.organization_id, service__active=True
            ).values("staff_id")
        )
        .filter(
            pk__in=AvailabilityRule.all_objects.filter(
                organization_id=context.organization_id, active=True
            ).values("staff_id")
        )
        .count()
    )
    waiting = None
    if context.has_permission(BOOKING_MANAGE):
        waiting = (
            Appointment.all_objects.filter(
                organization_id=context.organization_id,
                status=AppointmentStatus.CONFIRMED,
                ends_at__gt=timezone.now(),
            )
            .filter(Q(needs_assignment=True) | Q(auto_assigned=True))
            .count()
        )
    return Overview(
        bookable_staff=bookable,
        teams=StaffTeam.all_objects.filter(organization_id=context.organization_id).count(),
        waiting=waiting,
    )


@dataclass(frozen=True, slots=True)
class Candidate:
    staff: StaffMember
    team_ids: list[UUID]
    #: active, suspended, invited or none — an account is not needed to work.
    account: str
    does_service: bool
    status: WindowStatus
    on_visit: bool
    lead: bool
    day_visits: int
    day_minutes: int
    next_free: datetime | None


def candidates(*, appointment_id: UUID, everyone: bool = False) -> list[Candidate]:
    """Who could do this visit, and why not when they cannot („kto jest wolny”).

    By default the people who do its service and whoever is on it already;
    `everyone` adds the rest of the company. Free people first, then the least
    busy that day — the order the office reads the list in.
    """
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    appointment = with_crew(
        Appointment.all_objects.filter(pk=appointment_id, organization_id=context.organization_id)
    ).first()
    if appointment is None:
        raise NotFound("Rezerwacja nie istnieje.")
    crew = crew_of(appointment)
    performers = set(
        ServiceStaff.all_objects.filter(service_id=appointment.service_id).values_list(
            "staff_id", flat=True
        )
    )
    people = StaffMember.all_objects.filter(
        organization_id=context.organization_id, active=True
    ).select_related("membership")
    if not everyone:
        people = people.filter(Q(pk__in=performers) | Q(pk__in=crew))
    teams: dict[UUID, list[UUID]] = {}
    for staff_id, team_id in StaffTeamMember.all_objects.filter(
        organization_id=context.organization_id
    ).values_list("staff_id", "team_id"):
        teams.setdefault(staff_id, []).append(team_id)
    zone = ZoneInfo(appointment.timezone)
    day = appointment.starts_at.astimezone(zone).date()
    day_bounds = (
        datetime.combine(day, time.min, zone),
        datetime.combine(day + timedelta(days=1), time.min, zone),
    )
    loads: dict[UUID, tuple[set[UUID], timedelta]] = {}
    for staff_id, other_id, taken in (
        AppointmentStaffAllocation.all_objects.filter(
            organization_id=context.organization_id,
            active=True,
            occupied_range__overlap=day_bounds,
        )
        .exclude(appointment_id=appointment.id)
        .values_list("staff_id", "appointment_id", "occupied_range")
    ):
        visits, minutes = loads.get(staff_id, (set(), timedelta(0)))
        visits.add(other_id)
        overlap = min(taken.upper, day_bounds[1]) - max(taken.lower, day_bounds[0])
        loads[staff_id] = (visits, minutes + max(overlap, timedelta(0)))
    result: list[Candidate] = []
    for person in people:
        status = window_status(
            staff_id=person.id,
            location_id=appointment.location_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            occupied_from=appointment.occupied_from,
            occupied_until=appointment.occupied_until,
            ignore_appointment_id=appointment.id,
        )
        visits, minutes = loads.get(person.id, (set(), timedelta(0)))
        result.append(
            Candidate(
                staff=person,
                team_ids=teams.get(person.id, []),
                account=_account(person),
                does_service=person.id in performers,
                status=status,
                on_visit=person.id in crew,
                lead=person.id == appointment.staff_id and person.id in crew,
                day_visits=len(visits),
                day_minutes=int(minutes.total_seconds() // 60),
                next_free=(
                    _next_free(appointment, person.id, day)
                    if status.state != "free" and person.id in performers
                    else None
                ),
            )
        )
    return sorted(
        result,
        key=lambda item: (
            not item.on_visit,
            item.status.state != "free",
            item.day_minutes,
            item.staff.display_name,
        ),
    )


@transaction.atomic
def assign_crew(
    *,
    appointment_id: UUID,
    staff_ids: Sequence[UUID],
    lead_id: UUID | None,
    expected_version: int,
    notify_staff: bool,
    idempotency_key: str,
    principal_ref: str,
) -> Appointment:
    """The office puts exactly these people on the visit (ADR-058 §9).

    `expected_version` is the crew the office looked at: a newer one means
    somebody else changed it meanwhile, and the answer names them instead of
    overwriting their work. The same people again is „Zostaw” — the office has
    looked, so the visit leaves the queue.
    """
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    appointment = (
        Appointment.all_objects.select_for_update()
        .filter(pk=appointment_id, organization_id=context.organization_id)
        .first()
    )
    if appointment is None:
        raise NotFound("Rezerwacja nie istnieje.")
    request_hash = _hash({
        "staff_ids": [str(person) for person in staff_ids],
        "lead_id": str(lead_id) if lead_id else None,
        "expected_version": expected_version,
        "notify": notify_staff,
    })
    existing = BookingMutation.all_objects.filter(
        action="assign", principal_ref=principal_ref, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return with_crew(Appointment.all_objects.filter(pk=appointment.id)).get()
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise AppointmentNotChangeable
    if appointment.crew_version != expected_version:
        raise CrewChanged(last_crew_actor(appointment))
    set_crew(
        appointment,
        staff_ids,
        lead_id=lead_id,
        auto=False,
        notify_staff=notify_staff,
    )
    BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="assign",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return with_crew(Appointment.all_objects.filter(pk=appointment.id)).get()


def _account(person: StaffMember) -> str:
    membership = person.membership
    if membership is not None and membership.status in {
        MembershipStatus.ACTIVE,
        MembershipStatus.SUSPENDED,
    }:
        return str(membership.status)
    return "invited" if person.invitation_id else "none"


def _next_free(appointment: Appointment, staff_id: UUID, day: Any) -> datetime | None:
    """The first start of this service for this one person from the visit's day on."""
    days = available_days(
        service_id=appointment.service_id,
        location_id=appointment.location_id,
        from_date=day,
        to_date=day + timedelta(days=_NEXT_FREE_DAYS - 1),
        staff_ids=[staff_id],
    )
    for candidate in days:
        times = available_times(
            service_id=appointment.service_id,
            location_id=appointment.location_id,
            day=candidate,
            staff_ids=[staff_id],
        )
        if times:
            return times[0].starts_at
    return None
