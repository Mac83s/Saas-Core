from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization

from .models import (
    AppointmentResourceAllocation,
    AppointmentStaffAllocation,
    AvailabilityRule,
    Location,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    TimeOff,
)

#: Starts are offered every five minutes from the beginning of a rule.
_GRID = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class AvailableSlot:
    starts_at: datetime
    ends_at: datetime
    staff_id: UUID
    resource_id: UUID | None


@dataclass(frozen=True, slots=True)
class AvailableTime:
    """One start and who is free for it, each with the resource that goes along."""

    starts_at: datetime
    ends_at: datetime
    staff: dict[UUID, UUID | None]


@dataclass(frozen=True, slots=True)
class _Schedule:
    """What one search reads, loaded once for its whole window."""

    zone: ZoneInfo
    resource_ids: list[UUID | None]
    earliest: datetime
    duration: timedelta
    before: timedelta
    after: timedelta
    rules: list[AvailabilityRule]
    time_off: list[tuple[UUID | None, UUID | None, datetime, datetime]]
    staff_allocations: list[tuple[UUID, Any]]
    resource_allocations: list[tuple[UUID, Any]]


def available_slots(
    *,
    service_id: UUID,
    location_id: UUID,
    from_date: date,
    to_date: date,
    now: datetime | None = None,
    limit: int = 250,
) -> list[AvailableSlot]:
    """Every free (start, person, resource) of whole days.

    `limit` is checked when a day ends, never inside one (ADR-058 §5): a cut in
    the middle of a day hid every person after it, and with them the start a
    booking had asked for.
    """
    _check_horizon(from_date, to_date)
    if not 1 <= limit <= 500:
        raise ValidationError("Limit terminów jest nieprawidłowy.")
    schedule = _search(service_id, location_id, from_date, to_date, now=now)
    if schedule is None:
        return []
    results: list[AvailableSlot] = []
    day = from_date
    while day <= to_date and len(results) < limit:
        results.extend(_day_slots(schedule, day))
        day += timedelta(days=1)
    unique = {(item.starts_at, item.staff_id, item.resource_id): item for item in results}
    return sorted(
        unique.values(),
        key=lambda item: (item.starts_at, str(item.staff_id), str(item.resource_id)),
    )


def available_days(
    *,
    service_id: UUID,
    location_id: UUID,
    from_date: date,
    to_date: date,
    staff_ids: Sequence[UUID] | None = None,
    now: datetime | None = None,
) -> list[date]:
    """Days with a free start; each day stops at its first one (ADR-058 §5)."""
    _check_horizon(from_date, to_date)
    schedule = _search(service_id, location_id, from_date, to_date, staff_ids=staff_ids, now=now)
    if schedule is None:
        return []
    days = (from_date + timedelta(days=n) for n in range((to_date - from_date).days + 1))
    return [day for day in days if next(_day_slots(schedule, day), None) is not None]


def available_times(
    *,
    service_id: UUID,
    location_id: UUID,
    day: date,
    staff_ids: Sequence[UUID] | None = None,
    now: datetime | None = None,
) -> list[AvailableTime]:
    """Every free start of one day, once, sorted by UTC, with who can take it."""
    schedule = _search(service_id, location_id, day, day, staff_ids=staff_ids, now=now)
    if schedule is None:
        return []
    times: dict[datetime, AvailableTime] = {}
    for slot in _day_slots(schedule, day):
        entry = times.setdefault(slot.starts_at, AvailableTime(slot.starts_at, slot.ends_at, {}))
        entry.staff.setdefault(slot.staff_id, slot.resource_id)
    return [times[key] for key in sorted(times)]


def free_at(
    *,
    service: Service,
    location: Location,
    starts_at: datetime,
    staff_ids: Sequence[UUID] | None = None,
    resource_ids: Sequence[UUID | None] | None = None,
    ignore_appointment_id: UUID | None = None,
) -> list[tuple[UUID, UUID | None]]:
    """Every (person, resource) free at one concrete start, by staff id.

    Checks the start the way `_day_slots` would have found it — a rule's
    five-minute grid, minimum notice, time off, allocations — without walking
    the day, so no result limit can turn a free start down.
    """
    zone = _zone()
    day = starts_at.astimezone(zone).date()
    schedule = _load(
        service,
        location.id,
        zone,
        day,
        day,
        staff_ids=staff_ids,
        ignore_appointment_id=ignore_appointment_id,
    )
    if schedule is None or starts_at < schedule.earliest:
        return []
    covered = dict.fromkeys(
        rule.staff_id
        for rule in schedule.rules
        if _rule_on(rule, day) and _covers(schedule, rule, day, starts_at)
    )
    return [
        (staff_id, resource_id)
        for staff_id in covered
        for resource_id in schedule.resource_ids
        if (resource_ids is None or resource_id in resource_ids)
        and _is_free(schedule, staff_id, resource_id, starts_at)
    ]


