"""Stays: an offer booked from–to — nights, days (ADR-072 §1, §3, §5; phase 2c).

A stay is an `Appointment` like a visit, with the same customer, history,
self-service link and reminder, but it takes a unit instead of people
(`staff_required` 0, no lead). Its time comes from the offer: a night runs
from check-in on the arrival day to check-out on the departure day, a day from
pickup on the first day to return on the last one — local times turned into
instants in the company's zone, so DST is the same code as for visits.

The rules of the arrival day apply (the season the stay starts in — a
temporary answer until the owner says how a stay across two seasons counts,
ADR-072, Konsekwencje). A closed day of the unit's place inside the stay
refuses it. The unit's time is held by an allocation under the exclusion
constraint, so of two guests racing for one cottage the database picks one;
a booking of a group tries its least busy free unit first and the next one
when it loses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext, require_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.customers.api import match_or_create
from saas_core.modules.shared.notifications.security import decrypt_secret, encrypt_secret
from saas_core.modules.shared.notifications.services import queue_email

from . import orders
from .availability import _valid_instants, _zone, closed_days
from .consents import BookingConsents
from .crew import lost_slot_race
from .models import (
    Appointment,
    AppointmentResourceAllocation,
    AppointmentStatus,
    AppointmentStatusHistory,
    BookingMutation,
    BookingRule,
    RangeUnit,
    Resource,
    ResourceGroup,
    SelfServiceRoute,
    Service,
    ServiceGroup,
    ServiceResource,
    TimeModel,
    TimeOff,
)
from .observers import RESCHEDULED, AppointmentChange
from .rules import rule_for
from .security import issue_self_service_token
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BookingIdempotencyConflict,
    CreatedAppointment,
    SlotUnavailable,
    _announce,
    _self_service_expiry,
    arm_reminder,
    local_time,
    record_new_booking,
)

if TYPE_CHECKING:
    # Imported late where it runs: the quote reads translations, whose setup
    # writes import this module's neighbours.
    from .quote import Quote

#: Without a season saying otherwise, a stay is at least one night or day.
_MIN_LENGTH = 1
#: Without a season saying otherwise, the longest stay a calendar offers.
_MAX_LENGTH = 90
#: How far around a stay a unit's load is counted when the least busy one is picked.
_LOAD_WINDOW = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Stay:
    first_day: date
    #: Night: the departure day. Day: the last day, included.
    last_day: date
    starts_at: datetime
    ends_at: datetime
    #: Nights or days.
    length: int

    def days(self, unit: str) -> list[date]:
        """The local days the stay takes: a night's departure day is not one."""
        last = self.last_day - timedelta(days=1) if unit == RangeUnit.NIGHT else self.last_day
        count = (last - self.first_day).days + 1
        return [self.first_day + timedelta(days=n) for n in range(count)]


@dataclass(frozen=True, slots=True)
class StayPlan:
    """What a booking of a stay would take: which unit, when, how long."""

    service: Service
    unit: Resource
    stay: Stay
    occupied_from: datetime
    occupied_until: datetime
    #: The other free units of the group, in the order a lost race tries them.
    fallbacks: tuple[Resource, ...] = ()
    #: What it would cost, where a preview says so (ADR-072 §7).
    quote: Quote | None = None


class StayRefused(ValidationError):
    """A stay the offer's rules or the calendar do not allow — a 400 the
    caller fixes by picking other dates (ADR-076 pkt 5)."""


