"""A site's content types as the company runs them (ADR-079 pkt 1, 21–25).

A content type is a `ContentCollection`: the blog is the first, „Realizacje”
may be the second. Making one stays in `collections.create_collection`; this
module is everything a company does with a type afterwards — what it is
called and what it is to search engines and feed readers, switching it off
and on again, removing an empty one — and the one read the panel's list and
the assistant take their choices from.

Every operation is a service with typed arguments, a preview where it decides
something a visitor sees, and an audit row; the views only validate shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import field_changes, record_audit
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .collections import CollectionNotFound
from .content_type_limit import (
    ContentTypeArchived,
    ContentTypesLimit,
    content_types_limit,
    ensure_content_type_capacity,
)
from .localization import collection_index_path
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    ContentSchemaType,
    EntryScheduleState,
    Site,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import SiteNotFound, assert_person_required, assert_within_grant

CONTENT_TYPE_UPDATED = "sites.content_type.updated"
CONTENT_TYPE_SWITCHED_OFF = "sites.content_type.switched_off"
CONTENT_TYPE_SWITCHED_ON = "sites.content_type.switched_on"
CONTENT_TYPE_DELETED = "sites.content_type.deleted"

#: Taking a type off the site and bringing it back decide what visitors can
#: open; removing one is a removal. A person's, each of them (ADR-079 pkt 23).
SWITCH_OFF_GATE = "Wyłączenie typu treści"
SWITCH_ON_GATE = "Włączenie typu treści"
DELETE_GATE = "Usunięcie typu treści"

SCHEDULE_CALLED_OFF = "Typ treści został wyłączony, zanim nadszedł termin publikacji."

NAME_MIN, NAME_MAX = 2, 160

#: What a company chooses from when it says what a type's entries are, in the
#: order the panel offers them, with the feed's default for each (pkt 18): an
#: article-like type joins the site's feed, a type of plain pages does not —
#: projects do not land in the blog readers' reader until the company wants.
SCHEMA_TYPES: tuple[dict[str, Any], ...] = (
    {
        "schema_type": ContentSchemaType.BLOG_POSTING.value,
        "title": {"pl": "Wpisy bloga", "en": "Blog posts"},
        "hint": {
            "pl": "Artykuły, porady, poradniki — treść z autorem i datą.",
            "en": "Articles, tips, guides — content with an author and a date.",
        },
        "in_site_feed": True,
    },
    {
        "schema_type": ContentSchemaType.NEWS_ARTICLE.value,
        "title": {"pl": "Aktualności", "en": "News"},
        "hint": {
            "pl": "Wiadomości i komunikaty, w których liczy się dzień publikacji.",
            "en": "News and announcements, where the day of publication matters.",
        },
        "in_site_feed": True,
    },
    {
        "schema_type": ContentSchemaType.ARTICLE.value,
        "title": {"pl": "Artykuły", "en": "Articles"},
        "hint": {
            "pl": "Dłuższe teksty, które nie są wpisami bloga ani aktualnościami.",
            "en": "Longer texts that are neither blog posts nor news.",
        },
        "in_site_feed": True,
    },
    {
        "schema_type": ContentSchemaType.WEB_PAGE.value,
        "title": {"pl": "Zwykłe strony", "en": "Plain pages"},
        "hint": {
            "pl": "Realizacje, oferty, miejsca — strony, które nie są artykułami.",
            "en": "Projects, offers, places — pages that are not articles.",
        },
        "in_site_feed": False,
    },
)


def default_in_site_feed(schema_type: str) -> bool:
    return next(
        (
            bool(item["in_site_feed"])
            for item in SCHEMA_TYPES
            if item["schema_type"] == schema_type
        ),
        True,
    )


class ContentTypeNotEmpty(APIException):
    status_code = 409
    default_detail = (
        "Typ treści ma wpisy, więc nie można go usunąć. Można go wyłączyć: "
        "wpisy zostaną, a typ zniknie ze strony."
    )
    default_code = "content_type_not_empty"


@dataclass(frozen=True, slots=True)
class ContentTypeRow:
    """A content type with what the list says about it."""

    collection: ContentCollection
    #: Its entries, drafts included, and those visitors can open.
    entries: int
    published: int
    #: The languages it has entries in, in the company's order.
    locales: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContentTypes:
    """A site's content types and whether it may have one more."""

    #: The first made first — the blog leads; switched-off ones included.
    types: tuple[ContentTypeRow, ...]
    limit: ContentTypesLimit


