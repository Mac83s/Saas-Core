"""What a search engine would read on a page after the next publication
(TL18, ADR-071 pkt 16): the title and description, the address, the other
languages, and the structured data — worked out and never saved.

The preview builds the snapshot the next publication would carry, through the
same steps as `publish_site`, and reads the page from it with the public
route's own code. So it cannot promise something the publication then does
not do; a test publishes right after a preview and compares the two.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_decoration import stored_block_payload
from .language_publication import language_entries, previous_source_ids
from .localization import build_localization_report
from .models import (
    Domain,
    DomainStatus,
    Page,
    PageBlock,
    PageTranslation,
    Publication,
    Site,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .publication_routing import (
    PublicPage,
    public_page_payload,
    serving_locales,
    visible_snapshot,
)
from .services import (
    PageNotFound,
    SiteNotFound,
    SitePublicationNotReady,
    _current_version_id,
    _language_entry_media,
    _navigation_snapshot,
    _page_version_media_asset_ids,
    _publication_snapshot,
    _supported_locales,
    assert_within_grant,
)

#: A search result shows about 60 characters of a title and 160 of a
#: description; the preview carries enough to show what is cut, not a page.
TITLE_LIMIT = 300
DESCRIPTION_LIMIT = 600

#: Why a language version would not be public after the next publication.
NOT_WRITTEN = "not_written"
WITHHELD = "withheld"
LANGUAGE_OFF = "language_off"
LANGUAGE_NOT_LIVE = "language_not_live"


class SiteAddressMissing(APIException):
    status_code = 409
    default_detail = "Strona nie ma jeszcze adresu."
    default_code = "site_address_missing"


def next_snapshot(*, context: TenantContext, site: Site) -> dict[str, Any]:
    """The snapshot `publish_site` would write now; reads only, locks nothing."""
    pages = list(
        Page.all_objects.select_related("current_draft")
        .filter(organization_id=context.organization_id, deleted_at__isnull=True, site_id=site.id)
        .order_by("id")
    )
    if not pages or any(page.current_draft_id is None for page in pages):
        raise SitePublicationNotReady
    translations = list(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
            locale__in=_supported_locales(),
        )
        .select_related("site", "body_current__source_version")
        .order_by("page_id", "locale")
    )
    localization = build_localization_report(
        site=site,
        pages=pages,
        translations=translations,
        supported_locales=_supported_locales(),
    )
    if not localization.ready_to_publish:
        raise SitePublicationNotReady
    blocks_by_version: dict[UUID, list[PageBlock]] = {}
    for block in PageBlock.all_objects.filter(
        organization_id=context.organization_id,
        page_version_id__in=tuple(_current_version_id(page) for page in pages),
    ).order_by("page_version_id", "position"):
        blocks_by_version.setdefault(block.page_version_id, []).append(block)
    page_media_ids = {
        page.id: _page_version_media_asset_ids(
            context=context, version_id=_current_version_id(page)
        )
        for page in pages
    }
    current = site.current_publication.snapshot if site.current_publication else None
    source_blocks = {
        version_id: [stored_block_payload(block) for block in version_blocks]
        for version_id, version_blocks in blocks_by_version.items()
    }
    for block in PageBlock.all_objects.filter(
        organization_id=context.organization_id,
        page_version_id__in=previous_source_ids(current, site.default_locale) - set(source_blocks),
    ).order_by("page_version_id", "position"):
        source_blocks.setdefault(block.page_version_id, []).append(stored_block_payload(block))
    languages = language_entries(
        site=site,
        pages=pages,
        sources={page.id: page.current_draft for page in pages if page.current_draft},
        blocks=source_blocks,
        translations=translations,
        previous=current,
    )
    # Holds back the versions whose pictures are gone, as the publication does.
    _language_entry_media(
        context=context,
        languages=languages,
        known={str(_current_version_id(page)): page_media_ids[page.id] for page in pages},
    )
    return _publication_snapshot(
        site=site,
        pages=pages,
        blocks_by_version=blocks_by_version,
        localization=localization,
        languages=languages,
        page_media_ids=page_media_ids,
        navigation=_navigation_snapshot(
            site=site,
            organization_id=context.organization_id,
            published_page_ids={page.id for page in pages},
        ),
    )


def _address(site: Site) -> Domain:
    """The address the site calls its own — or will, once it is verified: a
    preview before the first publication is still worth reading."""
    domains = sorted(
        Domain.all_objects.filter(site_id=site.id),
        key=lambda domain: (not domain.is_canonical, domain.status != DomainStatus.VERIFIED),
    )
    if not domains:
        raise SiteAddressMissing
    return domains[0]


def _why_not(
    snapshot: dict[str, Any], page_id: UUID, locale: str, available: frozenset[str]
) -> str:
    """Why a language version would not be public after the next publication:
    the publication's own reason where it gives one."""
    for item in snapshot.get("skipped_locales", []):
        if str(item.get("page_id")) == str(page_id) and item.get("locale") == locale:
            return str(item.get("reason"))
    entry = next(
        (
            version
            for page in snapshot.get("pages", [])
            if str(page.get("page_id")) == str(page_id)
            for version in page.get("locales", [])
            if isinstance(version, dict) and version.get("locale") == locale
        ),
        None,
    )
    if entry is None or "blocks" not in entry:
        return NOT_WRITTEN
    if locale not in available:
        return LANGUAGE_OFF
    # Written and carried from an earlier publication, but the source has
    # since changed a fact it does not have (ADR-070 pkt 10).
    return WITHHELD if entry.get("withheld") else LANGUAGE_NOT_LIVE


