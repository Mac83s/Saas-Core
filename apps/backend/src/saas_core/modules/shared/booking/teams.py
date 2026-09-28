"""Teams: standing groups of people, e.g. a crew that drives out together
(ADR-058 §2). A team is a shortcut for choosing people; it never owns a visit,
so changing or removing one leaves every booked visit as it was."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .models import StaffMember, StaffTeam, StaffTeamMember
from .services import BOOKING_ENABLED, BOOKING_MANAGE, BOOKING_READ

_TAKEN = "Zespół o tej nazwie już jest."


def list_teams() -> list[StaffTeam]:
    """Every team with its members; whoever sees the calendar may read them."""
    context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    return list(
        StaffTeam.all_objects.filter(organization_id=context.organization_id)
        .prefetch_related("members")
        .order_by("name", "id")
    )


@transaction.atomic
def create_team(*, name: str, member_ids: Sequence[UUID]) -> StaffTeam:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    clean = _name(name)
    try:
        with transaction.atomic():
            team = StaffTeam.all_objects.create(organization_id=context.organization_id, name=clean)
    except IntegrityError as error:
        raise ValidationError({"name": _TAKEN}) from error
    _set_members(team, member_ids)
    _audit(OrganizationAuditAction.BOOKING_TEAM_CREATED, context.actor_id, team)
    return team


@transaction.atomic
def update_team(
    *, team_id: UUID, name: str | None = None, member_ids: Sequence[UUID] | None = None
) -> StaffTeam:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    team = (
        StaffTeam.all_objects.select_for_update()
        .filter(pk=team_id, organization_id=context.organization_id)
        .first()
    )
    if team is None:
        raise NotFound("Nie ma takiego zespołu.")
    if name is not None and _name(name) != team.name:
        team.name = _name(name)
        try:
            with transaction.atomic():
                team.save(update_fields=["name", "updated_at"])
        except IntegrityError as error:
            raise ValidationError({"name": _TAKEN}) from error
    if member_ids is not None:
        _set_members(team, member_ids)
    _audit(OrganizationAuditAction.BOOKING_TEAM_UPDATED, context.actor_id, team)
    return team


@transaction.atomic
def delete_team(*, team_id: UUID) -> None:
    """Visits the team was chosen for keep their people; the choice itself
    reads „zespół usunięty” from then on."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    team = (
        StaffTeam.all_objects.select_for_update()
        .filter(pk=team_id, organization_id=context.organization_id)
        .first()
    )
    if team is None:
        raise NotFound("Nie ma takiego zespołu.")
    _audit(OrganizationAuditAction.BOOKING_TEAM_DELETED, context.actor_id, team)
    team.delete()


def member_ids(team: StaffTeam) -> list[UUID]:
    return [member.staff_id for member in team.members.all()]


def _name(value: str) -> str:
    clean = " ".join(value.split())
    if not clean:
        raise ValidationError({"name": "Podaj nazwę zespołu."})
    return clean[:160]


def _set_members(team: StaffTeam, staff_ids: Sequence[UUID]) -> None:
    wanted = list(dict.fromkeys(staff_ids))
    if StaffMember.all_objects.filter(pk__in=wanted, active=True).count() != len(wanted):
        raise ValidationError({"member_ids": "Nie ma takiej osoby w zespole firmy."})
    StaffTeamMember.all_objects.filter(team=team).exclude(staff_id__in=wanted).delete()
    present = set(StaffTeamMember.all_objects.filter(team=team).values_list("staff_id", flat=True))
    StaffTeamMember.all_objects.bulk_create([
        StaffTeamMember(organization_id=team.organization_id, team=team, staff_id=staff_id)
        for staff_id in wanted
        if staff_id not in present
    ])


def _audit(action: str, actor_id: UUID, team: StaffTeam) -> None:
    record_audit(
        organization=Organization.objects.get(pk=team.organization_id),
        action=action,
        actor=User.objects.filter(pk=actor_id).first(),
        target_type="team",
        target_id=team.id,
        metadata={
            "name": team.name,
            "members": [
                str(staff_id)
                for staff_id in StaffTeamMember.all_objects.filter(team_id=team.id).values_list(
                    "staff_id", flat=True
                )
            ],
        },
    )
