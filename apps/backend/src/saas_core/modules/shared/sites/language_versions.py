"""Writing a page body in another language (ADR-070, plan TL8c).

A person edits text units, never blocks. Each save is a new, append-only
`PageLocaleVersion` bound to the source version the language version follows,
and moves the translation's own lock, `body_version` — the source page's
`version` stays where it was, so a German save never makes a change set
waiting for the Polish page stale. The units go through `localized_bodies`,
which assembles the blocks a visitor will get and names every unit that does
not fit, by key and code.

Automation writes a language version through change sets (TL13); until then
these doors are a person's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol import registry
from saas_core.content_protocol.provenance import (
    ORIGIN_AI,
    ORIGIN_COPY,
    ORIGIN_HUMAN,
    ORIGIN_UNTRANSLATED,
    PROTECTED_ORIGINS,
    Provenance,
    unit_hash,
)
from saas_core.content_protocol.registry import WaitingReview
from saas_core.content_protocol.sources import LIST_LIMIT, ContentContext, TranslationSource
from saas_core.content_protocol.units import unit_state
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.command_registry import organization_modules
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_decoration import stored_block_payload
from .localization import entry_path
from .localized_bodies import (
    LocaleUnitsInvalid,
    TextUnit,
    assemble,
    extract_units,
)
from .localized_bodies import structure_signature as body_structure_signature
from .models import (
    ContentEntry,
    ContentEntryState,
    Page,
    PageBlock,
    PageLocaleVersion,
    PageTranslation,
    PageVersion,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import (
    MutationResult,
    PageAutomationForbidden,
    PageNotFound,
    SiteNotFound,
    SitesIdempotencyConflict,
    TranslationNotFound,
    _idempotency_key,
    _is_automation,
)
from .source_changes import ENTRY_SOURCE_KEY, PAGE_SOURCE_KEY

LOCALE_BODY_SAVED = "sites.page.locale_body_saved"
LOCALE_BODY_RESTORED = "sites.page.locale_body_restored"
LOCALE_BODY_REBASED = "sites.page.locale_body_rebased"

ORIGIN_SAVE = "save"
ORIGIN_COPY_SOURCE = "copy"
ORIGIN_RESTORE = "restore"
ORIGIN_REBASE = "rebase"
# Not translations, whatever text they hold: the source standing in.
UNTRANSLATED_ORIGINS = frozenset({ORIGIN_COPY, ORIGIN_UNTRANSLATED})


class LocaleNotEnabled(APIException):
    status_code = 400
    default_detail = "Ten język nie jest włączony dla tej strony internetowej."
    default_code = "locale_not_enabled"


class LocaleIsSource(APIException):
    status_code = 400
    default_detail = (
        "To język źródłowy strony: jego treść zmienia się w edytorze strony, nie jako tłumaczenie."
    )
    default_code = "locale_is_source"


class LocaleBodyVersionConflict(APIException):
    status_code = 409
    default_detail = "Treść tej wersji językowej zmieniła się od odczytu; odśwież ją."
    default_code = "locale_body_version_conflict"


class SourceVersionMismatch(APIException):
    status_code = 409
    default_detail = (
        "Wersja językowa jest związana z inną wersją źródła niż ta, którą edytowano; odśwież ją."
    )
    default_code = "source_version_mismatch"


UNIT_MESSAGES = {
    "unknown_unit": "Wersja źródłowa nie ma takiego fragmentu.",
    "required": "Ten fragment nie może być pusty.",
    "too_long": "Tekst jest dłuższy, niż pozwala to miejsce w bloku.",
    "token_missing": "Brakuje znacznika ⟦n⟧…⟦/n⟧ z tekstu źródłowego.",
    "token_unexpected": "Tekst ma znacznik, którego nie ma w tekście źródłowym.",
    "token_malformed": "Znaczniki ⟦n⟧ i ⟦/n⟧ są źle sparowane.",
    "token_nesting": "Znaczniki nie mogą być w sobie zagnieżdżone.",
    "token_empty": "Znacznik nie może obejmować pustego tekstu.",
    "block_invalid": "Złożony blok nie spełnia kontraktu bloku.",
}


class LocaleUnitInvalid(ValidationError):
    """Every unit that does not fit, as field errors `units.<key>` with a code
    each (ADR-076: input the caller can fix is a 400)."""

    problem_code = "locale_unit_invalid"

    def __init__(self, error: LocaleUnitsInvalid) -> None:
        units: dict[str, list[ErrorDetail]] = {}
        for problem in error.problems:
            message = UNIT_MESSAGES.get(problem.code, "Fragment nie pasuje do wersji źródłowej.")
            units.setdefault(problem.key, []).append(ErrorDetail(message, code=problem.code))
        super().__init__({"units": units})


class LocaleBodyVersionNotFound(NotFound):
    default_detail = "Nie ma takiej wersji treści w tym języku."
    default_code = "locale_body_version_not_found"


@dataclass(frozen=True, slots=True)
class UnitState:
    unit: TextUnit
    # Stored text for this language; None where nothing was written yet.
    text: str | None
    origin: str | None
    # A person's text for the unit's earlier source, kept after the source
    # changed: offered for review, never published as a translation.
    suggestion: str | None = None
    # While a waiting version is read (`LocaleBody.waiting`): what the
    # language's own version says here now, so the change can be seen.
    current_text: str | None = None

    @property
    def translated(self) -> bool:
        return self.unit.copied or (
            self.text is not None and self.origin not in UNTRANSLATED_ORIGINS
        )


@dataclass(frozen=True, slots=True)
class WaitingMetadata:
    """A title or description that waits with a version: a translation job
    wrote it into the version (`meta/*`), and accepting the version makes it
    the language's own."""

    field: str
    # The source language's, which this text translates; empty when it has none.
    source_text: str
    text: str
    # What the language has now; None where it has nothing.
    current_text: str | None


