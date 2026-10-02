"""What a customer may choose on the public form (ADR-058 §8, answer 2 of
24.09): a team by its name, or a person the company shows its customers —
never the staff list itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ParseError

from saas_core.modules.shared.profiles.api import person_names

from .crew import crew_of
from .models import (
    Appointment,
    Service,
    ServiceStaff,
    StaffChoice,
    StaffMember,
    StaffTeam,
    StaffTeamMember,
)


@dataclass(frozen=True, slots=True)
class PublicChoices:
    #: Per service: the teams able to take it, the people shown who do it.
    services: dict[UUID, tuple[list[UUID], list[UUID]]]
    teams: list[tuple[UUID, str]]
    people: list[tuple[UUID, str]]


def public_choices(organization_id: UUID, services: list[Service]) -> PublicChoices:
    """A team is offered for a service when enough of its current members do
    the service to staff a visit; a person when they do it and are shown."""
    performers: dict[UUID, set[UUID]] = {}
    for service_id, staff_id in ServiceStaff.all_objects.filter(
        organization_id=organization_id, staff__active=True
    ).values_list("service_id", "staff_id"):
        performers.setdefault(service_id, set()).add(staff_id)
    members: dict[UUID, set[UUID]] = {}
    for team_id, staff_id in StaffTeamMember.all_objects.filter(
        organization_id=organization_id, staff__active=True
    ).values_list("team_id", "staff_id"):
        members.setdefault(team_id, set()).add(staff_id)
    shown = dict(
        StaffMember.all_objects.filter(
            organization_id=organization_id, active=True, profile__isnull=False
        ).values_list("id", "profile_id")
    )
    names = person_names(organization_id, shown.values())
    choices: dict[UUID, tuple[list[UUID], list[UUID]]] = {}
    for service in services:
        doing = performers.get(service.id, set())
        teams = (
            [team for team, ids in members.items() if len(ids & doing) >= service.staff_count]
            if service.public_staff_choice == StaffChoice.TEAM
            else []
        )
        people = (
            [person for person in shown if person in doing]
            if service.public_staff_choice == StaffChoice.PERSON and service.staff_count == 1
            else []
        )
        choices[service.id] = (teams, people)
    team_ids = {team for teams, _ in choices.values() for team in teams}
    person_ids = {person for _, people in choices.values() for person in people}
    return PublicChoices(
        services=choices,
        teams=list(
            StaffTeam.all_objects.filter(organization_id=organization_id, pk__in=team_ids)
            .order_by("name", "id")
            .values_list("id", "name")
        ),
        people=sorted(
            ((person, names[shown[person]]) for person in person_ids if shown[person] in names),
            key=lambda item: (item[1], str(item[0])),
        ),
    )


def public_people(
    organization_id: UUID,
    service_id: UUID,
    *,
    team_id: UUID | None = None,
    person_id: UUID | None = None,
) -> tuple[list[UUID] | None, int]:
    """Who a public search or booking may use, and how many at once.

    A choice the service does not offer is refused rather than ignored: the
    customer would otherwise be shown times of somebody they did not pick.
    """
    service = Service.all_objects.filter(
        organization_id=organization_id, pk=service_id, active=True
    ).first()
    if service is None:
        return None, 1
    if team_id is not None:
        if service.public_staff_choice != StaffChoice.TEAM or not (
            StaffTeam.all_objects.filter(organization_id=organization_id, pk=team_id).exists()
        ):
            raise ParseError("Tej usługi nie rezerwuje się u wybranego zespołu.")
        return (
            list(
                StaffTeamMember.all_objects.filter(
                    organization_id=organization_id, team_id=team_id
                ).values_list("staff_id", flat=True)
            ),
            service.staff_count,
        )
    if person_id is not None:
        if (
            service.public_staff_choice != StaffChoice.PERSON
            or service.staff_count != 1
            or not StaffMember.all_objects.filter(
                organization_id=organization_id,
                pk=person_id,
                active=True,
                profile__isnull=False,
            ).exists()
        ):
            raise ParseError("Tej usługi nie rezerwuje się u wybranej osoby.")
        return [person_id], 1
    return None, service.staff_count


def shown_to_customer(appointment: Appointment) -> tuple[str | None, str | None]:
    """The team the customer chose, and „Przyjmie Cię”: the lead's public name
    when the lead is on the visit and shown to customers."""
    team = appointment.requested_team.name if appointment.requested_team is not None else None
    lead = appointment.staff
    person = None
    if lead is not None and lead.profile_id is not None and lead.id in crew_of(appointment):
        person = person_names(appointment.organization_id, [lead.profile_id]).get(lead.profile_id)
    return team, person
