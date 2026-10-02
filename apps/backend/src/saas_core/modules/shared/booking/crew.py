"""Who does a visit (ADR-058 §2–§4).

The lead is `Appointment.staff`; everybody on the visit, the lead included,
has an active allocation, so the exclusion constraint keeps each person in
one place at a time. Every change of the people goes through `set_crew`,
which keeps the one invariant: the lead has an active allocation, or the
visit is a vacancy (`needs_assignment`) waiting in „Do przydzielenia”.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction

from . import notify
from .availability import window_status
from .models import (
    Appointment,
    AppointmentStaffAllocation,
    AppointmentStatus,
    QueueReason,
    StaffMember,
)


class PersonUnavailable(APIException):
    """One named person cannot take the visit's time; the caller can act on it."""

    status_code = 409
    default_code = "slot_unavailable"

    def __init__(self, name: str) -> None:
        super().__init__(detail=f"Termin jest zajęty dla: {name}.", code=self.default_code)


class CrewChanged(APIException):
    """Somebody changed the people on the visit after the caller looked."""

    status_code = 409
    default_code = "crew_changed"

    def __init__(self, who: str | None) -> None:
        detail = (
            f"Skład tej wizyty zmienił w międzyczasie: {who}. Odśwież i spróbuj ponownie."
            if who
            else "Skład tej wizyty zmienił się w międzyczasie. Odśwież i spróbuj ponownie."
        )
        super().__init__(detail=detail, code=self.default_code)


@dataclass(frozen=True, slots=True)
class CrewChange:
    appointment_id: UUID
    added: tuple[UUID, ...]
    removed: tuple[UUID, ...]
    kept: tuple[UUID, ...]
    lead_before: UUID | None
    lead_after: UUID | None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed) or self.lead_before != self.lead_after


def crew_of(appointment: Appointment) -> list[UUID]:
    """The people with the visit's time blocked, the lead first."""
    people = list(
        dict.fromkeys(
            AppointmentStaffAllocation.all_objects.filter(appointment=appointment, active=True)
            .order_by("id")
            .values_list("staff_id", flat=True)
        )
    )
    if appointment.staff_id in people:
        people.remove(appointment.staff_id)
        people.insert(0, appointment.staff_id)
    return people


def allocate(
    appointment: Appointment, staff: StaffMember, *, since: datetime | None = None
) -> None:
    """Blocks the visit's time for one person, or names them when it is taken.

    `since` starts the block later than the visit (somebody joining a visit
    already under way); the end is always the visit's.
    """
    start = max(since, appointment.occupied_from) if since else appointment.occupied_from
    try:
        with transaction.atomic():
            AppointmentStaffAllocation.all_objects.create(
                organization_id=appointment.organization_id,
                appointment=appointment,
                staff_id=staff.id,
                occupied_range=(start, max(start, appointment.occupied_until)),
            )
    except (IntegrityError, OperationalError) as error:
        if not lost_slot_race(error):
            raise
        raise PersonUnavailable(staff.display_name) from error


def lost_slot_race(error: Exception) -> bool:
    """The exclusion constraint, or the deadlock two racing inserts can end in
    (40P01) — for the loser the same outcome a millisecond earlier."""
    return isinstance(error, IntegrityError) or (
        getattr(error.__cause__, "sqlstate", None) == "40P01"
    )