@dataclass(frozen=True, slots=True)
class LocaleBody:
    page: Page
    translation: PageTranslation
    # The source version the language version follows; for a language with
    # no body yet, the page's current version.
    source_version: PageVersion
    version: PageLocaleVersion | None
    units: tuple[UnitState, ...]
    # The units are the waiting version's text against its source, not the
    # language's own body: a person decides on it first (`_waiting`).
    waiting: bool = False
    # With `waiting`: the title and description the waiting version carries.
    metadata: tuple[WaitingMetadata, ...] = ()

    @property
    def untranslated(self) -> int:
        return sum(1 for state in self.units if not state.translated)

    def source_blocks(self) -> list[dict[str, Any]]:
        """The source version's blocks, which the editor's language mode names
        sections and marks from (TL15)."""
        return _source_blocks(self.source_version)

    @property
    def outdated(self) -> bool:
        """A newer source version exists than the one this language follows."""
        return self.page.current_draft_id != self.source_version.id


def site_locales(site: Site) -> tuple[str, ...]:
    """The languages a site's content may have: the company's own list, within
    the profile's (ADR-071 pkt 4 and 8), with the site's source language first."""
    company = organization_content_locales(site.organization)
    return (site.default_locale, *(code for code in company if code != site.default_locale))


def get_locale_body(*, page_id: UUID, locale: str, waiting: bool = False) -> LocaleBody:
    """The language's body. `waiting`: for a person reading it — while a
    version waits for acceptance the language is read with that version's
    text (`LocaleBody.waiting`), each unit beside what the language says now,
    so the decision is made on words that can be seen. Writes go on from the
    language's own body."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=False)
    body = _body(page, translation)
    return (_waiting(body) or body) if waiting else body


@transaction.atomic
def save_locale_body(
    *,
    page_id: UUID,
    locale: str,
    source_version_id: UUID,
    expected_body_version: int,
    units: Mapping[str, str],
    idempotency_key: str,
    preview: bool = False,
    provenance_model: str = "",
) -> MutationResult[LocaleBody]:
    """Writes the given units over the current ones.

    A person's text, unless somebody acts for the person (the assistant, a
    translation job — `acting_via`): then it is AI text, keeps the machine
    marker and is not protected like a person's correction, and the version
    names who acted (`acting_ref`). `provenance_model` is the model that wrote
    it, when the caller knows. Units not named keep what they had. With
    `preview` nothing is saved: the answer is the body as it would be, with
    every problem a save would raise.
    """
    return _write(
        page_id=page_id,
        locale=locale,
        source_version_id=source_version_id,
        expected_body_version=expected_body_version,
        idempotency_key=idempotency_key,
        preview=preview,
        origin=ORIGIN_SAVE,
        changes=lambda body, context: _written(
            body,
            units,
            ORIGIN_AI if context.acting_via else ORIGIN_HUMAN,
            model=provenance_model,
        ),
        request={
            "units": dict(sorted(units.items())),
            **({"provenance_model": provenance_model} if provenance_model else {}),
        },
    )


@transaction.atomic
def copy_source_into_locale_body(
    *,
    page_id: UUID,
    locale: str,
    source_version_id: UUID,
    expected_body_version: int,
    idempotency_key: str,
) -> MutationResult[LocaleBody]:
    """Fills every unit with no text yet with the source text, to translate
    by hand in place. A copy stays untranslated until somebody changes it or
    keeps it on purpose (saving the same text makes it theirs)."""
    return _write(
        page_id=page_id,
        locale=locale,
        source_version_id=source_version_id,
        expected_body_version=expected_body_version,
        idempotency_key=idempotency_key,
        preview=False,
        origin=ORIGIN_COPY_SOURCE,
        changes=lambda body, _context: _written(
            body,
            {
                state.unit.key: state.unit.text
                for state in body.units
                if state.text is None and not state.unit.copied
            },
            ORIGIN_COPY,
        ),
        request={"copy": True},
    )


def list_locale_body_versions(*, page_id: UUID, locale: str) -> list[PageLocaleVersion]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=False)
    return list(
        PageLocaleVersion.all_objects.select_related("source_version", "created_by")
        .filter(organization_id=page.organization_id, translation_id=translation.id)
        .order_by("-number")
    )


def locale_body_version_blocks(
    *, page_id: UUID, locale: str, version_id: UUID
) -> tuple[PageLocaleVersion, list[dict[str, Any]]]:
    """A past version as a visitor would have got it, for a read-only preview."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=False)
    version = _version(page, translation, version_id)
    return version, assemble(_source_blocks(version.source_version), _texts(version.units)).blocks


