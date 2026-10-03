"""What the company's history calls a farm (UX-055): which farm was added or
changed, with the way to its card."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target

from .models import Farm


def _farms(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        farm.id: HistoryTarget(label=farm.name, href=f"/panel/farms/{farm.id}")
        for farm in Farm.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("farm", _farms)
