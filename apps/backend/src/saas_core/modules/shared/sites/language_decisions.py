"""A person's decisions about a language version (ADR-070 pkt 12).

Accept a version waiting for review, reject it, publish the current one, take
a public one off the site, accept several at once. Each decision that changes
the site is a derived publication: the published snapshot with exactly that
language entry changed, its page's hreflang and the live languages — never
`publish_site`, so nobody's drafts, menu or appearance go out with it. The
version is checked against the source version the snapshot publishes; one bound
to a newer, unpublished draft waits for the person's own publication of that
draft (`source_unpublished`).

Every one of these is a person's decision (`assert_person_required`); an
automatic job publishes its results under ADR-069, not through these doors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.shared.billing.api import authorize_entitled

from .block_decoration import stored_block_payload
from .derived_publication import publish_derived
from .language_publication import (
    LOCALE_HOME_MISSING,
    fresh_entry,
    snapshot_home,
    with_language_entry,
    withdrawn_entry,
)
from .language_versions import LocaleBodyVersionConflict, _target
from .models import (
    Page,
    PageBlock,
    PageTranslation,
    PageVersion,
    Publication,
    PublicationReason,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import (
    PageNotFound,
    SitePublicationNotReady,
    _idempotency_key,
    assert_person_required,
)

LOCALE_ACCEPTED = "sites.page.locale_accepted"
LOCALE_REJECTED = "sites.page.locale_rejected"
LOCALE_PUBLISHED = "sites.page.locale_published"
LOCALE_WITHDRAWN = "sites.page.locale_withdrawn"

PERSON_GATE = "Publikacja wersji językowej"


class NothingPending(APIException):
    status_code = 409
    default_detail = "Ta wersja językowa nie ma treści czekającej na akceptację."
    default_code = "locale_nothing_pending"


class LocaleNotPublic(APIException):
    status_code = 409
    default_detail = "Tej wersji językowej nie ma na stronie publicznej."
    default_code = "locale_not_public"


class LocaleBatchStale(APIException):
    status_code = 409
    default_detail = "Lista do akceptacji zmieniła się od podglądu; pobierz go jeszcze raz."
    default_code = "locale_batch_stale"


@dataclass(frozen=True, slots=True)
class LanguageDecision:
    page: Page
    translation: PageTranslation
    publication: Publication | None
    # Why the version did not go out, when it did not.
    skipped: str | None = None


def accept_locale_version(
    *, page_id: UUID, locale: str, expected_body_version: int, idempotency_key: str
) -> LanguageDecision:
    """Makes the waiting version current and publishes it, if it may go out."""
    return accept_locale_versions(
        items=[(page_id, locale, expected_body_version)],
        digest=None,
        idempotency_key=idempotency_key,
    )[0]


@transaction.atomic
def accept_locale_versions(
    *,
    items: list[tuple[UUID, str, int]],
    digest: str | None,
    idempotency_key: str,
    preview: bool = False,
    site_id: UUID | None = None,
) -> list[LanguageDecision]:
    """Accepts several waiting versions of one site in one derived publication.

    With `preview` nothing changes and the answer says what would go out; its
    digest (`batch_digest`) must come back with the real call when there is
    more than one item, so a person approves exactly the list they saw.
    """
    context = _person(SITE_PUBLISH)
    targets = [
        _target(context, page_id=page_id, locale=locale, lock=not preview)
        for page_id, locale, _expected in items
    ]
    site_id = site_id or targets[0][0].site_id
    if any(page.site_id != site_id for page, _translation in targets):
        raise PageNotFound
    for (_page, translation), (_page_id, _locale, expected) in zip(targets, items, strict=True):
        if translation.body_pending_id is None:
            raise NothingPending
        if translation.body_version != expected:
            raise LocaleBodyVersionConflict
    if not preview and len(items) > 1 and digest != batch_digest(targets):
        raise LocaleBatchStale
    key = _idempotency_key(idempotency_key) if not preview else ""
    site = targets[0][0].site
    snapshot = _current_snapshot(site)
    # The home page first: a language opens with it (ADR-070 pkt 7).
    home = (snapshot_home(snapshot) or {}).get("page_id")
    targets.sort(key=lambda target: str(target[0].id) != home)
    decisions: list[LanguageDecision] = []
    for page, translation in targets:
        entry, skipped = _entry_for(site, page, translation, snapshot, translation.body_pending)
        if entry is not None:
            snapshot = with_language_entry(
                snapshot, page_id=str(page.id), locale=translation.locale, entry=entry
            )
        decisions.append(LanguageDecision(page, translation, None, skipped))
    if preview:
        return decisions
    publication = None
    if any(decision.skipped is None for decision in decisions):
        publication = _publish(
            context, site, snapshot, key, PublicationReason.LOCALE_ACCEPT, f"accept:{key}"
        )
    now = timezone.now()
    for page, translation in targets:
        PageTranslation.all_objects.filter(pk=translation.id).update(
            body_current=translation.body_pending_id,
            body_pending=None,
            pending_reason="",
            withdrawn_at=None,
            body_version=translation.body_version + 1,
            updated_at=now,
        )
        if publication is not None and any(
            decision.translation.id == translation.id and decision.skipped is None
            for decision in decisions
        ):
            _lock_slug(translation)
        _audit(context, LOCALE_ACCEPTED, page, translation, publication)
    return [
        LanguageDecision(decision.page, decision.translation, publication, decision.skipped)
        for decision in decisions
    ]


def batch_digest(targets: list[tuple[Page, PageTranslation]]) -> str:
    return canonical_json_hash(
        sorted(
            [str(translation.id), str(translation.body_pending_id)]
            for _page, translation in targets
        )
    )


@transaction.atomic
def reject_locale_version(
    *, page_id: UUID, locale: str, expected_body_version: int, idempotency_key: str
) -> LanguageDecision:
    """Drops the waiting version; the current one stays as it was."""
    context = _person(SITE_CONTENT_EDIT, "Odrzucenie wersji językowej")
    _idempotency_key(idempotency_key)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=True)
    if translation.body_pending_id is None:
        raise NothingPending
    if translation.body_version != expected_body_version:
        raise LocaleBodyVersionConflict
    PageTranslation.all_objects.filter(pk=translation.id).update(
        body_pending=None,
        pending_reason="",
        body_version=translation.body_version + 1,
        updated_at=timezone.now(),
    )
    _audit(context, LOCALE_REJECTED, page, translation, None)
    return LanguageDecision(page, translation, None)


@transaction.atomic
def publish_locale_version(
    *, page_id: UUID, locale: str, idempotency_key: str, preview: bool = False
) -> LanguageDecision:
    """Publishes this language version's current body, if it may go out."""
    context = _person(SITE_PUBLISH)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=not preview)
    site = page.site
    snapshot = _current_snapshot(site)
    entry, skipped = _entry_for(site, page, translation, snapshot, translation.body_current)
    if preview or entry is None:
        return LanguageDecision(page, translation, None, skipped)
    key = _idempotency_key(idempotency_key)
    publication = _publish(
        context,
        site,
        with_language_entry(snapshot, page_id=str(page.id), locale=translation.locale, entry=entry),
        key,
        PublicationReason.LOCALE_PUBLISH,
        f"publish:{key}",
    )
    PageTranslation.all_objects.filter(pk=translation.id).update(
        withdrawn_at=None, updated_at=timezone.now()
    )
    _lock_slug(translation)
    _audit(context, LOCALE_PUBLISHED, page, translation, publication)
    return LanguageDecision(page, translation, publication)


