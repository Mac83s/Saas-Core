"""Removing an entry, and erasing the removed ones with their content type
(ADR-079 „Uzupełnienie CT2"; the owner's answers of 2026-10-08).

**Removing** an entry — one language version at a time — takes it off the
site, the lists and the counters, the feeds, the sitemap, `llms.txt`, other
entries' language alternates, the translation sources and what an integration
is shown, all in the same moment: every reader of entries reads
`ContentEntry.all_objects`, which leaves a removed one out. Its address
answers 404 like a withdrawn entry's. The rows stay — versions, publications,
what it was filed under — hidden like a removed page's, and the audit row
says what it was. Its slug, its place in its translation group and its
creation key are given back, so the address can be used again and the article
can get that language again.

**Erasing** happens only with the whole type: a content type whose every
entry is removed can be deleted, and that deletes those entries' texts and
publication history for good. A person decides both; the erasure asks for the
type's name, typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import record_resource_references
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import authorize_entitled

from .collections import (
    ENTRY_VERSION_REFERENCE_OWNER,
    EntryNotFound,
    is_translation_source,
    take_down_entry,
)
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentEntryVersion,
    ContentProposal,
    EntryScheduleState,
    EntryTranslationWrite,
    SiteOutboxEvent,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .publication_routing import published_entry_path
from .services import MEDIA_ASSET_RESOURCE_TYPE, assert_person_required
from .source_changes import notify_entry_withdrawn

ENTRY_REMOVED = "sites.entry.removed"
ENTRY_REMOVE_GATE = "Usunięcie wpisu"
SCHEDULE_CALLED_OFF = "Wpis został usunięty, zanim nadszedł termin publikacji."
CONFIRMATION_REQUIRED = "confirmation_required"

#: How many erased entries an audit row names one by one; it always says how
#: many there were.
AUDIT_NAMED_ENTRIES = 200


@dataclass(frozen=True, slots=True)
class EntryRemoval:
    """Removing an entry: as done, or — in a preview — as it would be."""

    entry: ContentEntry
    title: str
    locale: str
    #: Whether visitors can open it today, and where; that address answers
    #: 404 from the moment it is removed.
    published: bool
    path: str | None
    #: A publication planned for later, which removing calls off.
    scheduled: bool
    #: Whether a translation job made this version: where the site translates
    #: entries by itself, a later job may make it again.
    machine_translation: bool
    #: The article's other language versions, which stay as they are.
    other_languages: tuple[dict[str, str], ...]
    removed: bool = False


@transaction.atomic
def remove_entry(*, entry_id: UUID, dry_run: bool = False) -> EntryRemoval:
    """Removes one entry — one language version of an article; its other
    language versions stay (`other_languages`).

    It leaves the site at once: its address answers 404, and it is on no
    list, in no feed, sitemap or `llms.txt`, among no other entry's language
    versions, in no translation job's offer and in nothing an integration is
    shown. A publication planned for later is called off. Nothing is erased:
    its versions and publications stay as history, hidden, and its slug and
    its language in the article become free. There is no putting it back from
    the panel. An entry of a switched-off type can be removed too — that is
    how such a type is emptied before it is deleted.

    A person's decision (`person_required` for an integration and the
    assistant); taking a published entry off the site needs the right to
    publish. `dry_run` answers with what would happen and writes nothing."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, ENTRY_REMOVE_GATE)
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("collection", "site", "current_publication")
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    published = (
        entry.state == ContentEntryState.PUBLISHED and entry.current_publication is not None
    )
    if published:
        authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    path = (
        published_entry_path(
            entry, entry.current_publication.snapshot, str(entry.site.default_locale)
        )
        if published and entry.current_publication is not None
        else None
    )
    others = tuple(
        {"locale": str(other.locale), "title": str(other.title), "state": str(other.state)}
        for other in ContentEntry.all_objects.filter(
            organization_id=context.organization_id, translation_group=entry.translation_group
        )
        .exclude(pk=entry.pk)
        .order_by("locale")
    )
    result = EntryRemoval(
        entry=entry,
        title=str(entry.title),
        locale=str(entry.locale),
        published=published,
        path=path,
        scheduled=entry.schedule_state == EntryScheduleState.PENDING,
        machine_translation=entry.translation_of_id is not None,
        other_languages=others,
    )
    if dry_run:
        return result
    source = is_translation_source(entry)
    metadata: dict[str, Any] = {
        "title": entry.title,
        "locale": entry.locale,
        "slug": entry.slug,
        "collection_id": str(entry.collection_id),
        "translation_group": str(entry.translation_group),
        "translation_of": str(entry.translation_of_id) if entry.translation_of_id else None,
        "was_published": published,
        "path": path,
        "other_languages": [other["locale"] for other in others],
    }
    if published:
        # Off the site the way a withdrawn entry goes, with its notice to the
        # translation sources: its translations stand on their own.
        take_down_entry(context, entry, reason="removed")
        if source:
            notify_entry_withdrawn(context=context, entry_id=entry.id)
    if entry.schedule_state == EntryScheduleState.PENDING:
        entry.schedule_state = EntryScheduleState.CANCELLED
        entry.schedule_error = SCHEDULE_CALLED_OFF
    entry.state = ContentEntryState.REMOVED
    entry.current_publication = None
    # Given back: the address, the language in the article, the creation key.
    entry.slug = f"removed-{entry.id.hex}"
    entry.translation_group = uuid7()
    entry.idempotency_key = f"removed:{entry.id}"
    entry.save(
        update_fields=[
            "state",
            "current_publication",
            "slug",
            "translation_group",
            "idempotency_key",
            "schedule_state",
            "schedule_error",
            "updated_at",
        ]
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_REMOVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata=metadata,
    )
    return EntryRemoval(
        entry=entry,
        title=result.title,
        locale=result.locale,
        published=published,
        path=path,
        scheduled=result.scheduled,
        machine_translation=result.machine_translation,
        other_languages=others,
        removed=True,
    )


