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

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    ContentAutomationGrant,
    ContentEntry,
    ContentEntryVersion,
    ContentProposal,
    Page,
    PageBlock,
    PageVersion,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import assert_person_required

PROPOSAL_DISCARDED = "sites.proposal.discarded"


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
        _proposal_payload(proposal)
        for proposal in sorted(
            current.values(), key=lambda item: item.created_at, reverse=True
        )[:limit]
    ]


def read_proposal(*, proposal_id: UUID) -> dict[str, Any]:
    """One proposal, with what the draft looked like before and after it.

    The diff is rebuilt from the two stored versions rather than from the
    change set that arrived. What is in the database is what a visitor would
    get if this were published; the document that asked for it is the sender's
    account of its own intent, and an operator deciding should be looking at
    the former.
    """
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    proposal = ContentProposal.all_objects.filter(
        pk=proposal_id, organization_id=context.organization_id
    ).first()
    if proposal is None:
        raise ProposalNotFound

    version_model: Any = (
        PageVersion if proposal.resource_type == "site_page" else ContentEntryVersion
    )
    field = "page_id" if proposal.resource_type == "site_page" else "entry_id"
    versions = {
        version.number: version
        for version in version_model.all_objects.filter(
            organization_id=context.organization_id,
            **{field: proposal.resource_id},
            number__in=[proposal.version, proposal.version - 1],
        )
    }
    return {
        **_proposal_payload(proposal),
        "blocks_before": _blocks(
            context, proposal, versions.get(proposal.version - 1)
        ),
        "blocks_after": _blocks(context, proposal, versions.get(proposal.version)),
    }


def _blocks(context: Any, proposal: ContentProposal, version: Any) -> list[dict[str, Any]]:
    if version is None:
        return []
    if proposal.resource_type != "site_page":
        return list(version.blocks)
    return [
        {
            "block_type": block.block_type,
            "schema_version": block.schema_version,
            "data": block.data,
        }
        for block in PageBlock.all_objects.filter(
            organization_id=context.organization_id, page_version_id=version.id
        ).order_by("position")
    ]


def _proposal_payload(proposal: ContentProposal) -> dict[str, Any]:
    return {
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


class ProposalNotFound(NotFound):
    default_detail = "Propozycja nie istnieje."
    default_code = "proposal_not_found"


class ProposalSuperseded(APIException):
    status_code = 409
    default_detail = "Draft zmienił się od czasu tej propozycji."
    default_code = "proposal_superseded"


@transaction.atomic
def discard_proposal(*, proposal_id: UUID) -> dict[str, Any]:
    """Puts the draft back to the version before the proposal arrived.

    Rejecting has to mean something, and the only honest meaning available is
    "undo what the automation wrote". Nothing is deleted: versions are
    immutable and stay, and the pointer moves back — so a rejection can be
    looked at afterwards, and the text that was proposed is still on record.

    A person's own edit after the proposal supersedes it. Reverting then would
    throw away work nobody asked us to touch, so it refuses instead.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Odrzucenie propozycji")
    proposal = ContentProposal.all_objects.filter(
        pk=proposal_id, organization_id=context.organization_id
    ).first()
    if proposal is None:
        raise ProposalNotFound

    resource: Any
    if proposal.resource_type == "site_page":
        resource = Page.all_objects.select_for_update().filter(
            pk=proposal.resource_id, organization_id=context.organization_id
        ).first()
        version_model: Any = PageVersion
        audit_target = "page"
    else:
        resource = ContentEntry.all_objects.select_for_update().filter(
            pk=proposal.resource_id, organization_id=context.organization_id
        ).first()
        version_model = ContentEntryVersion
        audit_target = "content_entry"
    if resource is None:
        raise ProposalNotFound
    if resource.version != proposal.version:
        raise ProposalSuperseded

    field = "page_id" if proposal.resource_type == "site_page" else "entry_id"
    previous = (
        version_model.all_objects.filter(
            organization_id=context.organization_id,
            **{field: proposal.resource_id},
        )
        .filter(number__lt=proposal.version)
        .order_by("-number")
        .first()
    )
    resource.current_draft = previous
    resource.version = previous.number if previous is not None else 0
    resource.save(update_fields=["current_draft", "version", "updated_at"])

    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=PROPOSAL_DISCARDED,
        actor=User.objects.get(pk=context.actor_id),
        target_type=audit_target,
        target_id=proposal.resource_id,
        metadata={
            "proposal_id": str(proposal.id),
            "discarded_version": proposal.version,
            "restored_version": resource.version,
        },
    )
    proposal.delete()
    return {
        "resource_type": proposal.resource_type,
        "resource_id": str(proposal.resource_id),
        "restored_version": resource.version,
    }
