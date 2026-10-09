"""Content collections: repeatable surfaces that publish one entry at a time.

Kept out of `services.py` because the lifecycle genuinely differs. A page belongs
to a site-wide atomic snapshot; an entry is published, withdrawn and rolled back
on its own (ADR-035 §1), and mixing the two flows in one module made both harder
to follow.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol.provenance import (
    ORIGIN_AI,
    ORIGIN_HUMAN,
    ORIGIN_IMPORT,
    Provenance,
    unit_hash,
)
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
from saas_core.modules.core.organizations.locales import (
    assert_organization_content_locale,
    content_locale_problem,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.observability import correlation_id

from .block_contracts import validate_site_block
from .block_decoration import normalize_block, validate_decoration, validate_presentation
from .content_type_limit import ContentTypeArchived, ensure_content_type_capacity
from .entry_addresses import assert_slug_not_former
from .language_publication import _origin as translation_origin
from .localization import (
    collection_index_path,
    entry_path,
    first_segment_reserved,
    section_segment,
)
from .localized_bodies import extract_units, structure_signature
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentEntryVersion,
    ContentSchemaType,
    ContentTag,
    EntryScheduleState,
    PageAutomationPolicy,
    PageTranslation,
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
    SlugReserved,
    _idempotency_key,
    _is_automation,
    _schedule_site_outbox_delivery,
    assert_links_within_grant,
    assert_person_blocks,
    assert_person_required,
    assert_within_grant,
    default_automation_rel,
    emit_draft_saved_event,
)
from .source_changes import notify_entry_published, notify_entry_withdrawn
from .term_addresses import close_term_addresses, snapshot_terms, terms_to_close

logger = logging.getLogger(__name__)

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
ENTRY_METADATA_UPDATED = "sites.entry.metadata_updated"
COLLECTION_POLICY_SET = "sites.collection.automation_policy_set"
COLLECTION_NAVIGATION_SET = "sites.collection.navigation_set"
COLLECTION_PATHS_SET = "sites.collection.paths_set"
#: What the gate of a section's addresses is called: a person's decision, as
#: moving a page's address is (`change_page_url`).
SECTION_PATHS_GATE = "Zmiana adresu działu"
SECTION_PATH_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SECTION_PATH_MAX = 80
#: Field codes of a section's name in the addresses (ADR-076 §5).
SECTION_PATH_INVALID = "section_path_invalid"
SECTION_PATH_TAKEN = "section_path_taken"
SECTION_PATH_RESERVED = "slug_reserved"
SECTION_PATH_SOURCE_LOCALE = "section_path_source_locale"
SECTION_PATH_FORMER = "section_path_former"
SECTION_REASON_REQUIRED = "redirect_reason_required"
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


#: Keys of an imported text's fields in `ContentEntryVersion.units` — beside
#: the translation engine's keys (a source's unit keys, `meta/title`), never
#: among them: a version with these has no `source_version`.
IMPORT_TITLE = "import/title"
IMPORT_EXCERPT = "import/excerpt"
IMPORT_BODY = "import/body"
IMPORT_EDIT = "import/edit"
IMPORT_FIELDS = (IMPORT_TITLE, IMPORT_EXCERPT, IMPORT_BODY)


@dataclass(frozen=True, slots=True)
class ImportedText:
    """Who wrote each field of a text an import brings: `fields` maps
    `import/title|excerpt|body` to `{"origin", "model", "source_sha256"}`
    (origin one of `human`, `ai`, `import`). The publication's machine mark
    is read from it the way it is read from a translation's units."""

    fields: Mapping[str, Mapping[str, str]]
    ref: str = ""

    def units(self) -> dict[str, Any]:
        at = timezone.now().isoformat()
        return {
            key: {
                # The words live in the entry and its blocks; here is only
                # who wrote them and from what.
                "text": "",
                "provenance": {
                    name: str(value) for name, value in {**facts, "at": at}.items() if value
                },
            }
            for key, facts in self.fields.items()
            if key in IMPORT_FIELDS
        }


def _blocks_size(blocks: Any) -> int:
    return len(json.dumps(blocks, ensure_ascii=False, separators=(",", ":")))


