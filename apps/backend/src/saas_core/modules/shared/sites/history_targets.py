"""What the company's history calls the website's objects (UX-055)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target

from .models import (
    ContentEntry,
    Page,
    PageLocaleVersion,
    PageTranslation,
    PageVersion,
    Publication,
    Site,
)

Namer = Callable[[UUID, Sequence[UUID]], dict[UUID, HistoryTarget]]


def _pages(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        page.id: HistoryTarget(label=page.name, href=f"/panel/sites/pages/{page.id}")
        for page in Page.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def _of_page(model: Any, *, in_language: bool = False) -> Namer:
    """A saved draft or a language version is called after its page — and
    after its language, where the row is about one."""

    def name(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
        return {
            row.id: HistoryTarget(
                label=f"{row.page.name} ({row.locale.upper()})" if in_language else row.page.name,
                href=f"/panel/sites/pages/{row.page_id}",
            )
            for row in model.all_objects.filter(
                organization_id=organization_id, pk__in=ids
            ).select_related("page")
        }

    return name


def _site(site: Site) -> HistoryTarget:
    return HistoryTarget(label=site.name, href=f"/panel/sites?site={site.id}")


def _sites(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        site.id: _site(site)
        for site in Site.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def _publications(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        publication.id: _site(publication.site)
        for publication in Publication.all_objects.filter(
            organization_id=organization_id, pk__in=ids
        ).select_related("site")
    }


def _entries(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        entry.id: HistoryTarget(label=entry.title, href="/panel/sites/blog")
        for entry in ContentEntry.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("page", _pages)
    register_history_target("page_version", _of_page(PageVersion))
    register_history_target("page_translation", _of_page(PageTranslation, in_language=True))
    register_history_target("page_locale_version", _of_page(PageLocaleVersion, in_language=True))
    register_history_target("site", _sites)
    register_history_target("publication", _publications)
    register_history_target("content_entry", _entries)