@dataclass(frozen=True, slots=True)
class ContentTypeSwitch:
    """Switching a type off or on: as done, or — in a preview — as it would be."""

    collection: ContentCollection
    #: False when the type already is what was asked for.
    changed: bool
    #: The entries visitors can open today (off) or will open again (on).
    published: int
    #: Publications planned for later that switching off calls off.
    scheduled: int
    #: Where the type's list answers per language — the addresses that stop
    #: answering (off) or answer again (on), with every entry under them.
    paths: dict[str, str]
    #: Whether the type could be switched on again right after this, on the
    #: plan as it is. Always true for switching on.
    restorable: bool
    #: Why not, in a company owner's words and as a code; "" when restorable.
    restore_problem: str = ""
    restore_problem_code: str = ""


def _site(context: Any, site_id: UUID, *, lock: bool = False) -> Site:
    sites = Site.all_objects.filter(pk=site_id, organization_id=context.organization_id)
    site = (sites.select_for_update() if lock else sites).first()
    if site is None:
        raise SiteNotFound
    return site


def _collection(context: Any, collection_id: UUID) -> ContentCollection:
    collection = ContentCollection.all_objects.filter(
        pk=collection_id, organization_id=context.organization_id
    ).first()
    if collection is None:
        raise CollectionNotFound
    return collection


def _locked(context: Any, collection_id: UUID) -> tuple[Site, ContentCollection]:
    """The type and its site, both locked, the site first: every change of
    what types a site has runs one at a time, as making one does."""
    found = _collection(context, collection_id)
    site = _site(context, found.site_id, lock=True)
    collection = ContentCollection.all_objects.select_for_update().get(pk=found.pk)
    collection.site = site
    return site, collection


