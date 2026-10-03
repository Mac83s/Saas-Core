"""The company's people as booking keeps them (ADR-058 §1, §9).

A person is a `StaffMember`, with an account or without one (a subcontractor).
The team screen joins these rows with the organization's memberships and
invitations; the calendar books a person by their services and hours.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import Any, NoReturn
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import field_changes, record_audit
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.lifecycle import (
    create_invitation,
    revoke_invitation,
    update_membership,
)
from saas_core.modules.core.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
)
from saas_core.modules.core.organizations.permissions import (
    MEMBERS_MANAGE,
    MEMBERS_MANAGE_LIMITED,
    MEMBERS_READ,
)
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.modules.shared.profiles.api import (
    create_person_profile,
    person_names,
    remove_person_profile,
    rename_person_profile,
)

from .availability import _rule_on, _valid_instants, _zone
from .crew import take_off
from .models import (
    AppointmentStaffAllocation,
    AvailabilityRule,
    Location,
    QueueReason,
    Service,
    ServiceLocation,
    ServiceStaff,
    StaffMember,
    StaffTeam,
    StaffTeamMember,
    TimeOff,
)
from .services import BOOKING_ENABLED, BOOKING_MANAGE, BOOKING_READ, _assert_member_of
from .setup import Saved, check_version, setup_write

#: Own hours and time off, where the product lets a working role set them
#: (owner's answer 7: Business yes, HoofCare's trimmer no).
SCHEDULE_OWN = "booking.schedule.own"

# `slugify` drops what NFKD cannot fold: "Łukasz" would become "ukasz".
_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


@dataclass(frozen=True, slots=True)
class Person:
    staff: StaffMember
    #: Active services the person does; with hours, that is "takes visits".
    service_ids: list[UUID]
    has_hours: bool
    #: Phone and reasons of absence: management and the person only (ADR-058 §9).
    private: bool
    #: The standing groups the person belongs to (ADR-058 §2).
    team_ids: list[UUID] = field(default_factory=list)
    #: „Pokazuj klientom”: the name customers see, or None (ADR-058 §8).
    public_name: str | None = None


@dataclass(frozen=True, slots=True)
class PersonDetail:
    person: Person
    hours: list[AvailabilityRule]
    time_off: list[TimeOff]


@dataclass(frozen=True, slots=True)
class Hours:
    """One weekly rule as the panel sends it: a local weekday and times."""

    weekday: int
    local_start: time
    local_end: time
    location_id: UUID


@dataclass(frozen=True, slots=True)
class PersonDay:
    staff_id: UUID
    works: list[tuple[datetime, datetime]]
    time_off: list[tuple[datetime, datetime, str | None]]
    busy: list[tuple[datetime, datetime]]


def _management(context: TenantContext) -> bool:
    """Who runs the team: assigns visits or manages its members."""
    return any(
        context.has_permission(permission)
        for permission in (BOOKING_MANAGE, MEMBERS_MANAGE, MEMBERS_MANAGE_LIMITED)
    )


def _own(context: TenantContext, staff: StaffMember) -> bool:
    return staff.membership_id is not None and staff.membership_id == context.membership_id


def _actor(context: TenantContext) -> User | None:
    return User.objects.filter(pk=context.actor_id).first()


def _read() -> TenantContext:
    # A read: it keeps working when the plan has lapsed to read-only.
    return authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)


def _people(context: TenantContext, staff: list[StaffMember]) -> list[Person]:
    ids = [item.id for item in staff]
    services: dict[UUID, list[UUID]] = {}
    for staff_id, service_id in (
        ServiceStaff.all_objects.filter(
            organization_id=context.organization_id, staff_id__in=ids, service__active=True
        )
        .order_by("service__name", "service_id")
        .values_list("staff_id", "service_id")
    ):
        services.setdefault(staff_id, []).append(service_id)
    with_hours = set(
        AvailabilityRule.all_objects.filter(
            organization_id=context.organization_id, staff_id__in=ids, active=True
        ).values_list("staff_id", flat=True)
    )
    teams: dict[UUID, list[UUID]] = {}
    for staff_id, team_id in (
        StaffTeamMember.all_objects.filter(
            organization_id=context.organization_id, staff_id__in=ids
        )
        .order_by("team__name", "team_id")
        .values_list("staff_id", "team_id")
    ):
        teams.setdefault(staff_id, []).append(team_id)
    names = person_names(context.organization_id, (item.profile_id for item in staff))
    management = _management(context)
    return [
        Person(
            item,
            services.get(item.id, []),
            item.id in with_hours,
            management or _own(context, item),
            teams.get(item.id, []),
            names.get(item.profile_id) if item.profile_id else None,
        )
        for item in staff
    ]


def list_people(*, mine: bool = False) -> list[Person]:
    """Everyone for whoever may see the team; one's own entry for anyone else,
    so a trimmer without the team screen still has "my card"."""
    context = _read()
    query = StaffMember.all_objects.filter(organization_id=context.organization_id)
    if mine or not context.has_permission(MEMBERS_READ):
        query = query.filter(membership_id=context.membership_id)
    return _people(context, list(query.order_by("display_name", "id")))


def person_detail(staff_id: UUID) -> PersonDetail:
    context = _read()
    staff = StaffMember.all_objects.filter(
        organization_id=context.organization_id, pk=staff_id
    ).first()
    if staff is None or not (context.has_permission(MEMBERS_READ) or _own(context, staff)):
        raise NotFound("Nie ma takiego pracownika.")
    zone = _zone()
    today = datetime.combine(timezone.localdate(timezone=zone), time.min, zone)
    return PersonDetail(
        _people(context, [staff])[0],
        list(
            AvailabilityRule.all_objects.filter(
                organization_id=context.organization_id, staff=staff, active=True
            )
            .select_related("location")
            .order_by("weekday", "local_start", "id")
        ),
        # What is still ahead, and what is going on today.
        list(
            TimeOff.all_objects.filter(
                organization_id=context.organization_id, staff=staff, ends_at__gt=today
            ).order_by("starts_at", "id")
        ),
    )


def _free_slug(organization_id: UUID, name: str) -> str:
    base = slugify(name.translate(_FOLD))[:72] or "osoba"
    slug, number = base, 1
    taken = StaffMember.all_objects.filter(organization_id=organization_id)
    while taken.filter(public_slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    return slug


def _locked(context: TenantContext, staff_id: UUID) -> StaffMember:
    staff = (
        StaffMember.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, pk=staff_id)
        .first()
    )
    if staff is None:
        raise NotFound("Nie ma takiego pracownika.")
    return staff


def _only_location(organization_id: UUID) -> UUID:
    locations = list(
        Location.all_objects.filter(organization_id=organization_id, active=True).values_list(
            "pk", flat=True
        )[:2]
    )
    if len(locations) != 1:
        raise ValidationError({
            "location_id": (
                "Wybierz miejsce pracy."
                if locations
                else "Najpierw dodaj miejsce pracy w Ustawieniach › Usługi i grafik."
            )
        })
    return locations[0]


def _weekly(organization_id: UUID, value: dict[str, Any]) -> list[Hours]:
    """The same hours on the chosen weekdays, as the add dialog asks for them."""
    location_id = value.get("location_id") or _only_location(organization_id)
    return [
        Hours(day, value["local_start"], value["local_end"], location_id)
        for day in sorted(set(value["weekdays"]))
    ]


def _copied_hours(organization_id: UUID, staff_id: UUID) -> list[Hours]:
    """Another person's week, rule by rule ("hours like …")."""
    if not StaffMember.all_objects.filter(organization_id=organization_id, pk=staff_id).exists():
        raise ValidationError({"copy_hours_from": "Nie ma takiego pracownika."})
    return [
        Hours(rule.weekday, rule.local_start, rule.local_end, rule.location_id)
        for rule in AvailabilityRule.all_objects.filter(
            organization_id=organization_id, staff_id=staff_id, active=True
        )
    ]


