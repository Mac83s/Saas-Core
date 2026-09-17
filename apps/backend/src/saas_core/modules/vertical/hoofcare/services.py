"""Use cases of the HoofCare vertical.

Every one of them goes through `authorize_entitled`: the permission says the
person may do it, the entitlement says this organization's plan includes the
vertical at all. Hiding a menu entry is not authorization, and a product that
composes the module still sells it under a plan.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import Animal, Farm, HerdVisit

HERD_READ = "hoofcare.herd.read"
HERD_MANAGE = "hoofcare.herd.manage"
HOOFCARE_ENABLED = "hoofcare.enabled"

#: Enough for a working list; a herd of 240 is a big farm, and nobody scrolls
#: past a few hundred rows without filtering first.
PAGE_LIMIT = 500


def list_farms() -> list[Farm]:
    context = authorize_entitled(HERD_READ, HOOFCARE_ENABLED, operation=FeatureOperation.READ)
    return list(Farm.all_objects.filter(organization_id=context.organization_id)[:PAGE_LIMIT])


@transaction.atomic
def create_farm(*, data: dict[str, Any]) -> Farm:
    context = authorize_entitled(HERD_MANAGE, HOOFCARE_ENABLED)
    return Farm.all_objects.create(organization_id=context.organization_id, **data)


def list_animals(*, farm_id: UUID | None = None) -> list[Animal]:
    context = authorize_entitled(HERD_READ, HOOFCARE_ENABLED, operation=FeatureOperation.READ)
    query = Animal.all_objects.filter(organization_id=context.organization_id)
    if farm_id is not None:
        query = query.filter(farm_id=farm_id)
    return list(query.select_related("farm")[:PAGE_LIMIT])


@transaction.atomic
def create_animal(*, farm_id: UUID, data: dict[str, Any]) -> Animal:
    context = authorize_entitled(HERD_MANAGE, HOOFCARE_ENABLED)
    # The farm is read under the tenant, so a farm of another organization is
    # simply not found here — the database trigger is the second line, not the
    # first, and a 404 is the honest answer to "that is not yours".
    farm = Farm.all_objects.get(organization_id=context.organization_id, id=farm_id)
    return Animal.all_objects.create(
        organization_id=context.organization_id, farm=farm, **data
    )


def list_visits() -> list[HerdVisit]:
    context = authorize_entitled(HERD_READ, HOOFCARE_ENABLED, operation=FeatureOperation.READ)
    return list(
        HerdVisit.all_objects.filter(organization_id=context.organization_id)
        .select_related("farm", "appointment")[:PAGE_LIMIT]
    )