@transaction.atomic
def restore_locale_body_version(
    *,
    page_id: UUID,
    locale: str,
    version_id: UUID,
    expected_body_version: int,
    idempotency_key: str,
) -> MutationResult[LocaleBody]:
    """Makes a past version current again, as a new version with its text and
    its binding; nothing is rewritten."""
    context = _person_context()
    page, translation = _target(context, page_id=page_id, locale=locale, lock=True)
    old = _version(page, translation, version_id)
    key = _idempotency_key(idempotency_key)
    request_hash = canonical_json_hash({
        "page_id": str(page.id),
        "locale": translation.locale,
        "restore": str(old.id),
        "expected_body_version": expected_body_version,
    })
    replay = _replay(translation, context.actor_id, key, request_hash, page)
    if replay is not None:
        return replay
    if translation.body_version != expected_body_version:
        raise LocaleBodyVersionConflict
    version = _create_version(
        page=page,
        translation=translation,
        source_version=old.source_version,
        units=old.units,
        actor_id=context.actor_id,
        credential_id=None,
        origin=ORIGIN_RESTORE,
        origin_ref=str(old.number),
        idempotency_key=key,
        request_hash=request_hash,
    )
    _advance(
        translation,
        version,
        expected_body_version,
        accepted=translation.body_accepted_id == old.id,
    )
    record_audit(
        organization=page.site.organization,
        action=LOCALE_BODY_RESTORED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page_locale_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "locale": translation.locale,
            "version": version.number,
            "restored_version": old.number,
        },
    )
    return MutationResult(_body(page, translation), True)


@transaction.atomic
def rebase_locale_body(
    *,
    page_id: UUID,
    locale: str,
    expected_body_version: int,
    idempotency_key: str,
    preview: bool = False,
) -> MutationResult[LocaleBody]:
    """Moves a language version onto the page's current source version.

    A unit whose source text did not change keeps its translation wherever it
    moved, and a source sentence already translated on another page of the
    site (its current body) is taken from there: matched by the hash of the source text, never
    by position. A changed unit starts untranslated, and a person's or an
    integration's text for its old wording stays beside it as a suggestion —
    never dropped silently, never shipped as a translation of words it did
    not translate. Already on the current version: nothing to do.
    """
    context = _person_context()
    page, translation = _target(context, page_id=page_id, locale=locale, lock=not preview)
    key = _idempotency_key(idempotency_key) if not preview else ""
    target = page.current_draft
    request_hash = canonical_json_hash({
        "page_id": str(page.id),
        "locale": translation.locale,
        "rebase_to": str(target.id) if target is not None else "",
        "expected_body_version": expected_body_version,
    })
    if not preview:
        replay = _replay(translation, context.actor_id, key, request_hash, page)
        if replay is not None:
            return replay
    if translation.body_version != expected_body_version:
        raise LocaleBodyVersionConflict
    body = _body(page, translation)
    if target is None or not body.outdated or body.version is None:
        return MutationResult(body, False)
    units = _carried(page, translation, body, target)
    if preview:
        return MutationResult(_preview(_on(body, target), units), False)
    version = _create_version(
        page=page,
        translation=translation,
        source_version=target,
        units=units,
        actor_id=context.actor_id,
        credential_id=None,
        origin=ORIGIN_REBASE,
        origin_ref=f"{body.source_version.number}->{target.number}",
        idempotency_key=key,
        request_hash=request_hash,
    )
    # What is carried was accepted; what changed starts untranslated.
    _advance(
        translation,
        version,
        expected_body_version,
        accepted=translation.body_accepted_id == body.version.id,
    )
    rebased = _body(page, translation)
    record_audit(
        organization=page.site.organization,
        action=LOCALE_BODY_REBASED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page_locale_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "locale": translation.locale,
            "version": version.number,
            "from_source_version": body.source_version.number,
            "to_source_version": target.number,
            "untranslated_units": rebased.untranslated,
        },
    )
    return MutationResult(rebased, True)


def _on(body: LocaleBody, source: PageVersion) -> LocaleBody:
    """The same language version seen against another source version."""
    return LocaleBody(
        page=body.page,
        translation=body.translation,
        source_version=source,
        version=body.version,
        units=tuple(_state(unit, None) for unit in extract_units(_source_blocks(source))),
    )


