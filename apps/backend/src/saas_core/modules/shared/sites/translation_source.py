"""Company pages as a translation source: `sites.page` (ADR-069, ADR-070; plan TL11a).

The engine reads a page's text units in a target language, writes what its
model produced and publishes the results that went live — through this
adapter and nowhere else (`docs/architecture/translation-sources.md` §6).

- **Units** are the page's block units (`localized_bodies.extract_units`) plus
  its title and description (`meta/title`, `meta/description`): a language
  version is publishable only with its own (ADR-070 pkt 6).
- **Targets** come from the language's current body, realigned to the source
  the read is against: by the hash of the source text (the body itself, then
  the site's translation memory), then — for a unit reworded in place — the
  old text at the same key, so it reads as stale with what was there.
- **Writes** become a new `PageLocaleVersion`: `live` and `draft` as the
  current body (bound to the published source or to the draft), `pending` as
  the waiting body with its reason. The language's title and description
  follow a live write; the slug is computed from the title and never changes
  once it is public (ADR-070 pkt 18). A receipt per (page, language, key)
  answers a repeat with the same outcomes.
- **Publish** is a derived publication of the published state with the
  versions this job made current (`translation_job`), never `publish_site`;
  **revert** puts back what the job replaced (`translation_revert`).
- Decisions on waiting results are a person's (`language_decisions`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import (
    REASON_OVERWRITES_HUMAN,
    PublicationFacts,
    decide_publication,
)
from saas_core.content_protocol.provenance import Provenance
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_DELETED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    EXCLUDED_SOURCE_UNPUBLISHED,
    LIST_LIMIT,
    Basis,
    Completeness,
    ContentContext,
    FieldError,
    ObjectPage,
    ObjectRef,
    ProtectedTerm,
    ReviewAction,
    ReviewItem,
    SourceAction,
    SourceRead,
    Staging,
    WriteBatch,
    WriteItem,
    WriteOutcome,
)
from saas_core.content_protocol.transliteration import slug_from_title
from saas_core.content_protocol.units import DATA_PUBLIC, UNIT_TEXT, Target, Unit, unit_state
from saas_core.content_protocol.writes import (
    GATE_UNKNOWN_UNIT,
)
from saas_core.content_protocol.writes import item_digest as _item_digest
from saas_core.content_protocol.writes import outcome_from_dict as _outcome_from
from saas_core.content_protocol.writes import outcome_to_dict as _outcome_dict
from saas_core.content_protocol.writes import write_gate as _gate
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import authorize_entitled

from .block_decoration import stored_block_payload
from .language_publication import fresh_entry, home_page
from .language_versions import (
    _create_version,
    _translated_by_source,
    site_locales,
    translation_memory,
)
from .localized_bodies import extract_units
from .models import (
    ContentCollection,
    Page,
    PageBlock,
    PageLocaleVersion,
    PageTranslation,
    PageTranslationWrite,
    PageType,
    PageVersion,
    PublicationReason,
    Site,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import PageNotFound
from .source_changes import PAGE_SOURCE_KEY

SOURCE_KEY = PAGE_SOURCE_KEY
META_TITLE = "meta/title"
META_DESCRIPTION = "meta/description"
META_FIELDS = {META_TITLE: "title", META_DESCRIPTION: "description"}
#: The version origin of a translation job's text (`PageLocaleVersion.origin`):
#: made current by the job, or waiting for a person — whose acceptance is
#: theirs, so undoing the job leaves it.
ORIGIN_TRANSLATION_JOB = "translation_job"
ORIGIN_TRANSLATION_PENDING = "translation_pending"
LOCALE_TRANSLATED = "sites.page.locale_translated"


class PageTranslationSource:
    key = SOURCE_KEY
    module_id = "shared.sites"
    labels: Mapping[str, str] = {"pl": "Podstrony stron firm", "en": "Company site pages"}
    staging: Staging = "versioned"
    bases: frozenset[str] = frozenset({"published", "working"})
    write_targets: frozenset[str] = frozenset({"draft", "pending", "live"})
    translations_publish_separately = False

    # -- permissions

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        with _tenant(context):
            _authorize(context, action, object_ids)

    # -- what there is

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        with _tenant(context):
            _authorize(context, "read", ())
            pages = Page.all_objects.select_related("site__current_publication", "current_draft")
            pages = pages.filter(organization_id=context.organization_id, deleted_at__isnull=True)
            if changed_since is not None:
                pages = pages.filter(updated_at__gte=changed_since)
            by_site: dict[UUID, list[Page]] = {}
            for page in sorted(pages, key=lambda page: page.id):
                by_site.setdefault(page.site_id, []).append(page)
            homes = {site_id: home_page(site_pages) for site_id, site_pages in by_site.items()}
            priority = {
                page.id: 0 if homes[page.site_id] is page else 1
                for site_pages in by_site.values()
                for page in site_pages
            }
            ordered = sorted(
                (page for site_pages in by_site.values() for page in site_pages),
                key=lambda page: (str(page.site_id), priority[page.id], page.id),
            )
            start = int(cursor or 0)
            chunk = ordered[start : start + min(limit, LIST_LIMIT)]
            end = start + len(chunk)
            items = []
            for page in chunk:
                published = _published_source(page)
                items.append(
                    ObjectRef(
                        object_id=page.id,
                        label=page.name,
                        scope=str(page.site_id),
                        priority=priority[page.id],
                        public=published is not None,
                        published_version=(
                            _basis_version(page, published) if published is not None else None
                        ),
                        working_version=(
                            _basis_version(page, page.current_draft)
                            if page.current_draft is not None
                            else None
                        ),
                        changed_at=page.updated_at,
                    )
                )
            return ObjectPage(
                items=tuple(items), next_cursor=str(end) if end < len(ordered) else None
            )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        with _tenant(context):
            _authorize(context, "read", (object_id,))
            return _read(context, _page(context, object_id), locale, basis)

    # -- writes

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        if batch.source_key != self.key:
            raise ValueError("The batch is for another source.")
        with _tenant(context):
            _authorize(context, "translate", [item.object_id for item in batch.items])
            published_now = set(batch.published_in_job)
            outcomes: list[WriteOutcome] = []
            for item in batch.items:
                outcomes.extend(_write_item(context, batch, item, published_now))
            return tuple(outcomes)

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        from .language_decisions import publish_job_versions

        with _tenant(context):
            _authorize(context, "publish", ())
            site = Site.all_objects.get(pk=UUID(scope), organization_id=context.organization_id)
            publication = publish_job_versions(
                site=site,
                job_ref=job_ref,
                reason=PublicationReason.TRANSLATION_JOB,
                idempotency_key=idempotency_key,
            )
            return str(publication.id) if publication is not None else None

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        with _tenant(context):
            _authorize(context, "read", (object_id,))
            page = _page(context, object_id)
            read = _read(context, page, locale, "published")
            if read.excluded:
                return Completeness(complete=False, publishable=False, reasons=(read.excluded,))
            untranslated = tuple(
                unit.key
                for unit in read.units
                if unit.required
                and not unit.copied
                and unit_state(unit, read.targets.get(unit.key)).status in ("missing", "blocked")
            )
            reasons: list[str] = []
            row = _translation(page, locale)
            if row is not None and row.body_current is not None:
                source = _published_source(page)
                assert source is not None
                _entry, reason = fresh_entry(page.site, row, source, _blocks(source))
                if reason:
                    reasons.append(reason)
            elif untranslated:
                reasons.append("untranslated_units")
            return Completeness(
                complete=not untranslated,
                publishable=not untranslated and not reasons,
                untranslated=untranslated,
                reasons=tuple(reasons),
            )

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]:
        """The site's name and the company's — brands are kept as written."""
        with _tenant(context):
            page = _page(context, object_id)
            names = {page.site.name.strip(), page.site.organization.name.strip()}
            return tuple(ProtectedTerm(text=name, rule="keep") for name in sorted(names) if name)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision on waiting results, one call per site
        (ADR-070 pkt 12): accepting makes them current and publishes them."""
        from .language_decisions import (
            accept_locale_versions,
            batch_digest,
            reject_locale_version,
        )

        with _tenant(context):
            outcomes: list[WriteOutcome] = []
            if action == "accept":
                by_site: dict[UUID, list[tuple[UUID, str, int]]] = {}
                for item in items:
                    page = _page(context, item.object_id)
                    by_site.setdefault(page.site_id, []).append((
                        page.id,
                        item.locale,
                        _expected(page, item),
                    ))
                for site_id, site_items in by_site.items():
                    seen = accept_locale_versions(
                        items=site_items,
                        digest=None,
                        idempotency_key="",
                        preview=True,
                        review=True,
                    )
                    decisions = accept_locale_versions(
                        items=site_items,
                        digest=batch_digest([(d.page, d.translation) for d in seen]),
                        idempotency_key=f"{idempotency_key}:{site_id}"[:120],
                        review=True,
                    )
                    outcomes.extend(
                        WriteOutcome(
                            object_id=decision.page.id,
                            locale=decision.translation.locale,
                            state="live" if decision.skipped is None else "pending",
                            keys=(),
                            reason=decision.skipped,
                        )
                        for decision in decisions
                    )
            elif action == "discard":
                for item in items:
                    page = _page(context, item.object_id)
                    decision = reject_locale_version(
                        page_id=page.id,
                        locale=item.locale,
                        expected_body_version=_expected(page, item),
                        idempotency_key=f"{idempotency_key}:{page.id}:{item.locale}"[:120],
                        review=True,
                    )
                    outcomes.append(
                        WriteOutcome(
                            object_id=page.id,
                            locale=decision.translation.locale,
                            state="refused",
                            keys=(),
                            reason="discarded",
                        )
                    )
            else:
                raise ValueError(f"Review action {action!r} is not offered for pages.")
            return tuple(outcomes)

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """What the job made current goes back to what was there before, in a
        derived publication per site (`translation_revert`). The operator's
        command reverts in the job's own context, so no person gate here."""
        from .language_decisions import publish_job_versions

        with _tenant(context):
            _authorize(context, "publish", ())
            touched = PageTranslation.all_objects.select_for_update(of=("self",)).filter(
                organization_id=context.organization_id,
                id__in=PageLocaleVersion.all_objects.filter(
                    organization_id=context.organization_id, origin_ref=job_ref
                ).values("translation_id"),
            )
            outcomes: list[WriteOutcome] = []
            sites: dict[UUID, set[UUID]] = {}
            for row in touched.select_related("body_current", "body_pending").order_by("id"):
                changes: dict[str, Any] = {}
                current = row.body_current
                if made_by_job(current, job_ref):
                    changes["body_current"] = before_job(current, job_ref)
                if row.body_pending is not None and row.body_pending.origin_ref == job_ref:
                    changes.update(body_pending=None, pending_reason="")
                if not changes:
                    # A person's version since, or their acceptance: theirs.
                    continue
                PageTranslation.all_objects.filter(pk=row.id).update(
                    **changes, body_version=row.body_version + 1, updated_at=timezone.now()
                )
                if "body_current" in changes:
                    sites.setdefault(row.site_id, set()).add(row.id)
                outcomes.append(
                    WriteOutcome(
                        object_id=row.page_id,
                        locale=row.locale,
                        state="live",
                        keys=(),
                        reason="reverted",
                        target_version=str(row.body_version + 1),
                    )
                )
            for site_id, rows in sites.items():
                publish_job_versions(
                    site=Site.all_objects.get(pk=site_id),
                    job_ref=job_ref,
                    reason=PublicationReason.TRANSLATION_REVERT,
                    idempotency_key=f"{idempotency_key}:{site_id}"[:120],
                    reverting=rows,
                )
            return tuple(outcomes)


