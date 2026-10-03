"""Blog articles as a translation source: `sites.entry` (ADR-069, ADR-070 pkt 16;
plan TL11b).

An article in another language is an entry of its own in the same translation
group, with its own publication (`translations_publish_separately`).

- **Objects** are each group's source: a person's entry, in the site's language
  when there is one (`collections.group_source`). A machine translation is
  never one.
- **Units** are the source version's block units plus its title and excerpt
  (`meta/title`, `meta/excerpt`) — from the publication for `published`, from
  the draft and the entry for `working`.
- **Targets** are the sibling's in the language: a translation job's entry
  (`translation_of`), or a person's still without text, which the first write
  takes on. A person's own text in another structure is not written into
  (`human_version`); their edits of a machine translation are kept unit by unit
  (`collections._edited_translation`) and so protected.
- **Writes** become a sibling version assembled from the source's blocks, with
  the units, the source version and the job: the draft for `live` and
  `draft`, the waiting version for `pending`. The title and excerpt follow, the
  tags are the source's, and the address follows the title until the sibling
  is first published. A receipt per (entry, language, key) answers a repeat.
- **Publish** is `publish_entry` of each sibling the job wrote live, unless a
  person withdrew it; **revert** puts back the draft and the publication from
  before the job.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    EXCLUDED_SOURCE_UNPUBLISHED,
    EXCLUDED_WITHDRAWN,
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
from saas_core.content_protocol.units import DATA_PUBLIC, UNIT_TEXT, Unit, unit_state
from saas_core.modules.core.organizations.api import list_resource_reference_ids
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required
from saas_core.modules.shared.billing.api import authorize_entitled

from .collections import (
    ENTRY_VERSION_REFERENCE_OWNER,
    EntryNotFound,
    group_source,
    publish_entry,
    record_entry_publication,
    record_entry_translation,
    record_entry_version,
    take_down_entry,
)
from .language_decisions import REVIEW_GATE
from .language_publication import _translated
from .language_versions import _texts, site_locales
from .localized_bodies import LocaleUnitsInvalid, assemble, extract_units
from .models import (
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentEntryVersion,
    EntryTranslationWrite,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import MEDIA_ASSET_RESOURCE_TYPE
from .source_changes import ENTRY_SOURCE_KEY
from .translation_source import (
    GATE_UNKNOWN_UNIT,
    ORIGIN_TRANSLATION_JOB,
    ORIGIN_TRANSLATION_PENDING,
    _actor,
    _gate,
    _item_digest,
    _outcome_dict,
    _outcome_from,
    _target,
    _tenant,
    _tenant_context,
    before_job,
    made_by_job,
    realign,
)

SOURCE_KEY = ENTRY_SOURCE_KEY
META_TITLE = "meta/title"
META_EXCERPT = "meta/excerpt"
META_FIELDS = {META_TITLE: "title", META_EXCERPT: "excerpt"}
META_LIMITS = {"title": 200, "excerpt": 400}
LOCALE_TRANSLATED = "sites.entry.locale_translated"
#: The read of a machine translation, or of a person's second language of an
#: article: only the group's source is translated.
EXCLUDED_NOT_SOURCE = "not_a_source"
#: The language's article is a person's own text, in a structure of its own.
EXCLUDED_HUMAN_VERSION = "human_version"


class EntryTranslationSource:
    key = SOURCE_KEY
    module_id = "shared.sites"
    labels: Mapping[str, str] = {"pl": "Wpisy blogów", "en": "Blog articles"}
    staging: Staging = "versioned"
    bases: frozenset[str] = frozenset({"published", "working"})
    write_targets: frozenset[str] = frozenset({"draft", "pending", "live"})
    translations_publish_separately = True

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        with _tenant(context):
            _authorize(context, action, object_ids)

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
            groups: dict[UUID, list[ContentEntry]] = {}
            for entry in (
                ContentEntry.all_objects.select_related("site")
                .filter(organization_id=context.organization_id)
                .order_by("id")
            ):
                groups.setdefault(entry.translation_group, []).append(entry)
            sources = [
                source
                for group in groups.values()
                if (source := group_source(group, group[0].site.default_locale)) is not None
                and (changed_since is None or source.updated_at >= changed_since)
            ]
            ordered = sorted(sources, key=lambda entry: (str(entry.site_id), entry.id))
            start = int(cursor or 0)
            chunk = ordered[start : start + min(limit, LIST_LIMIT)]
            end = start + len(chunk)
            items = []
            for entry in chunk:
                published = _basis(entry, "published")
                working = _basis(entry, "working")
                items.append(
                    ObjectRef(
                        object_id=entry.id,
                        label=entry.title,
                        scope=str(entry.site_id),
                        priority=1,
                        public=published is not None,
                        published_version=published.token if published else None,
                        working_version=working.token if working else None,
                        changed_at=entry.updated_at,
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
            return _read(context, _entry(context, object_id), locale, basis)

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
        """Each sibling of the site the job wrote live, published on its own."""
        with _tenant(context):
            _authorize(context, "publish", ())
            live = sorted({
                (receipt.entry_id, receipt.locale)
                for receipt in EntryTranslationWrite.all_objects.filter(
                    organization_id=context.organization_id, site_id=UUID(scope), job_ref=job_ref
                )
                if any(outcome["state"] == "live" for outcome in receipt.outcomes)
            })
            first: str | None = None
            for entry_id, locale in live:
                entry = _entry(context, entry_id)
                sibling = _sibling(entry, locale)
                if (
                    sibling is None
                    or sibling.state == ContentEntryState.WITHDRAWN
                    or not made_by_job(sibling.current_draft, job_ref)
                    or not _publishable(sibling.current_draft)
                ):
                    continue
                publication, _created = publish_entry(
                    entry_id=sibling.id,
                    idempotency_key=f"tr:{_short([idempotency_key, sibling.id])}",
                    # The translation sits beside its original in the index.
                    published_at=entry.published_at,
                )
                first = first or str(publication.id)
            return first

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        with _tenant(context):
            _authorize(context, "read", (object_id,))
            entry = _entry(context, object_id)
            read = _read(context, entry, locale, "published")
            if read.excluded:
                return Completeness(complete=False, publishable=False, reasons=(read.excluded,))
            untranslated = tuple(
                unit.key
                for unit in read.units
                if unit.required
                and not unit.copied
                and unit_state(unit, read.targets.get(unit.key)).status in ("missing", "blocked")
            )
            return Completeness(
                complete=not untranslated,
                publishable=not untranslated,
                untranslated=untranslated,
                reasons=("untranslated_units",) if untranslated else (),
            )

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]:
        """The site's name and the company's — brands are kept as written."""
        with _tenant(context):
            entry = _entry(context, object_id)
            names = {entry.site.name.strip(), entry.site.organization.name.strip()}
            return tuple(ProtectedTerm(text=name, rule="keep") for name in sorted(names) if name)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision: accepting a waiting translation makes it the
        sibling's draft and publishes it; withdrawing takes a public one off the
        site, as when the original was taken down (`translation-sources.md`
        §8.3 pkt 3)."""
        if action not in ("accept", "discard", "withdraw"):
            raise ValueError(f"Review action {action!r} is not offered for articles.")
        with _tenant(context):
            authorize_entitled(
                SITE_CONTENT_EDIT if action == "discard" else SITE_PUBLISH, SITES_ENABLED
            )
            assert_person_required(_tenant_context(context), REVIEW_GATE)
            return tuple(
                _decide(context, action, item, f"{idempotency_key}:{item.object_id}:{item.locale}")
                for item in items
            )

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """What the job made current goes back to what was there before it: the
        draft, and the publication visitors had. The operator's command reverts
        in the job's own context, so no person gate here."""
        with _tenant(context):
            _authorize(context, "publish", ())
            siblings = ContentEntry.all_objects.select_for_update(of=("self",)).filter(
                organization_id=context.organization_id,
                id__in=ContentEntryVersion.all_objects.filter(
                    organization_id=context.organization_id, origin_ref=job_ref
                ).values("entry_id"),
            )
            outcomes: list[WriteOutcome] = []
            for sibling in siblings.select_related(
                "current_draft", "pending_version", "current_publication"
            ).order_by("id"):
                changed = _revert_sibling(
                    context, sibling, job_ref, f"revert:{_short([idempotency_key, sibling.id])}"
                )
                if changed:
                    outcomes.append(
                        WriteOutcome(
                            object_id=sibling.translation_of_id or sibling.id,
                            locale=sibling.locale,
                            state="live",
                            keys=(),
                            reason="reverted",
                            target_version=str(sibling.version),
                        )
                    )
            return tuple(outcomes)