def _offer_where_worked(staff: StaffMember) -> None:
    """A service is bookable where somebody who does it works — the link the
    settings form has always created alongside the hours."""
    organization_id = staff.organization_id
    services = set(
        ServiceStaff.all_objects.filter(organization_id=organization_id, staff=staff).values_list(
            "service_id", flat=True
        )
    )
    locations = set(
        AvailabilityRule.all_objects.filter(
            organization_id=organization_id, staff=staff, active=True
        ).values_list("location_id", flat=True)
    )
    for service_id in services:
        for location_id in locations:
            ServiceLocation.all_objects.get_or_create(
                organization_id=organization_id, service_id=service_id, location_id=location_id
            )


def _set_services(staff: StaffMember, service_ids: list[UUID]) -> None:
    wanted = set(service_ids)
    found = set(
        Service.all_objects.filter(
            organization_id=staff.organization_id, pk__in=wanted, active=True
        ).values_list("pk", flat=True)
    )
    if found != wanted:
        raise ValidationError({"service_ids": "Nie ma takiej usługi."})
    links = ServiceStaff.all_objects.filter(organization_id=staff.organization_id, staff=staff)
    links.exclude(service_id__in=wanted).delete()
    present = set(links.values_list("service_id", flat=True))
    ServiceStaff.all_objects.bulk_create([
        ServiceStaff(organization_id=staff.organization_id, service_id=service_id, staff=staff)
        for service_id in sorted(wanted - present)
    ])
    _offer_where_worked(staff)