def _carried(
    page: Page, translation: PageTranslation, body: LocaleBody, target: PageVersion
) -> dict[str, dict[str, Any]]:
    own = body.version.units if body.version is not None else {}
    by_source = _translated_by_source(own.values())
    memory = translation_memory(page=page, locale=translation.locale)
    previous = {state.unit.key: state.unit for state in body.units}
    old_types = [block["block_type"] for block in _source_blocks(body.source_version)]
    new_blocks = _source_blocks(target)
    units: dict[str, dict[str, Any]] = {}
    for unit in extract_units(new_blocks):
        entry = by_source.get(unit.source_hash) or memory.get(unit.source_hash)
        if entry is not None:
            units[unit.key] = dict(entry)
            continue
        # The same place reworded: same position, same kind of block, same
        # field. A block that moved or was inserted is not a rewording.
        position = int(unit.key.split("/", 1)[0])
        same_block = (
            position < len(old_types) and old_types[position] == new_blocks[position]["block_type"]
        )
        old_unit, old_entry = previous.get(unit.key), own.get(unit.key)
        if (
            same_block
            and old_unit is not None
            and old_unit.kind == unit.kind
            and isinstance(old_entry, dict)
            and "text" in old_entry
            and old_entry.get("provenance", {}).get("origin") in PROTECTED_ORIGINS
        ):
            units[unit.key] = {"suggestion": {k: old_entry[k] for k in ("text", "provenance")}}
    return units


def _translated_by_source(entries: Any) -> dict[str, dict[str, Any]]:
    """Entries that translate something, by the hash of what they translate;
    a person's or an integration's text wins over a machine's."""
    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "text" not in entry:
            continue
        provenance = entry.get("provenance", {})
        origin, source_hash = provenance.get("origin"), provenance.get("source_hash")
        if not source_hash or origin in UNTRANSLATED_ORIGINS:
            continue
        held = found.get(source_hash)
        if held is None or (
            origin in PROTECTED_ORIGINS
            and held.get("provenance", {}).get("origin") not in PROTECTED_ORIGINS
        ):
            found[source_hash] = {"text": entry["text"], "provenance": provenance}
    return found


def translation_memory(*, page: Page, locale: str) -> dict[str, dict[str, Any]]:
    """The site's translations into one language, by the hash of the source
    text: the units of every page's current body in that language. Waiting
    bodies stay out — text nobody has reviewed must not reach another page
    for free. No table of its own: the bodies are the memory."""
    ids = PageTranslation.all_objects.filter(
        organization_id=page.organization_id,
        site_id=page.site_id,
        locale=locale,
        body_current__isnull=False,
    ).values_list("body_current_id", flat=True)
    entries = (
        entry
        for units in PageLocaleVersion.all_objects.filter(
            organization_id=page.organization_id, id__in=list(ids)
        ).values_list("units", flat=True)
        for entry in units.values()
    )
    return _translated_by_source(entries)


def _person_context() -> Any:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        # TL13 lets SeoContentRank write a language version through a change
        # set, with its grant and its structure check; not through this door.
        raise PageAutomationForbidden
    return context


def _target(
    context: Any, *, page_id: UUID, locale: str, lock: bool
) -> tuple[Page, PageTranslation]:
    pages = Page.all_objects.select_related("site__organization", "current_draft")
    if lock:
        pages = pages.select_for_update(of=("self",))
    page = pages.filter(
        pk=page_id, organization_id=context.organization_id, deleted_at__isnull=True
    ).first()
    if page is None:
        raise PageNotFound
    normalized = locale.strip().lower()
    if normalized == page.site.default_locale:
        raise LocaleIsSource
    if normalized not in site_locales(page.site):
        raise LocaleNotEnabled
    translations = PageTranslation.all_objects.select_related(
        "body_current__source_version", "body_pending__source_version"
    )
    if lock:
        translations = translations.select_for_update(of=("self",))
    translation = translations.filter(
        organization_id=context.organization_id, page_id=page.id, locale=normalized
    ).first()
    if translation is None:
        # The address and title come first; the body is written for them.
        raise TranslationNotFound
    return page, translation


def _source_blocks(version: PageVersion) -> list[dict[str, Any]]:
    return [
        stored_block_payload(block)
        for block in PageBlock.all_objects.filter(
            organization_id=version.organization_id, page_version_id=version.id
        ).order_by("position")
    ]


#: Units a body carries beside its blocks' — the language's title and
#: description a translation job wrote (`translation_source`).
METADATA_PREFIX = "meta/"
METADATA_FIELDS = ("title", "description")


def _texts(units: Mapping[str, Any]) -> dict[str, str]:
    # An entry with only a suggestion has no text for this language yet.
    return {
        key: str(entry["text"])
        for key, entry in units.items()
        if isinstance(entry, dict) and "text" in entry and not key.startswith(METADATA_PREFIX)
    }


def _body(page: Page, translation: PageTranslation) -> LocaleBody:
    version = translation.body_current
    source = version.source_version if version is not None else page.current_draft
    if source is None:
        raise PageNotFound
    stored = version.units if version is not None else {}
    states = tuple(
        _state(unit, stored.get(unit.key)) for unit in extract_units(_source_blocks(source))
    )
    return LocaleBody(
        page=page, translation=translation, source_version=source, version=version, units=states
    )


