"""An entry's address: its slug, the slugs it had, and changing one
(ADR-079 pkt 13, 14, 16; „Uzupełnienie CT4”).

An entry answers under one slug in its content type and language. Changing it
before the entry ever went out is free and leaves nothing behind. After that
the address is something visitors and search engines hold: only a person
changes it, with a stated reason where it answers today; the slug it had
joins `ContentEntry.former_slugs` and answers one 308 to today's address
(`public_archives.moved_address`), and a published entry is published again
under the new address **with the content of its current publication** — what
waits in the draft stays in the draft.

Whose former slugs count. A slug an entry of the same type and language once
had is taken for everything that picks an address by itself — a slug made
from a title, an entry an integration or the assistant creates — and for a
new entry anybody creates. A person can take it over when changing an
address: the preview names the redirect that stops, and saving asks for it
(`take_over_former`). A removed entry has no slugs left to hold (its row is
renamed and no reader sees it); a withdrawn entry keeps its own, because it
can come back.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .localization import entry_path, section_segment
from .models import ContentCollection, ContentEntry, ContentEntryState
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import _is_automation, assert_person_required

ENTRY_ADDRESS_CHANGED = "sites.entry.address_changed"
ENTRY_FORMER_SLUGS_RECORDED = "sites.entry.former_slugs_recorded"

#: The label of the person-only gate (`assert_person_required`).
ENTRY_ADDRESS_GATE = "Zmiana adresu opublikowanego wpisu"

ENTRY_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
#: `ContentEntry.slug` holds 140; a slug made from a title with a number
#: after it must still fit.
ENTRY_SLUG_MAX = 120
#: How many slugs an entry remembers. Past it the oldest stay: an address
#: search engines learned first is the one most worth keeping.
ENTRY_FORMER_SLUGS_MAX = 50

ENTRY_SLUG_INVALID = "entry_slug_invalid"
ENTRY_SLUG_TAKEN = "entry_slug_taken"
ENTRY_SLUG_FORMER = "entry_slug_former"
ENTRY_REASON_REQUIRED = "redirect_reason_required"
#: Why a publication exists: the entry's address changed, its text did not.
ADDRESS_CHANGE_REASON = "address_changed"


def _error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(message, code=code)]})


@dataclass(frozen=True, slots=True)
class EntryAddressChange:
    """A change of an entry's address: as done, or — in a preview — as it
    would be."""

    entry: ContentEntry
    #: The slug before, and the slug as it is (would be) afterwards.
    previous_slug: str
    slug: str
    #: Where the entry answers (would answer) afterwards.
    path: str
    changed: bool
    #: The entry answers visitors today: the change publishes it again.
    published: bool
    #: Addresses visitors can open today that move, each with one 308:
    #: [{"from_path", "to_path"}]. Not empty means a reason is required.
    moved: tuple[dict[str, str], ...] = ()
    #: Every address that redirects to the entry afterwards.
    redirects: tuple[dict[str, str], ...] = ()
    #: Redirects of other entries that stop, because this entry takes the
    #: slug they started from: [{"slug", "entry_id", "title"}].
    takes_over: tuple[dict[str, str], ...] = ()
    #: The draft holds changes the current publication does not. They stay
    #: unpublished: the address change publishes what is public already.
    unpublished_changes: bool = False


def valid_entry_slug(value: str) -> bool:
    return bool(ENTRY_SLUG_PATTERN.fullmatch(value)) and len(value) <= ENTRY_SLUG_MAX


def former_slug_owners(
    *,
    organization_id: Any,
    collection_id: Any,
    locale: str,
    slug: str,
    exclude: Any | None = None,
) -> list[ContentEntry]:
    """Entries of the type and language that once answered under `slug`.
    Removed entries are not read: they hold no address any more."""
    owners = ContentEntry.all_objects.filter(
        organization_id=organization_id,
        collection_id=collection_id,
        locale=locale,
        former_slugs__contains=[slug],
    )
    if exclude is not None:
        owners = owners.exclude(pk=exclude)
    return list(owners.order_by("id"))


def assert_slug_not_former(
    *, organization_id: Any, collection_id: Any, locale: str, slug: str
) -> None:
    """A new entry does not start under an address that redirects to another
    entry of its type and language (pkt 14). A person who wants that address
    takes it over by changing an entry's address, after a preview."""
    owners = former_slug_owners(
        organization_id=organization_id,
        collection_id=collection_id,
        locale=locale,
        slug=slug.strip().lower(),
    )
    if owners:
        raise _error(
            "slug",
            f"Ten adres przekierowuje dziś do wpisu „{owners[0].title}”. Wybierz inny adres "
            "albo przejmij ten, zmieniając adres wpisu.",
            ENTRY_SLUG_FORMER,
        )


