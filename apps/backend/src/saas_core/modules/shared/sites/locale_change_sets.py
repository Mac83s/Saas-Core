"""A change set for a page in another language (ADR-070 pkt 17, plan TL13).

In the site's source language a change set writes the page's draft. Any other
language has no blocks of its own: its body is text units bound to one source
version, so the base a connector computes against is the language's own lock
(`PageTranslation.body_version`) and the blocks its working version assembles
into. A `block.replace` is accepted when the result is still the source body
with other text, and it is written as units through the language version —
never as blocks and never moving `Page.version`, so a German change leaves a
change set waiting for the Polish page valid.

Every applied change set moves `body_version` by one, a metadata-only one
too: the lock is the version of the (page, language) base, as `Page.version`
is in the source language.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.content_protocol.provenance import ORIGIN_INTEGRATION, Provenance, unit_hash
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext

from .language_versions import (
    LOCALE_BODY_SAVED,
    LocaleBody,
    LocaleUnitInvalid,
    _body,
    _create_version,
    _source_blocks,
    _texts,
)
from .localized_bodies import (
    LocaleUnitsInvalid,
    StructureDiffers,
    assemble,
    structure_signature,
    texts_against,
)
from .models import (
    Page,
    PageAutomationPolicy,
    PageLocaleVersion,
    PageTranslation,
    canonical_json_hash,
)
from .services import (
    PAGE_DRAFT_SAVED_EVENT,
    PageNotFound,
    SitesIdempotencyConflict,
    _idempotency_key,
    _is_automation,
    assert_page_writable,
    emit_draft_saved_event,
)

#: `PageLocaleVersion.origin` of a version a change set wrote.
ORIGIN_CHANGE_SET = "change_set"
#: `PageTranslation.pending_reason` while such a version waits for a person.
PENDING_CHANGE_SET = "change_set"
#: What a language version cannot take: its structure is its source's.
STRUCTURAL_COMMANDS = frozenset({"block.insert", "block.remove", "block.reorder"})
#: What a change set may do outside the source language.
LOCALE_COMMANDS = ("block.replace", "translation.update")


class LocaleStructureLocked(APIException):
    status_code = 422
    default_detail = (
        "Wersja językowa ma strukturę strony źródłowej: w tym języku można zmienić tylko tekst. "
        "Bloki, ich kolejność, zdjęcia i linki zmienia się w języku źródłowym."
    )
    default_code = "locale_structure_locked"


class LocaleVersionWaiting(APIException):
    status_code = 409
    default_detail = (
        "Ta wersja językowa ma tłumaczenie czekające na decyzję osoby; "
        "zmiana będzie możliwa po jego akceptacji albo odrzuceniu."
    )
    default_code = "locale_version_waiting"


@dataclass(frozen=True, slots=True)
class LocaleBase:
    """What a change set for one language of a page is computed against."""

    page: Page
    translation: PageTranslation
    body: LocaleBody
    # The working version as a visitor would get it.
    blocks: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class LocaleWrite:
    body_version: int
    version: PageLocaleVersion | None
    pending: bool


def read_locale_base(
    context: TenantContext, *, site_id: Any, page_id: Any, locale: str
) -> LocaleBase | None:
    """The language's base, or None where the page has no version in it yet —
    its address and title come first, and those are a person's."""
    page = (
        Page.all_objects.select_related("site__organization", "current_draft")
        .filter(
            pk=page_id,
            organization_id=context.organization_id,
            site_id=site_id,
            deleted_at__isnull=True,
        )
        .first()
    )
    if page is None:
        return None
    translation = (
        PageTranslation.all_objects.select_related("body_current__source_version", "body_pending")
        .filter(organization_id=context.organization_id, page_id=page.id, locale=locale)
        .first()
    )
    if translation is None:
        return None
    try:
        body = _body(page, translation)
    except PageNotFound:
        # A page nobody has saved yet has nothing to translate.
        return None
    return LocaleBase(page, translation, body, version_blocks(body.version, body))


def version_blocks(
    version: PageLocaleVersion | None, body: LocaleBody | None = None
) -> list[dict[str, Any]]:
    """The blocks a language version assembles into; with no version, the
    source of `body` standing in."""
    if version is not None:
        return assemble(_source_blocks(version.source_version), _texts(version.units)).blocks
    if body is None:
        return []
    return assemble(_source_blocks(body.source_version), {}).blocks


