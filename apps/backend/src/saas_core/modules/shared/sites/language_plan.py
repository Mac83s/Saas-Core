"""What publishing the site would carry in each other language (TL15).

The same verdict the publication itself uses (`language_entries`), read
without saving anything: which language versions go out, which stay in their
last published form and why, which are withheld, taken off or skipped — so a
person sees it before pressing "Opublikuj", and an assistant can ask the same.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_decoration import stored_block_payload
from .language_publication import (
    OUTCOME_CARRIED,
    OUTCOME_MISSING,
    OUTCOME_PUBLISH,
    OUTCOME_SKIPPED,
    OUTCOME_UNCHANGED,
    OUTCOME_WITHDRAWN,
    OUTCOME_WITHHELD,
    _previous_entries,
    language_entries,
    previous_source_ids,
)
from .language_versions import site_locales
from .localization import build_localization_report
from .models import Page, PageBlock, PageTranslation, Site
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import SiteNotFound


@dataclass(frozen=True, slots=True)
class PlannedPage:
    page_id: UUID
    page_name: str
    outcome: str
    reason: str


@dataclass(frozen=True, slots=True)
class PlannedLanguage:
    locale: str
    #: Visitors can read the site in it now / after this publication.
    live: bool
    live_after: bool
    pages: tuple[PlannedPage, ...]


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    ready_to_publish: bool
    languages: tuple[PlannedLanguage, ...]


def preview_site_publication(*, site_id: UUID) -> PublicationPlan:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    try:
        site = Site.all_objects.select_related("current_publication").get(
            pk=site_id, organization_id=context.organization_id
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    locales = site_locales(site)
    others = [locale for locale in locales if locale != site.default_locale]
    pages = list(
        Page.all_objects.select_related("current_draft")
        .filter(organization_id=context.organization_id, deleted_at__isnull=True, site_id=site.id)
        .order_by("id")
    )
    translations = list(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id, locale__in=locales
        )
        .select_related("site", "body_current__source_version")
        .order_by("page_id", "locale")
    )
    ready = (
        bool(pages)
        and all(page.current_draft_id is not None for page in pages)
        and build_localization_report(
            site=site, pages=pages, translations=translations, supported_locales=locales
        ).ready_to_publish
    )
    current = site.current_publication.snapshot if site.current_publication else None
    live_now = set((current or {}).get("live_locales") or [])
    if not pages or any(page.current_draft is None for page in pages):
        # Nothing can be published yet, so there is nothing to compare.
        return PublicationPlan(
            ready_to_publish=False,
            languages=tuple(
                PlannedLanguage(locale=code, live=code in live_now, live_after=False, pages=())
                for code in others
            ),
        )
    sources = {page.id: page.current_draft for page in pages if page.current_draft is not None}
    wanted = {source.id for source in sources.values()} | previous_source_ids(
        current, site.default_locale
    )
    blocks: dict[UUID, list[dict[str, Any]]] = {}
    for block in PageBlock.all_objects.filter(
        organization_id=context.organization_id, page_version_id__in=wanted
    ).order_by("page_version_id", "position"):
        blocks.setdefault(block.page_version_id, []).append(stored_block_payload(block))
    verdict = language_entries(
        site=site,
        pages=pages,
        sources=sources,
        blocks=blocks,
        translations=translations,
        previous=current,
    )
    before = _previous_entries(current, site.default_locale)
    rows = {(row.page_id, row.locale): row for row in translations}
    skipped = {(item["page_id"], item["locale"]): item["reason"] for item in verdict.skipped}

    def planned(page: Page, locale: str) -> PlannedPage:
        key = (str(page.id), locale)
        row = rows.get((page.id, locale))
        entry = verdict.entries.get(key)
        if entry is None:
            outcome, reason = (
                (OUTCOME_SKIPPED, skipped[key]) if key in skipped else (OUTCOME_MISSING, "")
            )
        elif entry.get("withdrawn"):
            outcome, reason = OUTCOME_WITHDRAWN, ""
        elif entry.get("withheld"):
            outcome, reason = OUTCOME_WITHHELD, verdict.held.get(key, "")
        elif key in verdict.held:
            outcome, reason = OUTCOME_CARRIED, verdict.held[key]
        elif (
            key in before
            and row is not None
            and before[key].get("locale_version_id") == str(row.body_current_id)
        ):
            outcome, reason = OUTCOME_UNCHANGED, ""
        else:
            outcome, reason = OUTCOME_PUBLISH, ""
        return PlannedPage(page_id=page.id, page_name=page.name, outcome=outcome, reason=reason)

    ordered = sorted(pages, key=lambda page: (page.key, str(page.id)))
    return PublicationPlan(
        ready_to_publish=ready,
        languages=tuple(
            PlannedLanguage(
                locale=locale,
                live=locale in live_now,
                live_after=locale in verdict.live_locales,
                pages=tuple(planned(page, locale) for page in ordered),
            )
            for locale in others
        ),
    )
