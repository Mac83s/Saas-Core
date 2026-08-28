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
from saas_core.modules.core.organizations.api import (
    ResourceReferenceRejected,
    list_resource_reference_ids,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_contracts import validate_site_block
from .localization import entry_path
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
    MEDIA_ASSET_RESOURCE_TYPE,
    DraftVersionConflict,
    PageAutomationForbidden,
    PageEditingLocked,
    SiteMediaReferenceUnavailable,
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
    normalized_media_ids = tuple(sorted(set(media_asset_ids or []), key=str))
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