def stay_bounds(service: Service, first_day: date, last_day: date, zone: ZoneInfo) -> Stay:
    """The stay's instants from its local days and the offer's times."""
    if service.time_model != TimeModel.RANGE:
        raise _refuse("service_id", "not_a_range_offer", "Ta usługa nie jest rezerwacją okresu.")
    if service.range_unit == RangeUnit.NIGHT:
        length = (last_day - first_day).days
    elif service.range_unit == RangeUnit.DAY:
        length = (last_day - first_day).days + 1
    else:
        raise _refuse(
            "service_id", "range_unit_not_ready", "Rezerwacje na godziny przyjdą później."
        )
    if length < 1:
        raise _refuse("end_date", "end_before_start", "Koniec pobytu musi być po jego początku.")
    starts_at = _instant(first_day, service.range_start_local or time(0), zone)
    ends_at = _instant(last_day, service.range_end_local or time(0), zone)
    if ends_at <= starts_at:
        raise _refuse("end_date", "end_before_start", "Koniec pobytu musi być po jego początku.")
    return Stay(first_day, last_day, starts_at, ends_at, length)


def stay_starts(
    *,
    service_id: UUID,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    from_date: date,
    to_date: date,
    now: datetime | None = None,
) -> list[date]:
    """The days a stay can begin on (ADR-072 §5, T7): a unit is free for the
    shortest stay the season allows from that day. One query per table for
    the whole window, which may span up to `BOOKING_PERIOD_HORIZON_DAYS`."""
    _read()
    if to_date < from_date or (to_date - from_date).days > settings.BOOKING_PERIOD_HORIZON_DAYS:
        raise ValidationError({"to": "Zakres dni jest nieprawidłowy."}, code="invalid")
    service, units = _offer(service_id, resource_id, group_id)
    if not units:
        return []
    zone = _zone()
    calendar = _Calendar.load(service, units, from_date, to_date + timedelta(days=_MAX_LENGTH))
    moment = now or timezone.now()
    days: list[date] = []
    day = from_date
    while day <= to_date:
        if any(calendar.shortest(service, unit, day, zone, moment) for unit in units):
            days.append(day)
        day += timedelta(days=1)
    return days


def stay_ends(
    *,
    service_id: UUID,
    start_date: date,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    now: datetime | None = None,
) -> list[date]:
    """The days a stay beginning on `start_date` can end on (a night's
    departure day, a day's last day), for any free unit."""
    _read()
    service, units = _offer(service_id, resource_id, group_id)
    if not units:
        return []
    zone = _zone()
    calendar = _Calendar.load(service, units, start_date, start_date + timedelta(days=366))
    moment = now or timezone.now()
    ends: set[date] = set()
    for unit in units:
        ends.update(calendar.ends(service, unit, start_date, zone, moment))
    return sorted(ends)


def plan_stay(
    *,
    service_id: UUID,
    start_date: date,
    end_date: date,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    ignore_appointment_id: UUID | None = None,
    now: datetime | None = None,
    people: int | None = None,
) -> StayPlan:
    """The unit a stay would take, or the reason none can: the first rule it
    breaks, a closed day, or no free unit (409 `slot_unavailable`). With
    `people` — how many of those who come count towards capacity — only a
    unit that takes them is picked, the least busy of those."""
    service, units = _offer(service_id, resource_id, group_id)
    if not units:
        raise SlotUnavailable
    if people is not None:
        # Fit first, load second: a smaller unit being less busy is no reason
        # to refuse a party the larger one takes.
        fitting = [unit for unit in units if unit.capacity is None or unit.capacity >= people]
        if not fitting:
            most = max(unit.capacity or 0 for unit in units)
            raise _refuse(
                "participants",
                "unit_capacity_exceeded",
                f"Najwięcej osób w jednej jednostce: {most}.",
            )
        units = fitting
    zone = _zone()
    stay = stay_bounds(service, start_date, end_date, zone)
    calendar = _Calendar.load(
        service, units, start_date, end_date, ignore_appointment_id=ignore_appointment_id
    )
    moment = now or timezone.now()
    refusal: StayRefused | None = None
    taken = False
    free: list[Resource] = []
    for unit in units:
        problem = calendar.problem(service, unit, stay, moment)
        if problem is not None:
            refusal = refusal or problem
        elif calendar.free(unit, *calendar.occupied(service, unit, stay)):
            free.append(unit)
        else:
            taken = True
    if not free:
        # The season says why when it refused every unit; a taken one is 409.
        if refusal is not None and not taken:
            raise refusal
        raise SlotUnavailable
    ordered = calendar.by_load(free, stay)
    occupied_from, occupied_until = calendar.occupied(service, ordered[0], stay)
    return StayPlan(service, ordered[0], stay, occupied_from, occupied_until, tuple(ordered[1:]))


