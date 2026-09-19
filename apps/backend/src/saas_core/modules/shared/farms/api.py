"""Public use-case API of the farm register for other modules (ADR-051).

A vertical (HoofCare's trimming visit) points at a farm or an animal through
`FARM_MODEL` / `ANIMAL_MODEL` and reads them through the functions here, never
through the private models — the module contract puts the public surface here.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Animal, AnimalStatus, Farm
from .services import FARMS_ENABLED, FARMS_MANAGE, FARMS_READ, create_animal
from .species import normalize_identifier

#: Lazy references for another module's `ForeignKey`.
FARM_MODEL = "farms.Farm"
ANIMAL_MODEL = "farms.Animal"


def farm_for_tenant(organization_id: UUID, farm_id: UUID) -> Farm | None:
    """The farm if it belongs to this organization; None otherwise."""
    return Farm.all_objects.filter(organization_id=organization_id, id=farm_id).first()


def animal_for_tenant(organization_id: UUID, animal_id: UUID) -> Animal | None:
    """The animal if it belongs to this organization; None otherwise."""
    return Animal.all_objects.filter(organization_id=organization_id, id=animal_id).first()


def farm_animals(
    organization_id: UUID, farm_id: UUID, *, active_only: bool = True
) -> QuerySet[Animal]:
    """A farm's animals; `active_only` leaves out sold, culled and dead ones."""
    query = Animal.all_objects.filter(organization_id=organization_id, farm_id=farm_id)
    if active_only:
        query = query.filter(status=AnimalStatus.ACTIVE)
    return query


def resolve_animal(
    *,
    request: HttpRequest,
    organization_id: UUID,
    farm_id: UUID,
    national_id: str,
    working_number: str = "",
    species: str = "cattle",
) -> tuple[Animal, bool]:
    """The farm's animal with this tag, recorded on the spot when it is new.

    For a cow found in the barn but missing from the register: the tag is
    normalized and validated like any other, and creating it takes
    `farms.manage` and leaves the usual audit entry.
    """
    existing = Animal.all_objects.filter(
        organization_id=organization_id,
        farm_id=farm_id,
        species=species,
        national_id=normalize_identifier(national_id),
    ).first()
    if existing is not None:
        return existing, False
    created = create_animal(
        request=request,
        farm_id=farm_id,
        data={"species": species, "national_id": national_id, "working_number": working_number},
    )
    return created, True


__all__ = [
    "ANIMAL_MODEL",
    "FARMS_ENABLED",
    "FARMS_MANAGE",
    "FARMS_READ",
    "FARM_MODEL",
    "Animal",
    "AnimalStatus",
    "Farm",
    "animal_for_tenant",
    "farm_animals",
    "farm_for_tenant",
    "normalize_identifier",
    "resolve_animal",
]