#: Where a refusal of one weekly rule points: `rules.<i>.<field>` for a week
#: sent rule by rule (ADR-076 pkt 5).
type RulePath = Callable[[int, str], tuple[str | int, ...]]


def _rule_path(index: int, name: str) -> tuple[str | int, ...]:
    return ("rules", index, name)


def _refuse(path: tuple[str | int, ...], message: str, code: str) -> NoReturn:
    detail: Any = [ErrorDetail(message, code=code)]
    for part in reversed(path):
        detail = {part: detail}
    raise ValidationError(detail)


def _set_hours(staff: StaffMember, rules: list[Hours], at: RulePath = _rule_path) -> None:
    """Replaces the person's week. Old rules are switched off, not deleted:
    what the calendar offered last month stays readable."""
    places = set(
        Location.all_objects.filter(
            organization_id=staff.organization_id,
            active=True,
            pk__in={rule.location_id for rule in rules},
        ).values_list("pk", flat=True)
    )
    for index, rule in enumerate(rules):
        if rule.location_id not in places:
            _refuse(at(index, "location_id"), "Nie ma takiego miejsca pracy.", "location_unknown")
        if rule.local_end <= rule.local_start:
            _refuse(
                at(index, "local_end"), "Koniec pracy musi być po jej początku.", "end_before_start"
            )
    ordered = sorted(enumerate(rules), key=lambda item: (item[1].weekday, item[1].local_start))
    # One person is in one place at a time, whatever the location.
    for (_, before), (index, after) in pairwise(ordered):
        if before.weekday == after.weekday and after.local_start < before.local_end:
            _refuse(
                at(index, "local_start"),
                "Godziny jednego dnia nachodzą na siebie.",
                "hours_overlap",
            )
    AvailabilityRule.all_objects.filter(
        organization_id=staff.organization_id, staff=staff, active=True
    ).update(active=False)
    AvailabilityRule.all_objects.bulk_create([
        AvailabilityRule(
            organization_id=staff.organization_id,
            staff=staff,
            location_id=rule.location_id,
            weekday=rule.weekday,
            local_start=rule.local_start,
            local_end=rule.local_end,
        )
        for _, rule in ordered
    ])
    _offer_where_worked(staff)


