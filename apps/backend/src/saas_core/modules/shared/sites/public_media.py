from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState
from saas_core.modules.shared.media.storage import (
    ObjectNotFoundError,
    ObjectStorageError,
    get_object_storage,
)

from .domains import InvalidHostname, normalize_hostname
from .models import ContentEntry, ContentEntryState, Domain, DomainStatus
from .publication_routing import PublicSiteNotFound, tenant_is_servable


def _published_asset_ids(*, organization_id: Any, site_id: Any) -> set[str]:
    """Every asset the visitor is allowed to see, taken from what is published.

    Read from the snapshots rather than from the draft: an asset dropped from a
    page in the working copy must stop being public only when that change is
    published, and one added to a draft must not become public before it.
    """
    allowed: set[str] = set()
    domain_site = Domain.all_objects.select_related("site__current_publication").filter(
        site_id=site_id, organization_id=organization_id
    ).first()
    publication = domain_site.site.current_publication if domain_site else None
    if publication is not None:
        for raw_page in publication.snapshot.get("pages", []):
            if isinstance(raw_page, dict):
                allowed.update(str(item) for item in raw_page.get("media_asset_ids", []))
    for entry in ContentEntry.all_objects.select_related("current_publication").filter(
        organization_id=organization_id,
        site_id=site_id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    ):
        entry_publication = entry.current_publication
        if entry_publication is None:
            continue
        allowed.update(
            str(item) for item in entry_publication.snapshot.get("media_asset_ids", [])
        )
    return allowed


def serve_public_media(*, host: str, asset_id: UUID) -> HttpResponse:
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    domain = (
        Domain.all_objects.select_related("site")
        .filter(hostname=hostname, status=DomainStatus.VERIFIED)
        .first()
    )
    if domain is None or not tenant_is_servable(domain.organization_id):
        raise PublicSiteNotFound
    allowed = _published_asset_ids(
        organization_id=domain.organization_id, site_id=domain.site_id
    )
    if str(asset_id) not in allowed:
        # The same answer whether the asset belongs to somebody else or to
        # nobody: telling them apart would confirm which ids exist.
        raise PublicSiteNotFound
    with transaction.atomic():
        # `media_mediaasset` carries forced row-level security, so without the
        # tenant setting the app role sees no rows and every picture on every
        # published page would answer 404. The host told us which organization
        # this is; the read has to happen inside that.
        set_local_organization_id(domain.organization_id)
        asset = MediaAsset.all_objects.filter(
            pk=asset_id,
            organization_id=domain.organization_id,
            state=MediaAssetState.READY,
        ).first()
    if asset is None:
        raise PublicSiteNotFound
    storage = get_object_storage()
    try:
        content = storage.read(
            object_key=asset.object_key,
            max_bytes=settings.MEDIA_MAX_UPLOAD_BYTES,
        )
    except (ObjectNotFoundError, ObjectStorageError) as error:
        # The row says the asset is ready but the bytes are not there. That is
        # ours to notice, not something to hand the visitor a 500 over.
        raise Http404 from error
    response = HttpResponse(
        content,
        content_type=asset.detected_mime or asset.declared_mime,
    )
    # Published media is immutable — a new picture is a new asset with a new id
    # — so it can be cached for a long time without risking a stale image.
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