@transaction.atomic
def withdraw_locale_version(
    *, page_id: UUID, locale: str, idempotency_key: str, preview: bool = False
) -> LanguageDecision:
    """Takes a public language version off the site; its address answers 308
    to the page in the source language until it is published again."""
    context = _person(SITE_PUBLISH)
    page, translation = _target(context, page_id=page_id, locale=locale, lock=not preview)
    site = page.site
    snapshot = _current_snapshot(site)
    current = _snapshot_entry(snapshot, page.id, translation.locale)
    if current is None or "blocks" not in current:
        raise LocaleNotPublic
    if preview:
        return LanguageDecision(page, translation, None)
    key = _idempotency_key(idempotency_key)
    publication = _publish(
        context,
        site,
        with_language_entry(
            snapshot,
            page_id=str(page.id),
            locale=translation.locale,
            entry=withdrawn_entry(site, translation),
        ),
        key,
        PublicationReason.LOCALE_WITHDRAW,
        f"withdraw:{key}",
    )
    PageTranslation.all_objects.filter(pk=translation.id).update(
        withdrawn_at=timezone.now(), updated_at=timezone.now()
    )
    _audit(context, LOCALE_WITHDRAWN, page, translation, publication)
    return LanguageDecision(page, translation, publication)


def _person(permission: str, gate: str = PERSON_GATE) -> Any:
    context = authorize_entitled(permission, SITES_ENABLED)
    assert_person_required(context, gate)
    return context