def _assert_entry_writable(
    entry: ContentEntry | None,
    collection: ContentCollection,
    *,
    publishing: bool = False,
    payload_bytes: int | None = None,
    taking_down: bool = False,
) -> None:
    """Same two rules as pages (ADR-035 §4a), applied to the collection: the
    policy lives on the collection, the momentary lock on the entry.

    `taking_down` is the one write a switched-off type's entry still takes:
    being withdrawn puts nothing in front of readers.

    Under `proposed` the automation writes the draft and stops there — putting
    the article in front of readers, or taking it down, stays a person's act.
    Without an entry (one about to be created) there is no lock to respect.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        assert_within_grant(
            context,
            site_id=collection.site_id,
            collection_id=collection.id,
            writing=True,
            publishing=publishing,
            payload_bytes=payload_bytes,
        )
    # A switched-off type's entries are neither edited nor published, by a
    # person or a key alike (ADR-079 pkt 23) — said after the grant, so a key
    # learns it only about a type it was hired for. Withdrawing one stays
    # possible: a company that will not have the type back can still decide
    # that an entry is not to return with it.
    if collection.archived_at is not None and not taking_down:
        raise ContentTypeArchived
    if not _is_automation(context):
        return
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
    # section the customer has — and, as there, none that is switched off.
    from .inventory import _granted

    return [
        row for row in rows if row.archived_at is None and _granted(context, site_id, row.id)
    ]


@transaction.atomic
def create_collection(
    *,
    site_id: UUID,
    key: str,
    name: str,
    kind: str,
    base_path: str,
    idempotency_key: str,
    locale_paths: Mapping[str, str] | None = None,
    schema_type: str = ContentSchemaType.BLOG_POSTING,
    in_site_feed: bool | None = None,
    take_over_former: bool = False,
) -> tuple[ContentCollection, bool]:
    """`base_path` is the section's name in the addresses of the site's own
    language; `locale_paths` names it in other languages (`{"de":
    "ratgeber"}`), and a language left out follows `base_path`.

    `schema_type` says what the type's entries are to search engines and
    `in_site_feed` whether they are in the site's feeds; left out, an
    article-like type is in the feed and a type of plain pages is not.

    A site's first type takes the site's own entitlement only. A further one
    needs the platform's offer and room in the plan's limit
    (`content_type_limit`): `content_types_not_offered`, `quota_exceeded`,
    `plan_access_denied`.

    A name that today only redirects to another type — that type was called
    so once — is refused (`section_path_former`): an integration never takes
    it, a person does by sending `take_over_former`, and that redirect, with
    everything under it, stops."""
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
        # Only when given: a request without names per language hashes as it
        # did before they existed, so its replay still finds itself.
        **({"locale_paths": dict(sorted(locale_paths.items()))} if locale_paths else {}),
        **({"schema_type": schema_type} if schema_type != ContentSchemaType.BLOG_POSTING else {}),
        **({"in_site_feed": in_site_feed} if in_site_feed is not None else {}),
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
    site = (
        Site.all_objects.select_for_update()
        .filter(pk=site_id, organization_id=context.organization_id)
        .first()
    )
    if site is None:
        raise SiteNotFound
    # Under the site's lock, after the replay: a request answered once is
    # answered the same whatever the plan says today.
    ensure_content_type_capacity(site)
    # The blog's address is unprefixed in the site's language, like a page's.
    if first_segment_reserved(base_path):
        raise SlugReserved
    names = _section_names(site, base_path=base_path, locale_paths=locale_paths or {})
    _assert_section_names_free(site, None, base_path, names)
    _take_over_former_names(context, site, None, base_path, names, confirmed=take_over_former)
    # The table the panel's choices come from says the feed's default too.
    from .content_types import default_in_site_feed

    collection = ContentCollection.all_objects.create(
        organization_id=context.organization_id,
        site_id=site_id,
        key=key,
        name=name,
        kind=kind,
        base_path=base_path,
        locale_paths=names,
        schema_type=schema_type,
        in_site_feed=default_in_site_feed(schema_type) if in_site_feed is None else in_site_feed,
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


@dataclass(frozen=True, slots=True)
class SectionPaths:
    """A section's addresses, as they are or as a change would make them."""

    collection: ContentCollection
    #: Where its index answers in each of the site's languages.
    paths: dict[str, str]
    #: The index addresses visitors can open today that the change moves, and
    #: where each leads from then on (one 308, with everything under it).
    moved: tuple[dict[str, str], ...] = ()
    changed: bool = False
    #: Redirects of other sections that stop, because this one takes the name
    #: they start from: [{"locale", "path", "collection_id", "name"}].
    takes_over: tuple[dict[str, str], ...] = ()


def _path_error(field: str, locale: str | None, message: str, code: str) -> ValidationError:
    detail = [ErrorDetail(message, code=code)]
    return ValidationError({field: {locale: detail} if locale else detail})


