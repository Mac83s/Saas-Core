"""What the company's history calls a file (UX-055): its name at upload."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target

from .models import MediaAsset


def _assets(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        asset.id: HistoryTarget(label=asset.original_filename)
        for asset in MediaAsset.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("media_asset", _assets)