def _waiting(body: LocaleBody) -> LocaleBody | None:
    """The version that waits for a person's decision: its text against the
    source it was written for, each unit with what the language's own version
    says there now (`current_text`). `version` stays the language's own — None
    while its first version waits, since nothing is accepted yet."""
    pending = body.translation.body_pending
    if pending is None:
        return None
    source = pending.source_version
    # The waiting version may follow a newer source than the language's own:
    # a unit is the same place when its key and source text agree, otherwise
    # the same words wherever the source has them now.
    own = {state.unit.key: state for state in body.units}
    by_source: dict[tuple[str, str], str] = {}
    for state in body.units:
        if state.text is not None:
            by_source.setdefault((state.unit.kind, state.unit.source_hash), state.text)

    def current(unit: TextUnit) -> str | None:
        same = own.get(unit.key)
        if same is not None and (same.unit.kind, same.unit.source_hash) == (
            unit.kind,
            unit.source_hash,
        ):
            return same.text
        return by_source.get((unit.kind, unit.source_hash))

    # The title and description the version carries are read the same way:
    # beside the source's and what the language has now.
    page = body.page
    source_row = PageTranslation.all_objects.filter(
        organization_id=page.organization_id, page_id=page.id, locale=page.site.default_locale
    ).first()
    metadata = []
    for field in METADATA_FIELDS:
        entry = pending.units.get(f"{METADATA_PREFIX}{field}")
        if not isinstance(entry, dict) or "text" not in entry:
            continue
        limit = getattr(PageTranslation._meta.get_field(field), "max_length", None)
        metadata.append(
            WaitingMetadata(
                field=field,
                source_text=getattr(source_row, field).strip() if source_row is not None else "",
                text=str(entry["text"])[:limit],
                current_text=getattr(body.translation, field).strip() or None,
            )
        )

    return LocaleBody(
        page=body.page,
        translation=body.translation,
        source_version=source,
        version=body.version,
        units=tuple(
            replace(
                _state(unit, pending.units.get(unit.key)),
                current_text=current(unit) if body.version is not None else None,
            )
            for unit in extract_units(_source_blocks(source))
        ),
        waiting=True,
        metadata=tuple(metadata),
    )


def _written(
    body: LocaleBody, texts: Mapping[str, str], origin: str, *, model: str = ""
) -> dict[str, dict[str, Any]]:
    """Stored entries for the given texts. A key the source has no unit for
    passes through bare, so assembling names it with every other problem."""
    units = {state.unit.key: state.unit for state in body.units}
    at = timezone.now().isoformat()
    return {
        key: (
            {
                "text": text,
                "provenance": Provenance(
                    origin=origin,
                    source_hash=units[key].source_hash,
                    written_hash=unit_hash(units[key].kind, text),
                    model=model,
                    at=at,
                ).as_dict(),
            }
            if key in units
            else {"text": text}
        )
        for key, text in texts.items()
    }


def _write(
    *,
    page_id: UUID,
    locale: str,
    source_version_id: UUID,
    expected_body_version: int,
    idempotency_key: str,
    preview: bool,
    origin: str,
    changes: Any,
    request: dict[str, Any],
) -> MutationResult[LocaleBody]:
    context = _person_context()
    page, translation = _target(context, page_id=page_id, locale=locale, lock=not preview)
    key = _idempotency_key(idempotency_key) if not preview else ""
    request_hash = canonical_json_hash({
        "page_id": str(page.id),
        "locale": translation.locale,
        "source_version_id": str(source_version_id),
        "expected_body_version": expected_body_version,
        **request,
    })
    if not preview:
        replay = _replay(translation, context.actor_id, key, request_hash, page)
        if replay is not None:
            return replay
    if translation.body_version != expected_body_version:
        raise LocaleBodyVersionConflict
    body = _body(page, translation)
    if body.source_version.id != source_version_id:
        raise SourceVersionMismatch
    current = dict(body.version.units) if body.version is not None else {}
    written = changes(body, context)
    merged = {**current, **written}
    blocks = _source_blocks(body.source_version)
    try:
        assemble(blocks, _texts(merged))
    except LocaleUnitsInvalid as error:
        raise LocaleUnitInvalid(error) from error
    if preview:
        return MutationResult(_preview(body, merged), False)
    version = _create_version(
        page=page,
        translation=translation,
        source_version=body.source_version,
        units=merged,
        actor_id=context.actor_id,
        credential_id=None,
        origin=origin,
        origin_ref=context.acting_ref if context.acting_via else "",
        idempotency_key=key,
        request_hash=request_hash,
    )
    # A person editing a version they accepted still stands behind it; text
    # written for them (an assistant, an integration) starts unaccepted.
    _advance(
        translation,
        version,
        expected_body_version,
        accepted=(
            body.version is not None
            and translation.body_accepted_id == body.version.id
            and not context.acting_via
            and context.principal_kind == "membership"
        ),
    )
    saved = _body(page, translation)
    record_audit(
        organization=page.site.organization,
        action=LOCALE_BODY_SAVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page_locale_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "locale": translation.locale,
            "version": version.number,
            "source_version": body.source_version.number,
            "changed_units": len(written),
            "untranslated_units": saved.untranslated,
        },
    )
    return MutationResult(saved, True)


def _state(unit: TextUnit, entry: Any) -> UnitState:
    if not isinstance(entry, dict):
        return UnitState(unit=unit, text=None, origin=None)
    suggestion = entry.get("suggestion")
    return UnitState(
        unit=unit,
        text=str(entry["text"]) if "text" in entry else None,
        origin=str(entry.get("provenance", {}).get("origin", "")) if "text" in entry else None,
        suggestion=str(suggestion["text"]) if isinstance(suggestion, dict) else None,
    )


