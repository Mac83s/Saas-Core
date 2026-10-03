"""What the company's history calls the website's objects (UX-055)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target

from .models import ContentEntry, Page


def _pages(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        page.id: HistoryTarget(label=page.name, href=f"/panel/sites/pages/{page.id}")
        for page in Page.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def _entries(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        entry.id: HistoryTarget(label=entry.title, href="/panel/sites/blog")
        for entry in ContentEntry.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("page", _pages)
    register_history_target("content_entry", _entries)
