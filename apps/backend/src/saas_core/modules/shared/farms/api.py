"""Public use-case API of the farm register for other modules (ADR-051).

A vertical (HoofCare's trimming visit) points at a farm through
`FARM_MODEL` and reads one through `farm_for_tenant`, never through the
private models — the module contract puts the public surface here.
"""

from __future__ import annotations

from uuid import UUID

from .models import Farm
from .services import FARMS_ENABLED, FARMS_MANAGE, FARMS_READ

#: Lazy reference for another module's `ForeignKey` to a farm.
FARM_MODEL = "farms.Farm"


def farm_for_tenant(organization_id: UUID, farm_id: UUID) -> Farm | None:
    """The farm if it belongs to this organization; None otherwise."""
    return Farm.all_objects.filter(organization_id=organization_id, id=farm_id).first()


__all__ = ["FARMS_ENABLED", "FARMS_MANAGE", "FARMS_READ", "FARM_MODEL", "Farm", "farm_for_tenant"]