def list_content_types(*, site_id: UUID) -> ContentTypes:
    """A site's content types, the first made first, with how many entries
    each has and in which languages, and the gates' word on making one more
    (`limit`). Switched-off types are listed and marked: they can be switched
    on or, when empty, removed. An integration sees the types its grants
    name, as in the list of sections."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ
    )
    site = _site(context, site_id)
    rows = list(
        ContentCollection.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id
        ).order_by("created_at", "id")
    )
    if context.principal_kind != "membership":
        from .inventory import _granted

        rows = [row for row in rows if _granted(context, site.id, row.id)]
    counted = (
        ContentEntry.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id
        )
        .values("collection_id", "locale")
        .annotate(
            entries=Count("id"),
            published=Count(
                "id",
                filter=Q(state=ContentEntryState.PUBLISHED, current_publication__isnull=False),
            ),
        )
    )
    by_type: dict[UUID, dict[str, tuple[int, int]]] = {}
    for item in counted:
        by_type.setdefault(item["collection_id"], {})[item["locale"]] = (
            item["entries"],
            item["published"],
        )
    order = _company_locales(site)
    return ContentTypes(
        types=tuple(
            ContentTypeRow(
                collection=row,
                entries=sum(count for count, _published in by_type.get(row.id, {}).values()),
                published=sum(published for _count, published in by_type.get(row.id, {}).values()),
                locales=tuple(
                    sorted(
                        by_type.get(row.id, {}),
                        key=lambda code: (order.index(code) if code in order else len(order), code),
                    )
                ),
            )
            for row in rows
        ),
        limit=content_types_limit(site),
    )


def _company_locales(site: Site) -> list[str]:
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    return list(dict.fromkeys((site.default_locale, *organization_content_locales(organization))))


def _answering_paths(site: Site, collection: ContentCollection) -> dict[str, str]:
    """Where the type's list answers a visitor: the site's own language
    always, another one once it has an entry out."""
    written = set(
        ContentEntry.all_objects.filter(
            organization_id=site.organization_id,
            collection_id=collection.id,
            state=ContentEntryState.PUBLISHED,
            current_publication__isnull=False,
        ).values_list("locale", flat=True)
    )
    return {
        locale: collection_index_path(
            collection, default_locale=site.default_locale, locale=locale
        )
        for locale in _company_locales(site)
        if locale == site.default_locale or locale in written
    }


@transaction.atomic
def update_content_type(
    *,
    collection_id: UUID,
    name: str | None = None,
    schema_type: str | None = None,
    in_site_feed: bool | None = None,
    dry_run: bool = False,
) -> tuple[ContentCollection, bool]:
    """Changes what a content type is called (`name`), what its entries are to
    search engines (`schema_type`, one of `SCHEMA_TYPES`) and whether they are
    in the site's RSS and Atom feeds (`in_site_feed`). A field left out stays.

    All three are read when a page is asked for, so the change is on the site
    at once and nothing is republished: the heading of the type's list, the
    structured data of every entry, the feeds. One place is not: the site's
    menu names the type as the site's last publication did, so a new name
    reaches the menu with the site's next publication — like every menu
    change. The type's addresses are another operation
    (`set_collection_paths`). `dry_run` validates and answers with the type as
    it would be, and writes nothing. Answers `(type, changed)`.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    found = _collection(context, collection_id)
    # What a type is belongs to the site, like making one: a key hired for
    # one section does not rename it or change what search engines read.
    assert_within_grant(context, site_id=found.site_id, writing=True)
    _site_row, collection = _locked(context, collection_id)
    if collection.archived_at is not None:
        raise ContentTypeArchived
    problems: dict[str, list[ErrorDetail]] = {}
    before = {
        "name": collection.name,
        "schema_type": collection.schema_type,
        "in_site_feed": collection.in_site_feed,
    }
    if name is not None:
        normalized = " ".join(name.split())
        if not NAME_MIN <= len(normalized) <= NAME_MAX:
            problems["name"] = [
                ErrorDetail(
                    f"Nazwa typu treści ma od {NAME_MIN} do {NAME_MAX} znaków.",
                    code="name_length",
                )
            ]
        collection.name = normalized
    if schema_type is not None:
        if schema_type not in ContentSchemaType.values:
            problems["schema_type"] = [
                ErrorDetail("Nie ma takiego rodzaju treści.", code="invalid_choice")
            ]
        collection.schema_type = schema_type
    if in_site_feed is not None:
        collection.in_site_feed = in_site_feed
    if problems:
        raise ValidationError(problems)
    after = {
        "name": collection.name,
        "schema_type": collection.schema_type,
        "in_site_feed": collection.in_site_feed,
    }
    changed = after != before
    if dry_run or not changed:
        return collection, changed
    collection.save(update_fields=["name", "schema_type", "in_site_feed", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=CONTENT_TYPE_UPDATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={"changes": field_changes(before, after)},
    )
    return collection, True


def _restore_word(site: Site, collection: ContentCollection) -> tuple[bool, str, str]:
    limit = content_types_limit(site, beside=collection)
    return limit.allowed, limit.message, limit.code


@transaction.atomic
def switch_off_content_type(*, collection_id: UUID, dry_run: bool = False) -> ContentTypeSwitch:
    """Takes a content type off the site without removing anything.

    From the moment it is saved every address of the type — its list, entries,
    subjects' archives, their later pages — answers 404, and the type leaves
    the menu, the feeds, the sitemap and every other page's language links.
    Its entries stay as they are, published ones included, but are not edited
    or published while the type is off — only withdrawn, by a person, so that
    an entry does not return with the type; publications planned for later
    are called off, with the reason on the entry. The type's names in
    addresses stay taken, so switching it on brings everything back where it
    was.

    A switched-off type does not count to the plan's limit, and switching it
    on needs room in it: `restorable` says whether the plan as it is would let
    it back, and `restore_problem` why not. `dry_run` answers the same without
    saving. A person's decision: an integration and the assistant are refused
    (`person_required`).
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, SWITCH_OFF_GATE)
    if dry_run:
        collection = _collection(context, collection_id)
        site = _site(context, collection.site_id)
    else:
        site, collection = _locked(context, collection_id)
    entries = ContentEntry.all_objects.filter(
        organization_id=context.organization_id, collection_id=collection.id
    )
    scheduled = entries.filter(schedule_state=EntryScheduleState.PENDING)
    restorable, problem, code = _restore_word(site, collection)
    result = ContentTypeSwitch(
        collection=collection,
        changed=collection.archived_at is None,
        published=entries.filter(
            state=ContentEntryState.PUBLISHED, current_publication__isnull=False
        ).count(),
        scheduled=scheduled.count(),
        paths=_answering_paths(site, collection),
        restorable=restorable,
        restore_problem=problem,
        restore_problem_code=code,
    )
    if dry_run or not result.changed:
        return result
    moment = timezone.now()
    called_off = [str(entry_id) for entry_id in scheduled.values_list("id", flat=True)]
    scheduled.update(
        schedule_state=EntryScheduleState.CANCELLED,
        schedule_error=SCHEDULE_CALLED_OFF,
        updated_at=moment,
    )
    collection.archived_at = moment
    collection.save(update_fields=["archived_at", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=CONTENT_TYPE_SWITCHED_OFF,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={
            "key": collection.key,
            "published": result.published,
            "paths": result.paths,
            "schedules_called_off": called_off,
        },
    )
    return result


@transaction.atomic
def switch_on_content_type(*, collection_id: UUID, dry_run: bool = False) -> ContentTypeSwitch:
    """Puts a switched-off content type back on the site: its list and every
    entry that was out answer again at the addresses they had, at once, and
    it is back in the menu (where it was set to be), the feeds and the sitemap.

    Needs room in the plan's limit and the platform's offer, like making a
    type (`quota_exceeded`, `plan_access_denied`, `content_types_not_offered`)
    — otherwise switching types off and on in turn would walk around the
    limit. Publications called off when it was switched off stay called off.
    `dry_run` answers without saving. A person's decision.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, SWITCH_ON_GATE)
    if dry_run:
        collection = _collection(context, collection_id)
        site = _site(context, collection.site_id)
    else:
        site, collection = _locked(context, collection_id)
    changed = collection.archived_at is not None
    if changed:
        ensure_content_type_capacity(site, beside=collection)
    result = ContentTypeSwitch(
        collection=collection,
        changed=changed,
        published=ContentEntry.all_objects.filter(
            organization_id=context.organization_id,
            collection_id=collection.id,
            state=ContentEntryState.PUBLISHED,
            current_publication__isnull=False,
        ).count(),
        scheduled=0,
        paths=_answering_paths(site, collection),
        restorable=True,
    )
    if dry_run or not changed:
        return result
    collection.archived_at = None
    collection.save(update_fields=["archived_at", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=CONTENT_TYPE_SWITCHED_ON,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={"key": collection.key, "published": result.published, "paths": result.paths},
    )
    return result


@dataclass(frozen=True, slots=True)
class ContentTypeRemoval:
    """Deleting a content type: as done, or — in a preview — as it would be."""

    collection: ContentCollection
    #: Entries that keep the type: it is deleted only when it has none.
    entries: int
    #: Entries a person removed. Deleting the type erases them for good —
    #: their texts and their publication history — which is why it then asks
    #: for the type's name.
    removed_entries: int
    removed_publications: int
    #: The type's categories, which go with it.
    categories: int
    #: Where the type's list answered per language: the names that become free.
    paths: dict[str, str]
    deletable: bool
    confirmation_required: bool
    deleted: bool = False


@transaction.atomic
def delete_content_type(
    *, collection_id: UUID, confirm_name: str = "", dry_run: bool = False
) -> ContentTypeRemoval:
    """Removes a content type that has no entry — a draft counts
    (`content_type_not_empty`); a type with entries is switched off instead,
    or its entries are removed first, one by one.

    Entries a person removed do not keep the type, and go with it **for
    good**: their texts, versions and publication history are erased and
    cannot be brought back. Because of that, deleting a type that has removed
    entries takes its name typed in `confirm_name` (`confirmation_required`
    without it); the preview says how many entries and publications would be
    erased. The type's categories go with it, its names in addresses become
    free, its former names stop leading anywhere, and automation grants that
    named it go too. Switched on or off alike.

    A person's decision only — never an integration key or the assistant
    (`person_required`). Deleting what is already gone is a 404. `dry_run`
    answers with what would happen and writes nothing.
    """
    from .entry_removal import assert_erasure_confirmed, erase_removed_entries, removed_entries
    from .models import ContentEntryPublication, ContentTag

    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, DELETE_GATE)
    site, collection = _locked(context, collection_id)
    kept = ContentEntry.all_objects.filter(
        organization_id=context.organization_id, collection_id=collection.id
    ).count()
    removed = removed_entries(collection)
    categories = ContentTag.all_objects.filter(
        organization_id=context.organization_id, taxonomy__collection_id=collection.id
    ).count()
    result = ContentTypeRemoval(
        collection=collection,
        entries=kept,
        removed_entries=len(removed),
        removed_publications=ContentEntryPublication.all_objects.filter(
            organization_id=context.organization_id, entry_id__in=[entry.id for entry in removed]
        ).count(),
        categories=categories,
        paths={
            locale: collection_index_path(
                collection, default_locale=site.default_locale, locale=locale
            )
            for locale in _company_locales(site)
        },
        deletable=kept == 0,
        confirmation_required=bool(removed),
    )
    if dry_run:
        return result
    if kept:
        raise ContentTypeNotEmpty
    assert_erasure_confirmed(collection, removed, confirm_name)
    metadata = {
        "key": collection.key,
        "name": collection.name,
        "base_path": collection.base_path,
        "locale_paths": dict(collection.locale_paths or {}),
        "categories": categories,
        # What was erased with it, kept here because nothing else is.
        **erase_removed_entries(context, removed),
    }
    target_id = collection.id
    collection.delete()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=CONTENT_TYPE_DELETED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=target_id,
        metadata=metadata,
    )
    return ContentTypeRemoval(
        collection=collection,
        entries=0,
        removed_entries=result.removed_entries,
        removed_publications=result.removed_publications,
        categories=categories,
        paths=result.paths,
        deletable=True,
        confirmation_required=result.confirmation_required,
        deleted=True,
    )