def stay_to_price(
    *,
    service_id: UUID,
    start_date: date,
    end_date: date,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    people: int | None = None,
) -> tuple[Service, Resource, Stay]:
    """The unit and the days a price is asked about, whether or not the stay
    could be booked: a taken unit, a season's rule, a closed day and an offer
    still switched off do not stop it. The price list's preview asks this
    (phase 3e); a booking asks `plan_stay`. Of the units asked about, the
    first by name that takes `people`."""
    service, units = _offer(service_id, resource_id, group_id, switched_off=True)
    if not units:
        raise NotFound("Ta oferta nie ma jednostek.")
    fitting = [
        unit for unit in units if people is None or unit.capacity is None or unit.capacity >= people
    ]
    # No unit takes them all: the quote says so, with the largest one's number.
    unit = fitting[0] if fitting else max(units, key=lambda unit: unit.capacity or 0)
    return service, unit, stay_bounds(service, start_date, end_date, _zone())


@transaction.atomic
def book_stay(
    *,
    service_id: UUID,
    start_date: date,
    end_date: date,
    customer_data: dict[str, str],
    idempotency_key: str,
    principal_ref: str,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    customer_notes: str = "",
    participants: Sequence[Mapping[str, Any]] | None = None,
    extras: Sequence[Mapping[str, Any]] | None = None,
    quote_digest: str = "",
    preview: bool = False,
    consents: BookingConsents | None = None,
) -> CreatedAppointment | StayPlan:
    """Books a stay from the panel; with `preview`, says which unit it would
    take and refuses what the booking would, with nothing written.

    `participants` — who comes (`[{"category_id", "count"}]`; one standard
    person when empty); `extras` — the optional extras picked
    (`[{"extra_id", "quantity"}]`). The price is worked out here and frozen in
    the booking;
    `quote_digest` is the digest of the quote the caller showed, and another
    price by now is 409 `quote_changed` (ADR-072 §7). `consents` — the
    documents the customer accepted, when the caller showed them
    (`consents.record`)."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    people = _people(context.organization_id, participants)
    if preview:
        plan = plan_stay(
            service_id=service_id,
            start_date=start_date,
            end_date=end_date,
            resource_id=resource_id,
            group_id=group_id,
            people=people,
        )
        return replace(
            plan,
            quote=stay_quote(
                plan,
                participants=participants,
                extras=extras,
                locale=customer_data.get("locale") or None,
            ),
        )
    request_hash = _hash({
        "stay": True,
        "service_id": str(service_id),
        "resource_id": str(resource_id) if resource_id else None,
        "group_id": str(group_id) if group_id else None,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "customer": customer_data,
        **({"notes": customer_notes} if customer_notes else {}),
        **(
            {
                "participants": [
                    [str(line.get("category_id") or ""), int(line["count"])]
                    for line in participants
                ]
            }
            if participants
            else {}
        ),
        **(
            {"extras": [[str(line["extra_id"]), int(line.get("quantity") or 1)] for line in extras]}
            if extras
            else {}
        ),
    })
    with connection.cursor() as cursor:
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
    plan = plan_stay(
        service_id=service_id,
        start_date=start_date,
        end_date=end_date,
        resource_id=resource_id,
        group_id=group_id,
        people=people,
    )
    organization = Organization.objects.get(pk=context.organization_id)
    customer, email = match_or_create(organization, customer_data)
    token, digest = issue_self_service_token()
    expires = _self_service_expiry(plan.stay.ends_at)
    appointment = Appointment.all_objects.create(
        organization=organization,
        customer=customer,
        service=plan.service,
        staff=None,
        location_id=_location_of(plan.service, plan.unit),
        resource=plan.unit,
        requested_group_id=group_id,
        starts_at=plan.stay.starts_at,
        ends_at=plan.stay.ends_at,
        occupied_from=plan.occupied_from,
        occupied_until=plan.occupied_until,
        timezone=organization.timezone,
        service_name=plan.service.name,
        customer_service_name=_customer_service_name(plan.service, customer.locale),
        self_service_token_ciphertext=encrypt_secret(token),
        self_service_expires_at=expires,
        staff_required=0,
        crew_version=1,
        customer_notes=customer_notes.strip()[:500],
    )
    unit = _hold(appointment, plan)
    # The unit that was held, not the one planned: a lost race takes another.
    _freeze(appointment, unit, plan.stay, participants, extras, quote_digest)
    record_new_booking(
        organization,
        appointment,
        customer,
        email=email,
        token=token,
        digest=digest,
        expires=expires,
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        walk_in=False,
        metadata={
            "starts_at": plan.stay.starts_at.isoformat(),
            "ends_at": plan.stay.ends_at.isoformat(),
            "resource": str(unit.id),
        },
        consents=consents,
        asked_locale=customer_data.get("locale"),
    )
    return CreatedAppointment(appointment, token, True)


@transaction.atomic
def move_stay(
    *,
    appointment_id: UUID,
    start_date: date,
    end_date: date,
    idempotency_key: str,
    principal_ref: str,
    quote_digest: str = "",
    preview: bool = False,
) -> Appointment | StayPlan:
    """Moves a stay to other dates: its unit when it is free then, otherwise
    another free unit of the group it was booked in (ADR-072, Konsekwencje).
    A stay that has a quote is priced again for the new dates."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    appointment = (
        Appointment.all_objects.select_for_update()
        .filter(pk=appointment_id, organization_id=context.organization_id)
        .first()
    )
    if appointment is None or appointment.status != AppointmentStatus.CONFIRMED:
        raise NotFound("Aktywna rezerwacja nie istnieje.")
    if appointment.service.time_model != TimeModel.RANGE:
        raise _refuse("appointment_id", "not_a_stay", "To nie jest pobyt.")
    request_hash = _hash({"start_date": start_date.isoformat(), "end_date": end_date.isoformat()})
    existing = BookingMutation.all_objects.filter(
        organization_id=context.organization_id,
        action="reschedule",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
    ).first()
    if existing and not preview:
        if existing.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return appointment
    # The people it was booked for, as its quote keeps them.
    people = (
        _people(context.organization_id, appointment.quote.get("participants"), kept=True)
        if appointment.quote is not None
        else None
    )
    try:
        plan = plan_stay(
            service_id=appointment.service_id,
            start_date=start_date,
            end_date=end_date,
            resource_id=appointment.resource_id,
            ignore_appointment_id=appointment.id,
            people=people,
        )
    except (SlotUnavailable, StayRefused):
        if appointment.requested_group_id is None:
            raise
        plan = plan_stay(
            service_id=appointment.service_id,
            start_date=start_date,
            end_date=end_date,
            group_id=appointment.requested_group_id,
            ignore_appointment_id=appointment.id,
            people=people,
        )
    if preview:
        if appointment.quote is None:
            return plan
        return replace(
            plan,
            quote=stay_quote(
                plan,
                participants=appointment.quote.get("participants"),
                extras=appointment.quote.get("extras"),
                locale=appointment.customer.locale,
                kept=True,
            ),
        )
    AppointmentResourceAllocation.all_objects.filter(appointment=appointment, active=True).update(
        active=False
    )
    previous = appointment.starts_at
    appointment.starts_at, appointment.ends_at = plan.stay.starts_at, plan.stay.ends_at
    appointment.occupied_from, appointment.occupied_until = (
        plan.occupied_from,
        plan.occupied_until,
    )
    expires = max(appointment.self_service_expires_at, plan.stay.ends_at)
    if expires != appointment.self_service_expires_at:
        appointment.self_service_expires_at = expires
        SelfServiceRoute.objects.filter(
            appointment_id=appointment.id, revoked_at__isnull=True
        ).update(expires_at=expires)
    appointment.save(
        update_fields=[
            "starts_at",
            "ends_at",
            "occupied_from",
            "occupied_until",
            "self_service_expires_at",
            "updated_at",
        ]
    )
    unit = _hold(appointment, plan)
    if appointment.quote is not None:
        _freeze(
            appointment,
            unit,
            plan.stay,
            appointment.quote.get("participants"),
            appointment.quote.get("extras"),
            quote_digest,
            kept=True,
        )
        orders.repriced(appointment)
    mutation = BookingMutation.all_objects.create(
        organization_id=context.organization_id,
        appointment=appointment,
        action="reschedule",
        principal_ref=principal_ref,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    arm_reminder(appointment)
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
            template_version=2,
            locale=customer.locale,
            template_context={
                "organization_name": organization.name,
                "previous_starts_at": local_time(previous, appointment.timezone, customer.locale),
                "starts_at": local_time(
                    appointment.starts_at, appointment.timezone, customer.locale
                ),
            },
            idempotency_key=f"booking-reschedule:{mutation.id}",
            causation_id=f"booking:{appointment.id}",
        )
    record_audit(
        organization=organization,
        action="booking.appointment.rescheduled",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="appointment",
        target_id=appointment.id,
        metadata={"starts_at": appointment.starts_at.isoformat(), "resource": str(unit.id)},
    )
    _announce(
        AppointmentChange(
            change=RESCHEDULED,
            organization_id=organization.id,
            appointment_id=appointment.id,
            previous_starts_at=previous,
            starts_at=appointment.starts_at,
            previous_status=appointment.status,
            status=appointment.status,
            timezone=appointment.timezone,
        )
    )
    return appointment


