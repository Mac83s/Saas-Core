"""Obłożenie: the company's units against days (ADR-072 phase 2d).

One read for the grid the office books stays from: every active unit, what
holds each of them in the window — a stay, a visit that takes the room, a
block — and the days the company or a place is closed. The same few queries whatever
the window, the units or the stays (seven with the permission check, pinned by
a test), so a season's worth of days stays cheap.

Whoever reads the calendar reads the grid. Where a product narrows whose
visits a person sees (UX-023, `visibility.py`), somebody else's booking still
takes its unit — the time is not personal — but comes without its name and
without a way into it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from uuid import UUID

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .availability import _zone
from .models import (
    Appointment,
    AppointmentResourceAllocation,
    BookingClosure,
    Resource,
    Service,
    TimeModel,
    TimeOff,
)
from .services import BOOKING_ENABLED, BOOKING_READ
from .visibility import own_visits_q, sees_others

#: The longest window one read covers: two months of a grid.
MAX_DAYS = 62


@dataclass(frozen=True, slots=True)
class Held:
    """A unit taken: by a booking (`appointment`) or by a block (`block`)."""

    unit_id: UUID
    starts_at: datetime
    ends_at: datetime
    appointment: Appointment | None = None
    block: TimeOff | None = None
    #: Somebody else's booking the caller may not see (UX-023): only the time.
    hidden: bool = False

    @property
    def kind(self) -> str:
        if self.block is not None:
            return "block"
        assert self.appointment is not None
        return "stay" if self.appointment.service.time_model == TimeModel.RANGE else "visit"


@dataclass(frozen=True, slots=True)
class Occupancy:
    first: date
    last: date
    timezone: str
    units: list[Resource]
    held: list[Held]
    closures: list[BookingClosure]


def occupancy(*, first: date, last: date, group_id: UUID | None = None) -> Occupancy:
    """What holds each active unit from `first` to `last`, local days included."""
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    if last < first:
        raise ValidationError({"to": "Koniec przed początkiem."})
    if (last - first).days + 1 > MAX_DAYS:
        raise ValidationError({"to": f"Najwyżej {MAX_DAYS} dni naraz."})
    zone = _zone()
    starts = datetime.combine(first, time(), zone)
    ends = datetime.combine(last + timedelta(days=1), time(), zone)
    organization_id = context.organization_id
    units = Resource.all_objects.filter(organization_id=organization_id, active=True)
    if group_id is not None:
        units = units.filter(group_id=group_id)
    unit_list = list(units.select_related("group", "location").order_by("group__name", "name"))
    ids = [unit.id for unit in unit_list]
    held: list[Held] = []
    for allocation in AppointmentResourceAllocation.all_objects.filter(
        organization_id=organization_id,
        resource_id__in=ids,
        active=True,
        appointment__isnull=False,
        occupied_range__overlap=(starts, ends),
    ).select_related("appointment", "appointment__customer", "appointment__service"):
        booking = allocation.appointment
        assert booking is not None
        held.append(
            Held(allocation.resource_id, booking.starts_at, booking.ends_at, appointment=booking)
        )
    # Every block, holding or not: one that could not take its time still
    # keeps the unit out of search.
    held += [
        Held(block.resource_id, block.starts_at, block.ends_at, block=block)
        for block in TimeOff.all_objects.filter(
            organization_id=organization_id,
            resource_id__in=ids,
            starts_at__lt=ends,
            ends_at__gt=starts,
        )
        if block.resource_id is not None
    ]
    if not sees_others(context):
        booked = [item.appointment.pk for item in held if item.appointment is not None]
        own = set(
            Appointment.all_objects.filter(own_visits_q(context), pk__in=booked).values_list(
                "pk", flat=True
            )
        )
        held = [
            replace(item, hidden=item.appointment.pk not in own)
            if item.appointment is not None
            else item
            for item in held
        ]
    held.sort(key=lambda item: (item.starts_at, str(item.unit_id)))
    closures = list(
        BookingClosure.all_objects.filter(
            Q(location__isnull=True) | Q(location_id__in={u.location_id for u in unit_list}),
            organization_id=organization_id,
            starts_on__lte=last,
            ends_on__gte=first,
        ).order_by("starts_on")
    )
    return Occupancy(first, last, zone.key, unit_list, held, closures)


def books_stays() -> bool:
    """Whether the company sells anything by dates — the grid has a use then."""
    return Service.all_objects.filter(
        organization_id=require_tenant_context().organization_id,
        active=True,
        time_model=TimeModel.RANGE,
    ).exists()
