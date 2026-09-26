"""Content collections: repeatable surfaces that publish one entry at a time.

Kept out of `services.py` because the lifecycle genuinely differs. A page belongs
to a site-wide atomic snapshot; an entry is published, withdrawn and rolled back
on its own (ADR-035 §1), and mixing the two flows in one module made both harder
to follow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    ResourceReferenceRejected,
    list_resource_reference_ids,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.observability import correlation_id

from .block_contracts import validate_site_block
from .block_decoration import normalize_block, validate_decoration, validate_presentation
from .localization import entry_path
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentEntryVersion,
    ContentTag,
    EntryScheduleState,
    PageAutomationPolicy,
    Site,
    SiteOutboxEvent,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .real_media import assert_real_media_slots
from .rich_content import assert_unique_anchors, block_asset_ids
from .services import (
    DRAFTABLE_POLICIES,
    MEDIA_ASSET_RESOURCE_TYPE,
    DraftVersionConflict,
    PageAutomationForbidden,
    PageEditingLocked,
    SiteMediaReferenceUnavailable,
    SiteNotFound,
    SitesIdempotencyConflict,
    _idempotency_key,
    _is_automation,
    _schedule_site_outbox_delivery,
    assert_links_within_grant,
    assert_person_blocks,
    assert_person_required,
    assert_within_grant,
    emit_draft_saved_event,
)

COLLECTION_CREATED = "sites.collection.created"
ENTRY_CREATED = "sites.entry.created"
ENTRY_DRAFT_SAVED = "sites.entry.draft_saved"
ENTRY_TAGS_SET = "sites.entry.tags_set"
ENTRY_PUBLISHED = "sites.entry.published"
ENTRY_PUBLISHED_EVENT = "sites.entry.published"
ENTRY_DRAFT_SAVED_EVENT = "sites.entry.draft_saved"
ENTRY_PUBLICATION_SCHEDULED = "sites.entry.publication_scheduled"
ENTRY_SCHEDULE_CANCELLED = "sites.entry.schedule_cancelled"
ENTRY_SCHEDULE_FAILED = "sites.entry.schedule_failed"
ENTRY_WITHDRAWN = "sites.entry.withdrawn"
ENTRY_TRANSLATION_CREATED = "sites.entry.translation_created"
COLLECTION_POLICY_SET = "sites.collection.automation_policy_set"
COLLECTION_NAVIGATION_SET = "sites.collection.navigation_set"
ENTRY_VERSION_REFERENCE_OWNER = "sites.content_entry_version"
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


class EntryTranslationExists(APIException):
    status_code = 409
    default_detail = "Ten artykuł ma już wersję w tym języku."
    default_code = "entry_translation_exists"


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
    media_asset_ids: tuple[UUID, ...] = ()


def _blocks_size(blocks: Any) -> int:
    return len(json.dumps(blocks, ensure_ascii=False, separators=(",", ":")))


def _assert_entry_writable(
    entry: ContentEntry | None,
    collection: ContentCollection,
    *,
    publishing: bool = False,
    payload_bytes: int | None = None,
) -> None:
    """Same two rules as pages (ADR-035 §4a), applied to the collection: the
    policy lives on the collection, the momentary lock on the entry.

    Under `proposed` the automation writes the draft and stops there — putting
    the article in front of readers, or taking it down, stays a person's act.
    Without an entry (one about to be created) there is no lock to respect.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if not _is_automation(context):
        return
    assert_within_grant(
        context,
        site_id=collection.site_id,
        collection_id=collection.id,
        writing=True,
        publishing=publishing,
        payload_bytes=payload_bytes,
    )
    allowed = (
        {PageAutomationPolicy.AUTOMATED} if publishing else DRAFTABLE_POLICIES
    )
    if collection.automation_policy not in allowed:
        raise PageAutomationForbidden
    if (
        entry is not None
        and entry.editing_locked_until is not None
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
    rows = list(
        ContentCollection.all_objects.filter(
            organization_id=context.organization_id, site_id=site_id
        ).order_by("key")
    )
    if not _is_automation(context):
        return rows
    # A key sees the sections its grants name, as in the inventory, not every
    # section the customer has.
    from .inventory import _granted

    return [row for row in rows if _granted(context, site_id, row.id)]


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
    # A new section of the site is the site's business: a grant for one
    # collection never opens another beside it. Checked before the replay, so
    # a revoked key does not get its old answer back either.
    assert_within_grant(context, site_id=site_id, writing=True)
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
    collection = ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).first()
    if collection is None:
        raise CollectionNotFound
    # Titles and addresses of unpublished articles, like a draft, are read
    # only where the key was granted the collection.
    assert_within_grant(
        context, site_id=collection.site_id, collection_id=collection.id
    )
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
    collection = ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).first()
    if collection is None:
        raise CollectionNotFound
    # The title and the address are published with the article, so creating
    # one is writing into the collection: same grant and policy as its draft.
    _assert_entry_writable(None, collection)
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
        ContentEntry.all_objects.select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    # A draft is unpublished work. An integration reads it only where it was
    # granted the collection — otherwise a key issued for one blog could survey
    # everything the customer has not published yet.
    assert_within_grant(
        context, site_id=entry.collection.site_id, collection_id=entry.collection_id
    )
    return EntryDraft(
        entry=entry,
        version=entry.current_draft,
        media_asset_ids=(
            list_resource_reference_ids(
                context=context,
                resource_type=MEDIA_ASSET_RESOURCE_TYPE,
                owner_type=ENTRY_VERSION_REFERENCE_OWNER,
                owner_id=entry.current_draft.id,
            )
            if entry.current_draft is not None
            else ()
        ),
    )