def taken_entry_slugs(
    *, organization_id: Any, collection_id: Any, locale: str, exclude: Any | None = None
) -> set[str]:
    """Every slug another entry of the type and language answers under or
    once did — what a slug picked by code keeps clear of."""
    rows = ContentEntry.all_objects.filter(
        organization_id=organization_id, collection_id=collection_id, locale=locale
    )
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    taken: set[str] = set()
    for slug, former in rows.values_list("slug", "former_slugs"):
        taken.add(str(slug))
        taken.update(str(item) for item in former or [])
    return taken


def _has_unpublished_changes(entry: ContentEntry) -> bool:
    publication = entry.current_publication
    if publication is None or entry.current_draft is None:
        return False
    snapshot = publication.snapshot
    return bool(
        snapshot.get("version") != entry.current_draft.number
        or snapshot.get("title") != entry.title
        or snapshot.get("excerpt", "") != entry.excerpt
    )


def _former_after(entry: ContentEntry, wanted: str, *, keep_previous: bool) -> list[str]:
    former = [str(item) for item in entry.former_slugs or []]
    if keep_previous:
        former.append(entry.slug)
    # A slug taken back is the entry's own again, not a former one.
    unique = [
        item for index, item in enumerate(former) if item != wanted and item not in former[:index]
    ]
    return unique[:ENTRY_FORMER_SLUGS_MAX]


