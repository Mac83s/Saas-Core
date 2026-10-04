"""What a connector may act on, and what state it is in (W9.6.6).

SeoContentRank plans against a snapshot of the world. Reading that snapshot one
endpoint at a time makes the plan inconsistent by construction: the pages come
from one moment and the collections from another, and a change set computed
across the seam is refused for reasons neither side can reproduce. One read,
one moment, one hash.

Nothing here is a draft. Like capabilities, this describes shape and state; the
text of unpublished work stays behind the draft endpoints, which check the
grant separately.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .capabilities import CONTENT_CONTRACT_VERSION, MINIMUM_CONTENT_CONTRACT_VERSION
from .language_publication import home_page
from .language_versions import _page_rows, _published_bodies, site_locales
from .localization import localized_path
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    Domain,
    DomainStatus,
    Page,
    PageTranslation,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import _is_automation, assert_within_grant


def read_inventory() -> dict[str, Any]:
    """Every resource this caller may act on, as of one moment.

    For a credential the listing is narrowed to what its grants cover, so an
    integration hired for the blog cannot even enumerate the pages around it —
    a list of a customer's addresses is itself worth withholding.
    """
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    automation = _is_automation(context)
    sites = list(
        Site.all_objects.filter(organization_id=context.organization_id)
        .select_related("current_publication", "organization")
        .order_by("created_at")
    )
    payload: list[dict[str, Any]] = []
    for site in sites:
        collections = [
            collection
            for collection in ContentCollection.all_objects.filter(
                organization_id=context.organization_id, site_id=site.id
            ).order_by("key")
            if not automation or _granted(context, site.id, collection.id)
        ]
        site_granted = not automation or _granted(context, site.id, None)
        if not site_granted and not collections:
            continue
        payload.append(
            _site_entry(
                site,
                context=context,
                collections=collections,
                # A collection-scoped grant reaches its entries and nothing
                # else; the pages beside them are not part of the agreement.
                pages=_pages(context, site) if site_granted else [],
            )
        )
    return {
        "contract_version": CONTENT_CONTRACT_VERSION,
        "minimum_contract_version": MINIMUM_CONTENT_CONTRACT_VERSION,
        "observed_at": timezone.now().isoformat(),
        "sites": payload,
    }


def inventory_etag(inventory: dict[str, Any]) -> str:
    """A hash of everything except the moment it was read.

    Including `observed_at` would make every response a new version and the
    ETag worthless — the point is to say "nothing you act on has changed".
    """
    stable = {key: value for key, value in inventory.items() if key != "observed_at"}
    return f'"{canonical_json_hash(stable)}"'


def _granted(context: Any, site_id: Any, collection_id: Any) -> bool:
    from .services import AutomationGrantMissing

    try:
        assert_within_grant(context, site_id=site_id, collection_id=collection_id)
    except AutomationGrantMissing:
        return False
    return True


def _site_entry(
    site: Site,
    *,
    context: Any,
    collections: list[ContentCollection],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    publication = site.current_publication
    return {
        "site_id": str(site.id),
        "slug": site.slug,
        "purpose": site.purpose,
        "default_locale": site.default_locale,
        # The languages a change set may name here, the source first; any
        # other answers `locale_not_enabled`.
        "locales": list(site_locales(site)),
        "hostnames": _hostnames(context, site),
        # Published state only. A change set reads its actual target draft and
        # localized metadata through content-base; this hash cannot replace it.
        "publication": (
            {
                "publication_id": str(publication.id),
                "sequence": publication.sequence,
                "snapshot_hash": f"sha256:{publication.snapshot_hash}",
                "published_at": publication.created_at.isoformat(),
            }
            if publication is not None
            else None
        ),
        "pages": pages,
        "collections": [
            {
                "collection_id": str(collection.id),
                "key": collection.key,
                "base_path": collection.base_path,
                "kind": collection.kind,
                "automation_policy": collection.automation_policy,
                "published_entries": ContentEntry.all_objects.filter(
                    organization_id=context.organization_id,
                    collection_id=collection.id,
                    state=ContentEntryState.PUBLISHED,
                ).count(),
            }
            for collection in collections
        ],
    }


def _hostnames(context: Any, site: Site) -> list[str]:
    return list(
        Domain.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
            status=DomainStatus.VERIFIED,
        )
        .order_by("-is_canonical", "hostname")
        .values_list("hostname", flat=True)
    )


def _pages(context: Any, site: Site) -> list[dict[str, Any]]:
    pages = list(
        Page.all_objects.select_related("current_draft")
        .filter(organization_id=context.organization_id, site_id=site.id, deleted_at__isnull=True)
        .order_by("created_at")
    )
    translations: dict[Any, list[PageTranslation]] = {}
    for translation in PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        page_id__in=[page.id for page in pages],
    ).order_by("locale"):
        translations.setdefault(translation.page_id, []).append(translation)
    languages = _languages(context, site, pages)
    return [
        {
            "page_id": str(page.id),
            "key": page.key,
            "name": page.name,
            "page_type": page.page_type,
            "automation_policy": page.automation_policy,
            # The version a change set must declare as its base in the site's
            # source language. A stale one is a 409 and an explicit
            # recomputation, never a silent overwrite. Each language has its
            # own: `locales[].base_version`.
            "version": page.version,
            "locales": [
                {
                    "locale": translation.locale,
                    "slug": translation.slug,
                    "version": translation.version,
                    "slug_locked": translation.slug_locked_at is not None,
                    **languages[page.id, translation.locale],
                }
                for translation in translations.get(page.id, [])
            ],
        }
        for page in pages
    ]


def _languages(
    context: Any, site: Site, pages: list[Page]
) -> dict[tuple[Any, str], dict[str, Any]]:
    """Each page in each language it has: where it answers, the version a
    change set for that language declares, how far its translation is and
    whether visitors get it (plan TL13). State, never text."""
    enabled = site_locales(site)
    snapshot = site.current_publication.snapshot if site.current_publication else {}
    published = _published_bodies(snapshot)
    published_pages = {
        str(page.get("page_id")): page
        for page in snapshot.get("pages", [])
        if isinstance(page, dict)
    }
    cells = {
        (row.id, cell.locale): cell
        for row in _page_rows(
            site, tuple(code for code in enabled if code != site.default_locale)
        )
        for cell in row.cells
    }
    hostnames = _hostnames(context, site)
    home = home_page(pages)
    rows = PageTranslation.all_objects.select_related("body_current").filter(
        organization_id=context.organization_id, page_id__in=[page.id for page in pages]
    )
    by_page = {page.id: page for page in pages}
    found: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in rows:
        page = by_page[row.page_id]
        source = row.locale == site.default_locale
        if home is not None and page.id == home.id:
            # The home page answers at the root of its language.
            path = "/" if source else f"/{row.locale}/"
        else:
            path = localized_path(
                default_locale=site.default_locale, locale=row.locale, slug=row.slug
            )
        out = published_pages.get(str(page.id), {})
        if source:
            state, untranslated = "source", 0
            is_published = bool(out)
            in_sync = is_published and out.get("version") == page.version
            base_version = page.version
        else:
            cell = cells.get((page.id, row.locale))
            state = cell.state if cell is not None else "disabled"
            untranslated = (cell.untranslated or 0) if cell is not None else 0
            is_published = (str(page.id), row.locale) in published
            entry = next(
                (
                    item
                    for item in out.get("locales", [])
                    if isinstance(item, dict) and item.get("locale") == row.locale
                ),
                {},
            )
            in_sync = is_published and entry.get("locale_version_id") == str(row.body_current_id)
            base_version = row.body_version
        found[page.id, row.locale] = {
            "source": source,
            # Off for a language the company turned off: its content stays,
            # and a change set for it answers `locale_not_enabled`.
            "enabled": row.locale in enabled,
            "path": path,
            "url": (
                f"{settings.PUBLIC_SITE_SCHEME}://{hostnames[0]}{path}" if hostnames else None
            ),
            # What `base.version` of a change set for this language must be.
            "base_version": base_version,
            # `source`, or how far this language's body is: `untranslated`,
            # `complete`, `outdated` (the source moved on), `pending` (a
            # version waits for a person).
            "state": state,
            "untranslated_units": untranslated,
            # Whether visitors get this language of the page, and whether what
            # they get is the working version.
            "published": is_published,
            "published_in_sync": in_sync,
        }
    return found