def assert_no_other_version_waits(base: LocaleBase) -> None:
    """A translation waiting for a person's decision is decided first: writing
    beside it would either be lost when it is accepted or take it away unseen.
    A change set's own waiting version is replaced by the next one."""
    waiting = base.translation.body_pending
    if waiting is not None and waiting.origin != ORIGIN_CHANGE_SET:
        raise LocaleVersionWaiting


def plan_locale_body(
    base: LocaleBase, blocks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The body the language version would have, and the units that change.

    `blocks` is the base with the change set's replacements. It is accepted
    when it is the language's source with other text; the answer is what the
    language version assembles into then — the same thing a visitor gets.
    """
    source = _source_blocks(base.body.source_version)
    units = {state.unit.key: state.unit for state in base.body.units}
    try:
        before = texts_against(source, base.blocks)
        after = texts_against(source, blocks)
    except StructureDiffers as error:
        raise LocaleStructureLocked from error
    if set(after) != set(units):
        # A text place appeared or went away: that is the block's shape.
        raise LocaleStructureLocked
    changed = {key: text for key, text in after.items() if text != before.get(key)}
    if any(units[key].copied for key in changed):
        # An address or a person's name is the same in every language.
        raise LocaleStructureLocked
    stored = _texts(base.body.version.units) if base.body.version is not None else {}
    try:
        assembled = assemble(source, {**stored, **changed}).blocks
    except LocaleUnitsInvalid as error:
        raise LocaleUnitInvalid(error) from error
    if structure_signature(assembled) != structure_signature(blocks):
        raise LocaleStructureLocked
    return assembled, changed


def write_locale_change_set(
    context: TenantContext,
    base: LocaleBase,
    *,
    base_version: int,
    blocks: list[dict[str, Any]],
    texts: Mapping[str, str],
    idempotency_key: str,
    document: dict[str, Any],
) -> LocaleWrite:
    """Writes the changed units as a new language version and moves the lock.

    On a `proposed` page an automation's version waits (`body_pending`) for a
    person; otherwise it becomes the working version. Refused with
    `change_set_stale` when the language moved since the plan was made.
    """
    from .change_sets import ChangeSetStale

    page, translation = base.page, base.translation
    # The source editor's lock is about the source's blocks (ADR-035 §4a); a
    # language version is guarded by its own lock, `body_version`.
    assert_page_writable(
        page,
        context,
        payload_bytes=len(json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))),
        editing_lock=False,
    )
    automation = _is_automation(context)
    pending = automation and page.automation_policy == PageAutomationPolicy.PROPOSED
    version: PageLocaleVersion | None = None
    if texts:
        key = _idempotency_key(idempotency_key)
        if PageLocaleVersion.all_objects.filter(
            organization_id=page.organization_id,
            translation_id=translation.id,
            created_by_id=context.actor_id,
            idempotency_key=key,
        ).exists():
            # A retry of the same intent is stale by now; the same key on
            # another base is a different intent under an old name.
            raise SitesIdempotencyConflict
        units = {state.unit.key: state.unit for state in base.body.units}
        at = timezone.now().isoformat()
        written = {
            unit_key: {
                "text": text,
                "provenance": Provenance(
                    origin=ORIGIN_INTEGRATION,
                    source_hash=units[unit_key].source_hash,
                    written_hash=unit_hash(units[unit_key].kind, text),
                    at=at,
                ).as_dict(),
            }
            for unit_key, text in texts.items()
        }
        current = dict(base.body.version.units) if base.body.version is not None else {}
        version = _create_version(
            page=page,
            translation=translation,
            source_version=base.body.source_version,
            units={**current, **written},
            actor_id=context.actor_id,
            credential_id=context.credential_id if automation else None,
            origin=ORIGIN_CHANGE_SET,
            origin_ref=str(document["idempotency_key"]),
            idempotency_key=key,
            request_hash=canonical_json_hash({"change_set": document}),
            replaces=translation.body_current,
        )
    changes: dict[str, Any] = {}
    if version is not None and pending:
        changes = {"body_pending": version, "pending_reason": PENDING_CHANGE_SET}
    elif version is not None:
        # An earlier change set's waiting version is superseded by this one.
        changes = {"body_current": version, "body_pending": None, "pending_reason": ""}
    updated = PageTranslation.all_objects.filter(
        pk=translation.id,
        organization_id=page.organization_id,
        body_version=base_version,
    ).update(**changes, body_version=base_version + 1, updated_at=timezone.now())
    if updated != 1:
        raise ChangeSetStale
    emit_draft_saved_event(
        context=context,
        event_type=PAGE_DRAFT_SAVED_EVENT,
        resource_type="site_page",
        resource_id=page.id,
        version=base_version + 1,
        locale=translation.locale,
        causation_id=f"sites-locale-draft:{page.id}:{translation.locale}:{base_version + 1}",
    )
    if version is not None:
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
                "source_version": base.body.source_version.number,
                "changed_units": len(texts),
                "origin": ORIGIN_CHANGE_SET,
                "pending": pending,
            },
        )
    return LocaleWrite(body_version=base_version + 1, version=version, pending=pending)


def proposal_translation(
    organization_id: UUID, *, page_id: UUID, locale: str, lock: bool = False
) -> PageTranslation | None:
    """The language version a page proposal is about; None for the site's
    source language, whose proposals are about the page's draft."""
    source = (
        Page.all_objects.filter(pk=page_id, organization_id=organization_id)
        .values_list("site__default_locale", flat=True)
        .first()
    )
    if source is None or locale == source:
        return None
    rows = PageTranslation.all_objects.select_related(
        "page__site__organization",
        "page__current_draft",
        "body_current__source_version",
        "body_pending",
    )
    if lock:
        rows = rows.select_for_update(of=("self",))
    translation = rows.filter(
        organization_id=organization_id, page_id=page_id, locale=locale
    ).first()
    if translation is None:
        raise PageNotFound
    return translation


def proposal_blocks(
    translation: PageTranslation, version_id: UUID | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """What a person compares: the language's body before the proposal and
    with it. A proposal that changed titles and descriptions only has the
    body as it is on both sides."""
    version = (
        PageLocaleVersion.all_objects.select_related("source_version", "replaces__source_version")
        .filter(
            pk=version_id,
            organization_id=translation.organization_id,
            translation_id=translation.id,
        )
        .first()
        if version_id is not None
        else None
    )
    if version is None:
        current = version_blocks(translation.body_current, _body(translation.page, translation))
        return current, current
    before = (
        version_blocks(version.replaces)
        if version.replaces is not None
        else assemble(_source_blocks(version.source_version), {}).blocks
    )
    return before, version_blocks(version)


def accept_proposed_version(
    translation: PageTranslation, version_id: UUID | None, key: str
) -> bool:
    """A person accepts the proposal's body, through the language version: a
    waiting version becomes the working one and goes out if it may
    (`accept_locale_version`). Says whether it was published. A version that
    is the working one already has nothing left to accept here."""
    from .language_decisions import accept_locale_version

    if version_id is None or translation.body_pending_id != version_id:
        return False
    decision = accept_locale_version(
        page_id=translation.page_id,
        locale=translation.locale,
        expected_body_version=translation.body_version,
        idempotency_key=key,
    )
    return decision.publication is not None


def discard_proposed_version(
    context: TenantContext, translation: PageTranslation, version_id: UUID | None, key: str
) -> int:
    """A person rejects the proposal's body, through the language version, and
    the answer is the language's lock afterwards. A waiting version is dropped;
    one that became the working version is followed by a new version with the
    text that was there before it — history is kept, as in the source language."""
    from .language_decisions import reject_locale_version
    from .language_versions import ORIGIN_RESTORE, _advance, restore_locale_body_version

    if version_id is None:
        return int(translation.body_version)
    if translation.body_pending_id == version_id:
        reject_locale_version(
            page_id=translation.page_id,
            locale=translation.locale,
            expected_body_version=translation.body_version,
            idempotency_key=key,
        )
    elif translation.body_current_id == version_id:
        version = PageLocaleVersion.all_objects.select_related("source_version").get(
            pk=version_id, organization_id=translation.organization_id
        )
        if version.replaces_id is not None:
            restore_locale_body_version(
                page_id=translation.page_id,
                locale=translation.locale,
                version_id=version.replaces_id,
                expected_body_version=translation.body_version,
                idempotency_key=key,
            )
        else:
            # The language had no text of its own before: a version with none.
            empty = _create_version(
                page=translation.page,
                translation=translation,
                source_version=version.source_version,
                units={},
                actor_id=context.actor_id,
                credential_id=None,
                origin=ORIGIN_RESTORE,
                origin_ref="0",
                idempotency_key=_idempotency_key(key),
                request_hash=canonical_json_hash({"discard": str(version.id)}),
            )
            _advance(translation, empty, translation.body_version)
    else:
        return int(translation.body_version)
    return int(translation.body_version) + 1
