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

from django.utils import timezone

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .capabilities import CONTENT_CONTRACT_VERSION, MINIMUM_CONTENT_CONTRACT_VERSION
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
        .select_related("current_publication")
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
        "hostnames": list(
            Domain.all_objects.filter(
                organization_id=context.organization_id,
                site_id=site.id,
                status=DomainStatus.VERIFIED,
            )
            .order_by("-is_canonical", "hostname")
            .values_list("hostname", flat=True)
        ),
        # The base a change set declares. A connector that sends a different
        # one is planning against a state that has moved.
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


def _pages(context: Any, site: Site) -> list[dict[str, Any]]:
    pages = list(
        Page.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id
        ).order_by("created_at")
    )
    translations: dict[Any, list[PageTranslation]] = {}
    for translation in PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        page_id__in=[page.id for page in pages],
    ).order_by("locale"):
        translations.setdefault(translation.page_id, []).append(translation)
    return [
        {
            "page_id": str(page.id),
            "key": page.key,
            "name": page.name,
            "page_type": page.page_type,
            "automation_policy": page.automation_policy,
            # The version a change set must declare as its base. A stale one
            # is a 409 and an explicit recomputation, never a silent overwrite.
            "version": page.version,
            "locales": [
                {
                    "locale": translation.locale,
                    "slug": translation.slug,
                    "version": translation.version,
                    "slug_locked": translation.slug_locked_at is not None,
                }
                for translation in translations.get(page.id, [])
            ],
        }
        for page in pages
    ]
