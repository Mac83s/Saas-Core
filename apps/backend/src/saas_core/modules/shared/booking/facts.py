"""What a person did, counted by the module that knows it (team plan, phase 5).

Booking keeps the registry and the doors; every module counts its own: the
calendar its visits and hours, the warehouse what a person took and used, a
product what its people did in the field. Core knows no product by name, so a
product registers a provider through `booking.api.register_staff_facts`.

Who reads what (owner's answers 3, 24.09 and 2.1a, 29.09): one's own facts
always, under each module's own read; somebody else's only with
`booking.staff.performance.read` (owner and administrator) and the module's
read of other people's data. The right to assign visits is not a right to
personnel data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.core.organizations.permissions import MEMBERS_READ

from .availability import _zone
from .models import (
    Appointment,
    AppointmentStaffAllocation,
    AppointmentStatus,
    StaffMember,
    StaffTeamMember,
    TimeOff,
)
from .passing import took_place_q
from .staff import _management, _own, _read

#: Somebody else's results and history (owner's answer 3, 24.09).
STAFF_PERFORMANCE_READ = "booking.staff.performance.read"
#: A period longer than a year is a report, not a card.
MAX_DAYS = 366
HISTORY_PAGE = 50


@dataclass(frozen=True, slots=True)
class Period:
    """Local days `first`–`last` of the organization, as instants."""

    first: date
    last: date
    starts: datetime
    ends: datetime

    def previous(self) -> Period:
        """The same number of days just before, to compare with."""
        days = (self.last - self.first).days + 1
        return _period(self.first - timedelta(days=days), self.first - timedelta(days=1))


@dataclass(frozen=True, slots=True)
class StaffSubject:
    """The person the facts are about, as every provider needs them."""

    organization_id: UUID
    staff_id: UUID
    name: str
    membership_id: UUID | None
    user_id: UUID | None
    #: The viewer reads their own facts.
    own: bool
    #: Management or the person: reasons of absence (ADR-058 §9).
    private: bool


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    value: int
    #: "count", "minutes" or "money" (minor units of the organization's currency).
    unit: str = "count"
    #: A number's parts, e.g. visits as the lead and in the crew.
    parts: dict[str, int] = field(default_factory=dict)
    #: False for a state rather than a count, like today's stock.
    comparable: bool = True


@dataclass(frozen=True, slots=True)
class Event:
    at: datetime
    event: str
    params: dict[str, Any] = field(default_factory=dict)
    value: int | None = None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class StaffFacts:
    """One module's facts about a person."""

    name: str
    metrics: Callable[[StaffSubject, Period], list[Metric]]
    history: Callable[[StaffSubject, Period], list[Event]] | None = None
    #: The module's read of one's own data; None: the calendar's read is enough.
    own_permission: str | None = None
    #: The module's read of other people's data, on top of the performance read.
    others_permission: str | None = None
    #: Where the group stands on the card: the calendar first, products last.
    order: int = 100


_providers: dict[str, StaffFacts] = {}


def register_staff_facts(provider: StaffFacts) -> None:
    _providers[provider.name] = provider


def _day_start(day: date, zone: Any) -> datetime:
    return datetime.combine(day, time.min, zone)


def _period(first: date, last: date) -> Period:
    zone = _zone()
    return Period(first, last, _day_start(first, zone), _day_start(last + timedelta(days=1), zone))


def period(first: date | None, last: date | None) -> Period:
    """This month so far unless the caller names the days."""
    today = timezone.localdate(timezone=_zone())
    last = last or today
    first = first or last.replace(day=1)
    if last < first:
        raise ValidationError({"from": ["Początek okresu jest po jego końcu."]})
    if (last - first).days + 1 > MAX_DAYS:
        raise ValidationError({"from": [f"Okres może mieć najwyżej {MAX_DAYS} dni."]})
    return _period(first, last)


def _subject(context: TenantContext, staff: StaffMember) -> StaffSubject:
    user_id = (
        Membership.objects.filter(pk=staff.membership_id).values_list("user_id", flat=True).first()
        if staff.membership_id
        else None
    )
    own = _own(context, staff)
    return StaffSubject(
        organization_id=context.organization_id,
        staff_id=staff.id,
        name=staff.display_name,
        membership_id=staff.membership_id,
        user_id=user_id,
        own=own,
        private=own or _management(context),
    )