def _section_names(
    site: Site, *, base_path: str, locale_paths: Mapping[str, str]
) -> dict[str, str]:
    """The names per language as stored: lower case, no empty ones, none for
    the site's own language, each a language the company offers."""
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    if not SECTION_PATH_PATTERN.fullmatch(base_path) or len(base_path) > SECTION_PATH_MAX:
        raise _path_error(
            "base_path",
            None,
            "Adres działu to małe litery łacińskie, cyfry i pojedyncze łączniki.",
            SECTION_PATH_INVALID,
        )
    names: dict[str, str] = {}
    for locale, raw in sorted(locale_paths.items()):
        name = str(raw or "").strip().lower()
        if not name:
            # „Follows the site's language": no name of its own.
            continue
        if locale == site.default_locale:
            raise _path_error(
                "locale_paths",
                locale,
                "Adres działu w języku strony ustawia pole base_path.",
                SECTION_PATH_SOURCE_LOCALE,
            )
        problem = content_locale_problem(locale, organization=organization)
        if problem is not None:
            raise _path_error(
                "locale_paths", locale, "Firma nie udostępnia treści w tym języku.", problem
            )
        if not SECTION_PATH_PATTERN.fullmatch(name) or len(name) > SECTION_PATH_MAX:
            raise _path_error(
                "locale_paths",
                locale,
                "Adres działu to małe litery łacińskie, cyfry i pojedyncze łączniki.",
                SECTION_PATH_INVALID,
            )
        names[locale] = name
    return names


def _assert_section_names_free(
    site: Site, collection: ContentCollection | None, base_path: str, names: Mapping[str, str]
) -> None:
    """One address, one answer, in every language (ADR-071 pkt 14): a
    section's name there is no other section's, no page's and no reserved
    segment — a platform path, a language's prefix, a record source's section
    in any language. Asked of the names that change only: a section keeps
    what it had before a rule, as a page does (`sites_reserved_slugs`)."""
    others = list(
        ContentCollection.all_objects.filter(
            organization_id=site.organization_id, site_id=site.id
        ).exclude(pk__in=[collection.id] if collection is not None else [])
    )
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    locales = {
        site.default_locale,
        *organization_content_locales(organization),
        *names,
        *(code for other in others for code in other.locale_paths or {}),
    }
    for locale in sorted(locales, key=lambda code: (code != site.default_locale, code)):
        source = locale == site.default_locale
        name = base_path if source else names.get(locale) or base_path
        if collection is not None and name == section_segment(
            collection, default_locale=site.default_locale, locale=locale
        ):
            continue
        # Named for the language it was typed in; a clash that only a
        # language following the site's name has is the site's name's.
        field, key = ("base_path", None) if source or locale not in names else (
            "locale_paths",
            locale,
        )
        if first_segment_reserved(name):
            if source:
                raise SlugReserved
            raise _path_error(
                field,
                key,
                "Ten adres jest zarezerwowany dla platformy, języków albo stron rekordów.",
                SECTION_PATH_RESERVED,
            )
        if any(
            section_segment(other, default_locale=site.default_locale, locale=locale) == name
            for other in others
        ):
            raise _path_error(
                field,
                key,
                f"Inny dział ma już adres /{name}/ w języku {locale}.",
                SECTION_PATH_TAKEN,
            )
        if PageTranslation.all_objects.filter(
            organization_id=site.organization_id,
            site_id=site.id,
            locale=locale,
            slug=name,
            page__deleted_at__isnull=True,
        ).exists():
            raise _path_error(
                field,
                key,
                f"Podstrona ma już adres /{name}/ w języku {locale}.",
                SECTION_PATH_TAKEN,
            )


def _former_names_taken(
    site: Site, collection: ContentCollection | None, base_path: str, names: Mapping[str, str]
) -> list[tuple[ContentCollection, dict[str, Any]]]:
    """The former names of other sections that these names would take
    (ADR-079 pkt 14), each with the section it leads to. A former name of the
    site's own language counts in every language, as it does for the redirect
    (`moved_address`)."""
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    default = site.default_locale
    locales = dict.fromkeys((default, *organization_content_locales(organization), *names))
    wanted = {
        locale: base_path if locale == default else names.get(locale) or base_path
        for locale in locales
    }
    taken: list[tuple[ContentCollection, dict[str, Any]]] = []
    for other in ContentCollection.all_objects.filter(
        organization_id=site.organization_id, site_id=site.id
    ).exclude(pk__in=[collection.id] if collection is not None else []):
        for item in other.former_paths or []:
            if isinstance(item, dict) and any(
                item.get("path") == name and item.get("locale") in (locale, default)
                for locale, name in wanted.items()
            ):
                taken.append((other, item))
    return taken