@transaction.atomic
def save_entry_draft(
    *,
    entry_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    media_asset_ids: list[UUID] | None = None,
    idempotency_key: str,
) -> tuple[ContentEntryVersion, bool]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_blocks = [normalize_block(block) for block in blocks]
    for block in normalized_blocks:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    assert_unique_anchors(normalized_blocks)
    assert_real_media_slots(organization_id=context.organization_id, blocks=normalized_blocks)
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
    # The volume of one write, measured on what is actually stored rather than
    # on the request body, so a limit cannot be dodged with whitespace.
    _assert_entry_writable(
        entry,
        entry.collection,
        payload_bytes=_blocks_size(blocks),
    )
    # The same person-only rules as a page draft: an entry is no side door.
    assert_person_blocks(
        context,
        normalized_blocks,
        lambda: entry.current_draft.blocks if entry.current_draft is not None else [],
    )
    if _is_automation(context):
        assert_links_within_grant(
            context,
            site_id=entry.collection.site_id,
            collection_id=entry.collection_id,
            blocks=normalized_blocks,
            base_blocks=entry.current_draft.blocks if entry.current_draft else [],
        )
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
    # Nested images (figures, galleries) are referenced even when unlisted.
    normalized_media_ids = tuple(
        sorted(
            {*(UUID(str(asset_id)) for asset_id in media_asset_ids or []),
             *block_asset_ids(normalized_blocks)},
            key=str,
        )
    )
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=ENTRY_VERSION_REFERENCE_OWNER,
            owner_id=version.id,
            resource_ids=normalized_media_ids,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    entry.version = version.number
    entry.current_draft = version
    entry.save(update_fields=["version", "current_draft", "updated_at"])
    emit_draft_saved_event(
        context=context,
        event_type=ENTRY_DRAFT_SAVED_EVENT,
        resource_type="content_entry",
        resource_id=entry.id,
        version=version.number,
    )
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
        .select_related("collection", "current_draft", "site")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection, publishing=True)
    if entry.current_draft is None or not entry.current_draft.blocks:
        raise EntryNotReady

    published_media_ids = list_resource_reference_ids(
        context=context,
        resource_type=MEDIA_ASSET_RESOURCE_TYPE,
        owner_type=ENTRY_VERSION_REFERENCE_OWNER,
        owner_id=entry.current_draft.id,
    )
    for block in entry.current_draft.blocks:
        validate_decoration(block.get("decoration"))
        validate_presentation(block.get("presentation"))
    assert_real_media_slots(
        organization_id=context.organization_id, blocks=entry.current_draft.blocks
    )
    snapshot = {
        "schema_version": ENTRY_SNAPSHOT_SCHEMA_VERSION,
        "entry_id": str(entry.id),
        "collection_key": entry.collection.key,
        "base_path": entry.collection.base_path,
        "locale": entry.locale,
        "slug": entry.slug,
        "path": entry_path(
            default_locale=entry.site.default_locale,
            locale=entry.locale,
            base_path=entry.collection.base_path,
            slug=entry.slug,
        ),
        "title": entry.title,
        "excerpt": entry.excerpt,
        "author_name": entry.author_name,
        "noindex": entry.noindex,
        # Carried in the snapshot rather than read live: what a visitor sees
        # has to be what was published, including which archives list it.
        "tags": [
            {"slug": tag.slug, "name": tag.name}
            for tag in ContentTag.all_objects.filter(
                organization_id=context.organization_id,
                entry_links__entry_id=entry.id,
            ).order_by("slug")
        ],
        "version": entry.current_draft.number,
        "blocks": entry.current_draft.blocks,
        # Read by the public media endpoint: an asset is fetchable by a visitor
        # only while something published names it.
        "media_asset_ids": [str(asset_id) for asset_id in published_media_ids],
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
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        entry_publication=publication,
        event_type=ENTRY_PUBLISHED_EVENT,
        version=1,
        actor_id=context.actor_id,
        correlation_id=(
            UUID(active_correlation_id) if active_correlation_id else uuid7()
        ),
        causation_id=f"sites-entry-publish:{publication.id}",
        payload={
            "entry_id": str(entry.id),
            "collection_id": str(entry.collection_id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "path": snapshot["path"],
            "locale": entry.locale,
        },
    )
    # After commit, so a subscriber never hears about a publication a rolled
    # back transaction took away again.
    _schedule_site_outbox_delivery(event)
    return publication, True


class TooManyTags(APIException):
    status_code = 400
    default_detail = "Wpis może mieć najwyżej dziesięć tagów."
    default_code = "entry_too_many_tags"


class TagNameInvalid(APIException):
    status_code = 400
    default_detail = "Nazwa tagu nie może być pusta."
    default_code = "entry_tag_name_invalid"


def tag_slug(name: str) -> str:
    """A tag's address, derived from its name rather than typed twice.

    Polish letters fold to their ASCII shapes: an address a person cannot read
    aloud over the phone is one they will not link to.
    """
    folded = name.strip().lower()
    for source_char, target in (
        ("ą", "a"), ("ć", "c"), ("ę", "e"), ("ł", "l"), ("ń", "n"),
        ("ó", "o"), ("ś", "s"), ("ź", "z"), ("ż", "z"),
    ):
        folded = folded.replace(source_char, target)
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug[:80]


@transaction.atomic
def set_entry_tags(*, entry_id: UUID, names: list[str]) -> list[ContentTag]:
    """Replaces the whole set rather than adding to it.

    A caller sending the tags it wants cannot accidentally leave one behind,
    which is what makes this safe to call from an automation replaying the same
    change set twice.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    _assert_entry_writable(entry, entry.collection)

    wanted: dict[str, str] = {}
    for raw in names:
        slug = tag_slug(raw)
        if not slug:
            raise TagNameInvalid
        # First spelling wins, so "Porady" and "porady" are one tag rather than
        # two addresses holding half the archive each.
        wanted.setdefault(slug, raw.strip())
    if len(wanted) > 10:
        raise TooManyTags

    tags: list[ContentTag] = []
    for slug, name in wanted.items():
        tag, _created = ContentTag.all_objects.get_or_create(
            organization_id=context.organization_id,
            site_id=entry.site_id,
            slug=slug,
            defaults={"name": name, "created_by_id": context.actor_id},
        )
        tags.append(tag)
    # One order everywhere — the listing, the snapshot and this reply — so
    # nothing downstream reads meaning into a sequence nothing preserves.
    tags.sort(key=lambda item: item.slug)

    ContentEntryTag.all_objects.filter(
        organization_id=context.organization_id, entry_id=entry.id
    ).exclude(tag_id__in=[tag.id for tag in tags]).delete()
    for tag in tags:
        ContentEntryTag.all_objects.get_or_create(
            organization_id=context.organization_id, entry_id=entry.id, tag_id=tag.id
        )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_TAGS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"tags": [tag.slug for tag in tags]},
    )
    return tags


def entry_tags(*, entry_id: UUID) -> list[ContentTag]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ
    )
    entry = ContentEntry.all_objects.filter(
        pk=entry_id, organization_id=context.organization_id
    ).first()
    if entry is None:
        raise EntryNotFound
    assert_within_grant(context, site_id=entry.site_id, collection_id=entry.collection_id)
    return list(
        ContentTag.all_objects.filter(
            organization_id=context.organization_id,
            entry_links__entry_id=entry_id,
        ).order_by("slug")
    )


class ScheduleInPast(APIException):
    status_code = 400
    default_detail = "Termin publikacji musi być w przyszłości."
    default_code = "entry_schedule_in_past"


class ScheduleNotPending(APIException):
    status_code = 409
    default_detail = "Ten wpis nie ma zaplanowanej publikacji."
    default_code = "entry_schedule_not_pending"


@transaction.atomic
def schedule_entry_publication(
    *, entry_id: UUID, publish_at: datetime
) -> ContentEntry:
    """Asks for this article to go live at a stated moment.

    The check that the author may publish happens twice: now, so a refusal is
    immediate and visible, and again when the moment arrives, because access
    can be withdrawn in between and a queue is not a way around that.
    """
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    entry = (
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
    if publish_at <= timezone.now():
        raise ScheduleInPast

    entry.scheduled_publish_at = publish_at
    entry.schedule_state = EntryScheduleState.PENDING
    entry.schedule_error = ""
    entry.scheduled_by_id = context.actor_id
    # What gets asked again when the moment comes. A key's membership id is
    # synthetic and would never be found, so a key is remembered as itself.
    automation = _is_automation(context)
    entry.scheduled_membership_id = None if automation else context.membership_id
    entry.scheduled_credential_id = context.credential_id if automation else None
    entry.save(
        update_fields=[
            "scheduled_publish_at",
            "schedule_state",
            "schedule_error",
            "scheduled_by",
            "scheduled_membership_id",
            "scheduled_credential_id",
            "updated_at",
        ]
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_PUBLICATION_SCHEDULED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"publish_at": publish_at.isoformat()},
    )
    return entry


@transaction.atomic
def cancel_entry_publication_schedule(*, entry_id: UUID) -> ContentEntry:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    # Calling off a publication decides what readers see, exactly as setting
    # one does, so it takes the same grant and policy.
    _assert_entry_writable(entry, entry.collection, publishing=True)
    if entry.schedule_state != EntryScheduleState.PENDING:
        raise ScheduleNotPending
    # The moment is kept rather than cleared: an operator looking at this
    # tomorrow needs to see what was cancelled, not an empty field.
    entry.schedule_state = EntryScheduleState.CANCELLED
    entry.save(update_fields=["schedule_state", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_SCHEDULE_CANCELLED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={
            "publish_at": (
                entry.scheduled_publish_at.isoformat()
                if entry.scheduled_publish_at
                else None
            )
        },
    )
    return entry


def due_scheduled_entries(*, limit: int = 100) -> list[dict[str, str | None]]:
    """Every article whose moment has arrived, across every tenant.

    Deliberately unscoped, and deliberately returning only identifiers: the
    caller has no tenant context yet, and establishing one per entry is what
    the worker does next. Exactly one of `membership_id` and `credential_id`
    is set — whichever authorised the schedule.
    """
    rows = (
        ContentEntry.all_objects.filter(
            schedule_state=EntryScheduleState.PENDING,
            scheduled_publish_at__lte=timezone.now(),
        )
        .order_by("scheduled_publish_at", "id")
        .values(
            "id",
            "organization_id",
            "scheduled_membership_id",
            "scheduled_credential_id",
            "scheduled_by_id",
        )[:limit]
    )
    return [
        {
            "entry_id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "membership_id": _optional_id(row["scheduled_membership_id"]),
            "credential_id": _optional_id(row["scheduled_credential_id"]),
            "actor_id": str(row["scheduled_by_id"]),
        }
        for row in rows
        if row["scheduled_by_id"]
        and (row["scheduled_membership_id"] or row["scheduled_credential_id"])
    ]


def _optional_id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def close_schedule_without_authority(
    *,
    entry_id: UUID,
    organization_id: str,
    membership_id: str | None,
    credential_id: str | None,
    actor_id: str,
) -> None:
    """Closes a schedule whose author can no longer be acted for.

    Left pending, the scan would hand it to the worker again every minute,
    forever, and the article would never say why it did not appear. Only the
    schedule this run was issued for is closed: a person may have set a new
    one since.
    """
    reason = (
        "Klucz, który zaplanował publikację, jest unieważniony albo stracił zakres publikacji."
        if credential_id
        else "Osoba, która zaplanowała publikację, nie ma już dostępu do organizacji."
    )
    with transaction.atomic():
        # The entry needs no tenant setting; the audit row and the
        # organization it names do.
        set_local_organization_id(UUID(organization_id))
        closed = ContentEntry.all_objects.filter(
            pk=entry_id,
            organization_id=organization_id,
            schedule_state=EntryScheduleState.PENDING,
            scheduled_membership_id=membership_id,
            scheduled_credential_id=credential_id,
        ).update(
            schedule_state=EntryScheduleState.FAILED,
            schedule_error=reason,
            updated_at=timezone.now(),
        )
        if not closed:
            return
        record_audit(
            organization=Organization.objects.get(pk=organization_id),
            action=ENTRY_SCHEDULE_FAILED,
            actor=User.objects.filter(pk=actor_id).first(),
            target_type="content_entry",
            target_id=entry_id,
            metadata={"code": "schedule_authority_lost"},
        )


def run_scheduled_publication(*, entry_id: UUID) -> ContentEntryPublication | None:
    """Publishes one article whose time has come, inside an established tenant.

    Idempotent through the publication's own key: the key is derived from the
    entry and the moment it was scheduled for, so a retried task finds the
    publication it already made rather than making a second one.
    """
    context = require_tenant_context()
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None or entry.schedule_state != EntryScheduleState.PENDING:
        # Cancelled between the scan and the run, or already handled. Not an
        # error: a queue that shouts about work somebody withdrew is a queue
        # people learn to ignore.
        return None
    moment = entry.scheduled_publish_at
    key = f"schedule:{entry.id}:{moment.isoformat() if moment else 'none'}"
    try:
        publication, _created = publish_entry(entry_id=entry.id, idempotency_key=key)
    except APIException as error:
        ContentEntry.all_objects.filter(pk=entry.id).update(
            schedule_state=EntryScheduleState.FAILED,
            schedule_error=str(getattr(error, "detail", error))[:500],
            updated_at=timezone.now(),
        )
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=ENTRY_SCHEDULE_FAILED,
            actor=User.objects.get(pk=context.actor_id),
            target_type="content_entry",
            target_id=entry.id,
            metadata={"code": getattr(error, "default_code", "error")},
        )
        return None
    ContentEntry.all_objects.filter(pk=entry.id).update(
        schedule_state=EntryScheduleState.NONE,
        scheduled_publish_at=None,
        schedule_error="",
        updated_at=timezone.now(),
    )
    return publication


@transaction.atomic
def withdraw_entry(*, entry_id: UUID) -> ContentEntry:
    """Takes an article off the public site without destroying its history: the
    publication rows stay, so republishing is a normal publish, not a restore."""
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    # Taking content off a customer's site is a removal, and ADR-035 §4 keeps
    # removals for a person however wide the grant is.
    assert_person_required(context, "Wycofanie wpisu")
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


@transaction.atomic
def set_collection_navigation(*, collection_id: UUID, show: bool) -> ContentCollection:
    """Whether the published menu links to this collection.

    Publishing the site is what makes the change visible, exactly as it is for
    a page: the menu a visitor sees comes from the snapshot, never from the
    working copy.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    # The menu is what a visitor is steered by, so an integration must not be
    # able to put its own surface into it — the same limit the policy switch
    # has, and enforced here as well as on the route.
    if _is_automation(context):
        raise PageAutomationForbidden
    collection = (
        ContentCollection.all_objects.select_for_update()
        .filter(pk=collection_id, organization_id=context.organization_id)
        .first()
    )
    if collection is None:
        raise CollectionNotFound
    if collection.show_in_navigation != show:
        collection.show_in_navigation = show
        collection.save(update_fields=["show_in_navigation", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=COLLECTION_NAVIGATION_SET,
            actor=User.objects.get(pk=context.actor_id),
            target_type="content_collection",
            target_id=collection.id,
            metadata={"show_in_navigation": show},
        )
    return collection


@transaction.atomic
def create_entry_translation(
    *,
    entry_id: UUID,
    locale: str,
    slug: str,
    title: str,
    idempotency_key: str,
) -> tuple[ContentEntry, bool]:
    """Starts the same article in another language.

    A separate entry rather than another field on this one: the two texts are
    written at different times, published at different times, and one of them
    often never exists. Sharing only the group id is what lets each keep its
    own lifecycle while still being one article to a search engine.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    source = (
        ContentEntry.all_objects.select_related("collection")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if source is None:
        raise EntryNotFound
    _assert_entry_writable(source, source.collection)
    if locale == source.locale:
        raise EntryTranslationExists
    existing = ContentEntry.all_objects.filter(
        organization_id=context.organization_id,
        collection_id=source.collection_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return existing, False
    if ContentEntry.all_objects.filter(
        organization_id=context.organization_id,
        translation_group=source.translation_group,
        locale=locale,
    ).exists():
        raise EntryTranslationExists

    request_hash = canonical_json_hash({
        "entry_id": str(entry_id),
        "locale": locale,
        "slug": slug,
        "title": title,
    })
    translation = ContentEntry.all_objects.create(
        organization_id=context.organization_id,
        collection=source.collection,
        site_id=source.site_id,
        slug=slug,
        locale=locale,
        translation_group=source.translation_group,
        title=title,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_TRANSLATION_CREATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=translation.id,
        metadata={
            "source_entry_id": str(source.id),
            "translation_group": str(source.translation_group),
            "locale": locale,
        },
    )
    return translation, True


def list_entry_translations(*, entry_id: UUID) -> list[ContentEntry]:
    """Every language version of one article, the source included."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    source = ContentEntry.all_objects.filter(
        pk=entry_id, organization_id=context.organization_id
    ).first()
    if source is None:
        raise EntryNotFound
    assert_within_grant(
        context, site_id=source.site_id, collection_id=source.collection_id
    )
    return list(
        ContentEntry.all_objects.select_related("current_draft")
        .filter(
            organization_id=context.organization_id,
            translation_group=source.translation_group,
        )
        .order_by("locale")
    )