def _person(staff_id: UUID) -> tuple[TenantContext, StaffSubject]:
    context = _read()
    staff = StaffMember.all_objects.filter(
        organization_id=context.organization_id, pk=staff_id
    ).first()
    if staff is None:
        raise NotFound("Nie ma takiego pracownika.")
    subject = _subject(context, staff)
    if not subject.own and not context.has_permission(STAFF_PERFORMANCE_READ):
        # Nobody but the person, the owner and the administrator (answer 3).
        raise OrganizationPermissionDenied
    return context, subject


def _readable(context: TenantContext, own: bool) -> list[StaffFacts]:
    return sorted(
        (
            provider
            for provider in _providers.values()
            if (permission := provider.own_permission if own else provider.others_permission)
            is None
            or context.has_permission(permission)
        ),
        key=lambda provider: (provider.order, provider.name),
    )


def staff_facts(staff_id: UUID, first: date | None, last: date | None) -> dict[str, Any]:
    """A person's numbers for a period, each beside the one before it."""
    context, subject = _person(staff_id)
    current = period(first, last)
    previous = current.previous()
    groups = []
    for provider in _readable(context, subject.own):
        now = provider.metrics(subject, current)
        if not now:
            continue
        before = {metric.key: metric for metric in provider.metrics(subject, previous)}
        groups.append({
            "provider": provider.name,
            "metrics": [
                {
                    "key": metric.key,
                    "value": metric.value,
                    "unit": metric.unit,
                    "parts": metric.parts,
                    "previous": before[metric.key].value
                    if metric.comparable and metric.key in before
                    else None,
                }
                for metric in now
            ],
        })
    return {
        "period_from": current.first,
        "period_to": current.last,
        "previous_from": previous.first,
        "previous_to": previous.last,
        "groups": groups,
    }


def staff_history(
    staff_id: UUID,
    first: date | None,
    last: date | None,
    *,
    kind: str = "",
    before: datetime | None = None,
) -> dict[str, Any]:
    """What happened to a person, newest first, a page at a time."""
    context, subject = _person(staff_id)
    current = period(first, last)
    events: list[tuple[str, Event]] = []
    for provider in _readable(context, subject.own):
        if provider.history is None or (kind and kind != provider.name):
            continue
        events.extend((provider.name, event) for event in provider.history(subject, current))
    if before is not None:
        events = [item for item in events if item[1].at < before]
    events.sort(key=lambda item: item[1].at, reverse=True)
    page = events[:HISTORY_PAGE]
    return {
        "period_from": current.first,
        "period_to": current.last,
        "kinds": [
            provider.name
            for provider in _readable(context, subject.own)
            if provider.history is not None
        ],
        "items": [
            {
                "at": event.at,
                "kind": name,
                "event": event.event,
                "params": event.params,
                "value": event.value,
                "unit": event.unit,
            }
            for name, event in page
        ],
        "next_before": page[-1][1].at if len(events) > HISTORY_PAGE else None,
    }


