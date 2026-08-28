"""Content collections: repeatable surfaces that publish one entry at a time.

Kept out of `services.py` because the lifecycle genuinely differs. A page belongs
to a site-wide atomic snapshot; an entry is published, withdrawn and rolled back
on its own (ADR-035 §1), and mixing the two flows in one module made both harder
to follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_contracts import validate_site_block
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryVersion,
    PageAutomationPolicy,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import (
    DRAFTABLE_POLICIES,
    DraftVersionConflict,
    PageAutomationForbidden,
    PageEditingLocked,
    SiteNotFound,
    SitesIdempotencyConflict,
    _idempotency_key,
    _is_automation,
    assert_within_grant,
)

COLLECTION_CREATED = "sites.collection.created"
ENTRY_CREATED = "sites.entry.created"
ENTRY_DRAFT_SAVED = "sites.entry.draft_saved"
ENTRY_PUBLISHED = "sites.entry.published"
ENTRY_WITHDRAWN = "sites.entry.withdrawn"
COLLECTION_POLICY_SET = "sites.collection.automation_policy_set"
ENTRY_SNAPSHOT_SCHEMA_VERSION = 1


class CollectionNotFound(NotFound):
    default_detail = "Kolekcja nie istnieje."
    default_code = "content_collection_not_found"


class EntryNotFound(NotFound):
    default_detail = "Wpis nie istnieje."
    default_code = "content_entry_not_found"


class EntrySlugConflict(APIException):
    status_code = 409
    default_detail = "Adres wpisu jest już używany w tej kolekcji i locale."
    default_code = "content_entry_slug_conflict"


class CollectionInvalidPolicy(APIException):
    status_code = 400
    default_detail = "Nieznana polityka automatyzacji."
    default_code = "collection_invalid_policy"


class EntryNotReady(APIException):
    status_code = 409
    default_detail = "Wpis nie ma treści do opublikowania."
    default_code = "content_entry_not_ready"


@dataclass(frozen=True, slots=True)
class EntryDraft:
    entry: ContentEntry
    version: ContentEntryVersion | None


def _assert_entry_writable(
    entry: ContentEntry,
    collection: ContentCollection,
    *,
    publishing: bool = False,
) -> None:
    """Same two rules as pages (ADR-035 §4a), applied to the collection: the
    policy lives on the collection, the momentary lock on the entry.

    Under `proposed` the automation writes the draft and stops there — putting
    the article in front of readers, or taking it down, stays a person's act.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if not _is_automation(context):
        return
    assert_within_grant(
        context, site_id=collection.site_id, collection_id=collection.id
    )
    allowed = (
        {PageAutomationPolicy.AUTOMATED} if publishing else DRAFTABLE_POLICIES
    )
    if collection.automation_policy not in allowed:
        raise PageAutomationForbidden
    if (
        entry.editing_locked_until is not None
        and entry.editing_locked_until > timezone.now()
    ):
        raise PageEditingLocked(
            detail=(
                "Wpis jest edytowany ręcznie do "
                f"{entry.editing_locked_until.isoformat()}."
            )
        )


def list_collections(*, site_id: UUID) -> list[ContentCollection]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id, organization_id=context.organization_id
    ).exists():
        raise SiteNotFound
    return list(
        ContentCollection.all_objects.filter(
            organization_id=context.organization_id, site_id=site_id
        ).order_by("key")
    )


@transaction.atomic
def create_collection(
    *,
    site_id: UUID,
    key: str,
    name: str,
    kind: str,
    base_path: str,
    idempotency_key: str,
) -> tuple[ContentCollection, bool]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    request_hash = canonical_json_hash({
        "site_id": str(site_id),
        "key": key,
        "name": name,
        "kind": kind,
        "base_path": base_path,
    })
    existing = ContentCollection.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return existing, False
    if not Site.all_objects.filter(
        pk=site_id, organization_id=context.organization_id
    ).exists():
        raise SiteNotFound
    collection = ContentCollection.all_objects.create(
        organization_id=context.organization_id,
        site_id=site_id,
        key=key,
        name=name,
        kind=kind,
        base_path=base_path,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=COLLECTION_CREATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={"key": collection.key, "kind": collection.kind},
    )
    return collection, True


def list_entries(
    *,
    collection_id: UUID,
    cursor: UUID | None,
    limit: int,
) -> tuple[list[ContentEntry], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).exists():
        raise CollectionNotFound
    queryset = (
        # The listing reports who wrote each waiting draft, so the draft comes
        # with the row rather than one query per entry.
        ContentEntry.all_objects.select_related("current_draft")
        .filter(organization_id=context.organization_id, collection_id=collection_id)
        .order_by("id")
    )
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


@transaction.atomic
def create_entry(
    *,
    collection_id: UUID,
    slug: str,
    locale: str,
    title: str,
    idempotency_key: str,
) -> tuple[ContentEntry, bool]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    request_hash = canonical_json_hash({
        "collection_id": str(collection_id),
        "slug": slug,
        "locale": locale,
        "title": title,
    })
    existing = ContentEntry.all_objects.filter(
        organization_id=context.organization_id,
        collection_id=collection_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return existing, False
    collection = ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).first()
    if collection is None:
        raise CollectionNotFound
    if ContentEntry.all_objects.filter(
        organization_id=context.organization_id,
        collection_id=collection_id,
        locale=locale,
        slug=slug.strip().lower(),
    ).exists():
        raise EntrySlugConflict
    entry = ContentEntry.all_objects.create(
        organization_id=context.organization_id,
        collection=collection,
        site_id=collection.site_id,
        slug=slug,
        locale=locale,
        title=title,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_CREATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"slug": entry.slug, "locale": entry.locale},
    )
    return entry, True