def _preview(body: LocaleBody, units: Mapping[str, Any]) -> LocaleBody:
    states = tuple(_state(state.unit, units.get(state.unit.key)) for state in body.units)
    return LocaleBody(
        page=body.page,
        translation=body.translation,
        source_version=body.source_version,
        version=body.version,
        units=states,
    )


def _replay(
    translation: PageTranslation,
    actor_id: UUID,
    key: str,
    request_hash: str,
    page: Page,
) -> MutationResult[LocaleBody] | None:
    existing = PageLocaleVersion.all_objects.filter(
        organization_id=translation.organization_id,
        translation_id=translation.id,
        created_by_id=actor_id,
        idempotency_key=key,
    ).first()
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise SitesIdempotencyConflict
    return MutationResult(_body(page, translation), False)


def _create_version(
    *,
    page: Page,
    translation: PageTranslation,
    source_version: PageVersion,
    units: Mapping[str, Any],
    actor_id: UUID,
    credential_id: UUID | None,
    origin: str,
    origin_ref: str,
    idempotency_key: str,
    request_hash: str,
    replaces: PageLocaleVersion | None = None,
) -> PageLocaleVersion:
    last = (
        PageLocaleVersion.all_objects.filter(
            organization_id=page.organization_id, translation_id=translation.id
        ).aggregate(number=Max("number"))["number"]
        or 0
    )
    return PageLocaleVersion.all_objects.create(
        organization_id=page.organization_id,
        site_id=page.site_id,
        page=page,
        translation=translation,
        locale=translation.locale,
        number=last + 1,
        source_version=source_version,
        structure_signature=body_structure_signature(_source_blocks(source_version)),
        units=dict(units),
        content_hash=canonical_json_hash({
            "source_version_id": str(source_version.id),
            "units": _texts(units),
        }),
        created_by_id=actor_id,
        created_by_credential=credential_id,
        origin=origin,
        origin_ref=origin_ref[:160],
        replaces=replaces,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )


def _advance(
    translation: PageTranslation,
    version: PageLocaleVersion,
    expected_body_version: int,
    *,
    accepted: bool = False,
) -> None:
    """`accepted`: the new version is still what a person stands behind — their
    own edit, restore or move of a version they accepted (ADR-071 pkt 17)."""
    updated = PageTranslation.all_objects.filter(
        pk=translation.id,
        organization_id=translation.organization_id,
        body_version=expected_body_version,
    ).update(
        body_current=version,
        body_version=expected_body_version + 1,
        updated_at=timezone.now(),
        **({"body_accepted": version} if accepted else {}),
    )
    if updated != 1:
        raise LocaleBodyVersionConflict
    translation.body_current = version
    translation.body_version = expected_body_version + 1
    if accepted:
        translation.body_accepted = version


def _version(page: Page, translation: PageTranslation, version_id: UUID) -> PageLocaleVersion:
    version = (
        PageLocaleVersion.all_objects.select_related("source_version")
        .filter(pk=version_id, organization_id=page.organization_id, translation_id=translation.id)
        .first()
    )
    if version is None:
        raise LocaleBodyVersionNotFound
    return version


OVERVIEW_MISSING = "missing"
OVERVIEW_PENDING = "pending"
OVERVIEW_OUTDATED = "outdated"
OVERVIEW_UNTRANSLATED = "untranslated"
OVERVIEW_COMPLETE = "complete"
OVERVIEW_PUBLISHED = "published"
OVERVIEW_DRAFT = "draft"
OVERVIEW_STATES = (
    OVERVIEW_MISSING,
    OVERVIEW_PENDING,
    OVERVIEW_OUTDATED,
    OVERVIEW_UNTRANSLATED,
    OVERVIEW_COMPLETE,
    OVERVIEW_PUBLISHED,
    OVERVIEW_DRAFT,
)
# `other`: what the remaining translation sources hold — the site's own texts
# (tagline, footer, blog and tag names), the company's cards, its booking
# catalogue.
OVERVIEW_KINDS = ("page", "entry", "other")


@dataclass(frozen=True, slots=True)
class OverviewCell:
    locale: str
    state: str
    untranslated: int | None = None
    metadata_complete: bool | None = None
    # Pages: the site's publication carries this language's own body.
    on_site: bool | None = None
    # Where visitors read this language's version now (pages on the site,
    # published articles); joined to the site's address by the caller.
    path: str | None = None
    # A result waiting here that this person can accept (the engine's queue).
    review: WaitingReview | None = None


@dataclass(frozen=True, slots=True)
class OverviewRow:
    kind: str
    id: UUID
    title: str
    cells: tuple[OverviewCell, ...]
    # What a translation order names: the page itself, the article's entry in
    # the site's own language (None when the article has none), or the
    # source's object.
    source_id: UUID | None = None
    # The translation source the row belongs to (`sites.page`, …).
    source_key: str = PAGE_SOURCE_KEY