ENTRY_SOURCE = EntryTranslationSource()


# -- reading -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Source:
    """The source text a read is against: a version and the entry's own words."""

    version: ContentEntryVersion
    title: str
    excerpt: str

    @property
    def token(self) -> str:
        meta = hashlib.sha256(
            json.dumps([self.title, self.excerpt], ensure_ascii=False).encode()
        ).hexdigest()[:16]
        return f"{self.version.id}:{meta}"


def _authorize(context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]) -> None:
    authorize_entitled(
        SITE_PUBLISH if action in ("publish", "withdraw") else SITE_CONTENT_EDIT, SITES_ENABLED
    )
    wanted = set(object_ids)
    if wanted and ContentEntry.all_objects.filter(
        organization_id=context.organization_id, id__in=wanted
    ).count() != len(wanted):
        raise EntryNotFound


def _entry(context: ContentContext, object_id: UUID, *, lock: bool = False) -> ContentEntry:
    entries = ContentEntry.all_objects.select_related(
        "site__current_publication",
        "site__organization",
        "collection",
        "current_draft",
        "current_publication",
    )
    if lock:
        entries = entries.select_for_update(of=("self",))
    entry = entries.filter(pk=object_id, organization_id=context.organization_id).first()
    if entry is None:
        raise EntryNotFound
    return entry