def get_entry_draft(*, entry_id: UUID) -> EntryDraft:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    entry = (
        ContentEntry.all_objects.select_related("current_draft", "collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    # A draft is unpublished work. An integration reads it only where it was
    # granted the collection — otherwise a key issued for one blog could survey
    # everything the customer has not published yet.
    assert_within_grant(
        context, site_id=entry.site_id, collection_id=entry.collection_id
    )
    return EntryDraft(entry=entry, version=entry.current_draft)


@transaction.atomic
def save_entry_draft(
    *,
    entry_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    idempotency_key: str,
) -> tuple[ContentEntryVersion, bool]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_blocks = [
        {
            "block_type": block["block_type"],
            "schema_version": block["schema_version"],
            "data": block["data"],
        }
        for block in blocks
    ]
    for block in normalized_blocks:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    request_hash = canonical_json_hash({
        "entry_id": str(entry_id),
        "expected_version": expected_version,
        "blocks": normalized_blocks,
    })
    existing = ContentEntryVersion.all_objects.filter(
        organization_id=context.organization_id,
        entry_id=entry_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return existing, False
    entry = (
        ContentEntry.all_objects.select_for_update()
        .select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection)
    if entry.version != expected_version:
        raise DraftVersionConflict
    version = ContentEntryVersion.all_objects.create(
        organization_id=context.organization_id,
        entry=entry,
        number=entry.version + 1,
        blocks=normalized_blocks,
        content_hash=canonical_json_hash({"blocks": normalized_blocks}),
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        created_by_credential=(
            context.credential_id if _is_automation(context) else None
        ),
    )
    entry.version = version.number
    entry.current_draft = version
    entry.save(update_fields=["version", "current_draft", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_DRAFT_SAVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"version": version.number},
    )
    return version, True


@transaction.atomic
def publish_entry(
    *,
    entry_id: UUID,
    idempotency_key: str,
    published_at: Any = None,
) -> tuple[ContentEntryPublication, bool]:
    """Publishes one article.

    The snapshot holds this entry alone, which is what keeps the cost flat: a
    blog with ten thousand articles publishes the ten-thousand-and-first in the
    same time as its first.
    """
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    existing = ContentEntryPublication.all_objects.filter(
        organization_id=context.organization_id,
        entry_id=entry_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return existing, False
    entry = (
        # `of=("self",)` because `current_draft` is nullable: PostgreSQL refuses
        # FOR UPDATE on the nullable side of an outer join, and the row we need
        # to lock is the entry itself.
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("collection", "current_draft")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection, publishing=True)
    if entry.current_draft is None or not entry.current_draft.blocks:
        raise EntryNotReady

    snapshot = {
        "schema_version": ENTRY_SNAPSHOT_SCHEMA_VERSION,
        "entry_id": str(entry.id),
        "collection_key": entry.collection.key,
        "base_path": entry.collection.base_path,
        "locale": entry.locale,
        "slug": entry.slug,
        "path": f"/{entry.collection.base_path}/{entry.slug}/",
        "title": entry.title,
        "excerpt": entry.excerpt,
        "author_name": entry.author_name,
        "noindex": entry.noindex,
        "version": entry.current_draft.number,
        "blocks": entry.current_draft.blocks,
    }
    last = (
        ContentEntryPublication.all_objects.filter(
            organization_id=context.organization_id, entry_id=entry.id
        )
        .order_by("-sequence")
        .first()
    )
    publication = ContentEntryPublication.all_objects.create(
        organization_id=context.organization_id,
        entry=entry,
        sequence=(last.sequence + 1) if last else 1,
        snapshot=snapshot,
        snapshot_hash=canonical_json_hash(snapshot),
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    )
    entry.current_publication = publication
    entry.state = ContentEntryState.PUBLISHED
    # Set once, on first publication: later edits update the article without
    # moving it up the index, which is what a reader expects from a blog.
    if entry.published_at is None:
        entry.published_at = published_at or timezone.now()
    entry.save(
        update_fields=["current_publication", "state", "published_at", "updated_at"]
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_PUBLISHED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"sequence": publication.sequence},
    )
    return publication, True


@transaction.atomic
def withdraw_entry(*, entry_id: UUID) -> ContentEntry:
    """Takes an article off the public site without destroying its history: the
    publication rows stay, so republishing is a normal publish, not a restore."""
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    entry = (
        ContentEntry.all_objects.select_for_update()
        .select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection, publishing=True)
    entry.state = ContentEntryState.WITHDRAWN
    entry.current_publication = None
    entry.save(update_fields=["state", "current_publication", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_WITHDRAWN,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={},
    )
    return entry


@transaction.atomic
def set_collection_automation_policy(
    *, collection_id: UUID, policy: str
) -> ContentCollection:
    """Only a person changes this, for the same reason as a page: a credential
    able to widen its own reach would not be a limit."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        raise PageAutomationForbidden
    if policy not in PageAutomationPolicy.values:
        raise CollectionInvalidPolicy
    collection = (
        ContentCollection.all_objects.select_for_update()
        .filter(pk=collection_id, organization_id=context.organization_id)
        .first()
    )
    if collection is None:
        raise CollectionNotFound
    collection.automation_policy = policy
    collection.save(update_fields=["automation_policy", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=COLLECTION_POLICY_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={"automation_policy": policy},
    )
    return collection