def _current_snapshot(site: Any) -> dict[str, Any]:
    if site.current_publication is None:
        # Nothing is public yet: the first publication is the person's
        # publication of the whole site.
        raise SitePublicationNotReady
    return dict(site.current_publication.snapshot)


def _snapshot_entry(snapshot: dict[str, Any], page_id: UUID, locale: str) -> dict[str, Any] | None:
    for page in snapshot.get("pages", []):
        if isinstance(page, dict) and page.get("page_id") == str(page_id):
            return next(
                (item for item in page.get("locales", []) if item.get("locale") == locale),
                None,
            )
    return None


def _entry_for(
    site: Any,
    page: Page,
    translation: PageTranslation,
    snapshot: dict[str, Any],
    body: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """The entry `body` would publish against the source the snapshot
    publishes, or why it would not."""
    published = next(
        (
            item
            for item in snapshot.get("pages", [])
            if isinstance(item, dict) and item.get("page_id") == str(page.id)
        ),
        None,
    )
    if published is None or body is None:
        return None, "source_unpublished" if published is None else "untranslated_units"
    source = PageVersion.all_objects.get(
        pk=published["version_id"], organization_id=page.organization_id
    )
    home = snapshot_home(snapshot)
    live = snapshot.get("live_locales") or [snapshot.get("default_locale")]
    if home is not None and home.get("page_id") != str(page.id) and translation.locale not in live:
        return None, LOCALE_HOME_MISSING
    candidate = _with_body(translation, body)
    blocks = [
        stored_block_payload(block)
        for block in PageBlock.all_objects.filter(
            organization_id=page.organization_id, page_version_id=source.id
        ).order_by("position")
    ]
    return fresh_entry(site, candidate, source, blocks)


def _with_body(translation: PageTranslation, body: Any) -> PageTranslation:
    """The translation as it would be with `body` current, unsaved."""
    copy = PageTranslation(**{
        field.attname: getattr(translation, field.attname) for field in PageTranslation._meta.fields
    })
    copy.body_current = body
    return copy


def _publish(
    context: Any, site: Any, snapshot: dict[str, Any], key: str, reason: str, scope: str
) -> Publication:
    actor = User.objects.get(pk=context.actor_id)
    existing = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        created_by=actor,
        idempotency_key=f"locale-{scope}"[:120],
    ).first()
    if existing is not None:
        return existing
    return publish_derived(
        context=context,
        site=site,
        snapshot=snapshot,
        actor=actor,
        idempotency_key=f"locale-{scope}"[:120],
        reason=reason,
        snapshot_schema_version=2,
    )


def _lock_slug(translation: PageTranslation) -> None:
    if translation.slug_locked_at is None:
        PageTranslation.all_objects.filter(pk=translation.id, slug_locked_at__isnull=True).update(
            slug_locked_at=timezone.now()
        )


def _audit(
    context: Any,
    action: str,
    page: Page,
    translation: PageTranslation,
    publication: Publication | None,
) -> None:
    record_audit(
        organization=page.site.organization,
        action=action,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page_translation",
        target_id=translation.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "locale": translation.locale,
            **({"publication_id": str(publication.id)} if publication is not None else {}),
        },
    )