class _Calendar:
    """Everything one stay search reads, loaded once: the units' busy time,
    the seasons and the closed days."""

    def __init__(
        self,
        organization_id: UUID,
        units: Sequence[Resource],
        busy: dict[UUID, list[tuple[datetime, datetime]]],
        rules: list[BookingRule],
        closed: dict[UUID | None, frozenset[date]],
        zone: ZoneInfo,
    ) -> None:
        self.zone = zone
        self.organization_id = organization_id
        self.units = units
        self.busy = busy
        self.rules = rules
        self.closed = closed

    @classmethod
    def load(
        cls,
        service: Service,
        units: Sequence[Resource],
        first: date,
        last: date,
        *,
        ignore_appointment_id: UUID | None = None,
    ) -> _Calendar:
        context = require_tenant_context()
        start = datetime.combine(first - timedelta(days=1), time.min, UTC)
        end = datetime.combine(last + timedelta(days=2), time.min, UTC)
        ids = [unit.id for unit in units]
        busy: dict[UUID, list[tuple[datetime, datetime]]] = {unit.id: [] for unit in units}
        allocations = AppointmentResourceAllocation.all_objects.filter(
            organization_id=context.organization_id,
            resource_id__in=ids,
            active=True,
            occupied_range__overlap=(start, end),
        )
        if ignore_appointment_id is not None:
            allocations = allocations.exclude(appointment_id=ignore_appointment_id)
        for resource_id, taken in allocations.values_list("resource_id", "occupied_range"):
            busy[resource_id].append((taken.lower, taken.upper))
        # A block that could not hold its time still keeps the unit busy (ADR-075 pkt 6).
        for resource_id, starts_at, ends_at in TimeOff.all_objects.filter(
            organization_id=context.organization_id,
            resource_id__in=ids,
            starts_at__lt=end,
            ends_at__gt=start,
        ).values_list("resource_id", "starts_at", "ends_at"):
            busy[resource_id].append((starts_at, ends_at))
        groups = {unit.group_id for unit in units if unit.group_id}
        rules = list(
            BookingRule.all_objects.filter(
                Q(service=service) | Q(group_id__in=groups) | Q(resource_id__in=ids),
                organization_id=context.organization_id,
                active=True,
                starts_on__lte=last,
                ends_on__gte=first - timedelta(days=1),
            )
        )
        closed = {
            place: closed_days(context.organization_id, place, first, last)
            for place in {unit.location_id for unit in units}
        }
        return cls(context.organization_id, units, busy, rules, closed, _zone())

    def rule(self, service: Service, unit: Resource, day: date) -> BookingRule | None:
        return rule_for(
            self.rules,
            day=day,
            service_id=service.id,
            group_id=unit.group_id,
            resource_id=unit.id,
        )

    def occupied(self, service: Service, unit: Resource, stay: Stay) -> tuple[datetime, datetime]:
        """The stay's hold on the unit: with the offer's break before, and the
        season's break after (cleaning) or the offer's."""
        rule = self.rule(service, unit, stay.first_day)
        after = (
            rule.buffer_after_minutes
            if rule is not None and rule.buffer_after_minutes is not None
            else service.buffer_after_minutes
        )
        return (
            stay.starts_at - timedelta(minutes=service.buffer_before_minutes),
            stay.ends_at + timedelta(minutes=after),
        )

    def free(self, unit: Resource, starts: datetime, ends: datetime) -> bool:
        return not any(lower < ends and upper > starts for lower, upper in self.busy[unit.id])

    def problem(
        self, service: Service, unit: Resource, stay: Stay, now: datetime
    ) -> StayRefused | None:
        """The first thing the season or a closed day says against the stay."""
        rule = self.rule(service, unit, stay.first_day)
        minimum = (rule.min_length if rule else None) or _MIN_LENGTH
        notice = (
            timedelta(hours=rule.notice_hours)
            if rule is not None and rule.notice_hours is not None
            else timedelta(minutes=service.minimum_notice_minutes)
        )
        checks: Iterable[tuple[bool, str, str, str]] = (
            (
                rule is not None and rule.closed,
                "start_date",
                "rule_closed",
                "W tym sezonie nie przyjmujemy rezerwacji.",
            ),
            (
                stay.starts_at < now + notice,
                "start_date",
                "rule_notice",
                "Na ten termin jest już za późno.",
            ),
            (
                rule is not None
                and rule.window_days is not None
                and stay.first_day
                > now.astimezone(self.zone).date() + timedelta(days=rule.window_days),
                "start_date",
                "rule_window",
                "Tak daleko naprzód jeszcze nie przyjmujemy rezerwacji.",
            ),
            (
                bool(rule and rule.start_weekdays)
                and stay.first_day.weekday() not in (rule.start_weekdays if rule else []),
                "start_date",
                "rule_start_weekday",
                "W tym sezonie pobyt zaczyna się w inny dzień tygodnia.",
            ),
            (
                bool(rule and rule.end_weekdays)
                and stay.last_day.weekday() not in (rule.end_weekdays if rule else []),
                "end_date",
                "rule_end_weekday",
                "W tym sezonie pobyt kończy się w inny dzień tygodnia.",
            ),
            (
                stay.length < minimum,
                "end_date",
                "rule_min_length",
                f"Najkrótszy pobyt w tym terminie to {minimum}.",
            ),
            (
                rule is not None and rule.max_length is not None and stay.length > rule.max_length,
                "end_date",
                "rule_max_length",
                f"Najdłuższy pobyt w tym terminie to {rule.max_length if rule else 0}.",
            ),
            (
                rule is not None
                and rule.length_multiple is not None
                and stay.length % rule.length_multiple != 0,
                "end_date",
                "rule_length_multiple",
                f"W tym terminie pobyt trwa wielokrotność {rule.length_multiple if rule else 1}.",
            ),
            (
                any(
                    day in self.closed.get(unit.location_id, frozenset())
                    for day in stay.days(service.range_unit)
                ),
                "start_date",
                "closed_day",
                "W tym czasie firma jest zamknięta.",
            ),
        )
        for broken, field, code, message in checks:
            if broken:
                return _refuse(field, code, message)
        return None

    def shortest(
        self, service: Service, unit: Resource, day: date, zone: ZoneInfo, now: datetime
    ) -> bool:
        """Whether some stay of the unit can begin on `day`."""
        return next(self.ends(service, unit, day, zone, now, first_only=True), None) is not None

    def ends(
        self,
        service: Service,
        unit: Resource,
        start: date,
        zone: ZoneInfo,
        now: datetime,
        *,
        first_only: bool = False,
    ) -> Iterator[date]:
        rule = self.rule(service, unit, start)
        longest = (rule.max_length if rule and rule.max_length else None) or _MAX_LENGTH
        offset = 0 if service.range_unit == RangeUnit.DAY else 1
        for length in range(1, longest + 1):
            last = start + timedelta(days=length - 1 + offset)
            try:
                stay = stay_bounds(service, start, last, zone)
            except StayRefused:
                continue
            if not self.free(unit, *self.occupied(service, unit, stay)):
                # Longer stays only run further into what is taken.
                return
            if self.problem(service, unit, stay, now) is None:
                yield last
                if first_only:
                    return

    def by_load(self, units: Sequence[Resource], stay: Stay) -> list[Resource]:
        """The least busy first around the stay, then by name: the same pool
        does not wear one cottage out (ADR-058 §4 for units)."""
        start, end = stay.starts_at - _LOAD_WINDOW, stay.ends_at + _LOAD_WINDOW

        def load(unit: Resource) -> timedelta:
            return sum(
                (
                    min(upper, end) - max(lower, start)
                    for lower, upper in self.busy[unit.id]
                    if lower < end and upper > start
                ),
                timedelta(0),
            )

        return sorted(units, key=lambda unit: (load(unit), unit.name, str(unit.id)))