def _stopping_redirects(
    site: Site, taken: list[tuple[ContentCollection, dict[str, Any]]]
) -> list[dict[str, str]]:
    """What a person is told before taking a former name: every address that
    leads, with everything under it, to another section today and would stop.
    A former name is one thing — taken in one language it stops in all it
    served."""
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    default = site.default_locale
    every = list(dict.fromkeys((default, *organization_content_locales(organization))))
    stops: list[dict[str, str]] = []
    for other, item in taken:
        name = str(item.get("path"))
        for locale in every if item.get("locale") == default else [str(item.get("locale"))]:
            stops.append({
                "locale": locale,
                "path": f"/{name}/" if locale == default else f"/{locale}/{name}/",
                "collection_id": str(other.id),
                "name": other.name,
            })
    return stops


def _take_over_former_names(
    context: Any,
    site: Site,
    collection: ContentCollection | None,
    base_path: str,
    names: Mapping[str, str],
    *,
    confirmed: bool,
) -> None:
    """A former name is never taken quietly (ADR-079 pkt 14): by code — an
    integration, the assistant — never; by a person only having been told
    which redirects stop (`confirmed`: the preview's `takes_over`, read).
    Taken, it stops being a former name of the section it led to."""
    taken = _former_names_taken(site, collection, base_path, names)
    if not taken:
        return
    person = context.principal_kind == "membership" and not context.acting_via
    if not person or not confirmed:
        first = _stopping_redirects(site, taken)[0]
        raise _path_error(
            "base_path",
            None,
            f"Adres {first['path']} przekierowuje dziś do „{first['name']}”. "
            + (
                "Potwierdź, że to przekierowanie ma przestać działać."
                if person
                else "Taki adres może przejąć tylko osoba."
            ),
            SECTION_PATH_FORMER,
        )
    for other, item in taken:
        locked = ContentCollection.all_objects.select_for_update().get(pk=other.pk)
        locked.former_paths = [kept for kept in locked.former_paths or [] if kept != item]
        locked.save(update_fields=["former_paths", "updated_at"])


def _index_paths(site: Site, collection: ContentCollection) -> dict[str, str]:
    organization = Organization.objects.only("id", "public_locales").get(pk=site.organization_id)
    locales = dict.fromkeys((site.default_locale, *organization_content_locales(organization)))
    return {
        locale: collection_index_path(
            collection, default_locale=site.default_locale, locale=locale
        )
        for locale in locales
    }


def collection_paths(collection: ContentCollection) -> dict[str, str]:
    """Where the section's index answers in each of the site's languages —
    the addresses the panel shows beside the names."""
    return _index_paths(collection.site, collection)