def site_translation_overview(
    *,
    site_id: UUID,
    kind: str = "page",
    locale: str | None = None,
    state: str | None = None,
    cursor: UUID | None = None,
    limit: int = 50,
) -> tuple[list[OverviewRow], UUID | None, tuple[str, ...]]:
    """Every page (or every article) of a site against every other language.

    A page's cell is the first that holds of: no translation yet (`missing`),
    a translation waiting for review (`pending`), following an older source
    version (`outdated`), units still untranslated (`untranslated`),
    `complete` — and, apart from that, whether the site's publication carries
    the language's own body (`on_site`) and where (`path`). An article is a
    group of entries, one per language, each `published`, `draft` or
    `missing`. `other` lists what the remaining translation sources hold —
    the site's own texts, the company's cards, its booking catalogue — with
    the page's states read off their units. A cell with a result this person
    can accept in the engine's review queue names it (`review`). `state`
    keeps the rows with a cell in that state (in `locale`, when given).
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    site = Site.all_objects.filter(pk=site_id, organization_id=context.organization_id).first()
    if site is None:
        raise SiteNotFound
    locales = tuple(item for item in site_locales(site) if item != site.default_locale)
    shown = (locale,) if locale is not None else locales
    if kind == "entry":
        rows = _entry_rows(site, shown)
    elif kind == "other":
        rows = _other_rows(context, site, shown)
    else:
        snapshot = site.current_publication.snapshot if site.current_publication else {}
        rows = _page_rows(
            site,
            shown,
            published=_published_bodies(snapshot),
            waiting=registry.waiting_reviews(context),
        )
    if state is not None:
        rows = [row for row in rows if any(cell.state == state for cell in row.cells)]
    if cursor is not None and kind == "other":
        # These rows are not in id order: after the row the last answer ended on.
        after = next((index for index, row in enumerate(rows) if row.id == cursor), None)
        rows = rows[after + 1 :] if after is not None else []
    elif cursor is not None:
        rows = [row for row in rows if row.id > cursor]
    page = rows[: limit + 1]
    next_cursor = page[limit - 1].id if len(page) > limit else None
    return page[:limit], next_cursor, shown


def _published_bodies(snapshot: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """The (page, language) pairs a publication carries with their own body,
    each with the path it answers at."""
    return {
        (str(page.get("page_id")), str(entry.get("locale"))): str(entry.get("path") or "")
        for page in snapshot.get("pages", [])
        if isinstance(page, dict)
        for entry in page.get("locales", [])
        if isinstance(entry, dict) and "blocks" in entry and not entry.get("withheld")
    }


def _page_rows(
    site: Site,
    locales: tuple[str, ...],
    *,
    published: Mapping[tuple[str, str], str] | None = None,
    waiting: Mapping[tuple[str, UUID, str], WaitingReview] | None = None,
) -> list[OverviewRow]:
    pages = list(
        Page.all_objects.filter(
            organization_id=site.organization_id, site_id=site.id, deleted_at__isnull=True
        ).order_by("id")
    )
    translations = {
        (translation.page_id, translation.locale): translation
        for translation in PageTranslation.all_objects.select_related("body_current").filter(
            organization_id=site.organization_id, site_id=site.id, locale__in=locales
        )
    }
    sources = {page.current_draft_id for page in pages if page.current_draft_id}
    sources |= {
        translation.body_current.source_version_id
        for translation in translations.values()
        if translation.body_current is not None
    }
    blocks: dict[UUID, list[dict[str, Any]]] = {}
    for block in PageBlock.all_objects.filter(
        organization_id=site.organization_id, page_version_id__in=sources
    ).order_by("page_version_id", "position"):
        blocks.setdefault(block.page_version_id, []).append(stored_block_payload(block))
    rows: list[OverviewRow] = []
    for page in pages:
        cells = []
        for locale in locales:
            translation = translations.get((page.id, locale))
            on_site = None if published is None else (str(page.id), locale) in published
            path = (published or {}).get((str(page.id), locale)) or None
            if translation is None:
                cells.append(OverviewCell(locale, OVERVIEW_MISSING, on_site=on_site))
                continue
            version = translation.body_current
            source_id = version.source_version_id if version is not None else page.current_draft_id
            stored = version.units if version is not None else {}
            untranslated = sum(
                1
                for unit in extract_units(blocks.get(source_id, []) if source_id else [])
                if not _state(unit, stored.get(unit.key)).translated
            )
            if translation.body_pending_id is not None:
                cell_state = OVERVIEW_PENDING
            elif version is not None and source_id != page.current_draft_id:
                cell_state = OVERVIEW_OUTDATED
            elif untranslated:
                cell_state = OVERVIEW_UNTRANSLATED
            else:
                cell_state = OVERVIEW_COMPLETE
            cells.append(
                OverviewCell(
                    locale,
                    cell_state,
                    untranslated=untranslated,
                    metadata_complete=all((
                        translation.slug,
                        translation.title.strip(),
                        translation.description.strip(),
                    )),
                    on_site=on_site,
                    path=path,
                    # Only while the version still waits: one decided in the
                    # editor leaves nothing here to accept.
                    review=(waiting or {}).get((PAGE_SOURCE_KEY, page.id, locale))
                    if cell_state == OVERVIEW_PENDING
                    else None,
                )
            )
        rows.append(OverviewRow("page", page.id, page.name, tuple(cells), source_id=page.id))
    return rows


def page_language_states(site: Site, snapshot: Mapping[str, Any]) -> dict[tuple[UUID, str], str]:
    """Each page's version in another language: `published` when the site's
    publication carries its own body, otherwise the overview's cell."""
    locales = tuple(code for code in site_locales(site) if code != site.default_locale)
    published = _published_bodies(snapshot)
    return {
        (row.id, cell.locale): (
            OVERVIEW_PUBLISHED if (str(row.id), cell.locale) in published else cell.state
        )
        for row in _page_rows(site, locales)
        for cell in row.cells
    }


