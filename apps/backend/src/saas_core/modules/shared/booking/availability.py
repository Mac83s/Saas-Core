from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    TimeOff,
)


@dataclass(frozen=True, slots=True)
class AvailableSlot:
    starts_at: datetime
    ends_at: datetime
    staff_id: UUID
    resource_id: UUID | None


def available_slots(
    *,
    service_id: UUID,
    location_id: UUID,
    from_date: date,
    to_date: date,
    now: datetime | None = None,
    limit: int = 250,
) -> list[AvailableSlot]:
    context = require_tenant_context()
    if to_date < from_date or (to_date - from_date).days > settings.BOOKING_SLOT_HORIZON_DAYS:
        raise ValidationError("Horyzont wyszukiwania terminów jest nieprawidłowy.")
    if not 1 <= limit <= 500:
        raise ValidationError("Limit terminów jest nieprawidłowy.")
    service = Service.all_objects.filter(
        pk=service_id, organization_id=context.organization_id, active=True
    ).first()
    if (
        service is None
        or not ServiceLocation.all_objects.filter(service=service, location_id=location_id).exists()
    ):
        return []
    organization = Organization.objects.get(pk=context.organization_id)
    try:
        zone = ZoneInfo(organization.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValidationError("Organizacja ma nieprawidłową strefę czasową.") from error
    staff_ids = list(
        ServiceStaff.all_objects.filter(service=service, staff__active=True).values_list(
            "staff_id", flat=True
        )
    )
    required_resource_ids = list(
        ServiceResource.all_objects.filter(
            service=service, required=True, resource__active=True
        ).values_list("resource_id", flat=True)
    )
    resource_ids: list[UUID | None] = [*required_resource_ids] if required_resource_ids else [None]
    current = now or timezone.now()
    earliest = current + timedelta(minutes=service.minimum_notice_minutes)
    duration = timedelta(minutes=service.duration_minutes)
    before = timedelta(minutes=service.buffer_before_minutes)
    after = timedelta(minutes=service.buffer_after_minutes)
    rules = list(
        AvailabilityRule.all_objects.filter(
            organization_id=context.organization_id,
            staff_id__in=staff_ids,
            location_id=location_id,
            active=True,
        )
    )
    horizon_start = datetime.combine(from_date, time.min, zone).astimezone(UTC) - before
    horizon_end = (
        datetime.combine(to_date + timedelta(days=1), time.min, zone).astimezone(UTC) + after
    )
    time_off = list(
        TimeOff.all_objects.filter(
            organization_id=context.organization_id,
            starts_at__lt=horizon_end,
            ends_at__gt=horizon_start,
        ).values_list("staff_id", "resource_id", "starts_at", "ends_at")
    )
    staff_allocations = list(
        AppointmentStaffAllocation.all_objects.filter(
            organization_id=context.organization_id,
            staff_id__in=staff_ids,
            active=True,
            occupied_range__overlap=(horizon_start, horizon_end),
        ).values_list("staff_id", "occupied_range")
    )
    resource_allocations = list(
        AppointmentResourceAllocation.all_objects.filter(
            organization_id=context.organization_id,
            resource_id__in=required_resource_ids,
            active=True,
            occupied_range__overlap=(horizon_start, horizon_end),
        ).values_list("resource_id", "occupied_range")
    )
    results: list[AvailableSlot] = []
    day = from_date
    while day <= to_date:
        day_rules = (
            rule
            for rule in rules
            if rule.weekday == day.weekday()
            and (rule.valid_from is None or rule.valid_from <= day)
            and (rule.valid_until is None or rule.valid_until >= day)
        )
        for rule in day_rules:
            for local_start in _valid_instants(day, rule.local_start, zone):
                rule_ends = _valid_instants(day, rule.local_end, zone)
                if not rule_ends:
                    continue
                rule_end = max(rule_ends)
                candidate = local_start
                while candidate + duration <= rule_end:
                    if candidate >= earliest:
                        occupied_from = candidate - before
                        occupied_until = candidate + duration + after
                        for resource_id in resource_ids:
                            if _is_free(
                                rule.staff_id,
                                resource_id,
                                occupied_from,
                                occupied_until,
                                time_off=time_off,
                                staff_allocations=staff_allocations,
                                resource_allocations=resource_allocations,
                            ):
                                results.append(
                                    AvailableSlot(
                                        candidate, candidate + duration, rule.staff_id, resource_id
                                    )
                                )
                                if len(results) >= limit:
                                    return sorted(
                                        results,
                                        key=lambda item: (
                                            item.starts_at,
                                            str(item.staff_id),
                                            str(item.resource_id),
                                        ),
                                    )
                    candidate += timedelta(minutes=5)
        day += timedelta(days=1)
    unique = {(item.starts_at, item.staff_id, item.resource_id): item for item in results}
    return sorted(
        unique.values(),
        key=lambda item: (item.starts_at, str(item.staff_id), str(item.resource_id)),
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
    staff_id: UUID,
    resource_id: UUID | None,
    starts_at: datetime,
    ends_at: datetime,
    *,
    time_off: Sequence[tuple[UUID | None, UUID | None, datetime, datetime]],
    staff_allocations: Sequence[tuple[UUID, Any]],
    resource_allocations: Sequence[tuple[UUID, Any]],
) -> bool:
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
        for blocked_staff_id, blocked_resource_id, blocked_from, blocked_until in time_off
    ):
        return False
    if any(
        allocated_staff_id == staff_id
        and allocation.lower < ends_at
        and allocation.upper > starts_at
        for allocated_staff_id, allocation in staff_allocations
    ):
        return False
    return not resource_id or not any(
        allocated_resource_id == resource_id
        and allocation.lower < ends_at
        and allocation.upper > starts_at
        for allocated_resource_id, allocation in resource_allocations
    )