def set_crew(
    appointment: Appointment,
    staff_ids: Sequence[UUID],
    *,
    lead_id: UUID | None = None,
    reason: str = "",
    auto: bool | None = False,
    check: bool = True,
    since: datetime | None = None,
    notify_staff: bool = True,
) -> CrewChange:
    """Puts exactly these people on the visit (the caller holds its row lock).

    `lead_id` defaults to the first person. An empty list leaves the lead's
    name on the visit and marks the vacancy. `check` refuses anybody whose
    hours, absence or other visits rule the time out (off for a walk-in or
    somebody joining a visit at the farm). `auto`: whether the system chose
    the people and nobody from the company looked — None keeps the flag as it
    is, for a change that is not a choice (an absence takes a person off).
    `reason` says why the visit waits, when it ends up waiting.
    """
    context = require_tenant_context()
    current = crew_of(appointment)
    wanted = list(dict.fromkeys(staff_ids))
    lead = lead_id or (wanted[0] if wanted else appointment.staff_id)
    if wanted and lead not in wanted:
        raise ValidationError({"lead_id": "Prowadzący musi być jedną z wybranych osób."})
    people = {
        person.id: person for person in StaffMember.all_objects.filter(pk__in=wanted, active=True)
    }
    if len(people) != len(wanted):
        raise ValidationError({"staff_ids": "Nie ma takiej osoby w zespole firmy."})
    removed = tuple(person for person in current if person not in wanted)
    added = tuple(person for person in wanted if person not in current)
    kept = tuple(person for person in current if person in wanted)
    if removed:
        AppointmentStaffAllocation.all_objects.filter(
            appointment=appointment, staff_id__in=removed, active=True
        ).update(active=False)
    for person_id in added:
        person = people[person_id]
        if check:
            status = window_status(
                staff_id=person_id,
                location_id=appointment.location_id,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                occupied_from=appointment.occupied_from,
                occupied_until=appointment.occupied_until,
                ignore_appointment_id=appointment.id,
            )
            if status.state != "free":
                raise PersonUnavailable(person.display_name)
        allocate(appointment, person, since=since)
    lead_before = appointment.staff_id
    if wanted:
        appointment.staff_id = lead
    vacancy = len(wanted) < appointment.staff_required or not wanted
    was_waiting = appointment.needs_assignment or appointment.auto_assigned
    appointment.needs_assignment = vacancy
    if auto is not None:
        appointment.auto_assigned = auto and not vacancy
    waiting = appointment.needs_assignment or appointment.auto_assigned
    # A new reason replaces the old one: the queue says what happened last.
    if waiting and (not was_waiting or ((vacancy or auto) and reason)):
        appointment.queue_reason = reason or appointment.queue_reason or QueueReason.SHORT
        appointment.queued_at = appointment.queued_at if was_waiting else timezone.now()
    elif not waiting:
        appointment.queue_reason, appointment.queued_at = "", None
    change = CrewChange(appointment.id, added, removed, kept, lead_before, appointment.staff_id)
    appointment.crew_version += 1
    appointment.save(
        update_fields=[
            "staff",
            "needs_assignment",
            "auto_assigned",
            "queue_reason",
            "queued_at",
            "crew_version",
            "updated_at",
        ]
    )
    if change.changed:
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=OrganizationAuditAction.BOOKING_APPOINTMENT_CREW_CHANGED,
            actor=User.objects.filter(pk=context.actor_id).first(),
            target_type="appointment",
            target_id=appointment.id,
            metadata={
                "added": [str(person) for person in added],
                "removed": [str(person) for person in removed],
                "lead": str(appointment.staff_id),
                **({"reason": reason} if reason else {}),
            },
        )
        if notify_staff:
            notify.staff_assigned(appointment, added)
            notify.staff_unassigned(appointment, removed)
        if change.lead_before is not None and change.lead_before != change.lead_after:
            notify.customer_person_changed(appointment, previous_lead_id=change.lead_before)
    return change


@dataclass(frozen=True, slots=True)
class CrewPerson:
    staff_id: UUID
    name: str
    membership_id: UUID | None
    lead: bool


def crew_people(appointment: Appointment) -> list[CrewPerson]:
    """Who is on the visit, the lead first — for a product's own screens."""
    ids = crew_of(appointment)
    people = {person.id: person for person in StaffMember.all_objects.filter(pk__in=ids)}
    return [
        CrewPerson(
            key, people[key].display_name, people[key].membership_id, key == appointment.staff_id
        )
        for key in ids
        if key in people
    ]


def crew_member_filter(membership_id: UUID | None, *, through: str = "") -> Q:
    """Rows whose visit has this account on it: as the lead, or with its time
    blocked (ADR-058 §2). A lead taken off a visit that waits for somebody else
    keeps only their name on it, so a vacancy counts the blocked time alone.
    `through` is the path to the appointment, e.g. ``"appointment__"``; a join
    through allocations may repeat rows, so the caller takes `.distinct()`."""
    return Q(**{
        f"{through}staff__membership_id": membership_id,
        f"{through}needs_assignment": False,
    }) | Q(**{
        f"{through}staff_allocations__active": True,
        f"{through}staff_allocations__staff__membership_id": membership_id,
    })


def on_crew(appointment_id: UUID, membership_id: UUID | None) -> bool:
    """Whether this account has the visit's time blocked."""
    return (
        membership_id is not None
        and AppointmentStaffAllocation.all_objects.filter(
            appointment_id=appointment_id, active=True, staff__membership_id=membership_id
        ).exists()
    )