def _read() -> TenantContext:
    return authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)


def _offer(
    service_id: UUID,
    resource_id: UUID | None,
    group_id: UUID | None,
    *,
    switched_off: bool = False,
) -> tuple[Service, list[Resource]]:
    """The range offer and the units a stay of it may take: the one named, the
    group's, or every unit and group the offer lists. `switched_off` — an
    offer nobody can book yet is found too."""
    context = require_tenant_context()
    offers = Service.all_objects.filter(pk=service_id, organization_id=context.organization_id)
    service = (offers if switched_off else offers.filter(active=True)).first()
    if service is None or service.time_model != TimeModel.RANGE:
        raise NotFound("Nie ma takiej oferty pobytu.")
    linked_units = set(
        ServiceResource.all_objects.filter(service=service).values_list("resource_id", flat=True)
    )
    linked_groups = set(
        ServiceGroup.all_objects.filter(service=service).values_list("group_id", flat=True)
    )
    units = Resource.all_objects.filter(organization_id=context.organization_id, active=True)
    if resource_id is not None:
        units = units.filter(pk=resource_id).filter(
            Q(pk__in=linked_units) | Q(group_id__in=linked_groups)
        )
    elif group_id is not None:
        if (
            group_id not in linked_groups
            or not ResourceGroup.all_objects.filter(pk=group_id, active=True).exists()
        ):
            raise NotFound("Ta oferta nie ma takiej grupy.")
        units = units.filter(group_id=group_id)
    else:
        units = units.filter(Q(pk__in=linked_units) | Q(group_id__in=linked_groups))
    found = list(units.order_by("name", "id"))
    if resource_id is not None and not found:
        raise NotFound("Ta oferta nie ma takiej jednostki.")
    return service, found