@transaction.atomic
def set_collection_paths(
    *,
    collection_id: UUID,
    base_path: str,
    locale_paths: Mapping[str, str],
    reason: str = "",
    dry_run: bool = False,
    take_over_former: bool = False,
) -> SectionPaths:
    """Renames a section in the site's addresses: `base_path` in the site's
    own language, `locale_paths` in others (a language left out, or given an
    empty name, follows `base_path`).

    The whole set is sent each time. Every address under a name that stops
    being the section's — its index, articles, subjects' archives and their
    later pages — answers one 308 to today's from the moment this is saved;
    nothing is republished, the articles keep their slugs. Moving an address
    visitors can open today costs what it earned, so it takes a person and a
    stated `reason`, like moving a page's (`change_page_url`); naming a
    language nobody can read the section in yet takes neither.

    A name that today only redirects to another section is taken only
    knowingly: the preview's `takes_over` names the redirect that stops, and
    saving needs `take_over_former` (`section_path_former` without it).

    `dry_run` validates and answers with the addresses as they would be and
    what would move, and writes nothing.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, SECTION_PATHS_GATE)
    collection = (
        ContentCollection.all_objects.select_related("site")
        .filter(pk=collection_id, organization_id=context.organization_id)
        .first()
    )
    if collection is None:
        raise CollectionNotFound
    # One rename at a time on a site: two could each be free of the other's
    # old name and collide on the new ones.
    site = Site.all_objects.select_for_update().get(
        pk=collection.site_id, organization_id=context.organization_id
    )
    collection = ContentCollection.all_objects.select_for_update().get(pk=collection.id)
    collection.site = site
    if collection.archived_at is not None:
        raise ContentTypeArchived
    new_base = base_path.strip().lower()
    names = _section_names(site, base_path=new_base, locale_paths=locale_paths)
    _assert_section_names_free(site, collection, new_base, names)

    before = _index_paths(site, collection)
    old_names = {
        locale: section_segment(collection, default_locale=site.default_locale, locale=locale)
        for locale in {*before, *(collection.locale_paths or {}), *names}
    }
    collection.base_path, previous_base = new_base, collection.base_path
    collection.locale_paths, previous_names = names, dict(collection.locale_paths or {})
    changed = {
        locale: old
        for locale, old in old_names.items()
        if section_segment(collection, default_locale=site.default_locale, locale=locale) != old
    }
    after = _index_paths(site, collection)
    # What visitors can open today: the index in the site's own language
    # always, in another one once it lists an article.
    answering = {site.default_locale} | set(
        ContentEntry.all_objects.filter(
            organization_id=context.organization_id,
            collection_id=collection.id,
            state=ContentEntryState.PUBLISHED,
            current_publication__isnull=False,
        ).values_list("locale", flat=True)
    )
    moved = tuple(
        {"locale": locale, "from_path": before[locale], "to_path": after[locale]}
        for locale in before
        if locale in changed and locale in answering
    )
    stored = previous_base != new_base or previous_names != names
    result = SectionPaths(
        collection=collection,
        paths=after,
        moved=moved,
        changed=stored,
        takes_over=tuple(
            _stopping_redirects(site, _former_names_taken(site, collection, new_base, names))
        ),
    )
    if dry_run or not stored:
        # A preview answers with the section as it would be; nothing is saved.
        return result
    _take_over_former_names(
        context, site, collection, new_base, names, confirmed=take_over_former
    )
    normalized_reason = reason.strip()
    if moved and not normalized_reason:
        raise ValidationError({
            "reason": [
                ErrorDetail("Zmiana adresu wymaga uzasadnienia.", code=SECTION_REASON_REQUIRED)
            ]
        })
    # Old names answer with one move to today's; a name taken back is the
    # section's again, not a former one.
    former = [
        *(collection.former_paths or []),
        *({"locale": locale, "path": old} for locale, old in sorted(changed.items())),
    ]
    collection.former_paths = [
        item
        for index, item in enumerate(former)
        if item not in former[:index]
        and item.get("path")
        != section_segment(
            collection, default_locale=site.default_locale, locale=str(item.get("locale"))
        )
    ]
    collection.save(update_fields=["base_path", "locale_paths", "former_paths", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=COLLECTION_PATHS_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_collection",
        target_id=collection.id,
        metadata={
            "from": {"base_path": previous_base, "locale_paths": previous_names},
            "to": {"base_path": new_base, "locale_paths": names},
            "moved": list(moved),
            "reason": normalized_reason,
        },
    )
    return result


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
    locale = assert_organization_content_locale(locale, organization_id=context.organization_id)
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
    # An address that redirects to another entry is not a new entry's to
    # start under (ADR-079 pkt 14).
    assert_slug_not_former(
        organization_id=context.organization_id,
        collection_id=collection_id,
        locale=locale,
        slug=slug,
    )
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
    imported: ImportedText | None = None,
) -> tuple[ContentEntryVersion, bool]:
    """Saves the entry's draft. `imported` is the content import's alone
    (`content_import`; no endpoint passes it): who wrote each field of a text
    that arrives from elsewhere, kept with the version."""
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
        base_blocks = entry.current_draft.blocks if entry.current_draft else []
        assert_links_within_grant(
            context,
            site_id=entry.collection.site_id,
            collection_id=entry.collection_id,
            blocks=normalized_blocks,
            base_blocks=base_blocks,
        )
        normalized_blocks = default_automation_rel(
            context,
            site_id=entry.collection.site_id,
            blocks=normalized_blocks,
            base_blocks=base_blocks,
        )
    if entry.version != expected_version:
        raise DraftVersionConflict
    version = record_entry_version(
        context,
        entry,
        blocks=normalized_blocks,
        media_asset_ids=media_asset_ids or [],
        idempotency_key=normalized_key,
        request_hash=request_hash,
        **(
            {
                "units": imported.units(),
                "origin": ORIGIN_IMPORT,
                "origin_ref": imported.ref,
            }
            if imported is not None
            else _edited_translation(context, entry, normalized_blocks)
        ),
    )
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


def record_entry_version(
    context: Any,
    entry: ContentEntry,
    *,
    blocks: list[dict[str, Any]],
    media_asset_ids: list[UUID],
    idempotency_key: str,
    request_hash: str,
    current: bool = True,
    units: dict[str, Any] | None = None,
    source_version: ContentEntryVersion | None = None,
    origin: str = "",
    origin_ref: str = "",
    replaces: ContentEntryVersion | None = None,
) -> ContentEntryVersion:
    """A new version of the entry's text, with the media it names; the draft
    unless it is a translation waiting for a person (`current=False`).

    The caller has checked the blocks, the right to write and the version.
    """
    version = ContentEntryVersion.all_objects.create(
        organization_id=context.organization_id,
        entry=entry,
        number=entry.version + 1,
        blocks=blocks,
        content_hash=canonical_json_hash({"blocks": blocks}),
        units=units,
        source_version=source_version,
        origin=origin,
        origin_ref=origin_ref[:160],
        replaces=replaces,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        created_by_credential=(
            context.credential_id if _is_automation(context) else None
        ),
    )
    # Nested images (figures, galleries) are referenced even when unlisted.
    normalized_media_ids = tuple(
        sorted(
            {*(UUID(str(asset_id)) for asset_id in media_asset_ids),
             *block_asset_ids(blocks)},
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
    fields = ["version", "updated_at"]
    if current:
        entry.current_draft = version
        fields.append("current_draft")
    entry.save(update_fields=fields)
    return version


def _edited_translation(
    context: Any, entry: ContentEntry, blocks: list[dict[str, Any]]
) -> dict[str, Any]:
    """A person's edit of a machine translation stays one, unit by unit, while
    its structure is the source's: what they changed is theirs, and the next
    job proposes beside it rather than over it (ADR-070 pkt 5). Another
    structure is a text of their own, which no job writes into."""
    previous = entry.current_draft
    if (
        previous is not None
        and previous.source_version is None
        and isinstance(previous.units, dict)
        and IMPORT_BODY in previous.units
    ):
        # A text an import brought (`ImportedText`): its fields keep saying
        # who wrote them, and the edit is named beside them — a model's text
        # a person corrected is still, in part, a model's (ADR-071 pkt 17).
        if context.acting_via:
            return {}
        at = timezone.now().isoformat()
        return {
            "units": {
                **previous.units,
                IMPORT_EDIT: {
                    "text": "",
                    "provenance": {"origin": ORIGIN_HUMAN, "at": at},
                },
            }
        }
    if (
        entry.translation_of_id is None
        or previous is None
        or previous.units is None
        or previous.source_version is None
        or structure_signature(blocks) != structure_signature(previous.blocks)
    ):
        return {}
    source_units = {unit.key: unit for unit in extract_units(previous.source_version.blocks)}
    origin = ORIGIN_AI if context.acting_via else ORIGIN_HUMAN
    at = timezone.now().isoformat()
    units = dict(previous.units)
    for unit in extract_units(blocks):
        stored = units.get(unit.key)
        source = source_units.get(unit.key)
        if source is None or (isinstance(stored, dict) and stored.get("text") == unit.text):
            continue
        if stored is None and unit.text == source.text:
            # Still the source's words standing in for a missing translation.
            continue
        units[unit.key] = {
            "text": unit.text,
            "provenance": Provenance(
                origin=origin,
                source_hash=source.source_hash,
                written_hash=unit_hash(source.kind, unit.text),
                model="",
                at=at,
            ).as_dict(),
        }
    return {"units": units, "source_version": previous.source_version}


def is_translation_source(entry: ContentEntry) -> bool:
    """Whether this entry is what its group's machine translations translate."""
    if entry.translation_of_id is not None:
        return False
    group = ContentEntry.all_objects.filter(
        organization_id=entry.organization_id, translation_group=entry.translation_group
    )
    return group_source(list(group), entry.site.default_locale) == entry


