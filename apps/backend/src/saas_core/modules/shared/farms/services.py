"""Use cases of the farm register (ADR-051).

Every one goes through `authorize_entitled`: the permission says the person may
do it, the entitlement says the organization's plan includes the register.
Reads and writes happen under the tenant, so another organization's farm is
simply not found — the database guard is the second line, not the first.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import Animal, Farm
from .species import (
    HERD_NUMBER,
    SPECIES,
    TAX_ID,
    normalize_herd_number,
    normalize_identifier,
)

FARMS_READ = "farms.read"
FARMS_MANAGE = "farms.manage"
FARMS_ENABLED = "farms.enabled"

#: A working list; nobody scrolls past a few hundred rows without searching.
PAGE_LIMIT = 500


def _clean_farm(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(data)
    if "herd_number" in cleaned:
        cleaned["herd_number"] = normalize_herd_number(cleaned["herd_number"] or "")
        if cleaned["herd_number"] and not HERD_NUMBER.fullmatch(cleaned["herd_number"]):
            raise ValidationError({
                "herd_number": "Numer siedziby stada ma postać np. PL012345678-001."
            })
    if "tax_id" in cleaned:
        cleaned["tax_id"] = "".join(ch for ch in cleaned["tax_id"] or "" if ch.isdigit())
        if cleaned["tax_id"] and not TAX_ID.fullmatch(cleaned["tax_id"]):
            raise ValidationError({"tax_id": "NIP ma 10 cyfr."})
    return cleaned


def _clean_animal(data: dict[str, Any], *, species: str) -> dict[str, Any]:
    cleaned = dict(data)
    known = SPECIES.get(species)
    if known is None or not known.active:
        raise ValidationError({"species": "Ten gatunek nie jest jeszcze obsługiwany."})
    if "national_id" in cleaned:
        cleaned["national_id"] = normalize_identifier(cleaned["national_id"])
        if not known.identifier.fullmatch(cleaned["national_id"]):
            raise ValidationError({
                "national_id": "Numer nie ma formatu numeru identyfikacyjnego tego gatunku."
            })
    return cleaned


def _audit(request: HttpRequest, organization_id: UUID, action: str, target: Farm | Animal) -> None:
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=action,
        actor=cast(User, request.user),
        target_type=target._meta.model_name or "",
        target_id=target.id,
    )


def list_farms(*, search: str = "") -> list[Farm]:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    query = Farm.all_objects.filter(organization_id=context.organization_id)
    if search:
        query = query.filter(
            Q(name__icontains=search)
            | Q(village__icontains=search)
            | Q(keeper_name__icontains=search)
            | Q(herd_number__icontains=normalize_herd_number(search))
        )
    return list(query[:PAGE_LIMIT])


def get_farm(farm_id: UUID) -> Farm:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    farm = Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id).first()
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    return farm


@transaction.atomic
def create_farm(*, request: HttpRequest, data: dict[str, Any]) -> Farm:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    cleaned = _clean_farm(data)
    if Farm.all_objects.filter(
        organization_id=context.organization_id, name=cleaned["name"]
    ).exists():
        raise ValidationError({"name": "Gospodarstwo o tej nazwie już jest."})
    if (
        cleaned.get("herd_number")
        and Farm.all_objects.filter(
            organization_id=context.organization_id, herd_number=cleaned["herd_number"]
        ).exists()
    ):
        raise ValidationError({
            "herd_number": "Gospodarstwo z tym numerem siedziby stada już jest."
        })
    farm = Farm.all_objects.create(organization_id=context.organization_id, **cleaned)
    _audit(request, context.organization_id, OrganizationAuditAction.FARM_CREATED, farm)
    return farm


@transaction.atomic
def update_farm(*, request: HttpRequest, farm_id: UUID, data: dict[str, Any]) -> Farm:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    farm = (
        Farm.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, id=farm_id)
        .first()
    )
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    cleaned = _clean_farm(data)
    for field, value in cleaned.items():
        setattr(farm, field, value)
    duplicates = Farm.all_objects.filter(organization_id=context.organization_id).exclude(
        id=farm.id
    )
    if duplicates.filter(name=farm.name).exists():
        raise ValidationError({"name": "Gospodarstwo o tej nazwie już jest."})
    if farm.herd_number and duplicates.filter(herd_number=farm.herd_number).exists():
        raise ValidationError({
            "herd_number": "Gospodarstwo z tym numerem siedziby stada już jest."
        })
    farm.save()
    _audit(request, context.organization_id, OrganizationAuditAction.FARM_UPDATED, farm)
    return farm


def list_animals(*, farm_id: UUID | None = None, search: str = "") -> list[Animal]:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    query = Animal.all_objects.filter(organization_id=context.organization_id)
    if farm_id is not None:
        query = query.filter(farm_id=farm_id)
    if search:
        needle = normalize_identifier(search)
        query = query.filter(
            Q(national_id__icontains=needle)
            | Q(working_number__iexact=search.strip())
            | Q(name__icontains=search.strip())
        )
    return list(query.select_related("farm")[:PAGE_LIMIT])


@transaction.atomic
def create_animal(*, request: HttpRequest, farm_id: UUID, data: dict[str, Any]) -> Animal:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    farm = Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id).first()
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    species = data.pop("species", "cattle")
    cleaned = _clean_animal(data, species=species)
    if Animal.all_objects.filter(
        organization_id=context.organization_id,
        farm=farm,
        species=species,
        national_id=cleaned["national_id"],
    ).exists():
        raise ValidationError({"national_id": "To zwierzę jest już w tym gospodarstwie."})
    animal = Animal.all_objects.create(
        organization_id=context.organization_id, farm=farm, species=species, **cleaned
    )
    _audit(request, context.organization_id, OrganizationAuditAction.ANIMAL_CREATED, animal)
    return animal


@transaction.atomic
def update_animal(*, request: HttpRequest, animal_id: UUID, data: dict[str, Any]) -> Animal:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    animal = (
        Animal.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, id=animal_id)
        .first()
    )
    if animal is None:
        raise NotFound("Nie ma takiego zwierzęcia.")
    cleaned = _clean_animal(data, species=animal.species)
    for field, value in cleaned.items():
        setattr(animal, field, value)
    if (
        Animal.all_objects.filter(
            organization_id=context.organization_id,
            farm_id=animal.farm_id,
            species=animal.species,
            national_id=animal.national_id,
        )
        .exclude(id=animal.id)
        .exists()
    ):
        raise ValidationError({"national_id": "To zwierzę jest już w tym gospodarstwie."})
    animal.save()
    _audit(request, context.organization_id, OrganizationAuditAction.ANIMAL_UPDATED, animal)
    return animal