def _location_of(service: Service, unit: Resource) -> UUID:
    """Where the stay is: the unit's place, or the offer's only one."""
    if unit.location_id is not None:
        return unit.location_id
    from .models import ServiceLocation

    places = list(
        ServiceLocation.all_objects.filter(service=service).values_list("location_id", flat=True)[
            :2
        ]
    )
    if len(places) != 1:
        raise _refuse(
            "resource_id",
            "unit_without_place",
            "Ta jednostka nie ma miejsca — ustaw je w Ustawieniach › Usługi i grafik.",
        )
    return places[0]


def _hold(appointment: Appointment, plan: StayPlan) -> Resource:
    """Takes the planned unit, or — when another booking won it a moment
    earlier — the next free one of the group; none left is 409."""
    for unit in (plan.unit, *plan.fallbacks):
        try:
            with transaction.atomic():
                AppointmentResourceAllocation.all_objects.create(
                    organization_id=appointment.organization_id,
                    appointment=appointment,
                    resource=unit,
                    occupied_range=(plan.occupied_from, plan.occupied_until),
                )
        except (IntegrityError, OperationalError) as error:
            if not lost_slot_race(error):
                raise
            continue
        if appointment.resource_id != unit.id:
            appointment.resource = unit
            appointment.location_id = _location_of(plan.service, unit)
            appointment.save(update_fields=["resource", "location", "updated_at"])
        return unit
    raise SlotUnavailable