def _group(entry: ContentEntry) -> list[ContentEntry]:
    return list(
        ContentEntry.all_objects.filter(
            organization_id=entry.organization_id, translation_group=entry.translation_group
        ).order_by("id")
    )


def _sibling(entry: ContentEntry, locale: str, *, lock: bool = False) -> ContentEntry | None:
    siblings = ContentEntry.all_objects.filter(
        organization_id=entry.organization_id,
        translation_group=entry.translation_group,
        locale=locale,
    ).exclude(pk=entry.pk)
    if lock:
        siblings = siblings.select_for_update(of=("self",))
    return siblings.select_related(
        "current_draft__source_version", "pending_version", "current_publication"
    ).first()


def _manageable(sibling: ContentEntry | None) -> bool:
    """A job writes into its own translation while its structure is the
    source's, and takes on a person's language version that has no text yet."""
    if sibling is None:
        return True
    if sibling.translation_of_id is None:
        return sibling.current_draft_id is None and sibling.pending_version_id is None
    return sibling.current_draft is None or sibling.current_draft.units is not None


def _basis(entry: ContentEntry, basis: Basis) -> _Source | None:
    if basis == "working":
        if entry.current_draft is None:
            return None
        return _Source(entry.current_draft, entry.title.strip(), entry.excerpt.strip())
    publication = entry.current_publication
    if entry.state != ContentEntryState.PUBLISHED or publication is None:
        return None
    snapshot = publication.snapshot
    version = ContentEntryVersion.all_objects.filter(
        organization_id=entry.organization_id, entry_id=entry.id, number=snapshot.get("version")
    ).first()
    if version is None:
        return None
    return _Source(
        version, str(snapshot.get("title", "")).strip(), str(snapshot.get("excerpt", "")).strip()
    )


