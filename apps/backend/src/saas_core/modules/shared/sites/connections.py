"""What an integration is allowed to do here, and what it has been doing.

An operator who cannot see the connections cannot supervise them. This is the
read behind the panel: which credentials hold which grants, how far each one
reaches, when it last acted, and whether it is still live at all.

Everything here is deliberately about scope and activity rather than content.
Seeing what an automation touched is supervision; reading the drafts through
this screen would be a second, unaudited way into a customer's work.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Max

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    ContentAutomationGrant,
    ContentEntryVersion,
    ContentProposal,
    PageVersion,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED


def list_automation_connections() -> list[dict[str, Any]]:
    """Every grant this tenant has issued, live or spent.

    Revoked and expired grants stay in the list rather than disappearing: an
    operator asking "who had access last month" is asking a question the panel
    should be able to answer, and a list that silently drops them answers it
    wrongly.
    """
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    grants = list(
        ContentAutomationGrant.all_objects.filter(
            organization_id=context.organization_id
        )
        .select_related("site", "collection")
        .order_by("-created_at")
    )
    last_seen = _last_activity(
        context.organization_id, [grant.credential_id for grant in grants]
    )
    return [
        {
            "grant_id": str(grant.id),
            "credential_id": str(grant.credential_id),
            "mode": grant.mode,
            "scope": _scope(grant),
            "expires_at": grant.expires_at,
            "revoked_at": grant.revoked_at,
            "active": grant.active,
            "max_changes_per_day": grant.max_changes_per_day,
            "max_payload_bytes": grant.max_payload_bytes,
            "window_start": grant.window_start,
            "window_end": grant.window_end,
            "last_activity_at": last_seen.get(grant.credential_id),
        }
        for grant in grants
    ]


def list_pending_proposals(*, limit: int = 50) -> list[dict[str, Any]]:
    """Drafts an automation wrote that nobody has published yet.

    Ordered newest first and capped: this is a screen somebody scans, not an
    archive. A proposal superseded by a newer one for the same resource is not
    listed — the queue is about what is waiting now.
    """
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    proposals = list(
        ContentProposal.all_objects.filter(
            organization_id=context.organization_id
        ).order_by("-created_at")[: limit * 4]
    )
    current: dict[tuple[str, UUID], ContentProposal] = {}
    for proposal in proposals:
        key = (proposal.resource_type, proposal.resource_id)
        held = current.get(key)
        if held is None or proposal.version > held.version:
            current[key] = proposal
    return [
        {
            "proposal_id": str(proposal.id),
            "resource_type": proposal.resource_type,
            "resource_id": str(proposal.resource_id),
            "version": proposal.version,
            "credential_id": (
                str(proposal.credential_id) if proposal.credential_id else None
            ),
            # Stated as a claim, not as a finding: the panel shows what
            # SeoContentRank argued, and the person decides.
            "summary": proposal.summary,
            "risk": proposal.risk,
            "expected_outcome": proposal.expected_outcome,
            "sources": proposal.sources,
            "commands": proposal.commands,
            "created_at": proposal.created_at,
        }
        for proposal in sorted(
            current.values(), key=lambda item: item.created_at, reverse=True
        )[:limit]
    ]


def _scope(grant: ContentAutomationGrant) -> dict[str, Any]:
    """A grant names a site or a collection; the database refuses both or
    neither, so one of the two is always there."""
    if grant.site is not None:
        return {"kind": "site", "id": str(grant.site_id), "name": grant.site.slug}
    if grant.collection is not None:
        return {
            "kind": "collection",
            "id": str(grant.collection_id),
            "name": grant.collection.key,
        }
    return {"kind": "unknown", "id": "", "name": ""}


def _last_activity(organization_id: Any, credential_ids: list[UUID]) -> dict[UUID, Any]:
    """When each credential last wrote anything, from the versions it authored.

    Read from the drafts themselves rather than from a counter somebody has to
    remember to increment: a counter that drifts is worse than no counter on a
    screen an operator uses to decide whether to pull a key.
    """
    if not credential_ids:
        return {}
    seen: dict[UUID, Any] = {}
    for model in (PageVersion, ContentEntryVersion):
        rows = (
            model.all_objects.filter(
                organization_id=organization_id,
                created_by_credential__in=credential_ids,
            )
            .values("created_by_credential")
            .annotate(last=Max("created_at"))
        )
        for row in rows:
            credential_id = row["created_by_credential"]
            current = seen.get(credential_id)
            if current is None or row["last"] > current:
                seen[credential_id] = row["last"]
    return seen