@transaction.atomic
def join_visit_crew(*, appointment_id: UUID, staff_id: UUID, since: datetime) -> bool:
    """Somebody joins a visit under way — a product's „Dołącz” (answer 3A of
    28.09): their time is blocked from `since` to the visit's end, and a visit
    of theirs in that time loses them and waits in „Do przydzielenia”.

    The caller authorized the action; the schedule is not asked, because the
    person is already there. Says whether anything changed.
    """
    context = require_tenant_context()
    appointment = (
        Appointment.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, pk=appointment_id)
        .first()
    )
    staff = StaffMember.all_objects.filter(
        organization_id=context.organization_id, pk=staff_id, active=True
    ).first()
    if appointment is None or staff is None or appointment.status != AppointmentStatus.CONFIRMED:
        return False
    crew = crew_of(appointment)
    if staff.id in crew:
        return False
    take_off(staff, since=since, until=appointment.occupied_until, reason=QueueReason.JOINED)
    set_crew(
        appointment,
        [*crew, staff.id],
        lead_id=appointment.staff_id if appointment.staff_id in crew else None,
        auto=None,
        check=False,
        since=since,
    )
    return True


@transaction.atomic
def leave_visit_crew(*, appointment_id: UUID, staff_id: UUID) -> bool:
    """A helper leaves the visit's crew; the lead stays, and so does a visit
    that would be left with nobody."""
    context = require_tenant_context()
    appointment = (
        Appointment.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, pk=appointment_id)
        .first()
    )
    if appointment is None or staff_id == appointment.staff_id:
        return False
    crew = crew_of(appointment)
    if staff_id not in crew:
        return False
    set_crew(
        appointment,
        [person for person in crew if person != staff_id],
        lead_id=appointment.staff_id if appointment.staff_id in crew else None,
        auto=None,
        check=False,
    )
    return True


def take_off(staff: StaffMember, *, since: datetime, until: datetime | None, reason: str) -> int:
    """Takes one person off their confirmed visits in a window; each becomes a
    vacancy the office staffs from „Do przydzielenia” (ADR-058 §3). The others
    on the visit keep their time. Returns how many visits it touched."""
    query = AppointmentStaffAllocation.all_objects.filter(
        staff=staff,
        active=True,
        appointment__status=AppointmentStatus.CONFIRMED,
        appointment__ends_at__gt=max(since, timezone.now()),
    )
    if until is not None:
        query = query.filter(occupied_range__overlap=(since, until))
    appointment_ids = list(query.values_list("appointment_id", flat=True).distinct())
    for appointment in Appointment.all_objects.select_for_update().filter(pk__in=appointment_ids):
        people = [person for person in crew_of(appointment) if person != staff.id]
        set_crew(
            appointment,
            people,
            lead_id=appointment.staff_id if appointment.staff_id in people else None,
            reason=reason,
            auto=None,
            check=False,
        )
    return len(appointment_ids)


def least_loaded(
    organization: Organization, starts_at: datetime, people: Sequence[UUID]
) -> list[UUID]:
    """People in the order a booking tries them (ADR-058 §4): fewest minutes of
    active allocations that local day, then that ISO week, then id."""
    zone = ZoneInfo(organization.timezone)
    local = starts_at.astimezone(zone).date()

    def window(first: date, days: int) -> tuple[datetime, datetime]:
        last = first + timedelta(days=days)
        return datetime.combine(first, time.min, zone), datetime.combine(last, time.min, zone)

    day, week = window(local, 1), window(local - timedelta(days=local.weekday()), 7)
    booked = list(
        AppointmentStaffAllocation.all_objects.filter(
            organization=organization,
            staff_id__in=set(people),
            active=True,
            occupied_range__overlap=week,
        ).values_list("staff_id", "occupied_range")
    )

    def load(staff_id: UUID, bounds: tuple[datetime, datetime]) -> timedelta:
        return sum(
            (
                max(min(taken.upper, bounds[1]) - max(taken.lower, bounds[0]), timedelta(0))
                for owner, taken in booked
                if owner == staff_id
            ),
            timedelta(0),
        )

    return sorted(
        dict.fromkeys(people), key=lambda person: (load(person, day), load(person, week), person)
    )


def last_crew_actor(appointment: Appointment) -> str | None:
    """Who changed the people last, for the 409 an outdated assignment gets."""
    from saas_core.modules.core.organizations.models import OrganizationAuditEntry  # noqa: PLC0415

    entry = (
        OrganizationAuditEntry.objects.filter(
            organization_id=appointment.organization_id,
            action=OrganizationAuditAction.BOOKING_APPOINTMENT_CREW_CHANGED,
            target_id=appointment.id,
        )
        .select_related("actor_user")
        .order_by("-occurred_at")
        .first()
    )
    if entry is None or entry.actor_user is None:
        return None
    user = entry.actor_user
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email
