"""Publications made from the published state, not from drafts (ADR-065, ADR-070 pkt 11).

A derived publication is the current snapshot with exactly one kind of change:
a page taken off, a language version accepted, published or withdrawn, the
result of a translation job. It never reads drafts, the working menu or the
appearance, so nobody's half-finished work goes out with it. Media references
carry over from the publication it derives from — a photo tombstoned since does
not stop it, because its file stays while a publication points at it — and only
references new to the snapshot are checked.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    ResourceReferenceConflict,
    ResourceReferenceRejected,
    record_resource_references,
)
from saas_core.observability import correlation_id

from .models import Publication, Site, SiteOutboxEvent
from .services import (
    MEDIA_ASSET_RESOURCE_TYPE,
    PUBLICATION_REFERENCE_OWNER,
    SITE_PUBLISHED_EVENT,
    SiteMediaReferenceUnavailable,
    SitesIdempotencyConflict,
    _schedule_site_outbox_delivery,
)


def publish_derived(
    *,
    context: Any,
    site: Site,
    snapshot: dict[str, Any],
    actor: User,
    idempotency_key: str,
    reason: str,
    snapshot_schema_version: int | None = None,
) -> Publication:
    """Publishes `snapshot`, derived from the site's current publication.

    The caller builds the snapshot from the current one and decides who may
    ask; this records it, carries the media references, points the site at
    it and tells subscribers why it exists (`reason`, ADR-070 pkt 11).
    """
    previous = (
        Publication.all_objects.filter(organization_id=context.organization_id, site_id=site.id)
        .order_by("-sequence")
        .first()
    )
    current = site.current_publication
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=(previous.sequence + 1 if previous is not None else 1),
        # The current one's, unless the caller rewrote the snapshot to a newer
        # schema (a language decision on a schema 1 snapshot writes 2).
        snapshot_schema_version=(
            snapshot_schema_version
            or (current.snapshot_schema_version if current else 1)
        ),
        snapshot=snapshot,
        snapshot_hash="",
        created_by=actor,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    media_ids = sorted({
        asset_id
        for entry in snapshot.get("pages", [])
        if isinstance(entry, dict)
        for document in [entry, *entry.get("locales", [])]
        if isinstance(document, dict)
        for asset_id in document.get("media_asset_ids", [])
    })
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            owner_id=publication.id,
            resource_ids=tuple(UUID(asset_id) for asset_id in media_ids),
            carried_from=current.id if current is not None else None,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error
    Site.all_objects.filter(pk=site.id, organization_id=context.organization_id).update(
        current_publication=publication, updated_at=timezone.now()
    )
    from .tls import invalidate_site_tls_decisions

    transaction.on_commit(lambda: invalidate_site_tls_decisions(site_id=site.id))
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        publication=publication,
        event_type=SITE_PUBLISHED_EVENT,
        version=1,
        actor=actor,
        correlation_id=UUID(active_correlation_id) if active_correlation_id else uuid7(),
        causation_id=f"sites-{reason}:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "reason": reason,
        },
    )
    _schedule_site_outbox_delivery(event)
    return publication