def group_source(entries: list[ContentEntry], default_locale: str) -> ContentEntry | None:
    """A person's entry, in the site's language when there is one, otherwise
    the oldest: a machine translation is never a source (ADR-070 pkt 16)."""
    people = [entry for entry in entries if entry.translation_of_id is None]
    return min(people, key=lambda entry: (entry.locale != default_locale, entry.id), default=None)


@transaction.atomic
def publish_entry(
    *,
    entry_id: UUID,
    idempotency_key: str,
    published_at: Any = None,
    person_decision: bool = False,
    changed_at: datetime | None = None,
) -> tuple[ContentEntryPublication, bool]:
    """Publishes one article.

    The snapshot holds this entry alone, which is what keeps the cost flat: a
    blog with ten thousand articles publishes the ten-thousand-and-first in the
    same time as its first.

    `changed_at` is the content import's alone (ADR-079 pkt 34; no endpoint
    passes it): when a text brought from elsewhere last changed there. It
    stands for the moment the draft was saved, which for an import is the
    night of the import and says nothing a reader or a sitemap wants.
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
    if (
        person_decision
        and context.principal_kind == "membership"
        and not context.acting_via
        and entry.current_draft.units is not None
        and entry.accepted_version_id != entry.current_draft.id
    ):
        # A person publishing this translation themselves stands behind its
        # text (ADR-071 pkt 17); a job, a schedule or the source's follow-up
        # publication does not make it so.
        entry.accepted_version = entry.current_draft
        ContentEntry.all_objects.filter(pk=entry.id).update(accepted_version=entry.current_draft)
    # What it carries, and — with every category above those — what closes.
    carried, closing = terms_to_close(
        organization_id=context.organization_id, entry_id=entry.id
    )
    tags, terms = snapshot_terms(carried)
    snapshot = {
        "schema_version": ENTRY_SNAPSHOT_SCHEMA_VERSION,
        "entry_id": str(entry.id),
        "collection_key": entry.collection.key,
        # The section's name in the article's language, and the address, as
        # they are at this publication. `published_entry_path` reads both:
        # the address holds for as long as the section keeps this name.
        "base_path": section_segment(
            entry.collection, default_locale=entry.site.default_locale, locale=entry.locale
        ),
        "locale": entry.locale,
        "slug": entry.slug,
        "path": entry_path(
            entry.collection,
            default_locale=entry.site.default_locale,
            locale=entry.locale,
            slug=entry.slug,
        ),
        "title": entry.title,
        "excerpt": entry.excerpt,
        "author_name": entry.author_name,
        "noindex": entry.noindex,
        # Carried in the snapshot rather than read live: what a visitor sees
        # has to be what was published, including which archives list it.
        # `tags` is the site's tags in the shape it always had; `terms` names
        # every term the entry carries, categories too (ADR-079 pkt 8).
        "tags": tags,
        "terms": terms,
        "version": entry.current_draft.number,
        # When the text last changed, not when it was last published: a
        # sitemap's `lastmod` (TL14).
        "changed_at": (changed_at or entry.current_draft.created_at).isoformat(),
        "blocks": entry.current_draft.blocks,
        # Read by the public media endpoint: an asset is fetchable by a visitor
        # only while something published names it.
        "media_asset_ids": [str(asset_id) for asset_id in published_media_ids],
        # Who wrote a translation's text, for the marker on machine text
        # (ADR-071 pkt 17); an article written as itself has none.
        **(
            {
                "origin": translation_origin(
                    entry.current_draft.units.values(),
                    accepted=entry.accepted_version_id == entry.current_draft.id,
                )
            }
            if entry.current_draft.units is not None
            else {}
        ),
    }
    previous = entry.current_publication.snapshot if entry.current_publication else None
    publication = record_entry_publication(
        context, entry, snapshot, normalized_key, published_at=published_at
    )
    # The archives of what it carries answer from now on: their addresses
    # close. Never a reason not to publish — a translation job publishes
    # here, in the transaction that settles its credits.
    try:
        with transaction.atomic():
            close_term_addresses(
                closing, default_locale=entry.site.default_locale, locale=entry.locale
            )
    except Exception:
        logger.exception("sites.term_addresses_not_closed entry=%s", entry.id)
    if is_translation_source(entry):
        from .entry_translation_source import follow_source

        follow_source(context, entry)
        notify_entry_published(
            context=context, entry_id=entry.id, previous=previous, snapshot=snapshot
        )
    return publication, True


def record_entry_publication(
    context: Any,
    entry: ContentEntry,
    snapshot: dict[str, Any],
    idempotency_key: str,
    *,
    published_at: Any = None,
    reason: str = "",
) -> ContentEntryPublication:
    """The entry's next publication of `snapshot`, its audit and its event."""
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
        idempotency_key=idempotency_key,
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
        metadata={"sequence": publication.sequence, **({"reason": reason} if reason else {})},
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
    return publication