@transaction.atomic
def add_person(
    *,
    name: str,
    phone: str = "",
    invitation: dict[str, str] | None = None,
    membership_id: UUID | None = None,
    service_ids: list[UUID] | None = None,
    hours: dict[str, Any] | None = None,
    copy_hours_from: UUID | None = None,
    team_ids: list[UUID] | None = None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[StaffMember]:
    """Adds an employee: the entry, the invitation when there is an e-mail, the
    services and hours when the person takes visits, and the teams they join —
    all of it or nothing.

    A setup write (ADR-072 §11): the same key again answers the first person
    instead of adding a second, and `preview` runs it and rolls it back — the
    invitation's e-mail leaves only after a commit, so a preview sends none.
    No request: the actor is the tenant context's, so the panel and the
    assistant's command come the same way.

    The invitation goes through the organization's own rules (who may invite
    whom, the plan's accounts), so a dispatcher adds a subcontractor without
    being able to hand out an administrator's account.
    """
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    data: dict[str, Any] = {
        "name": name,
        "phone": phone,
        "invitation": invitation,
        "membership_id": membership_id,
        "service_ids": service_ids,
        "hours": hours,
        "copy_hours_from": copy_hours_from,
        "team_ids": team_ids,
    }
    return setup_write(
        context=context,
        action="staff.add",
        target_id=None,
        request=data,
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _added(_write_person(context, organization, **data)),
        replay=lambda item_id: _added(
            StaffMember.all_objects.get(organization=organization, pk=item_id), replayed=True
        ),
    )


def _added(staff: StaffMember, *, replayed: bool = False) -> Saved[StaffMember]:
    return Saved(staff, staff.id, staff.hours_version, True, {}, replayed)


def _write_person(
    context: TenantContext,
    organization: Organization,
    *,
    name: str,
    phone: str,
    invitation: dict[str, str] | None,
    membership_id: UUID | None,
    service_ids: list[UUID] | None,
    hours: dict[str, Any] | None,
    copy_hours_from: UUID | None,
    team_ids: list[UUID] | None,
) -> StaffMember:
    if invitation and membership_id:
        raise ValidationError({"invitation": "Ta osoba ma już konto."})
    _assert_member_of(organization, membership_id)
    invited = (
        create_invitation(
            actor=_actor(context), email=invitation["email"], role_key=invitation["role"]
        )
        if invitation
        else None
    )
    try:
        with transaction.atomic():
            staff = StaffMember.all_objects.create(
                organization=organization,
                display_name=name,
                public_slug=_free_slug(organization.id, name),
                phone=phone,
                membership_id=membership_id,
                invitation_id=invited.id if invited else None,
            )
    except IntegrityError as error:
        raise ValidationError({
            "membership_id": "Ten członek zespołu ma już swój wpis w kalendarzu."
        }) from error
    if service_ids:
        _set_services(staff, service_ids)
    rules = (
        _copied_hours(organization.id, copy_hours_from)
        if copy_hours_from
        else _weekly(organization.id, hours)
        if hours
        else []
    )
    if rules:
        _set_hours(
            staff,
            rules,
            # The add dialog sends one set of hours for its weekdays, or names
            # the person whose week it copies.
            (lambda _index, _name: ("copy_hours_from",))
            if copy_hours_from
            else (lambda _index, name: ("hours", name)),
        )
    teams = list(dict.fromkeys(team_ids or []))
    if StaffTeam.all_objects.filter(organization=organization, pk__in=teams).count() != len(teams):
        raise ValidationError({"team_ids": "Nie ma takiego zespołu."})
    StaffTeamMember.all_objects.bulk_create([
        StaffTeamMember(organization=organization, team_id=team_id, staff=staff)
        for team_id in teams
    ])
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BOOKING_STAFF_ADDED,
        actor=_actor(context),
        target_type="staff",
        target_id=staff.id,
        metadata={
            "account": "invited" if invited else "linked" if membership_id else "none",
            "services": len(service_ids or []),
            "hours": len(rules),
        },
    )
    return staff


def _schedule_context(staff_id: UUID) -> tuple[TenantContext, StaffMember]:
    """Management sets anyone's hours and time off; a person their own where
    their role carries `booking.schedule.own` (owner's answer 7)."""
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    if not (
        context.has_permission(BOOKING_MANAGE)
        or (_own(context, staff) and context.has_permission(SCHEDULE_OWN))
    ):
        raise OrganizationPermissionDenied
    return context, staff