@transaction.atomic
def change_entry_slug(
    *,
    entry_id: UUID,
    slug: str,
    reason: str = "",
    take_over_former: bool = False,
    dry_run: bool = False,
) -> EntryAddressChange:
    """Gives an entry another address (`slug`: lower-case Latin letters,
    digits and single hyphens, at most 120 characters).

    Before the entry was ever published the change is free and leaves no
    trace. Afterwards it is a person's decision (`person_required` for an
    integration and the assistant): the slug it had answers one 308 to the
    new address, and where the entry answers visitors today (`moved` of the
    preview is not empty) a `reason` is required and the entry is published
    again under the new address with the content of its **current
    publication** — changes waiting in the draft are not published
    (`unpublished_changes` says whether there are any).

    A slug another entry of the type and language answers under is refused
    (`entry_slug_taken`). One that only redirects to another entry today can
    be taken: the preview's `takes_over` names the redirect that stops, and
    saving needs `take_over_former` (`entry_slug_former` without it).

    `dry_run` validates and answers with what would happen, writing nothing.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    found = ContentEntry.all_objects.filter(
        pk=entry_id, organization_id=context.organization_id
    ).first()
    if found is None:
        from .collections import EntryNotFound

        raise EntryNotFound
    # The type's row first: one change of an address in a type at a time, so
    # two of them cannot hand each other's slug around.
    collection = ContentCollection.all_objects.select_for_update().get(
        pk=found.collection_id, organization_id=context.organization_id
    )
    entry = (
        ContentEntry.all_objects.select_for_update(of=("self",))
        .select_related("current_publication", "current_draft", "site")
        .get(pk=found.pk)
    )
    from .collections import _assert_entry_writable, record_entry_publication

    ever_published = entry.published_at is not None
    published = entry.state == ContentEntryState.PUBLISHED and entry.current_publication is not None
    if ever_published:
        # An address that answered is not an automation's to move (pkt 16).
        assert_person_required(context, ENTRY_ADDRESS_GATE)
    if published:
        authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    _assert_entry_writable(entry, collection, publishing=published)

    wanted = str(slug or "").strip().lower()
    if not valid_entry_slug(wanted):
        raise _error(
            "slug",
            "Adres to małe litery łacińskie, cyfry i pojedyncze łączniki, najwyżej "
            f"{ENTRY_SLUG_MAX} znaków.",
            ENTRY_SLUG_INVALID,
        )
    default_locale = str(entry.site.default_locale)

    def address(of: str) -> str:
        return entry_path(collection, default_locale=default_locale, locale=entry.locale, slug=of)

    previous_slug = entry.slug
    changed = wanted != previous_slug
    live = (
        ContentEntry.all_objects.filter(
            organization_id=context.organization_id,
            collection_id=collection.id,
            locale=entry.locale,
            slug=wanted,
        )
        .exclude(pk=entry.pk)
        .first()
    )
    if live is not None:
        raise _error("slug", f"Ten adres ma już wpis „{live.title}”.", ENTRY_SLUG_TAKEN)
    takes_over = tuple(
        {"slug": wanted, "entry_id": str(other.pk), "title": other.title}
        for other in former_slug_owners(
            organization_id=context.organization_id,
            collection_id=collection.id,
            locale=entry.locale,
            slug=wanted,
            exclude=entry.pk,
        )
    )
    former = _former_after(entry, wanted, keep_previous=changed and ever_published)
    moved = (
        ({"from_path": address(previous_slug), "to_path": address(wanted)},)
        if changed and published
        else ()
    )
    redirects = tuple({"from_path": address(item), "to_path": address(wanted)} for item in former)
    unpublished = _has_unpublished_changes(entry)

    def result(done: ContentEntry, *, was_changed: bool) -> EntryAddressChange:
        return EntryAddressChange(
            entry=done,
            previous_slug=previous_slug,
            slug=wanted,
            path=address(wanted),
            changed=was_changed,
            published=published,
            moved=moved,
            redirects=redirects,
            takes_over=takes_over,
            unpublished_changes=unpublished,
        )

    if dry_run or not changed:
        return result(entry, was_changed=changed)
    if takes_over and (not take_over_former or _is_automation(context) or context.acting_via):
        raise _error(
            "slug",
            f"Ten adres przekierowuje dziś do wpisu „{takes_over[0]['title']}”. Potwierdź, że "
            "to przekierowanie ma przestać działać.",
            ENTRY_SLUG_FORMER,
        )
    normalized_reason = reason.strip()
    if moved and not normalized_reason:
        raise _error("reason", "Zmiana adresu wymaga uzasadnienia.", ENTRY_REASON_REQUIRED)

    for taken in takes_over:
        other = ContentEntry.all_objects.select_for_update(of=("self",)).get(pk=taken["entry_id"])
        other.former_slugs = [item for item in other.former_slugs or [] if item != wanted]
        other.save(update_fields=["former_slugs", "updated_at"])
    entry.slug = wanted
    entry.former_slugs = former
    entry.save(update_fields=["slug", "former_slugs", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_ADDRESS_CHANGED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={
            "locale": entry.locale,
            "from": previous_slug,
            "to": wanted,
            "moved": list(moved),
            "takes_over": list(takes_over),
            "republished": published,
            "reason": normalized_reason,
        },
    )
    if published:
        assert entry.current_publication is not None
        # What is public, under the new address — never the draft (pkt 16).
        # The text did not change, so neither does `changed_at`, and nothing
        # tells the translation engine: its source reads the same.
        snapshot = {
            **entry.current_publication.snapshot,
            "slug": wanted,
            "base_path": section_segment(
                collection, default_locale=default_locale, locale=entry.locale
            ),
            "path": address(wanted),
        }
        record_entry_publication(
            context,
            entry,
            snapshot,
            f"address:{uuid.uuid4().hex}",
            reason=ADDRESS_CHANGE_REASON,
        )
    return result(entry, was_changed=True)


def read_entry_address(*, entry_id: UUID) -> EntryAddressChange:
    """An entry's address as it is, with every former address that leads to
    it — what the panel shows before anybody changes anything."""
    from .collections import EntryNotFound
    from .services import assert_within_grant

    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    entry = (
        ContentEntry.all_objects.select_related(
            "collection", "current_publication", "current_draft", "site"
        )
        .filter(pk=entry_id, organization_id=context.organization_id)
        .first()
    )
    if entry is None:
        raise EntryNotFound
    assert_within_grant(context, site_id=entry.site_id, collection_id=entry.collection_id)
    default_locale = str(entry.site.default_locale)

    def address(of: str) -> str:
        return entry_path(
            entry.collection, default_locale=default_locale, locale=entry.locale, slug=of
        )

    return EntryAddressChange(
        entry=entry,
        previous_slug=entry.slug,
        slug=entry.slug,
        path=address(entry.slug),
        changed=False,
        published=(
            entry.state == ContentEntryState.PUBLISHED and entry.current_publication is not None
        ),
        redirects=tuple(
            {"from_path": address(str(item)), "to_path": address(entry.slug)}
            for item in entry.former_slugs or []
        ),
        unpublished_changes=_has_unpublished_changes(entry),
    )


def record_former_entry_slugs(
    context: Any, entry: ContentEntry, slugs: Sequence[str]
) -> tuple[list[str], dict[str, str]]:
    """An import's own right (ADR-079 pkt 34): slugs the entry answered under
    somewhere else, recorded as former without a publication. The caller is
    inside the entry's transaction and has checked the right to write.

    Returns the slugs recorded now and, for each one left out, why: it is not
    slug-shaped, an entry of the type and language answers under it (a live
    address always wins, so the redirect could never fire), or it redirects
    to another entry already."""
    refused: dict[str, str] = {}
    current = [str(item) for item in entry.former_slugs or []]
    wanted: list[str] = []
    for raw in slugs:
        slug = str(raw or "").strip().lower()
        if not slug or slug == entry.slug or slug in current or slug in wanted:
            continue
        if not valid_entry_slug(slug):
            refused[slug] = "invalid"
            continue
        wanted.append(slug)
    if not wanted:
        return [], refused
    others = ContentEntry.all_objects.filter(
        organization_id=entry.organization_id,
        collection_id=entry.collection_id,
        locale=entry.locale,
    ).exclude(pk=entry.pk)
    live = set(others.filter(slug__in=wanted).values_list("slug", flat=True))
    held: set[str] = set()
    for former in others.filter(_contains_any(wanted)).values_list("former_slugs", flat=True):
        held.update(str(item) for item in former or [])
    recorded: list[str] = []
    for slug in wanted:
        if slug in live:
            refused[slug] = "live"
        elif slug in held:
            refused[slug] = "former_of_another"
        elif len(current) + len(recorded) >= ENTRY_FORMER_SLUGS_MAX:
            refused[slug] = "too_many"
        else:
            recorded.append(slug)
    if recorded:
        entry.former_slugs = [*current, *recorded]
        entry.save(update_fields=["former_slugs", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=ENTRY_FORMER_SLUGS_RECORDED,
            actor=User.objects.get(pk=context.actor_id),
            target_type="content_entry",
            target_id=entry.id,
            metadata={"locale": entry.locale, "slugs": recorded},
        )
    return recorded, refused


def _contains_any(slugs: Iterable[str]) -> Q:
    query = Q(pk__in=[])
    for slug in slugs:
        query |= Q(former_slugs__contains=[slug])
    return query


__all__ = [
    "ADDRESS_CHANGE_REASON",
    "ENTRY_ADDRESS_CHANGED",
    "ENTRY_ADDRESS_GATE",
    "ENTRY_FORMER_SLUGS_MAX",
    "ENTRY_FORMER_SLUGS_RECORDED",
    "ENTRY_REASON_REQUIRED",
    "ENTRY_SLUG_FORMER",
    "ENTRY_SLUG_INVALID",
    "ENTRY_SLUG_MAX",
    "ENTRY_SLUG_TAKEN",
    "EntryAddressChange",
    "assert_slug_not_former",
    "change_entry_slug",
    "former_slug_owners",
    "read_entry_address",
    "record_former_entry_slugs",
    "taken_entry_slugs",
    "valid_entry_slug",
]