def set_entry_tags(*, entry_id: UUID, names: list[str]) -> list[ContentTag]:
    """The entry's tags, the whole set — `taxonomies.set_entry_tags`, kept
    under the name it always had here."""
    from .taxonomies import set_entry_tags as set_tags

    return set_tags(entry_id=entry_id, names=names)


def entry_tags(*, entry_id: UUID) -> list[ContentTag]:
    from .taxonomies import entry_tags as tags_of

    return tags_of(entry_id=entry_id)


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
    _assert_entry_writable(entry, entry.collection, publishing=True, taking_down=True)
    take_down_entry(context, entry)
    if is_translation_source(entry):
        notify_entry_withdrawn(context=context, entry_id=entry.id)
    return entry


def take_down_entry(
    context: Any,
    entry: ContentEntry,
    *,
    reason: str = "",
    state: str = ContentEntryState.WITHDRAWN,
) -> None:
    """Off the public site. Undoing a translation job's first publication of
    an article leaves it a draft, as it was (`state`)."""
    entry.state = state
    entry.current_publication = None
    entry.save(update_fields=["state", "current_publication", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_WITHDRAWN,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"reason": reason} if reason else {},
    )


#: What `update_entry_metadata` changes, with each field's longest value.
ENTRY_METADATA_FIELDS = {"title": 200, "excerpt": 400, "author_name": 120}