def _units(source: _Source) -> tuple[Unit, ...]:
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
        for unit in extract_units(source.version.blocks)
    )
    meta = tuple(
        Unit(
            key=key,
            kind=UNIT_TEXT,
            text=getattr(source, field),
            data_class=DATA_PUBLIC,
            max_length=META_LIMITS[field],
        )
        for key, field in META_FIELDS.items()
        if getattr(source, field)
    )
    return body + meta


def _read(context: ContentContext, entry: ContentEntry, locale: str, basis: Basis) -> SourceRead:
    site = entry.site
    source = _basis(entry, basis)
    sibling = _sibling(entry, locale)
    source_entry = group_source(_group(entry), site.default_locale)
    excluded = None
    if source_entry is None or source_entry.id != entry.id:
        excluded = EXCLUDED_NOT_SOURCE
    elif locale == entry.locale:
        excluded = EXCLUDED_LOCALE_IS_SOURCE
    elif locale not in site_locales(site):
        excluded = EXCLUDED_LOCALE_NOT_ENABLED
    elif basis == "published" and entry.state == ContentEntryState.WITHDRAWN:
        excluded = EXCLUDED_WITHDRAWN
    elif source is None:
        excluded = EXCLUDED_SOURCE_UNPUBLISHED
    elif not _manageable(sibling):
        excluded = EXCLUDED_HUMAN_VERSION
    units = () if excluded or source is None else _units(source)
    return SourceRead(
        object_id=entry.id,
        locale=locale,
        basis=basis,
        scope=str(entry.site_id),
        source_locale=entry.locale,
        basis_version=source.token if source is not None else "",
        target_version=str(sibling.version) if sibling is not None else "0",
        units=units,
        targets=(
            {key: _target(item) for key, item in _aligned(sibling, units, source).items()}
            if source is not None and not excluded
            else {}
        ),
        facts=PublicationFacts(
            legal_document=False,
            locale_live=_locale_live(site, locale),
            actor_may_publish=context.has_permission(SITE_PUBLISH),
        ),
        excluded=excluded,
    )


def _locale_live(site: Site, locale: str) -> bool:
    """The language is on the site already: its pages, or another article."""
    publication = site.current_publication
    if publication is not None and locale in (publication.snapshot.get("live_locales") or []):
        return True
    return ContentEntry.all_objects.filter(
        organization_id=site.organization_id,
        site_id=site.id,
        locale=locale,
        state=ContentEntryState.PUBLISHED,
    ).exists()


def _aligned(
    sibling: ContentEntry | None, units: Sequence[Unit], source: _Source
) -> dict[str, dict[str, Any]]:
    """The sibling's stored entries ({text, provenance}) keyed by the units."""
    draft = sibling.current_draft if sibling is not None else None
    own: dict[str, Any] = (
        dict(draft.units)
        if draft is not None and draft.units is not None and draft.source_version is not None
        else {}
    )
    aligned = (
        realign(
            [unit for unit in units if unit.key not in META_FIELDS],
            own=own,
            old_blocks=draft.source_version.blocks,
            new_blocks=source.version.blocks,
            memory={},
        )
        if own and draft is not None and draft.source_version is not None
        else {}
    )
    for unit in units:
        if unit.key in META_FIELDS:
            entry = _meta_entry(sibling, unit, own.get(unit.key))
            if entry is not None:
                aligned[unit.key] = entry
    return aligned


def _meta_entry(sibling: ContentEntry | None, unit: Unit, stored: Any) -> dict[str, Any] | None:
    """The sibling's title or excerpt. One typed by a person has no provenance:
    protected and unverified. A job's sibling without text yet has none."""
    if sibling is None or (sibling.translation_of_id is not None and sibling.current_draft is None):
        return None
    value = getattr(sibling, META_FIELDS[unit.key]).strip()
    if not value:
        return None
    if isinstance(stored, dict) and stored.get("text") == value:
        return {k: stored[k] for k in ("text", "provenance") if k in stored}
    return {"text": value}