def team_performance(
    first: date | None, last: date | None, *, team_id: UUID | None = None
) -> dict[str, Any]:
    """Everybody's numbers side by side: the owner's and administrator's view."""
    context = _read()
    if not context.has_permission(STAFF_PERFORMANCE_READ):
        raise OrganizationPermissionDenied
    current = period(first, last)
    query = StaffMember.all_objects.filter(organization_id=context.organization_id, active=True)
    if team_id is not None:
        query = query.filter(
            id__in=StaffTeamMember.all_objects.filter(
                organization_id=context.organization_id, team_id=team_id
            ).values("staff_id")
        )
    people = list(query.order_by("display_name", "id"))
    teams: dict[UUID, list[UUID]] = {}
    for staff_id, team in StaffTeamMember.all_objects.filter(
        organization_id=context.organization_id, staff_id__in=[item.id for item in people]
    ).values_list("staff_id", "team_id"):
        teams.setdefault(staff_id, []).append(team)
    providers = _readable(context, own=False)
    columns: dict[str, dict[str, str]] = {}
    rows = []
    for staff in people:
        subject = _subject(context, staff)
        groups: dict[str, dict[str, int]] = {}
        for provider in providers:
            metrics = provider.metrics(subject, current)
            if not metrics:
                continue
            groups[provider.name] = {metric.key: metric.value for metric in metrics}
            units = columns.setdefault(provider.name, {})
            units.update({metric.key: metric.unit for metric in metrics})
        rows.append({
            "staff_id": staff.id,
            "name": staff.display_name,
            "membership_id": staff.membership_id,
            "team_ids": teams.get(staff.id, []),
            "groups": groups,
        })
    return {
        "period_from": current.first,
        "period_to": current.last,
        "columns": [
            {
                "provider": name,
                "metrics": [{"key": key, "unit": unit} for key, unit in units.items()],
            }
            for name, units in columns.items()
        ],
        "items": rows,
    }


# --- the calendar's own facts --------------------------------------------------------

def _now() -> datetime:
    """When a visit counts as past; a test moves it."""
    return timezone.now()


def _done(subject: StaffSubject, span: Period) -> list[AppointmentStaffAllocation]:
    """Visits the person was on that took place (`passing`, UX-031): time
    passed, neither canceled nor a no-show (3A), unless their module closes
    them itself. A visit ended with „Zakończ” took place at once, before its
    planned end.

    The person is on a visit while their time is held on it; a lead taken off a
    visit that waits for somebody else holds none (ADR-058 §2).
    """
    return list(
        AppointmentStaffAllocation.all_objects.filter(
            took_place_q(_now(), "appointment__"),
            organization_id=subject.organization_id,
            staff_id=subject.staff_id,
            active=True,
            appointment__starts_at__gte=span.starts,
            appointment__starts_at__lt=span.ends,
        )
        .select_related("appointment", "appointment__customer")
        .order_by("appointment__starts_at", "id")
    )


def _lead(allocation: AppointmentStaffAllocation) -> bool:
    appointment = allocation.appointment
    return appointment.staff_id == allocation.staff_id and not appointment.needs_assignment


