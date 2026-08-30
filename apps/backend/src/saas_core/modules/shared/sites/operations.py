from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryVersion,
    Page,
    PageVersion,
    Publication,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import _idempotency_key


class OperationStatus(TypedDict):
    idempotency_key: str
    found: bool
    resource_type: str | None
    resource_id: UUID | None
    created_at: datetime | None


_OPERATION_RESOURCES: tuple[tuple[str, Any], ...] = (
    ("page", Page),
    ("page_version", PageVersion),
    ("site_publication", Publication),
    ("content_collection", ContentCollection),
    ("content_entry", ContentEntry),
    ("content_entry_version", ContentEntryVersion),
    ("content_entry_publication", ContentEntryPublication),
)


def read_operation_status(*, idempotency_key: str) -> OperationStatus:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    normalized_key = _idempotency_key(idempotency_key)
    matches: list[tuple[datetime, str, UUID]] = []
    for resource_type, model in _OPERATION_RESOURCES:
        row = (
            model.all_objects.filter(
                organization_id=context.organization_id,
                created_by_id=context.actor_id,
                idempotency_key=normalized_key,
            )
            .order_by("created_at", "id")
            .values_list("created_at", "id")
            .first()
        )
        if row is not None:
            created_at, resource_id = row
            matches.append((created_at, resource_type, resource_id))

    if not matches:
        return {
            "idempotency_key": normalized_key,
            "found": False,
            "resource_type": None,
            "resource_id": None,
            "created_at": None,
        }

    created_at, resource_type, resource_id = min(matches)
    return {
        "idempotency_key": normalized_key,
        "found": True,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "created_at": created_at,
    }