def _publishable(version: ContentEntryVersion | None) -> bool:
    """Every unit of the source it translates has its translation."""
    if version is None or version.units is None or version.source_version is None:
        return False
    units = extract_units(version.source_version.blocks)
    if any(unit.placeholder for unit in units):
        return False
    return all(_translated(unit, version.units.get(unit.key)) for unit in units)


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

    entry = _entry(context, item.object_id, lock=True)
    receipt_key = hashlib.sha256(batch.idempotency_key.encode()).hexdigest()
    digest = _item_digest(item)
    done = EntryTranslationWrite.all_objects.filter(
        organization_id=entry.organization_id,
        entry_id=entry.id,
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
                EntryTranslationWrite.all_objects.create(
                    organization_id=entry.organization_id,
                    site_id=entry.site_id,
                    entry=entry,
                    locale=item.locale,
                    idempotency_key=receipt_key,
                    request_hash=digest,
                    job_ref=batch.trigger.job_ref or "",
                    outcomes=[_outcome_dict(result) for result in results],
                )
        except IntegrityError:
            pass
        return tuple(results)

    read = _read(context, entry, item.locale, item.basis)
    if read.excluded:
        return finish((outcome("refused", keys, read.excluded),))
    if item.basis_version != read.basis_version:
        return finish((outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),))
    if item.target_version != read.target_version:
        return finish((outcome("conflict", keys, CONFLICT_TARGET_CHANGED),))
    facts = replace(
        read.facts,
        object_published_in_job=entry.id in published_now,
        published_in_job=len(published_now - {entry.id}),
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
    terms = ENTRY_SOURCE.protected_terms(context=context, object_id=entry.id)
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
        written_entry = {"text": text, "provenance": provenance.as_dict()}
        if batch.protected != "overwrite" and unit_state(unit, read.targets.get(key)).protected:
            proposals[key] = written_entry
        else:
            written[key] = written_entry
    source = _basis(entry, item.basis)
    assert source is not None
    sibling = _sibling(entry, item.locale, lock=True)
    aligned = _aligned(sibling, read.units, source)
    job_ref = batch.trigger.job_ref or ""
    if (written or proposals) and sibling is None:
        sibling = _new_sibling(context, entry, item.locale)
    if sibling is not None and (written or proposals) and sibling.translation_of_id != entry.id:
        # A person's empty language version, or a job's sibling of an earlier
        # source of the group: this source's translation from now on.
        ContentEntry.all_objects.filter(pk=sibling.pk).update(translation_of=entry)
        sibling.translation_of = entry
    results: list[WriteOutcome] = []
    state = decision.outcome
    held: dict[str, dict[str, Any]] = {}
    hold_reason = ""
    if written and state == "pending":
        held.update(written)
        hold_reason = decision.reason or ""
    elif written:
        assert sibling is not None
        try:
            version = _store(
                context,
                sibling,
                source,
                {**aligned, **written},
                job_ref,
                receipt_key,
                current=True,
                replaces=sibling.current_draft,
            )
        except LocaleUnitsInvalid as invalid:
            errors.extend(_block_errors(invalid))
        else:
            _apply_meta(sibling, written)
            _copy_tags(entry, sibling)
            if state == "live":
                published_now.add(entry.id)
            _audit(context, entry, sibling, version, len(written))
            results.append(
                outcome(state, list(written), decision.reason, target_version=str(sibling.version))
            )
    if proposals:
        held.update(proposals)
        hold_reason = hold_reason or REASON_OVERWRITES_HUMAN
    if held:
        assert sibling is not None
        waiting = sibling.pending_version
        base = (
            dict(waiting.units)
            if waiting is not None
            and waiting.units is not None
            and waiting.source_version_id == source.version.id
            else aligned
        )
        if written and state != "pending":
            # What just went current stays in the waiting version, or
            # accepting it would take that back.
            base = {**base, **written}
        try:
            pending = _store(
                context,
                sibling,
                source,
                {**base, **held},
                job_ref,
                receipt_key + ":p",
                current=False,
                origin=ORIGIN_TRANSLATION_PENDING,
            )
        except LocaleUnitsInvalid as invalid:
            errors.extend(_block_errors(invalid))
        else:
            ContentEntry.all_objects.filter(pk=sibling.pk).update(
                pending_version=pending, pending_reason=hold_reason[:40]
            )
            if written and state == "pending":
                results.append(
                    outcome(
                        "pending",
                        list(written),
                        decision.reason,
                        target_version=str(sibling.version),
                    )
                )
            if proposals:
                results.append(
                    outcome(
                        "pending",
                        list(proposals),
                        REASON_OVERWRITES_HUMAN,
                        target_version=str(sibling.version),
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


def _short(parts: Sequence[Any]) -> str:
    return canonical_json_hash([str(part) for part in parts])[:40]


def _block_errors(invalid: LocaleUnitsInvalid) -> list[FieldError]:
    return [
        FieldError(f"units.{problem.key}", problem.code, "The section does not take this text.")
        for problem in invalid.problems
    ]


def _new_sibling(context: ContentContext, source: ContentEntry, locale: str) -> ContentEntry:
    """The article's entry in the language, made by its first translation:
    its title and address come from what the translation writes."""
    return record_entry_translation(
        context,
        source,
        locale=locale,
        slug=free_entry_slug(source, locale, source.slug),
        title=source.title,
        idempotency_key=f"translation:{source.id}:{locale}",
        request_hash=canonical_json_hash({"entry_id": str(source.id), "locale": locale}),
        machine=True,
    )


def _store(
    context: ContentContext,
    sibling: ContentEntry,
    source: _Source,
    entries: Mapping[str, Any],
    job_ref: str,
    key: str,
    *,
    current: bool,
    origin: str = ORIGIN_TRANSLATION_JOB,
    replaces: ContentEntryVersion | None = None,
) -> ContentEntryVersion:
    """The sibling's version: the source's blocks with the language's text,
    naming the media the source names."""
    blocks = assemble(source.version.blocks, _texts(entries)).blocks
    media = list_resource_reference_ids(
        context=_tenant_context(context),
        resource_type=MEDIA_ASSET_RESOURCE_TYPE,
        owner_type=ENTRY_VERSION_REFERENCE_OWNER,
        owner_id=source.version.id,
    )
    return record_entry_version(
        context,
        sibling,
        blocks=blocks,
        media_asset_ids=list(media),
        idempotency_key=key[:120],
        request_hash=hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        current=current,
        units=dict(entries),
        source_version=source.version,
        origin=origin,
        origin_ref=job_ref,
        replaces=replaces,
    )


def _apply_meta(sibling: ContentEntry, written: Mapping[str, Mapping[str, Any]]) -> None:
    """The language's title and excerpt; the address follows the title until
    the article is first published (ADR-070 pkt 18)."""
    changes: dict[str, Any] = {
        field: str(written[key]["text"])[: META_LIMITS[field]]
        for key, field in META_FIELDS.items()
        if key in written
    }
    if not changes:
        return
    if "title" in changes and sibling.published_at is None:
        changes["slug"] = free_entry_slug(
            sibling, sibling.locale, slug_from_title(changes["title"]) or sibling.slug
        )
    ContentEntry.all_objects.filter(pk=sibling.pk).update(**changes, updated_at=timezone.now())
    for field, value in changes.items():
        setattr(sibling, field, value)


def free_entry_slug(entry: ContentEntry, locale: str, wanted: str) -> str:
    base = (wanted or entry.slug or "wpis")[:120].strip("-") or "wpis"
    taken = set(
        ContentEntry.all_objects.filter(
            organization_id=entry.organization_id,
            collection_id=entry.collection_id,
            locale=locale,
        )
        .exclude(pk=entry.pk)
        .values_list("slug", flat=True)
    )
    slug, number = base, 2
    while slug in taken:
        slug, number = f"{base}-{number}", number + 1
    return slug


def _copy_tags(source: ContentEntry, sibling: ContentEntry) -> None:
    """The article's subjects are the original's (ADR-070 pkt 16)."""
    wanted = set(
        ContentEntryTag.all_objects.filter(
            organization_id=source.organization_id, entry_id=source.id
        ).values_list("tag_id", flat=True)
    )
    ContentEntryTag.all_objects.filter(
        organization_id=sibling.organization_id, entry_id=sibling.id
    ).exclude(tag_id__in=wanted).delete()
    for tag_id in wanted:
        ContentEntryTag.all_objects.get_or_create(
            organization_id=sibling.organization_id, entry_id=sibling.id, tag_id=tag_id
        )


def _audit(
    context: ContentContext,
    source: ContentEntry,
    sibling: ContentEntry,
    version: ContentEntryVersion,
    count: int,
) -> None:
    from saas_core.modules.core.identity.models import User

    record_audit(
        organization=Organization.objects.get(pk=source.organization_id),
        action=LOCALE_TRANSLATED,
        actor=User.objects.filter(pk=_actor(context)).first(),
        target_type="content_entry_version",
        target_id=version.id,
        metadata={
            "site_id": str(source.site_id),
            "entry_id": str(source.id),
            "translation_id": str(sibling.id),
            "locale": sibling.locale,
            "version": version.number,
            "translated_units": count,
        },
    )


# -- a person's decisions and undoing a job ------------------------------------


def _decide(
    context: ContentContext, action: ReviewAction, item: ReviewItem, key: str
) -> WriteOutcome:
    def outcome(state: str, reason: str | None, **extra: Any) -> WriteOutcome:
        return WriteOutcome(
            object_id=item.object_id,
            locale=item.locale,
            state=state,  # type: ignore[arg-type]
            keys=(),
            reason=reason,
            **extra,
        )

    entry = _entry(context, item.object_id)
    sibling = _sibling(entry, item.locale, lock=True)
    if action == "withdraw":
        if sibling is None or sibling.current_publication_id is None:
            return outcome("conflict", CONFLICT_TARGET_CHANGED)
        take_down_entry(context, sibling, reason="translation_withdraw")
        return outcome("draft", "withdrawn", target_version=str(sibling.version))
    if (
        sibling is None
        or sibling.pending_version is None
        or (item.expected_version is not None and item.expected_version != str(sibling.version))
    ):
        return outcome("conflict", CONFLICT_TARGET_CHANGED)
    waiting = sibling.pending_version
    if action == "discard":
        ContentEntry.all_objects.filter(pk=sibling.pk).update(
            pending_version=None, pending_reason="", version=sibling.version + 1
        )
        return outcome("refused", "discarded", target_version=str(sibling.version + 1))
    source = _basis(entry, "published")
    if source is None or waiting.source_version_id != source.version.id:
        # Translated from text visitors no longer read: the next job's.
        return outcome("conflict", CONFLICT_SOURCE_CHANGED)
    ContentEntry.all_objects.filter(pk=sibling.pk).update(
        current_draft=waiting, pending_version=None, pending_reason="", version=sibling.version + 1
    )
    sibling.current_draft = waiting
    sibling.version += 1
    _apply_meta(
        sibling,
        {name: stored for name, stored in (waiting.units or {}).items() if name in META_FIELDS},
    )
    _copy_tags(entry, sibling)
    if not _publishable(waiting) or sibling.state == ContentEntryState.WITHDRAWN:
        return outcome("draft", "untranslated_units", target_version=str(sibling.version))
    publish_entry(
        entry_id=sibling.id,
        idempotency_key=f"accept:{_short([key])}",
        published_at=entry.published_at,
    )
    return outcome("live", None, target_version=str(sibling.version))


def _revert_sibling(context: ContentContext, sibling: ContentEntry, job_ref: str, key: str) -> bool:
    changes: dict[str, Any] = {}
    current = sibling.current_draft
    if made_by_job(current, job_ref):
        before = before_job(current, job_ref)
        changes["current_draft"] = before
        meta = {
            field: str(before.units[meta_key]["text"])
            for meta_key, field in META_FIELDS.items()
            if before is not None
            and isinstance(before.units, dict)
            and isinstance(before.units.get(meta_key), dict)
        }
        changes.update(meta)
    if sibling.pending_version is not None and sibling.pending_version.origin_ref == job_ref:
        changes.update(pending_version=None, pending_reason="")
    publication = sibling.current_publication
    published_by_job = (
        publication is not None
        and ContentEntryVersion.all_objects.filter(
            organization_id=sibling.organization_id,
            entry_id=sibling.id,
            number=publication.snapshot.get("version"),
            origin_ref=job_ref,
            origin=ORIGIN_TRANSLATION_JOB,
        ).exists()
    )
    if not changes and not published_by_job:
        # A person's version since, or their acceptance: theirs.
        return False
    if changes:
        ContentEntry.all_objects.filter(pk=sibling.pk).update(
            **changes, version=sibling.version + 1, updated_at=timezone.now()
        )
        sibling.version += 1
    if published_by_job:
        assert publication is not None
        job_versions = set(
            ContentEntryVersion.all_objects.filter(
                organization_id=sibling.organization_id, entry_id=sibling.id, origin_ref=job_ref
            ).values_list("number", flat=True)
        )
        earlier = [
            item
            for item in ContentEntryPublication.all_objects.filter(
                organization_id=sibling.organization_id,
                entry_id=sibling.id,
                sequence__lt=publication.sequence,
            ).order_by("sequence")
            if item.snapshot.get("version") not in job_versions
        ]
        sibling.refresh_from_db()
        if earlier:
            record_entry_publication(
                context, sibling, dict(earlier[-1].snapshot), key, reason="translation_revert"
            )
        else:
            take_down_entry(
                context, sibling, reason="translation_revert", state=ContentEntryState.DRAFT
            )
    return True


def follow_source(context: ContentContext, source: ContentEntry) -> None:
    """After a source article's publication, a translation whose every unit is
    still translated — its blocks only moved, or what changed has no words —
    follows it without a model, and goes out again when it was public
    (ADR-070 pkt 4). The rest waits, as it was, for the next job."""
    published = _basis(source, "published")
    if published is None:
        return
    units = _units(published)
    siblings = ContentEntry.all_objects.select_for_update(of=("self",)).filter(
        organization_id=source.organization_id,
        translation_group=source.translation_group,
        translation_of__isnull=False,
    )
    for sibling in siblings.select_related("current_draft__source_version").order_by("id"):
        draft = sibling.current_draft
        if (
            draft is None
            or draft.units is None
            or draft.source_version_id in (None, published.version.id)
        ):
            continue
        aligned = _aligned(sibling, units, published)
        if any(
            unit_state(unit, _target(aligned[unit.key]) if unit.key in aligned else None).status
            not in ("fresh", "copied")
            for unit in units
        ):
            continue
        try:
            _store(
                context,
                sibling,
                published,
                aligned,
                draft.origin_ref,
                f"follow:{published.version.id}",
                current=True,
                origin=draft.origin,
                replaces=draft,
            )
        except LocaleUnitsInvalid:
            continue
        if sibling.state == ContentEntryState.PUBLISHED:
            publish_entry(
                entry_id=sibling.id,
                idempotency_key=f"follow:{_short([published.version.id, sibling.id])}",
            )


def register_entry_source() -> None:
    registry.register_translation_source(ENTRY_SOURCE)


__all__ = [
    "ENTRY_SOURCE",
    "META_EXCERPT",
    "META_FIELDS",
    "META_TITLE",
    "SOURCE_KEY",
    "free_entry_slug",
    "register_entry_source",
]