def stay_quote(
    plan: StayPlan,
    *,
    participants: Sequence[Mapping[str, Any]] | None = None,
    extras: Sequence[Mapping[str, Any]] | None = None,
    locale: str | None = None,
    kept: bool = False,
) -> Quote:
    """What the planned stay costs; nothing is written (ADR-072 §7)."""
    from .quote import quote_stay

    return quote_stay(
        service=plan.service,
        unit=plan.unit,
        days=plan.stay.days(plan.service.range_unit),
        participants=participants,
        extras=extras,
        locale=locale,
        kept=kept,
    )


def _people(
    organization_id: UUID,
    participants: Sequence[Mapping[str, Any]] | None,
    *,
    kept: bool = False,
) -> int:
    """How many of those who come a unit has to take."""
    from .quote import people_counted

    return people_counted(organization_id, participants, kept)


def _freeze(
    appointment: Appointment,
    unit: Resource,
    stay: Stay,
    participants: Sequence[Mapping[str, Any]] | None,
    extras: Sequence[Mapping[str, Any]] | None,
    shown: str,
    *,
    kept: bool = False,
) -> None:
    """Works the stay's price out inside the booking's transaction and keeps it."""
    from .quote import assert_shown, quote_stay

    quote = quote_stay(
        service=appointment.service,
        unit=unit,
        days=stay.days(appointment.service.range_unit),
        participants=participants,
        extras=extras,
        locale=appointment.customer.locale,
        kept=kept,
    )
    assert_shown(quote, shown)
    appointment.quote, appointment.quote_digest = quote.snapshot(), quote.digest
    appointment.save(update_fields=["quote", "quote_digest", "updated_at"])


def _instant(day: date, local: time, zone: ZoneInfo) -> datetime:
    """A local wall time as an instant; the hour the clocks skip becomes the
    first one after it."""
    found = _valid_instants(day, local, zone)
    if found:
        return found[0]
    later = (datetime.combine(day, local) + timedelta(hours=1)).time()
    return _valid_instants(day, later, zone)[0]


def _refuse(field: str, code: str, message: str) -> StayRefused:
    return StayRefused({field: [ErrorDetail(message, code=code)]})


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _customer_service_name(service: Any, locale: str) -> str:
    # Imported late: the translations' setup writes import this module.
    from .item_translations import customer_service_name

    return customer_service_name(service, locale)