def _clip(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def read_seo_preview(*, site_id: UUID, page_id: UUID, locale: str) -> dict[str, Any]:
    """One page in one language as the next publication would show it to a
    search engine. Nothing is written."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    site = (
        Site.all_objects.select_related("current_publication")
        .filter(pk=site_id, organization_id=context.organization_id)
        .first()
    )
    if site is None:
        raise SiteNotFound
    assert_within_grant(context, site_id=site_id)
    if not Page.all_objects.filter(
        pk=page_id,
        organization_id=context.organization_id,
        site_id=site.id,
        deleted_at__isnull=True,
    ).exists():
        raise PageNotFound
    canonical = _address(site)
    snapshot = next_snapshot(context=context, site=site)
    # Never saved: it only carries the snapshot through the public route's code.
    publication = Publication(organization_id=context.organization_id, site=site, snapshot=snapshot)
    available = (serving_locales(context.organization_id) or frozenset()) | {site.default_locale}
    visible = visible_snapshot(publication, available)
    found = next(
        (
            (page, version)
            for page in visible["pages"]
            if str(page.get("page_id")) == str(page_id)
            for version in page.get("locales", [])
            if isinstance(version, dict) and version.get("locale") == locale
        ),
        None,
    )
    base = {"site_id": site.id, "page_id": page_id, "locale": locale}
    if found is None:
        return {**base, "public": False, "reason": _why_not(snapshot, page_id, locale, available)}
    page, version = found
    payload = public_page_payload(
        PublicPage(
            organization_id=context.organization_id,
            site_id=site.id,
            hostname=canonical.hostname,
            canonical_hostname=canonical.hostname,
            requested_path=str(version["canonical_path"]),
            canonical_path=str(version["canonical_path"]),
            locale=locale,
            publication=publication,
            page={**page, "selected_locale": version},
            available=available,
        )
    )
    social = payload["social"]
    return {
        **base,
        "public": True,
        "reason": "",
        "url": payload["canonical_url"],
        "title": _clip(payload["title"], TITLE_LIMIT),
        "description": _clip(payload["description"], DESCRIPTION_LIMIT),
        "site_name": _clip(social["site_name"], TITLE_LIMIT),
        "noindex": payload["noindex"],
        "hreflang": payload["hreflang"],
        "x_default": payload["x_default"],
        "social_title": _clip(payload["social_title"] or payload["title"], TITLE_LIMIT),
        "social_description": _clip(
            payload["social_description"] or payload["description"], DESCRIPTION_LIMIT
        ),
        "image": social["image"],
        "structured_data": payload["structured_data"],
    }