@transaction.atomic
def update_entry_metadata(
    *,
    entry_id: UUID,
    title: str | None = None,
    excerpt: str | None = None,
    author_name: str | None = None,
    noindex: bool | None = None,
) -> ContentEntry:
    """What an article says about itself — its title, excerpt, author and
    whether search engines index it (ADR-070 pkt 16). A field left out keeps
    its value; visitors see the change with the entry's next publication."""
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
    wanted: dict[str, Any] = {}
    for field, value in (("title", title), ("excerpt", excerpt), ("author_name", author_name)):
        if value is None:
            continue
        value = value.strip()
        if field == "title" and not value:
            raise ValidationError({"title": ["Tytuł wpisu nie może być pusty."]}, code="required")
        if len(value) > ENTRY_METADATA_FIELDS[field]:
            raise ValidationError(
                {field: [f"Najwyżej {ENTRY_METADATA_FIELDS[field]} znaków."]}, code="max_length"
            )
        wanted[field] = value
    if noindex is not None:
        wanted["noindex"] = noindex
    changed = {field: value for field, value in wanted.items() if getattr(entry, field) != value}
    if not changed:
        return entry
    for field, value in changed.items():
        setattr(entry, field, value)
    entry.save(update_fields=[*changed, "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=ENTRY_METADATA_UPDATED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_entry",
        target_id=entry.id,
        metadata={"fields": sorted(changed)},
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
    if collection.archived_at is not None:
        raise ContentTypeArchived
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
    if collection.archived_at is not None:
        raise ContentTypeArchived
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
    locale = assert_organization_content_locale(locale, organization_id=context.organization_id)
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
    assert_slug_not_former(
        organization_id=context.organization_id,
        collection_id=source.collection_id,
        locale=locale,
        slug=slug,
    )
    translation = record_entry_translation(
        context,
        source,
        locale=locale,
        slug=slug,
        title=title,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    # The same article is filed under the same categories and tags, as a
    # translation job's version is (ADR-070 pkt 16; ADR-079 pkt 26). Visitors
    # see them with the version's own publication.
    links = ContentEntryTag.all_objects.filter(
        organization_id=context.organization_id, entry_id=source.id
    ).values_list("tag_id", flat=True)
    ContentEntryTag.all_objects.bulk_create([
        ContentEntryTag(
            organization_id=context.organization_id, entry_id=translation.id, tag_id=tag_id
        )
        for tag_id in links
    ])
    return translation, True


def record_entry_translation(
    context: Any,
    source: ContentEntry,
    *,
    locale: str,
    slug: str,
    title: str,
    idempotency_key: str,
    request_hash: str,
    machine: bool = False,
) -> ContentEntry:
    """The article's entry in another language: a person's, or a translation
    job's (`machine`), which knows the entry it translates."""
    translation = ContentEntry.all_objects.create(
        organization_id=context.organization_id,
        collection=source.collection,
        site_id=source.site_id,
        slug=slug,
        locale=locale,
        translation_group=source.translation_group,
        translation_of=source if machine else None,
        title=title,
        author_name=source.author_name if machine else "",
        noindex=source.noindex if machine else False,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
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
            **({"machine": True} if machine else {}),
        },
    )
    return translation


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