# -- erasing with the type -----------------------------------------------------


def removed_entries(collection: ContentCollection) -> list[ContentEntry]:
    return list(
        ContentEntry.with_removed.filter(
            organization_id=collection.organization_id,
            collection_id=collection.id,
            state=ContentEntryState.REMOVED,
        ).order_by("created_at", "id")
    )


def assert_erasure_confirmed(
    collection: ContentCollection, removed: list[ContentEntry], confirm_name: str
) -> None:
    """Erasing removed entries with their type takes the type's name, typed:
    what goes cannot be brought back."""
    if removed and confirm_name.strip() != collection.name.strip():
        raise ValidationError({
            "confirm_name": [
                ErrorDetail(
                    "Ten typ treści ma usunięte wpisy. Usunięcie typu skasuje na stałe ich "
                    "treść i historię publikacji. Żeby to potwierdzić, wpisz nazwę typu.",
                    code=CONFIRMATION_REQUIRED,
                )
            ]
        })


def erase_removed_entries(context: Any, removed: list[ContentEntry]) -> dict[str, Any]:
    """Deletes removed entries for good — their versions, publications, the
    events of those publications, proposals, translation receipts and what
    they were filed under — and answers with what an audit row keeps of them.
    Called by the deletion of their content type, inside its transaction."""
    if not removed:
        return {"erased_entries": 0}
    ids = [entry.id for entry in removed]
    named = [
        {
            "id": str(entry.id),
            "title": entry.title,
            "locale": entry.locale,
            "removed_at": entry.updated_at.isoformat(),
        }
        for entry in removed[:AUDIT_NAMED_ENTRIES]
    ]
    publications = ContentEntryPublication.all_objects.filter(
        organization_id=context.organization_id, entry_id__in=ids
    )
    versions = ContentEntryVersion.all_objects.filter(
        organization_id=context.organization_id, entry_id__in=ids
    )
    counts = {"publications": publications.count(), "versions": versions.count()}
    # A version's pictures stop being in use by it.
    for version_id in versions.values_list("id", flat=True):
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=ENTRY_VERSION_REFERENCE_OWNER,
            owner_id=version_id,
            resource_ids=(),
        )
    # A translation made from an erased entry is nobody's translation now.
    ContentEntry.with_removed.filter(
        organization_id=context.organization_id, translation_of_id__in=ids
    ).update(translation_of=None, updated_at=timezone.now())
    ContentEntry.with_removed.filter(pk__in=ids).update(
        current_draft=None,
        current_publication=None,
        pending_version=None,
        accepted_version=None,
        translation_of=None,
    )
    EntryTranslationWrite.all_objects.filter(
        organization_id=context.organization_id, entry_id__in=ids
    ).delete()
    ContentProposal.all_objects.filter(
        organization_id=context.organization_id,
        resource_type="content_entry",
        resource_id__in=ids,
    ).delete()
    SiteOutboxEvent.all_objects.filter(
        organization_id=context.organization_id, entry_publication__in=publications
    ).delete()
    ContentEntryTag.all_objects.filter(
        organization_id=context.organization_id, entry_id__in=ids
    ).delete()
    publications.delete()
    # A version may be the source another was translated from, or the draft
    # another replaced: those pointers go first, or the rows hold each other.
    version_ids = list(versions.values_list("id", flat=True))
    every_version = ContentEntryVersion.all_objects.filter(
        organization_id=context.organization_id
    )
    every_version.filter(source_version_id__in=version_ids).update(source_version=None)
    every_version.filter(replaces_id__in=version_ids).update(replaces=None)
    versions.delete()
    ContentEntry.with_removed.filter(pk__in=ids).delete()
    return {
        "erased_entries": len(ids),
        "erased_publications": counts["publications"],
        "erased_versions": counts["versions"],
        "entries": named,
    }


__all__ = [
    "ENTRY_REMOVED",
    "EntryRemoval",
    "assert_erasure_confirmed",
    "erase_removed_entries",
    "remove_entry",
    "removed_entries",
]
