"""What a customer may choose on the public form (ADR-058 §8, answer 2 of
24.09): a team by its name, or a person the company shows its customers —
never the staff list itself; and of the offers booked from–to, what a guest
chooses between (ADR-072, phase 5a).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ParseError

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.profiles.api import person_names

from .crew import crew_of
from .item_translations import localized_texts, source_locale, translatable
from .models import (
    Appointment,
    ParticipantCategory,
    Resource,
    ResourceGroup,
    Service,
    ServiceGroup,
    ServiceResource,
    ServiceStaff,
    StaffChoice,
    StaffMember,
    StaffTeam,
    StaffTeamMember,
    TimeModel,
)
from .quote import from_prices
from .unit_content import amenities_in, photo_urls, town_of

#: How far ahead „od X zł/noc” looks for the lowest price: a year has every
#: season once.
FROM_PRICE_DAYS = 365


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


def public_stays(
    organization: Organization, locale: str | None, public_slug: str
) -> list[dict[str, Any]]:
    """The offers booked from–to that the company takes on its form, each with
    what a guest chooses between: a group of identical units is one choice —
    the server picks the unit (ADR-072 §3) — and a unit the offer lists by
    itself is one. Only units at places offered online (B2); an offer with
    nothing left to book is not listed. Names in `locale` where the company
    translated them. A choice carries the content of a unit the company shows
    (slice 5c) — its pictures at the form's address (`public_slug`), what it
    has, its town, never its coordinates — and „od X zł/noc” from the quote.
    A fixed number of queries, whatever the company has."""
    offers = list(
        Service.all_objects.filter(
            organization=organization, time_model=TimeModel.RANGE, online=True, active=True
        ).order_by("name", "id")
    )
    if not offers:
        return []
    linked_groups: dict[UUID, set[UUID]] = {}
    for service_id, group_id in ServiceGroup.all_objects.filter(service__in=offers).values_list(
        "service_id", "group_id"
    ):
        linked_groups.setdefault(service_id, set()).add(group_id)
    linked_units: dict[UUID, set[UUID]] = {}
    for service_id, resource_id in ServiceResource.all_objects.filter(
        service__in=offers
    ).values_list("service_id", "resource_id"):
        linked_units.setdefault(service_id, set()).add(resource_id)
    groups = {
        group.id: group
        for group in ResourceGroup.all_objects.filter(
            organization=organization,
            active=True,
            pk__in={key for keys in linked_groups.values() for key in keys},
        )
    }
    units = list(
        Resource.all_objects.filter(organization=organization, active=True)
        .exclude(location__online=False)
        .order_by("name", "id")
    )
    pools: dict[UUID, list[Resource]] = {}
    for unit in units:
        if unit.group_id in groups:
            pools.setdefault(unit.group_id, []).append(unit)
    texts = {
        "service": localized_texts(translatable("service"), offers, locale),
        "group": localized_texts(translatable("group"), groups.values(), locale),
        "resource": localized_texts(translatable("resource"), units, locale),
    }

    def words(kind: str, item: Any) -> dict[str, str]:
        found = texts[kind].get(item.id, {})
        return {
            "name": found.get("name", item.name),
            "description": found.get("description", item.description),
        }

    # „od X zł/noc” for every offer and unit it can be booked on, worked out
    # by the quote from one read of the price list.
    today = organization.local_today()
    lowest = from_prices(
        organization,
        [
            (offer, unit)
            for offer in offers
            for unit in units
            if unit.id in linked_units.get(offer.id, ())
            or unit.group_id in linked_groups.get(offer.id, ())
        ],
        [today + timedelta(days=offset) for offset in range(FROM_PRICE_DAYS)],
    )
    language = locale or source_locale(organization)

    def content(shown: Resource | None) -> dict[str, Any]:
        """What a guest sees of a unit the company shows — with the unit's
        own address, by which its page is found; nothing of another."""
        if shown is None:
            return {"public_slug": "", "photos": [], "amenities": [], "town": None}
        return {
            "public_slug": shown.public_slug,
            "photos": [photo_urls(public_slug, photo) for photo in shown.photos],
            "amenities": amenities_in(shown.amenities, language),
            "town": town_of(shown),
        }

    def cheapest(offer: Service, among: Iterable[Resource]) -> dict[str, Any] | None:
        found = [lowest[offer.id, unit.id] for unit in among if (offer.id, unit.id) in lowest]
        if not found:
            return None
        # What is charged per night or day before a price charged once.
        best = min(found, key=lambda price: (price.per == "stay", price.gross_minor))
        return {"gross_minor": best.gross_minor, "currency": best.currency, "per": best.per}

    listed = []
    for offer in offers:
        pooled = sorted(
            (
                {
                    "id": group.id,
                    **words("group", group),
                    # The most people one of its units takes; null — nobody counts.
                    "capacity": (
                        None
                        if any(unit.capacity is None for unit in pools[group.id])
                        else max(unit.capacity or 0 for unit in pools[group.id])
                    ),
                    "units": len(pools[group.id]),
                    # Identical units: the first one the company shows speaks
                    # for the group.
                    **content(next((unit for unit in pools[group.id] if unit.public), None)),
                    "from_price": cheapest(offer, pools[group.id]),
                }
                for group in (groups.get(key) for key in linked_groups.get(offer.id, ()))
                if group is not None and pools.get(group.id)
            ),
            key=lambda item: (item["name"], str(item["id"])),
        )
        single = [
            {
                "id": unit.id,
                **words("resource", unit),
                "capacity": unit.capacity,
                **content(unit if unit.public else None),
                "from_price": cheapest(offer, [unit]),
            }
            for unit in units
            if unit.id in linked_units.get(offer.id, ())
        ]
        if not pooled and not single:
            continue
        listed.append({
            "id": offer.id,
            "name": texts["service"].get(offer.id, {}).get("name", offer.name),
            "public_slug": offer.public_slug,
            "range_unit": offer.range_unit,
            "range_start_local": offer.range_start_local,
            "range_end_local": offer.range_end_local,
            "confirmation": offer.confirmation,
            "response_hours": offer.response_hours,
            "groups": pooled,
            "units": single,
        })
    return listed


def public_participant_categories(
    organization: Organization, locale: str | None
) -> list[dict[str, Any]]:
    """Who may come besides standard people, as the form asks it („Dziecko”,
    „Pies”): the company's categories that are switched on."""
    categories = list(
        ParticipantCategory.all_objects.filter(organization=organization, active=True).order_by(
            "name", "id"
        )
    )
    names = localized_texts(translatable("participant_category"), categories, locale)
    return [
        {
            "id": category.id,
            "name": names.get(category.id, {}).get("name", category.name),
            "counts_towards_capacity": category.counts_towards_capacity,
        }
        for category in categories
    ]