@transaction.atomic
def set_person_services(*, staff_id: UUID, service_ids: list[UUID]) -> PersonDetail:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    _set_services(staff, service_ids)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.BOOKING_STAFF_SERVICES_CHANGED,
        actor=_actor(context),
        target_type="staff",
        target_id=staff.id,
        metadata={"services": len(set(service_ids))},
    )
    return person_detail(staff.id)


@transaction.atomic
def set_person_hours(
    *,
    staff_id: UUID,
    rules: list[dict[str, Any]],
    expected_version: int | None = None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[PersonDetail]:
    """Replaces the person's week — at the week's version the caller saw
    (`StaffMember.hours_version`, ADR-072 §11)."""
    context, staff = _schedule_context(staff_id)
    return setup_write(
        context=context,
        action="staff.hours.set",
        target_id=staff.id,
        request={"rules": rules, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_hours(context, staff, rules, expected_version),
        replay=lambda item_id: _saved_hours(item_id, replayed=True),
    )


def _week(staff: StaffMember) -> list[list[Any]]:
    return [
        [
            rule.weekday,
            rule.local_start.isoformat("minutes"),
            rule.local_end.isoformat("minutes"),
            str(rule.location_id),
        ]
        for rule in AvailabilityRule.all_objects.filter(
            organization_id=staff.organization_id, staff=staff, active=True
        ).order_by("weekday", "local_start")
    ]


def _saved_hours(
    staff_id: UUID, *, changes: dict[str, Any] | None = None, replayed: bool = False
) -> Saved[PersonDetail]:
    detail = person_detail(staff_id)
    return Saved(
        detail, staff_id, detail.person.staff.hours_version, False, changes or {}, replayed
    )


def _write_hours(
    context: TenantContext,
    staff: StaffMember,
    rules: list[dict[str, Any]],
    expected_version: int | None,
) -> Saved[PersonDetail]:
    check_version(staff.hours_version, expected_version)
    before = _week(staff)
    _set_hours(staff, [Hours(**rule) for rule in rules])
    changes = field_changes({"hours": before}, {"hours": _week(staff)})
    if changes:
        staff.hours_version += 1
        staff.save(update_fields=["hours_version", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=OrganizationAuditAction.BOOKING_STAFF_HOURS_CHANGED,
            actor=_actor(context),
            target_type="staff",
            target_id=staff.id,
            metadata={"rules": len(rules)},
        )
    return _saved_hours(staff.id, changes=changes)


@transaction.atomic
def add_time_off(
    *, staff_id: UUID, starts_at: datetime, ends_at: datetime, reason: str = ""
) -> tuple[TimeOff, int]:
    """The absence, and how many of the person's planned visits it ran into.

    The person comes off those visits and each becomes a vacancy in
    „Do przydzielenia” (ADR-058 §3); whoever else is on them keeps their time.
    """
    context, staff = _schedule_context(staff_id)
    if ends_at <= starts_at:
        raise ValidationError({"ends_at": "Koniec nieobecności musi być po jej początku."})
    item = TimeOff.all_objects.create(
        organization_id=context.organization_id,
        staff=staff,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason,
    )
    conflicts = take_off(staff, since=starts_at, until=ends_at, reason=QueueReason.TIME_OFF)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.BOOKING_STAFF_TIME_OFF_ADDED,
        actor=_actor(context),
        target_type="staff",
        target_id=staff.id,
        # Never the reason: an illness is health data, and history is forever.
        metadata={"time_off_id": str(item.id)},
    )
    return item, conflicts


@transaction.atomic
def remove_time_off(*, time_off_id: UUID) -> None:
    context = _read()
    item = TimeOff.all_objects.filter(
        organization_id=context.organization_id, pk=time_off_id, staff__isnull=False
    ).first()
    if item is None or item.staff_id is None:
        raise NotFound("Nie ma takiej nieobecności.")
    context, staff = _schedule_context(item.staff_id)
    item.delete()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.BOOKING_STAFF_TIME_OFF_REMOVED,
        actor=_actor(context),
        target_type="staff",
        target_id=staff.id,
        metadata={"time_off_id": str(time_off_id)},
    )


@transaction.atomic
def invite_person(*, request: HttpRequest, staff_id: UUID, email: str, role: str) -> Invitation:
    """An account for someone who was added without one; accepting it links it
    to this entry. A new e-mail replaces an invitation still waiting."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    if not staff.active:
        raise ValidationError({"email": "Najpierw przywróć tę osobę."})
    if staff.membership_id is not None:
        raise ValidationError({"email": "Ta osoba ma już konto."})
    waiting = (
        Invitation.objects.filter(pk=staff.invitation_id, status=InvitationStatus.PENDING)
        .exclude(email=User.objects.normalize_email(email))
        .first()
        if staff.invitation_id
        else None
    )
    if waiting is not None:
        revoke_invitation(request=request, invitation_id=waiting.id)
    invitation = create_invitation(request=request, email=email, role_key=role)
    staff.invitation_id = invitation.id
    staff.save(update_fields=["invitation", "updated_at"])
    return invitation


@transaction.atomic
def end_person(*, request: HttpRequest, staff_id: UUID) -> StaffMember:
    """Removes a person from the company: they stop taking visits and lose their
    account and an invitation still waiting. Their planned visits become
    vacancies in „Do przydzielenia” (ADR-058 §3, announced 26.09); the others
    on those visits keep their time."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    take_off(staff, since=timezone.now(), until=None, reason=QueueReason.ENDED)
    if (
        staff.membership_id is not None
        and Membership.objects.filter(
            pk=staff.membership_id,
            status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
        ).exists()
    ):
        update_membership(
            request=request,
            membership_id=staff.membership_id,
            membership_status=MembershipStatus.REVOKED,
        )
    if (
        staff.invitation_id is not None
        and Invitation.objects.filter(
            pk=staff.invitation_id, status=InvitationStatus.PENDING
        ).exists()
    ):
        revoke_invitation(request=request, invitation_id=staff.invitation_id)
    staff.active = False
    staff.save(update_fields=["active", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.BOOKING_STAFF_ENDED,
        actor=_actor(context),
        target_type="staff",
        target_id=staff.id,
    )
    return staff


@transaction.atomic
@transaction.atomic
def set_person_public(*, staff_id: UUID, shown: bool, name: str = "") -> StaffMember:
    """„Pokazuj klientom”: the person's name on the booking form and in the
    customer's confirmation, or nowhere (ADR-036 §4, ADR-058 §8).

    Turning it off removes the public profile: a name is never left behind
    on the public side for someone the office took off it.
    """
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    was = staff.profile_id is not None
    public = name.strip() or staff.display_name
    if shown and staff.profile_id is not None:
        rename_person_profile(context.organization_id, staff.profile_id, name=public)
    elif shown:
        staff.profile = create_person_profile(
            context.organization_id, name=public, membership_id=staff.membership_id
        )
        staff.save(update_fields=["profile", "updated_at"])
    elif staff.profile_id is not None:
        profile_id = staff.profile_id
        staff.profile = None
        staff.save(update_fields=["profile", "updated_at"])
        remove_person_profile(context.organization_id, profile_id)
    if shown != was:
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=OrganizationAuditAction.BOOKING_STAFF_PUBLIC_CHANGED,
            actor=_actor(context),
            target_type="staff",
            target_id=staff.id,
            metadata={"shown": shown},
        )
    return staff


def restore_person(*, staff_id: UUID) -> StaffMember:
    """Back on the team, without the account: that takes a new invitation."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    staff = _locked(context, staff_id)
    if not staff.active:
        staff.active = True
        staff.save(update_fields=["active", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=OrganizationAuditAction.BOOKING_STAFF_RESTORED,
            actor=_actor(context),
            target_type="staff",
            target_id=staff.id,
        )
    return staff


def link_on_join(invitation: Invitation, membership: Membership) -> None:
    """The person the office added under this invitation is the one who just
    joined (ADR-058 §1). Nobody added them: a company that sells services gets
    a calendar entry for them, one that does not keeps just the account.

    Runs inside the invitation's acceptance, under its tenant, without a tenant
    context: the joining person is not a member until this transaction ends.
    """
    organization_id = invitation.organization_id
    if StaffMember.all_objects.filter(
        organization_id=organization_id, membership_id=membership.id
    ).exists():
        return
    waiting = StaffMember.all_objects.filter(
        organization_id=organization_id, membership__isnull=True
    )
    # A resent invitation is a new row; the entry still names the first one.
    staff = (
        waiting.filter(invitation_id=invitation.id).first()
        or waiting.filter(invitation__email=invitation.email).order_by("-created_at").first()
    )
    user = membership.user
    if staff is not None:
        staff.membership_id = membership.id
        staff.invitation_id = invitation.id
        staff.save(update_fields=["membership", "invitation", "updated_at"])
        action = OrganizationAuditAction.BOOKING_STAFF_LINKED
    elif Service.all_objects.filter(organization_id=organization_id, active=True).exists():
        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        name = name or user.email.split("@")[0]
        staff = StaffMember.all_objects.create(
            organization_id=organization_id,
            display_name=name,
            public_slug=_free_slug(organization_id, name),
            membership_id=membership.id,
        )
        action = OrganizationAuditAction.BOOKING_STAFF_ADDED
    else:
        return
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=action,
        actor=user,
        target_type="staff",
        target_id=staff.id,
        metadata={"invitation_id": str(invitation.id)},
    )


def people_day(day: date | None = None) -> tuple[date, str, list[PersonDay]]:
    """Who works, who is away and who is busy on one local day (ADR-058 §9) —
    one read for the team's "Today", the assignment dialog and the day board."""
    context = _read()
    zone = _zone()
    day = day or timezone.localdate(timezone=zone)
    starts = datetime.combine(day, time.min, zone)
    ends = datetime.combine(day + timedelta(days=1), time.min, zone)
    query = StaffMember.all_objects.filter(organization_id=context.organization_id, active=True)
    if not context.has_permission(MEMBERS_READ):
        query = query.filter(membership_id=context.membership_id)
    staff = list(query.order_by("display_name", "id"))
    ids = [item.id for item in staff]
    private = {item.id for item in staff if _management(context) or _own(context, item)}
    works: dict[UUID, list[tuple[datetime, datetime]]] = {}
    for rule in AvailabilityRule.all_objects.filter(
        organization_id=context.organization_id, staff_id__in=ids, active=True
    ):
        if not _rule_on(rule, day):
            continue
        # A time the spring change skips has no instant: that rule is off.
        opens = _valid_instants(day, rule.local_start, zone)
        closes = _valid_instants(day, rule.local_end, zone)
        if opens and closes:
            works.setdefault(rule.staff_id, []).append((min(opens), max(closes)))
    away: dict[UUID, list[tuple[datetime, datetime, str | None]]] = {}
    for staff_id, starts_at, ends_at, reason in (
        TimeOff.all_objects.filter(
            organization_id=context.organization_id,
            staff_id__in=ids,
            starts_at__lt=ends,
            ends_at__gt=starts,
        )
        .order_by("starts_at", "id")
        .values_list("staff_id", "starts_at", "ends_at", "reason")
    ):
        away.setdefault(staff_id, []).append((
            starts_at,
            ends_at,
            reason if staff_id in private else None,
        ))
    busy: dict[UUID, list[tuple[datetime, datetime]]] = {}
    for staff_id, taken in AppointmentStaffAllocation.all_objects.filter(
        organization_id=context.organization_id,
        staff_id__in=ids,
        active=True,
        occupied_range__overlap=(starts, ends),
    ).values_list("staff_id", "occupied_range"):
        busy.setdefault(staff_id, []).append((taken.lower, taken.upper))
    return (
        day,
        zone.key,
        [
            PersonDay(
                item.id,
                sorted(works.get(item.id, [])),
                away.get(item.id, []),
                sorted(busy.get(item.id, [])),
            )
            for item in staff
        ],
    )