def _minutes(allocation: AppointmentStaffAllocation) -> int:
    """The visit's own time the person held: buffers out, cut at the real end."""
    appointment = allocation.appointment
    held = allocation.occupied_range
    # Closed before it began („Zakończ” on a visit still ahead): nothing held.
    if held.isempty:
        return 0
    after = appointment.occupied_until - appointment.ends_at
    start = max(held.lower, appointment.starts_at)
    end = min(held.upper - after, appointment.ends_at)
    return max(int((end - start).total_seconds() // 60), 0)


def _calendar_metrics(subject: StaffSubject, span: Period) -> list[Metric]:
    done = _done(subject, span)
    lead = sum(1 for allocation in done if _lead(allocation))
    in_period = Appointment.all_objects.filter(
        organization_id=subject.organization_id,
        starts_at__gte=span.starts,
        starts_at__lt=span.ends,
    )
    theirs = Q(staff_id=subject.staff_id) | Q(staff_allocations__staff_id=subject.staff_id)
    canceled = in_period.filter(theirs, status=AppointmentStatus.CANCELED).distinct().count()
    no_shows = in_period.filter(theirs, status=AppointmentStatus.NO_SHOW).distinct().count()
    chosen = (
        in_period.filter(requested_staff_id=subject.staff_id)
        .exclude(status=AppointmentStatus.CANCELED)
        .count()
    )
    return [
        Metric("visits_done", len(done), parts={"lead": lead, "crew": len(done) - lead}),
        Metric("hours", sum(_minutes(allocation) for allocation in done), unit="minutes"),
        Metric("canceled", canceled),
        Metric("no_shows", no_shows),
        Metric("chosen_by_customer", chosen),
    ]


def _calendar_history(subject: StaffSubject, span: Period) -> list[Event]:
    events = []
    for allocation in _done(subject, span):
        appointment = allocation.appointment
        events.append(
            Event(
                appointment.ends_at,
                "visit_done",
                {
                    "customer": appointment.customer.display_name,
                    "service": appointment.service_name,
                    "role": "lead" if _lead(allocation) else "crew",
                },
            )
        )
    staff = str(subject.staff_id)
    changes = OrganizationAuditEntry.objects.filter(
        organization_id=subject.organization_id,
        action=OrganizationAuditAction.BOOKING_APPOINTMENT_CREW_CHANGED,
        occurred_at__gte=span.starts,
        occurred_at__lt=span.ends,
    ).filter(Q(metadata__added__contains=[staff]) | Q(metadata__removed__contains=[staff]))
    rows = list(changes.select_related("actor_user"))
    visits = {
        appointment.id: appointment
        for appointment in Appointment.all_objects.filter(
            organization_id=subject.organization_id,
            id__in=[row.target_id for row in rows if row.target_id],
        ).select_related("customer")
    }
    for row in rows:
        visit = visits.get(row.target_id) if row.target_id else None
        added = staff in (row.metadata.get("added") or [])
        events.append(
            Event(
                row.occurred_at,
                "assigned" if added else "unassigned",
                {
                    "customer": visit.customer.display_name if visit else "",
                    "starts_at": visit.starts_at.isoformat() if visit else None,
                    "by": _name(row.actor_user),
                    "reason": row.metadata.get("reason") or "",
                },
            )
        )
    for away in TimeOff.all_objects.filter(
        organization_id=subject.organization_id,
        staff_id=subject.staff_id,
        starts_at__lt=span.ends,
        ends_at__gt=span.starts,
    ):
        events.append(
            Event(
                away.starts_at,
                "time_off",
                {
                    "from": away.starts_at.isoformat(),
                    "to": away.ends_at.isoformat(),
                    # A reason can be about health: the person and management only.
                    "reason": away.reason if subject.private else "",
                },
            )
        )
    return events


def _name(user: User | None) -> str:
    if user is None:
        return ""
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.email


_ACCOUNT_EVENTS: dict[str, str] = {
    OrganizationAuditAction.MEMBERSHIP_ROLE_CHANGED: "role_changed",
    OrganizationAuditAction.MEMBERSHIP_SUSPENDED: "suspended",
    OrganizationAuditAction.MEMBERSHIP_RESUMED: "resumed",
    OrganizationAuditAction.MEMBERSHIP_REVOKED: "revoked",
}


def _account_history(subject: StaffSubject, span: Period) -> list[Event]:
    """The account's role and access over time, from the organization's history."""
    if subject.membership_id is None:
        return []
    rows = list(
        OrganizationAuditEntry.objects.filter(
            organization_id=subject.organization_id,
            target_type="membership",
            target_id=subject.membership_id,
            action__in=list(_ACCOUNT_EVENTS),
            occurred_at__gte=span.starts,
            occurred_at__lt=span.ends,
        ).select_related("actor_user")
    )
    keys = {
        value
        for row in rows
        for value in (row.metadata.get("from"), row.metadata.get("to"))
        if value
    }
    names = {
        role.key: role.name
        for role in Role.objects.filter(key__in=keys).filter(
            Q(organization_id=subject.organization_id) | Q(organization__isnull=True)
        )
    }
    return [
        Event(
            row.occurred_at,
            _ACCOUNT_EVENTS[row.action],
            {
                "by": _name(row.actor_user),
                **(
                    {
                        "from": row.metadata.get("from"),
                        "to": row.metadata.get("to"),
                        "from_name": names.get(row.metadata.get("from"), ""),
                        "to_name": names.get(row.metadata.get("to"), ""),
                    }
                    if row.action == OrganizationAuditAction.MEMBERSHIP_ROLE_CHANGED
                    else {}
                ),
            },
        )
        for row in rows
    ]


def register_core_facts() -> None:
    register_staff_facts(StaffFacts("calendar", _calendar_metrics, _calendar_history, order=10))
    # Roles and access are the team's own record: who may see the team sees it.
    register_staff_facts(
        StaffFacts(
            "account",
            lambda _subject, _span: [],
            _account_history,
            others_permission=MEMBERS_READ,
            order=90,
        )
    )
