"""Evidence slots take real photographs only (ADR-059 pkt 8).

A portrait beside a quote or an author's photo claims a real person. An AI image
there would be fabricated proof, so the backend refuses it; the block manifest's
`realMediaOnly` only helps the panel hide such images.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from saas_core.modules.shared.media.api import ai_generated_asset_ids

# block type -> paths (inside block data) that must hold a real photograph
REAL_MEDIA_ONLY_SLOTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "core.quote": (("image", "asset_id"),),
    "core.rich_text": (("author", "image", "asset_id"),),
}


class AiMediaNotAllowedInSlot(APIException):
    status_code = 422
    default_detail = (
        "Obraz wygenerowany przez AI nie może być portretem przy cytacie ani zdjęciem autora."
    )
    default_code = "ai_media_not_allowed_in_slot"


def assert_real_media_slots(*, organization_id: UUID, blocks: Iterable[Mapping[str, Any]]) -> None:
    """Refuse AI media in evidence slots; `blocks` are `{block_type, data}` shaped."""
    asset_ids: set[str] = set()
    for block in blocks:
        for path in REAL_MEDIA_ONLY_SLOTS.get(str(block.get("block_type")), ()):
            value: Any = block.get("data")
            for key in path:
                value = value.get(key) if isinstance(value, Mapping) else None
            try:
                asset_ids.add(str(UUID(str(value))))
            except ValueError:
                continue
    if asset_ids and ai_generated_asset_ids(organization_id=organization_id, asset_ids=asset_ids):
        raise AiMediaNotAllowedInSlot
