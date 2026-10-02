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
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.content_protocol.provenance import (
    ORIGIN_COPY,
    ORIGIN_HUMAN,
    ORIGIN_UNTRANSLATED,
    Provenance,
    unit_hash,
)
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.shared.billing.api import authorize_entitled

from .block_decoration import stored_block_payload
from .localized_bodies import LocaleUnitsInvalid, TextUnit, assemble, extract_units
from .localized_bodies import structure_signature as body_structure_signature
from .models import (
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
    SitesIdempotencyConflict,
    TranslationNotFound,
    _idempotency_key,
    _is_automation,
)

LOCALE_BODY_SAVED = "sites.page.locale_body_saved"
LOCALE_BODY_RESTORED = "sites.page.locale_body_restored"

ORIGIN_SAVE = "save"
ORIGIN_COPY_SOURCE = "copy"
ORIGIN_RESTORE = "restore"
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


class LocaleUnitInvalid(APIException):
    status_code = 422
    default_detail = "Część fragmentów nie pasuje do układu wersji źródłowej."
    default_code = "locale_unit_invalid"

    def __init__(self, error: LocaleUnitsInvalid) -> None:
        super().__init__({
            "message": self.default_detail,
            "errors": [
                {"field": f"units.{problem.key}", "code": problem.code}
                for problem in error.problems
            ],
        })


class LocaleBodyVersionNotFound(NotFound):
    default_detail = "Nie ma takiej wersji treści w tym języku."
    default_code = "locale_body_version_not_found"


@dataclass(frozen=True, slots=True)
class UnitState:
    unit: TextUnit
    # Stored text for this language; None where nothing was written yet.
    text: str | None
    origin: str | None

    @property
    def translated(self) -> bool:
        return self.unit.copied or (
            self.text is not None and self.origin not in UNTRANSLATED_ORIGINS
        )


@dataclass(frozen=True, slots=True)
class LocaleBody:
    page: Page
    translation: PageTranslation
    # The source version the language version follows; for a language with
    # no body yet, the page's current version.
    source_version: PageVersion
    version: PageLocaleVersion | None
    units: tuple[UnitState, ...]

    @property
    def untranslated(self) -> int:
        return sum(1 for state in self.units if not state.translated)

    @property
    def outdated(self) -> bool:
        """A newer source version exists than the one this language follows."""
        return self.page.current_draft_id != self.source_version.id


def site_locales(site: Site) -> tuple[str, ...]:
    """The languages a site's content may have.

    The deployment profile's languages today; the organization's own list,
    within the profile's, once organizations choose theirs (plan TL10).
    """
    return tuple(settings.SITES_SUPPORTED_LOCALES)


def get_locale_body(*, page_id: UUID, locale: str) -> LocaleBody:
    authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    page, translation = _target(page_id=page_id, locale=locale, lock=False)
    return _body(page, translation)


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
) -> MutationResult[LocaleBody]:
    """Writes the given units over the current ones, as a person's text.

    Units not named keep what they had. With `preview` nothing is saved: the
    answer is the body as it would be, with every problem a save would raise.
    """
    return _write(
        page_id=page_id,
        locale=locale,
        source_version_id=source_version_id,
        expected_body_version=expected_body_version,
        idempotency_key=idempotency_key,
        preview=preview,
        origin=ORIGIN_SAVE,
        changes=lambda body: _written(body, units, ORIGIN_HUMAN),
        request={"units": dict(sorted(units.items()))},
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
        changes=lambda body: _written(
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
    authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    page, translation = _target(page_id=page_id, locale=locale, lock=False)
    return list(
        PageLocaleVersion.all_objects.select_related("source_version", "created_by")
        .filter(organization_id=page.organization_id, translation_id=translation.id)
        .order_by("-number")
    )


def locale_body_version_blocks(
    *, page_id: UUID, locale: str, version_id: UUID
) -> tuple[PageLocaleVersion, list[dict[str, Any]]]:
    """A past version as a visitor would have got it, for a read-only preview."""
    authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    page, translation = _target(page_id=page_id, locale=locale, lock=False)
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
    page, translation = _target(page_id=page_id, locale=locale, lock=True)
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
    _advance(translation, version, expected_body_version)
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


def _person_context() -> Any:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        # TL13 lets SeoContentRank write a language version through a change
        # set, with its grant and its structure check; not through this door.
        raise PageAutomationForbidden
    return context


def _target(*, page_id: UUID, locale: str, lock: bool) -> tuple[Page, PageTranslation]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
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
        "body_current__source_version", "body_pending"
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


def _texts(units: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(entry["text"]) for key, entry in units.items() if isinstance(entry, dict)}


def _body(page: Page, translation: PageTranslation) -> LocaleBody:
    version = translation.body_current
    source = version.source_version if version is not None else page.current_draft
    if source is None:
        raise PageNotFound
    stored = version.units if version is not None else {}
    states = tuple(
        UnitState(
            unit=unit,
            text=str(stored[unit.key]["text"]) if unit.key in stored else None,
            origin=(
                str(stored[unit.key].get("provenance", {}).get("origin", ""))
                if unit.key in stored
                else None
            ),
        )
        for unit in extract_units(_source_blocks(source))
    )
    return LocaleBody(
        page=page, translation=translation, source_version=source, version=version, units=states
    )


def _written(body: LocaleBody, texts: Mapping[str, str], origin: str) -> dict[str, dict[str, Any]]:
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
    page, translation = _target(page_id=page_id, locale=locale, lock=not preview)
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
    written = changes(body)
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
        origin_ref="",
        idempotency_key=key,
        request_hash=request_hash,
    )
    _advance(translation, version, expected_body_version)
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


def _preview(body: LocaleBody, units: Mapping[str, Any]) -> LocaleBody:
    states = tuple(
        UnitState(
            unit=state.unit,
            text=str(units[state.unit.key]["text"]) if state.unit.key in units else None,
            origin=(
                str(units[state.unit.key]["provenance"]["origin"])
                if state.unit.key in units
                else None
            ),
        )
        for state in body.units
    )
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
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )


def _advance(
    translation: PageTranslation, version: PageLocaleVersion, expected_body_version: int
) -> None:
    updated = PageTranslation.all_objects.filter(
        pk=translation.id,
        organization_id=translation.organization_id,
        body_version=expected_body_version,
    ).update(
        body_current=version,
        body_version=expected_body_version + 1,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise LocaleBodyVersionConflict
    translation.body_current = version
    translation.body_version = expected_body_version + 1


def _version(page: Page, translation: PageTranslation, version_id: UUID) -> PageLocaleVersion:
    version = (
        PageLocaleVersion.all_objects.select_related("source_version")
        .filter(pk=version_id, organization_id=page.organization_id, translation_id=translation.id)
        .first()
    )
    if version is None:
        raise LocaleBodyVersionNotFound
    return version