def validate_start(
    *,
    service: Service,
    location: Location,
    starts_at: datetime,
    staff_id: UUID,
    resource_id: UUID | None,
    ignore_appointment_id: UUID | None = None,
) -> bool:
    """Whether this person, with this resource, can take this start."""
    return bool(
        free_at(
            service=service,
            location=location,
            starts_at=starts_at,
            staff_ids=[staff_id],
            resource_ids=[resource_id],
            ignore_appointment_id=ignore_appointment_id,
        )
    )


def _check_horizon(from_date: date, to_date: date) -> None:
    if to_date < from_date or (to_date - from_date).days > settings.BOOKING_SLOT_HORIZON_DAYS:
        raise ValidationError("Horyzont wyszukiwania terminów jest nieprawidłowy.")


def _search(
    service_id: UUID,
    location_id: UUID,
    from_date: date,
    to_date: date,
    *,
    staff_ids: Sequence[UUID] | None = None,
    now: datetime | None = None,
) -> _Schedule | None:
    context = require_tenant_context()
    service = Service.all_objects.filter(
        pk=service_id, organization_id=context.organization_id, active=True
    ).first()
    if service is None:
        return None
    return _load(service, location_id, _zone(), from_date, to_date, staff_ids=staff_ids, now=now)


def _zone() -> ZoneInfo:
    organization = Organization.objects.get(pk=require_tenant_context().organization_id)
    try:
        return ZoneInfo(organization.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValidationError("Organizacja ma nieprawidłową strefę czasową.") from error


def _load(
    service: Service,
    location_id: UUID,
    zone: ZoneInfo,
    from_date: date,
    to_date: date,
    *,
    staff_ids: Sequence[UUID] | None = None,
    now: datetime | None = None,
    ignore_appointment_id: UUID | None = None,
) -> _Schedule | None:
    """One query per table for the whole window, however many days it spans."""
    context = require_tenant_context()
    if (
        not service.active
        or not ServiceLocation.all_objects.filter(service=service, location_id=location_id).exists()
    ):
        return None
    eligible = ServiceStaff.all_objects.filter(service=service, staff__active=True)
    if staff_ids is not None:
        eligible = eligible.filter(staff_id__in=staff_ids)
    service_staff_ids = list(eligible.values_list("staff_id", flat=True))
    required_resource_ids = list(
        ServiceResource.all_objects.filter(service=service, required=True, resource__active=True)
        .order_by("resource_id")
        .values_list("resource_id", flat=True)
    )
    before = timedelta(minutes=service.buffer_before_minutes)
    after = timedelta(minutes=service.buffer_after_minutes)
    horizon_start = datetime.combine(from_date, time.min, zone).astimezone(UTC) - before
    horizon_end = (
        datetime.combine(to_date + timedelta(days=1), time.min, zone).astimezone(UTC) + after
    )
    staff_allocations = AppointmentStaffAllocation.all_objects.filter(
        organization_id=context.organization_id,
        staff_id__in=service_staff_ids,
        active=True,
        occupied_range__overlap=(horizon_start, horizon_end),
    )
    resource_allocations = AppointmentResourceAllocation.all_objects.filter(
        organization_id=context.organization_id,
        resource_id__in=required_resource_ids,
        active=True,
        occupied_range__overlap=(horizon_start, horizon_end),
    )
    if ignore_appointment_id is not None:
        staff_allocations = staff_allocations.exclude(appointment_id=ignore_appointment_id)
        resource_allocations = resource_allocations.exclude(appointment_id=ignore_appointment_id)
    return _Schedule(
        zone=zone,
        resource_ids=[*required_resource_ids] if required_resource_ids else [None],
        earliest=(now or timezone.now()) + timedelta(minutes=service.minimum_notice_minutes),
        duration=timedelta(minutes=service.duration_minutes),
        before=before,
        after=after,
        rules=list(
            AvailabilityRule.all_objects.filter(
                organization_id=context.organization_id,
                staff_id__in=service_staff_ids,
                location_id=location_id,
                active=True,
            )
        ),
        time_off=list(
            TimeOff.all_objects.filter(
                organization_id=context.organization_id,
                starts_at__lt=horizon_end,
                ends_at__gt=horizon_start,
            ).values_list("staff_id", "resource_id", "starts_at", "ends_at")
        ),
        staff_allocations=list(staff_allocations.values_list("staff_id", "occupied_range")),
        resource_allocations=list(
            resource_allocations.values_list("resource_id", "occupied_range")
        ),
    )


def _rule_on(rule: AvailabilityRule, day: date) -> bool:
    return (
        rule.weekday == day.weekday()
        and (rule.valid_from is None or rule.valid_from <= day)
        and (rule.valid_until is None or rule.valid_until >= day)
    )


def _day_slots(schedule: _Schedule, day: date) -> Iterator[AvailableSlot]:
    """Free starts of one local day, rule by rule; lazy, so a caller may stop early."""
    schedule = _within_day(schedule, day)
    for rule in schedule.rules:
        if not _rule_on(rule, day):
            continue
        rule_ends = _valid_instants(day, rule.local_end, schedule.zone)
        if not rule_ends:
            continue
        rule_end = max(rule_ends)
        # Every start of the rule scans the person's visits: only theirs, then.
        own = replace(
            schedule,
            staff_allocations=[
                row for row in schedule.staff_allocations if row[0] == rule.staff_id
            ],
        )
        for local_start in _valid_instants(day, rule.local_start, schedule.zone):
            candidate = local_start
            while candidate + schedule.duration <= rule_end:
                if candidate >= schedule.earliest:
                    for resource_id in schedule.resource_ids:
                        if _is_free(own, rule.staff_id, resource_id, candidate):
                            yield AvailableSlot(
                                candidate, candidate + schedule.duration, rule.staff_id, resource_id
                            )
                candidate += _GRID


def _within_day(schedule: _Schedule, day: date) -> _Schedule:
    """The window's time off and visits one local day's starts can run into.

    Every candidate scans these lists; scanning the whole window's for each day
    made a booked-out month cost days times its bookings per start.
    """
    starts = datetime.combine(day, time.min, schedule.zone) - schedule.before
    ends = datetime.combine(day + timedelta(days=1), time.min, schedule.zone) + schedule.after
    return replace(
        schedule,
        time_off=[row for row in schedule.time_off if row[2] < ends and row[3] > starts],
        staff_allocations=[
            row
            for row in schedule.staff_allocations
            if row[1].lower < ends and row[1].upper > starts
        ],
        resource_allocations=[
            row
            for row in schedule.resource_allocations
            if row[1].lower < ends and row[1].upper > starts
        ],
    )


def _covers(schedule: _Schedule, rule: AvailabilityRule, day: date, starts_at: datetime) -> bool:
    """Whether `_day_slots` walking this rule would reach `starts_at`."""
    rule_ends = _valid_instants(day, rule.local_end, schedule.zone)
    return (
        bool(rule_ends)
        and starts_at + schedule.duration <= max(rule_ends)
        and any(
            starts_at >= local_start and (starts_at - local_start) % _GRID == timedelta(0)
            for local_start in _valid_instants(day, rule.local_start, schedule.zone)
        )
    )


def _valid_instants(day: date, local_time: time, zone: ZoneInfo) -> list[datetime]:
    naive = datetime.combine(day, local_time)
    values: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            values[utc] = utc
    return sorted(values)


def _is_free(
    schedule: _Schedule, staff_id: UUID, resource_id: UUID | None, candidate: datetime
) -> bool:
    """Whether the start with its buffers is clear of time off and of other visits."""
    starts_at = candidate - schedule.before
    ends_at = candidate + schedule.duration + schedule.after
    if any(
        (
            (blocked_staff_id is not None and blocked_staff_id == staff_id)
            or (
                resource_id is not None
                and blocked_resource_id is not None
                and blocked_resource_id == resource_id
            )
        )
        and blocked_from < ends_at
        and blocked_until > starts_at
        for blocked_staff_id, blocked_resource_id, blocked_from, blocked_until in schedule.time_off
    ):
        return False
    if any(
        allocated_staff_id == staff_id
        and allocation.lower < ends_at
        and allocation.upper > starts_at
        for allocated_staff_id, allocation in schedule.staff_allocations
    ):
        return False
    return not resource_id or not any(
        allocated_resource_id == resource_id
        and allocation.lower < ends_at
        and allocation.upper > starts_at
        for allocated_resource_id, allocation in schedule.resource_allocations
    )