def _entry_rows(site: Site, locales: tuple[str, ...]) -> list[OverviewRow]:
    groups: dict[UUID, list[ContentEntry]] = {}
    for entry in (
        ContentEntry.all_objects.select_related("collection")
        .filter(organization_id=site.organization_id, site_id=site.id)
        .order_by("id")
    ):
        groups.setdefault(entry.translation_group, []).append(entry)

    def cell(locale: str, entry: ContentEntry | None) -> OverviewCell:
        if entry is None:
            return OverviewCell(locale, OVERVIEW_MISSING)
        if entry.state != ContentEntryState.PUBLISHED:
            return OverviewCell(locale, OVERVIEW_DRAFT)
        return OverviewCell(
            locale,
            OVERVIEW_PUBLISHED,
            path=entry_path(
                default_locale=site.default_locale,
                locale=locale,
                base_path=entry.collection.base_path,
                slug=entry.slug,
            ),
        )

    rows: list[OverviewRow] = []
    for group, entries in sorted(groups.items()):
        own = next((entry for entry in entries if entry.locale == site.default_locale), None)
        source = own or entries[0]
        by_locale = {entry.locale: entry for entry in entries}
        rows.append(
            OverviewRow(
                "entry",
                group,
                source.title,
                tuple(cell(locale, by_locale.get(locale)) for locale in locales),
                source_id=own.id if own else None,
                source_key=ENTRY_SOURCE_KEY,
            )
        )
    return rows


def _other_rows(context: ContentContext, site: Site, locales: tuple[str, ...]) -> list[OverviewRow]:
    """One row per object of every other translation source the company's
    type composes: this site's own texts first, then what belongs to the
    whole company (its cards, its booking catalogue). A source the person may
    not read, or whose plan is off, is left out."""
    modules = organization_modules(context.organization_id)
    scopes = {str(site.id), str(context.organization_id)}
    waiting = registry.waiting_reviews(context)
    rows: list[tuple[tuple[bool, int, str, str], OverviewRow]] = []
    for source in registry.translation_sources():
        if source.key in (PAGE_SOURCE_KEY, ENTRY_SOURCE_KEY) or source.module_id not in modules:
            continue
        try:
            refs = source.list_objects(context=context, cursor=None, limit=LIST_LIMIT).items
            for ref in refs:
                if ref.scope not in scopes:
                    continue
                cells = tuple(
                    cell
                    for locale in locales
                    if (cell := _source_cell(context, source, ref.object_id, locale, waiting))
                )
                if cells:
                    order = (ref.scope != str(site.id), ref.priority, ref.label, str(ref.object_id))
                    rows.append((
                        order,
                        OverviewRow(
                            "other",
                            ref.object_id,
                            ref.label,
                            cells,
                            source_id=ref.object_id,
                            source_key=source.key,
                        ),
                    ))
        except APIException:
            continue
    return [row for _order, row in sorted(rows, key=lambda item: item[0])]


def _source_cell(
    context: ContentContext,
    source: TranslationSource,
    object_id: UUID,
    locale: str,
    waiting: Mapping[tuple[str, UUID, str], WaitingReview],
) -> OverviewCell | None:
    """A source's object in one language, in the page's words: every text
    untranslated (`missing`), a result waiting for a person (`pending`), a
    text translated from an earlier wording (`outdated`), texts still to
    translate (`untranslated`), `complete`. None where the language is the
    object's own, or the object has nothing to translate."""
    read = source.read(context=context, object_id=object_id, locale=locale, basis="published")
    if read.excluded is not None:
        return None
    statuses = [unit_state(unit, read.targets.get(unit.key)).status for unit in read.units]
    # A slot to fill in and a text copied as it is are nobody's to translate.
    statuses = [status for status in statuses if status not in ("blocked", "copied")]
    if not statuses:
        return None
    missing = statuses.count("missing")
    review = waiting.get((source.key, object_id, locale))
    if review is not None:
        state = OVERVIEW_PENDING
    elif missing == len(statuses):
        state = OVERVIEW_MISSING
    elif "stale" in statuses:
        state = OVERVIEW_OUTDATED
    elif missing:
        state = OVERVIEW_UNTRANSLATED
    else:
        state = OVERVIEW_COMPLETE
    return OverviewCell(locale, state, untranslated=missing, review=review)