PAGE_SOURCE = PageTranslationSource()


# -- reading -------------------------------------------------------------------


@contextmanager
def _tenant(context: ContentContext) -> Iterator[None]:
    """The engine and the contract pass the context explicitly; the sites
    services read the active one and the tables force row-level security."""
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(_tenant_context(context)):
            yield


def _tenant_context(context: ContentContext) -> TenantContext:
    if isinstance(context, TenantContext):
        return context
    raise TypeError("A sites translation call needs a tenant context.")


def _authorize(context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]) -> None:
    authorize_entitled(
        SITE_PUBLISH if action in ("publish", "withdraw") else SITE_CONTENT_EDIT, SITES_ENABLED
    )
    wanted = set(object_ids)
    if wanted and Page.all_objects.filter(
        organization_id=context.organization_id, id__in=wanted
    ).count() != len(wanted):
        raise PageNotFound


def _page(context: ContentContext, object_id: UUID) -> Page:
    page = (
        Page.all_objects.select_related(
            "site__current_publication", "site__organization", "current_draft"
        )
        .filter(pk=object_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    return page


def _published_source(page: Page) -> PageVersion | None:
    publication = page.site.current_publication
    if publication is None:
        return None
    entry = next(
        (
            item
            for item in publication.snapshot.get("pages", [])
            if isinstance(item, dict) and item.get("page_id") == str(page.id)
        ),
        None,
    )
    if entry is None:
        return None
    return PageVersion.all_objects.filter(
        pk=entry["version_id"], organization_id=page.organization_id
    ).first()


def _blocks(version: PageVersion) -> list[dict[str, Any]]:
    return [
        stored_block_payload(block)
        for block in PageBlock.all_objects.filter(
            organization_id=version.organization_id, page_version_id=version.id
        ).order_by("position")
    ]


def _source_row(page: Page) -> PageTranslation | None:
    return PageTranslation.all_objects.filter(
        organization_id=page.organization_id, page_id=page.id, locale=page.site.default_locale
    ).first()


def _translation(page: Page, locale: str) -> PageTranslation | None:
    return (
        PageTranslation.all_objects.select_related(
            "body_current__source_version", "body_pending__source_version"
        )
        .filter(organization_id=page.organization_id, page_id=page.id, locale=locale)
        .first()
    )


def _units(page: Page, source: PageVersion) -> tuple[Unit, ...]:
    body = tuple(
        Unit(
            key=unit.key,
            kind=unit.kind,
            text=unit.text,
            data_class=unit.data_class,
            max_length=unit.max_length,
            required=unit.required,
            placeholder=unit.placeholder,
        )
        for unit in extract_units(_blocks(source))
    )
    row = _source_row(page)
    meta = tuple(
        Unit(
            key=key,
            kind=UNIT_TEXT,
            text=getattr(row, field).strip(),
            data_class=DATA_PUBLIC,
            max_length=getattr(PageTranslation._meta.get_field(field), "max_length", None),
        )
        for key, field in META_FIELDS.items()
        if row is not None and getattr(row, field).strip()
    )
    return body + meta


def _basis_version(page: Page, source: PageVersion) -> str:
    """The source version, and the source language's title and description:
    a change of either makes a read stale."""
    row = _source_row(page)
    meta = hashlib.sha256(
        json.dumps([row.title, row.description] if row else [], ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return f"{source.id}:{meta}"


def _source(page: Page, basis: Basis) -> PageVersion | None:
    return _published_source(page) if basis == "published" else page.current_draft


def _read(context: ContentContext, page: Page, locale: str, basis: Basis) -> SourceRead:
    site = page.site
    excluded = None
    source = _source(page, basis)
    if page.deleted_at is not None:
        excluded = EXCLUDED_DELETED
    elif locale == site.default_locale:
        excluded = EXCLUDED_LOCALE_IS_SOURCE
    elif locale not in site_locales(site):
        excluded = EXCLUDED_LOCALE_NOT_ENABLED
    elif source is None:
        excluded = EXCLUDED_SOURCE_UNPUBLISHED
    row = _translation(page, locale)
    units = () if excluded or source is None else _units(page, source)
    return SourceRead(
        object_id=page.id,
        locale=locale,
        basis=basis,
        scope=str(site.id),
        source_locale=site.default_locale,
        basis_version=_basis_version(page, source) if source is not None else "",
        target_version=str(row.body_version) if row is not None else "0",
        units=units,
        targets=_targets(page, row, units, source) if source is not None else {},
        facts=_facts(context, page, locale),
        excluded=excluded,
    )


def _facts(context: ContentContext, page: Page, locale: str) -> PublicationFacts:
    publication = page.site.current_publication
    live = (publication.snapshot.get("live_locales") or []) if publication else []
    return PublicationFacts(
        legal_document=page.page_type == PageType.LEGAL,
        locale_live=locale in live,
        actor_may_publish=context.has_permission(SITE_PUBLISH),
    )


def _targets(
    page: Page,
    row: PageTranslation | None,
    units: Sequence[Unit],
    source: PageVersion,
) -> dict[str, Target]:
    """The language's current text for every current unit, realigned."""
    entries = _aligned_entries(page, row, units, source)
    return {key: _target(entry) for key, entry in entries.items()}


def _aligned_entries(
    page: Page,
    row: PageTranslation | None,
    units: Sequence[Unit],
    source: PageVersion,
) -> dict[str, dict[str, Any]]:
    """Stored entries ({text, provenance}) keyed by the current units."""
    body = row.body_current if row is not None else None
    own: dict[str, Any] = dict(body.units) if body is not None else {}
    aligned = realign(
        [unit for unit in units if unit.key not in META_FIELDS],
        own=own,
        old_blocks=_blocks(body.source_version) if body is not None else [],
        new_blocks=_blocks(source),
        memory=translation_memory(page=page, locale=row.locale) if row is not None else {},
    )
    for unit in units:
        if unit.key in META_FIELDS:
            entry = _meta_entry(row, unit, own.get(unit.key))
            if entry is not None:
                aligned[unit.key] = entry
    return aligned


def realign(
    units: Sequence[Unit],
    *,
    own: Mapping[str, Any],
    old_blocks: Sequence[Mapping[str, Any]],
    new_blocks: Sequence[Mapping[str, Any]],
    memory: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Stored entries of one language's body, written against `old_blocks`,
    keyed by the units of `new_blocks`: by the hash of the source text first
    (the body, then `memory`), then — for a unit reworded in place, same block
    type and field, whose old text exists nowhere now — the old text, which
    then reads as stale (ADR-070 pkt 4–5)."""
    by_source = _translated_by_source(own.values())
    old_types = [block["block_type"] for block in old_blocks]
    old_keys = {unit.key: (unit.kind, unit.source_hash) for unit in extract_units(old_blocks)}
    new_types = [block["block_type"] for block in new_blocks]
    current_hashes = {unit.source_hash for unit in units}
    aligned: dict[str, dict[str, Any]] = {}
    for unit in units:
        hit = by_source.get(unit.source_hash) or memory.get(unit.source_hash)
        if hit is not None:
            aligned[unit.key] = hit
            continue
        stored = own.get(unit.key)
        old = old_keys.get(unit.key)
        position = int(unit.key.split("/", 1)[0])
        same_block = (
            position < len(old_types)
            and position < len(new_types)
            and old_types[position] == new_types[position]
        )
        if (
            same_block
            and old is not None
            and old[0] == unit.kind
            # What stood here still exists elsewhere: it moved, and this unit
            # is new rather than reworded.
            and old[1] not in current_hashes
            and isinstance(stored, dict)
            and "text" in stored
        ):
            # Reworded in place: the old text stays, and reads as stale.
            aligned[unit.key] = {k: stored[k] for k in ("text", "provenance") if k in stored}
    return aligned


def _meta_entry(row: PageTranslation | None, unit: Unit, stored: Any) -> dict[str, Any] | None:
    """The language's title or description. Typed by a person in the
    metadata form, it has no provenance: protected and unverified."""
    if row is None:
        return None
    value = getattr(row, META_FIELDS[unit.key]).strip()
    if not value:
        return None
    if isinstance(stored, dict) and stored.get("text") == value:
        return {k: stored[k] for k in ("text", "provenance") if k in stored}
    return {"text": value}


def _target(entry: Mapping[str, Any]) -> Target:
    provenance = entry.get("provenance")
    return Target(
        text=str(entry["text"]),
        provenance=Provenance.from_dict(provenance) if isinstance(provenance, dict) else None,
    )


def made_by_job(version: Any, job_ref: str) -> bool:
    """A version the job itself made current — not one a person accepted."""
    return (
        version is not None
        and version.origin_ref == job_ref
        and version.origin == ORIGIN_TRANSLATION_JOB
    )


def before_job(version: Any, job_ref: str) -> Any:
    """What was current before the job's first version of this text."""
    while made_by_job(version, job_ref):
        version = version.replaces
    return version


def _expected(page: Page, item: ReviewItem) -> int:
    if item.expected_version is not None:
        return int(item.expected_version)
    row = _translation(page, item.locale)
    return row.body_version if row is not None else 0


# -- writing -------------------------------------------------------------------


def _write_item(
    context: ContentContext,
    batch: WriteBatch,
    item: WriteItem,
    published_now: set[UUID],
) -> tuple[WriteOutcome, ...]:
    keys = tuple(sorted(item.texts))

    def outcome(
        state: str, chosen: Sequence[str], reason: str | None, **extra: Any
    ) -> WriteOutcome:
        return WriteOutcome(
            object_id=item.object_id,
            locale=item.locale,
            state=state,  # type: ignore[arg-type]
            keys=tuple(sorted(chosen)),
            reason=reason,
            **extra,
        )

    page = (
        Page.all_objects.select_for_update(of=("self",))
        .select_related("site__current_publication", "site__organization", "current_draft")
        .get(pk=item.object_id, organization_id=context.organization_id)
    )
    Site.all_objects.select_for_update().filter(pk=page.site_id).first()
    receipt_key = hashlib.sha256(batch.idempotency_key.encode()).hexdigest()
    digest = _item_digest(item)
    done = PageTranslationWrite.all_objects.filter(
        organization_id=page.organization_id,
        page_id=page.id,
        locale=item.locale,
        idempotency_key=receipt_key,
    ).first()
    if done is not None:
        if done.request_hash != digest:
            return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        return tuple(_outcome_from(stored) for stored in done.outcomes)

    def finish(results: Sequence[WriteOutcome]) -> tuple[WriteOutcome, ...]:
        try:
            with transaction.atomic():
                PageTranslationWrite.all_objects.create(
                    organization_id=page.organization_id,
                    site_id=page.site_id,
                    page=page,
                    locale=item.locale,
                    idempotency_key=receipt_key,
                    request_hash=digest,
                    job_ref=batch.trigger.job_ref or "",
                    outcomes=[_outcome_dict(result) for result in results],
                )
        except IntegrityError:
            pass
        return tuple(results)

    read = _read(context, page, item.locale, item.basis)
    if read.excluded:
        return finish((outcome("refused", keys, read.excluded),))
    if item.basis_version != read.basis_version:
        return finish((outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),))
    if item.target_version != read.target_version:
        return finish((outcome("conflict", keys, CONFLICT_TARGET_CHANGED),))
    facts = replace(
        read.facts,
        object_published_in_job=page.id in published_now,
        published_in_job=len(published_now - {page.id}),
    )
    decision = decide_publication(
        policy=registry.translation_policy(organization_id=context.organization_id),
        requested=item.requested,
        requested_reason=item.reason,
        trigger=batch.trigger,
        facts=facts,
    )
    if decision.outcome == "refused":
        return finish((outcome("refused", keys, decision.reason),))
    units = {unit.key: unit for unit in read.units}
    terms = PAGE_SOURCE.protected_terms(context=context, object_id=page.id)
    written: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    errors: list[FieldError] = []
    for key, (text, provenance) in item.texts.items():
        unit = units.get(key)
        if unit is None:
            errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
            continue
        error = _gate(unit, text, terms)
        if error is not None:
            errors.append(error)
            continue
        entry = {"text": text, "provenance": provenance.as_dict()}
        if batch.protected != "overwrite" and unit_state(unit, read.targets.get(key)).protected:
            proposals[key] = entry
        else:
            written[key] = entry
    source = _source(page, item.basis)
    assert source is not None
    row = _translation(page, item.locale) or _new_translation(page, item.locale)
    row = PageTranslation.all_objects.select_for_update(of=("self",)).get(pk=row.pk)
    aligned = _aligned_entries(page, row, read.units, source)
    job_ref = batch.trigger.job_ref or ""
    results: list[WriteOutcome] = []
    state = decision.outcome
    held: dict[str, dict[str, Any]] = {}
    hold_reason = ""
    if written and state == "pending":
        held.update(written)
        hold_reason = decision.reason or ""
    elif written:
        version = _store(
            page,
            row,
            source,
            {**aligned, **written},
            context,
            job_ref,
            receipt_key,
            replaces=row.body_current,
        )
        _apply_meta(page, row, written)
        PageTranslation.all_objects.filter(pk=row.pk).update(
            body_current=version, body_version=row.body_version + 1, updated_at=timezone.now()
        )
        row.body_version += 1
        if state == "live":
            published_now.add(page.id)
        _audit(context, page, row, version, len(written))
        results.append(
            outcome(state, list(written), decision.reason, target_version=str(row.body_version))
        )
    if proposals:
        held.update(proposals)
        hold_reason = hold_reason or REASON_OVERWRITES_HUMAN
    if held:
        base = (
            dict(row.body_pending.units)
            if row.body_pending is not None and row.body_pending.source_version_id == source.id
            else aligned
        )
        if written and state != "pending":
            # What just went current stays in the waiting version, or
            # accepting it would take that back.
            base = {**base, **written}
        pending = _store(
            page,
            row,
            source,
            {**base, **held},
            context,
            job_ref,
            receipt_key + ":p",
            origin=ORIGIN_TRANSLATION_PENDING,
        )
        PageTranslation.all_objects.filter(pk=row.pk).update(
            body_pending=pending,
            pending_reason=hold_reason[:40],
            body_version=row.body_version + 1,
            updated_at=timezone.now(),
        )
        row.body_version += 1
        if written and state == "pending":
            results.append(
                outcome(
                    "pending", list(written), decision.reason, target_version=str(row.body_version)
                )
            )
        if proposals:
            results.append(
                outcome(
                    "pending",
                    list(proposals),
                    REASON_OVERWRITES_HUMAN,
                    target_version=str(row.body_version),
                )
            )
    if errors:
        results.append(
            outcome(
                "pending",
                [error.field.removeprefix("units.") for error in errors],
                "gate_failed",
                errors=tuple(errors),
            )
        )
    return finish(results)


def _actor(context: ContentContext) -> UUID:
    if context.actor_id is None:
        raise TypeError("A sites translation write needs the person the job acts for.")
    return context.actor_id


def _new_translation(page: Page, locale: str) -> PageTranslation:
    """The language's row, made by the first translation: its address and
    title come from what the translation writes."""
    row, _created = PageTranslation.all_objects.get_or_create(
        organization_id=page.organization_id,
        page=page,
        locale=locale,
        defaults={"site_id": page.site_id, "slug": free_slug(page, locale, page.key)},
    )
    return row


def _store(
    page: Page,
    row: PageTranslation,
    source: PageVersion,
    entries: Mapping[str, Any],
    context: ContentContext,
    job_ref: str,
    key: str,
    *,
    origin: str = ORIGIN_TRANSLATION_JOB,
    replaces: PageLocaleVersion | None = None,
) -> PageLocaleVersion:
    return _create_version(
        page=page,
        translation=row,
        source_version=source,
        units=entries,
        actor_id=_actor(context),
        credential_id=None,
        origin=origin,
        origin_ref=job_ref,
        idempotency_key=key[:120],
        request_hash=hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        replaces=replaces,
    )


def _apply_meta(page: Page, row: PageTranslation, written: Mapping[str, Mapping[str, Any]]) -> None:
    """A live title and description are the language's own; the address
    follows the title until it is public (ADR-070 pkt 18)."""
    changes: dict[str, Any] = {}
    for key, field in META_FIELDS.items():
        if key in written:
            changes[field] = str(written[key]["text"])[: 160 if field == "title" else 320]
    if not changes:
        return
    if "title" in changes and row.slug_locked_at is None:
        changes["slug"] = free_slug(
            page, row.locale, slug_from_title(changes["title"]) or page.key, keep=row.id
        )
    PageTranslation.all_objects.filter(pk=row.pk).update(
        **changes, version=row.version + 1, updated_at=timezone.now()
    )
    for field, value in changes.items():
        setattr(row, field, value)
    row.version += 1


def free_slug(page: Page, locale: str, wanted: str, *, keep: UUID | None = None) -> str:
    """Unique in (site, language) and never a collection's path, which the
    language's blog answers at (ADR-070 pkt 18)."""
    base = (wanted or page.key or "strona")[:72].strip("-") or "strona"
    taken = set(
        PageTranslation.all_objects.filter(
            organization_id=page.organization_id, site_id=page.site_id, locale=locale
        )
        .exclude(pk__in=[keep] if keep is not None else [])
        .values_list("slug", flat=True)
    ) | set(
        ContentCollection.all_objects.filter(
            organization_id=page.organization_id, site_id=page.site_id
        ).values_list("base_path", flat=True)
    )
    slug, number = base, 2
    while slug in taken:
        slug, number = f"{base}-{number}", number + 1
    return slug


def _audit(
    context: ContentContext,
    page: Page,
    row: PageTranslation,
    version: PageLocaleVersion,
    count: int,
) -> None:
    from saas_core.modules.core.identity.models import User

    record_audit(
        organization=Organization.objects.get(pk=page.organization_id),
        action=LOCALE_TRANSLATED,
        actor=User.objects.filter(pk=_actor(context)).first(),
        target_type="page_locale_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "locale": row.locale,
            "version": version.number,
            "translated_units": count,
        },
    )


def register_page_source() -> None:
    registry.register_translation_source(PAGE_SOURCE)


__all__ = [
    "META_DESCRIPTION",
    "META_FIELDS",
    "META_TITLE",
    "PAGE_SOURCE",
    "SOURCE_KEY",
    "free_slug",
    "register_page_source",
    "slug_from_title",
]
