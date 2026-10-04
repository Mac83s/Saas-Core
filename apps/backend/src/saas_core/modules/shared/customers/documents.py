"""The company's documents for its customers and the consent journal
(ADR-073 §9).

A document has a draft anybody with `customers.manage` writes, and versions
only a person approves, after a fresh second factor. A version and its texts
are append-only: a correction is a new text row and a change of substance is
the next version, so the text a customer agreed to never changes. Another
module reads the document in force through `current_document` and writes what
a person saw through `record_consent` — both in `customers.api`.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol import registry
from saas_core.content_protocol.provenance import ORIGIN_HUMAN, Provenance, unit_hash
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.step_up import require_step_up
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext, require_tenant_context
from saas_core.modules.core.organizations.locales import (
    assert_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required

from .models import (
    ConsentKind,
    ConsentRecord,
    Customer,
    CustomerDocument,
    DocumentKind,
    DocumentRoute,
    DocumentText,
    DocumentVersion,
)

CUSTOMERS_READ = "customers.read"
CUSTOMERS_MANAGE = "customers.manage"
#: What the person gate and the security log call the approval.
APPROVAL = "Dokument dla klientów"
STEP_UP_REASON = "customers.document.approve"
#: A protective bound, not a company's choice: a document is a few pages.
DOCUMENT_TEXT_MAX = 100_000
#: The translation memory's key for a document's text (`content_protocol`).
UNIT_KIND = "text"
#: The documents as a translation source (`translation_source.py`).
TRANSLATION_SOURCE = "customers.document"
#: In an accepted translation's provenance: the write that made the row.
ACCEPTED_WRITE = "write"

#: What a customer ticks to get the company's offers by e-mail (ADR-073 §9;
#: the owner's wording of 2026-10-04): one sentence for every form, with the
#: company's name in it. The journal keeps only its hash, so this is the one
#: place the words live — a form shows them and the panel's list of consents
#: reads them back through `marketing_wording`. A language without its own
#: sentence has none: a consent is never asked for in another language.
MARKETING_WORDING: dict[str, str] = {
    "pl": "Chcę otrzymywać oferty i promocje od {company} e-mailem.",
    "en": "I want to receive offers and promotions from {company} by e-mail.",
    "de": "Ich möchte Angebote und Aktionen von {company} per E-Mail erhalten.",
}
_PLATFORM_DEFAULT_LOCALE = "pl"


class DocumentVersionConflict(APIException):
    status_code = 409
    default_detail = "Dokument zmienił się w międzyczasie."
    default_code = "customers_document_version_conflict"


@dataclass(frozen=True, slots=True)
class DocumentInForce:
    """What a customer is shown and agrees to: one text row of the version in
    force, in exactly the language asked for."""

    document_id: UUID
    kind: str
    version: int
    effective_from: date
    text_id: UUID
    locale: str
    text: str
    text_hash: str
    #: Where anybody can read it, in that language.
    url: str


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def document_url(public_id: str, locale: str) -> str:
    """The document's public page on the platform, in a language: a guest
    page, so the default language has no prefix and every other content
    language stands under `/<code>` (the routing `notifications.public_url`
    follows for a booking's link)."""
    prefix = "" if locale == _PLATFORM_DEFAULT_LOCALE else f"/{locale}"
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{prefix}/documents/{public_id}"


def _organization(organization_id: UUID) -> Organization:
    return Organization.objects.get(pk=organization_id)


def _kind(kind: str) -> str:
    if kind not in DocumentKind.values:
        raise NotFound("Nie ma takiego dokumentu.")
    return kind


def _document(organization_id: UUID, kind: str, *, lock: bool = False) -> CustomerDocument | None:
    rows = CustomerDocument.all_objects.filter(organization_id=organization_id, kind=kind)
    if lock:
        rows = rows.select_for_update()
    return rows.first()


def _in_force(document: CustomerDocument, today: date) -> DocumentVersion | None:
    """The version customers get today: the latest one already in force."""
    return (
        DocumentVersion.all_objects.filter(
            organization_id=document.organization_id,
            document=document,
            effective_from__lte=today,
        )
        .order_by("-effective_from", "-number")
        .first()
    )


def _current_texts(version: DocumentVersion) -> dict[str, DocumentText]:
    """The version's text per language: the latest row of each."""
    texts: dict[str, DocumentText] = {}
    rows = DocumentText.all_objects.filter(
        organization_id=version.organization_id, version=version
    ).order_by("accepted_at", "id")
    for row in rows:
        texts[row.locale] = row
    return texts


def translated_version(document: CustomerDocument) -> DocumentVersion | None:
    """The version a machine translation is made for: the one that takes force
    last — the version in force, or the one approved for a later day, whose
    other languages are wanted before that day comes."""
    return (
        DocumentVersion.all_objects.filter(
            organization_id=document.organization_id, document=document
        )
        .order_by("-effective_from", "-number")
        .first()
    )


def _translation(document: CustomerDocument) -> dict[str, Any] | None:
    """What the panel needs to order a machine translation of the document and
    to say that one waits for a person (the engine's review queue, asked
    through the registry: nothing without the engine)."""
    version = translated_version(document)
    if version is None:
        return None
    waiting = registry.waiting_reviews(require_tenant_context())
    return {
        "object_id": document.id,
        "version": version.number,
        "waiting": sorted(
            locale
            for source_key, object_id, locale in waiting
            if source_key == TRANSLATION_SOURCE and object_id == document.id
        ),
    }


def _check_version(document: CustomerDocument | None, expected_version: int) -> None:
    if (document.version if document else 0) != expected_version:
        raise DocumentVersionConflict


def _checked_text(text: str, field: str = "text") -> str:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ValidationError({field: [ErrorDetail("Podaj treść dokumentu.", code="required")]})
    if len(text) > DOCUMENT_TEXT_MAX:
        raise ValidationError({
            field: [
                ErrorDetail(
                    f"Dokument może mieć najwyżej {DOCUMENT_TEXT_MAX} znaków.", code="max_length"
                )
            ]
        })
    return text


# --- what the panel reads -------------------------------------------------


def _names(user_ids: set[UUID]) -> dict[UUID, str]:
    return {
        user.id: f"{user.first_name} {user.last_name}".strip() or user.email
        for user in User.objects.filter(id__in=user_ids)
    }


def _version_payload(
    version: DocumentVersion, names: dict[UUID, str], *, with_texts: bool
) -> dict[str, Any]:
    texts = _current_texts(version)
    payload: dict[str, Any] = {
        "number": version.number,
        "source_locale": version.source_locale,
        "effective_from": version.effective_from,
        "approved_at": version.approved_at,
        "approved_by": names.get(version.approved_by, ""),
        "locales": sorted(texts),
    }
    if with_texts:
        source = texts.get(version.source_locale)
        payload["texts"] = [
            {
                "id": row.id,
                "locale": row.locale,
                "text": row.text,
                "text_hash": row.text_hash,
                "accepted_at": row.accepted_at,
                "accepted_by": names.get(row.accepted_by, ""),
                "stale": _stale(row, source),
            }
            for _locale, row in sorted(texts.items())
        ]
    return payload


def _stale(row: DocumentText, source: DocumentText | None) -> bool:
    """Whether a translation was accepted against another source text than
    the version's language reads now — the source was corrected since. A row
    that does not say what it was made from (the source itself, a text from
    before provenance) is never called stale."""
    made_from = (row.provenance or {}).get("source_hash")
    if source is None or row.locale == source.locale or not made_from:
        return False
    return bool(made_from != unit_hash(UNIT_KIND, source.text))


def _payload(
    organization: Organization,
    kind: str,
    document: CustomerDocument | None,
    *,
    with_texts: bool,
) -> dict[str, Any]:
    today = organization.local_today()
    versions = (
        list(
            DocumentVersion.all_objects.filter(
                organization_id=organization.id, document=document
            ).order_by("-number")
        )
        if document
        else []
    )
    in_force = _in_force(document, today) if document else None
    upcoming = next((row for row in versions if row.effective_from > today), None)
    names = _names(
        {row.approved_by for row in versions}
        | (
            set(
                DocumentText.all_objects.filter(
                    organization_id=organization.id, version__in=versions
                ).values_list("accepted_by", flat=True)
            )
            if with_texts
            else set()
        )
    )
    route = DocumentRoute.objects.filter(document_id=document.id).first() if document else None
    payload: dict[str, Any] = {
        "kind": kind,
        "version": document.version if document else 0,
        "draft": (
            {
                "text": document.draft_text,
                "locale": document.draft_locale,
                "origin_ref": document.draft_origin_ref,
            }
            if document and document.draft_text
            else None
        ),
        "in_force": (
            _version_payload(in_force, names, with_texts=with_texts) if in_force else None
        ),
        "upcoming": (
            _version_payload(upcoming, names, with_texts=with_texts) if upcoming else None
        ),
        "public_url": (
            document_url(route.public_id, in_force.source_locale) if route and in_force else None
        ),
    }
    if with_texts:
        payload["versions"] = [_version_payload(row, names, with_texts=False) for row in versions]
        payload["translation"] = _translation(document) if document else None
    return payload


def document_options(organization: Organization) -> dict[str, Any]:
    """What a caller may choose from: the kinds, the company's languages and
    the bound of a text."""
    locales = organization_content_locales(organization)
    return {
        "kinds": list(DocumentKind.values),
        "locales": list(locales),
        "default_locale": locales[0] if locales else str(settings.SITES_DEFAULT_LOCALE),
        "text_max": DOCUMENT_TEXT_MAX,
    }


def list_documents() -> dict[str, Any]:
    """Every kind of document, with or without anything written yet."""
    context = authorize(CUSTOMERS_READ)
    organization = _organization(context.organization_id)
    existing = {
        row.kind: row
        for row in CustomerDocument.all_objects.filter(organization_id=organization.id)
    }
    return {
        "documents": [
            _payload(organization, kind, existing.get(kind), with_texts=False)
            for kind in DocumentKind.values
        ],
        "options": document_options(organization),
    }


def read_document(kind: str) -> dict[str, Any]:
    context = authorize(CUSTOMERS_READ)
    organization = _organization(context.organization_id)
    return {
        "document": _payload(
            organization, _kind(kind), _document(organization.id, kind), with_texts=True
        ),
        "options": document_options(organization),
    }


# --- what the panel writes ------------------------------------------------


def _draft_input(text: str, locale: str, organization: Organization) -> tuple[str, str]:
    """The draft as it is stored — checked as a text in one of the company's
    languages — or two empty strings: an empty text clears the draft, and a
    draft that is gone has no language."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return "", ""
    text = _checked_text(text)
    assert_content_locale(locale, organization=organization)
    return text, locale


@dataclass(frozen=True, slots=True)
class DraftPlan:
    """What saving a draft would do, read and written nowhere."""

    #: Empty before the document's first write.
    document_id: str
    #: The lock the save will name (`expected_version`).
    version: int
    #: As it would be stored; empty removes the draft.
    text: str
    locale: str
    #: The length of the draft it replaces; 0 when there is none.
    replaces: int
    #: False when the draft is already exactly this: the save writes nothing.
    changes: bool
    #: The number of the version customers read today, if any.
    in_force: int | None


def plan_draft(kind: str, *, text: str, locale: str) -> DraftPlan:
    """The preview of `save_draft`: the same checks, the same refusals, and
    nothing written or locked — what a command shows before the click."""
    context = authorize(CUSTOMERS_MANAGE)
    organization = _organization(context.organization_id)
    document = _document(organization.id, _kind(kind))
    text, locale = _draft_input(text, locale, organization)
    in_force = _in_force(document, organization.local_today()) if document else None
    return DraftPlan(
        document_id=str(document.id) if document else "",
        version=document.version if document else 0,
        text=text,
        locale=locale,
        replaces=len(document.draft_text) if document else 0,
        changes=(document.draft_text, document.draft_locale) != (text, locale)
        if document
        else bool(text),
        in_force=in_force.number if in_force else None,
    )


@transaction.atomic
def save_draft(
    kind: str,
    *,
    text: str,
    locale: str,
    expected_version: int,
    origin_ref: str = "",
) -> dict[str, Any]:
    """Writes the draft, or clears it with an empty text. A draft binds
    nobody: customers keep reading the version in force."""
    context = authorize(CUSTOMERS_MANAGE)
    organization = _organization(context.organization_id)
    document = _document(organization.id, _kind(kind), lock=True)
    _check_version(document, expected_version)
    text, locale = _draft_input(text, locale, organization)
    if document is None:
        if not text:
            return _payload(organization, kind, None, with_texts=True)
        document = CustomerDocument.all_objects.create(organization=organization, kind=kind)
    if (document.draft_text, document.draft_locale) != (text, locale):
        document.draft_text = text
        document.draft_locale = locale
        document.draft_origin_ref = origin_ref if text else ""
        document.version += 1
        document.save(
            update_fields=[
                "draft_text",
                "draft_locale",
                "draft_origin_ref",
                "version",
                "updated_at",
            ]
        )
        record_audit(
            organization=organization,
            action="customers.document.draft_saved",
            actor=User.objects.filter(pk=context.actor_id).first(),
            target_type="customer_document",
            target_id=document.id,
            metadata={"kind": kind, "locale": document.draft_locale, "cleared": not text},
        )
    return _payload(organization, kind, document, with_texts=True)


def _approval_effect(
    organization: Organization,
    document: CustomerDocument,
    effective_from: date,
) -> dict[str, Any]:
    """What approving the draft does, said before it is done."""
    last = (
        DocumentVersion.all_objects.filter(organization_id=organization.id, document=document)
        .order_by("-number")
        .first()
    )
    others = [
        code for code in organization_content_locales(organization) if code != document.draft_locale
    ]
    latest = _latest_effective(document)
    return {
        "number": (last.number if last else 0) + 1,
        "effective_from": effective_from,
        # The day no new version may come before, when that is later than
        # today: a version already approved takes force then.
        "not_before": latest if latest and latest > organization.local_today() else None,
        "source_locale": document.draft_locale,
        # A new version starts with its own language only; customers who read
        # another one get no document until a person adds that text.
        "locales_without_text": others,
    }


def _latest_effective(document: CustomerDocument) -> date | None:
    """The latest day any approved version of the document takes force."""
    latest: date | None = (
        DocumentVersion.all_objects.filter(
            organization_id=document.organization_id, document=document
        )
        .order_by("-effective_from")
        .values_list("effective_from", flat=True)
        .first()
    )
    return latest


def _effective_from(
    organization: Organization, document: CustomerDocument, value: date | None
) -> date:
    """The day the new version takes force: the one asked for, else the
    earliest one possible. Never in the past, and never before a version
    already approved takes force — the later-dated one would silently take
    over from this one when its day came, though this one was approved last."""
    today = organization.local_today()
    latest = _latest_effective(document)
    if value is None:
        return max(today, latest) if latest else today
    if value < today:
        raise ValidationError({
            "effective_from": [
                ErrorDetail("Dokument nie może obowiązywać wstecz.", code="date_in_past")
            ]
        })
    if latest and value < latest:
        raise ValidationError({
            "effective_from": [
                ErrorDetail(
                    f"Ten dokument ma już wersję obowiązującą od {latest.isoformat()}. Nowa "
                    "wersja nie może wejść w życie wcześniej — wybierz ten dzień albo "
                    "późniejszy.",
                    code="before_latest_version",
                )
            ]
        })
    return value


@transaction.atomic
def approve_draft(
    kind: str,
    *,
    expected_version: int,
    effective_from: date | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    """Makes the draft the next version, in force from a date. Only a person,
    with a fresh second factor — never an automation (ADR-073 §9)."""
    context = authorize(CUSTOMERS_MANAGE)
    organization = _organization(context.organization_id)
    document = _document(organization.id, _kind(kind), lock=True)
    _check_version(document, expected_version)
    if document is None or not document.draft_text:
        raise ValidationError({
            "draft": [ErrorDetail("Nie ma szkicu do zatwierdzenia.", code="draft_missing")]
        })
    # The company may have switched the draft's language off since.
    assert_content_locale(document.draft_locale, organization=organization, field="draft")
    effect = _approval_effect(
        organization, document, _effective_from(organization, document, effective_from)
    )
    if preview:
        return {
            "effect": effect,
            "document": _payload(organization, kind, document, with_texts=True),
        }
    assert_person_required(context, APPROVAL)
    require_step_up(user_id=context.actor_id, reason=STEP_UP_REASON)
    now = timezone.now()
    version = DocumentVersion.all_objects.create(
        organization=organization,
        document=document,
        number=effect["number"],
        source_locale=document.draft_locale,
        effective_from=effect["effective_from"],
        approved_by=context.actor_id,
        approved_at=now,
    )
    DocumentText.all_objects.create(
        organization=organization,
        version=version,
        locale=document.draft_locale,
        text=document.draft_text,
        text_hash=text_hash(document.draft_text),
        accepted_by=context.actor_id,
        accepted_at=now,
    )
    DocumentRoute.objects.get_or_create(
        document_id=document.id,
        defaults={
            "public_id": secrets.token_urlsafe(16),
            "organization_id": organization.id,
        },
    )
    document.draft_text = ""
    document.draft_locale = ""
    document.draft_origin_ref = ""
    document.version += 1
    document.save(
        update_fields=["draft_text", "draft_locale", "draft_origin_ref", "version", "updated_at"]
    )
    record_audit(
        organization=organization,
        action="customers.document.approved",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="customer_document",
        target_id=document.id,
        metadata={
            "kind": kind,
            "number": version.number,
            "locale": version.source_locale,
            "effective_from": version.effective_from.isoformat(),
        },
    )
    _source_changed(context, document)
    return {"effect": effect, "document": _payload(organization, kind, document, with_texts=True)}


def _source_changed(context: TenantContext, document: CustomerDocument) -> None:
    """The text customers read in the document's own language changed — a new
    version, or a correction of one — in the transaction that changed it
    (docs/architecture/translation-sources.md §8)."""
    registry.notify_source_changed(
        context=context,
        source_key=TRANSLATION_SOURCE,
        object_ids=[document.id],
        change="changed",
        cause="user",
    )


@dataclass(frozen=True, slots=True)
class AcceptedTranslation:
    """A machine translation a person accepted in the translation review: what
    its row keeps beside the text."""

    #: Who wrote the text and against which source text.
    provenance: Provenance
    #: The acceptance that writes the row and the digest of what it carried: a
    #: repeat of it is answered with the row, never with a second one.
    write_key: str
    write_digest: str


@transaction.atomic
def add_text(
    kind: str,
    *,
    number: int,
    locale: str,
    text: str,
    expected_version: int,
    accepted: AcceptedTranslation | None = None,
) -> dict[str, Any]:
    """A version's text in another language, or a correction of one it has:
    always a new row, by a person with a fresh second factor — the same gate
    as the version itself. `accepted` is the document's translation source
    handing over a machine translation the person accepted: the same gate,
    and the row says a model wrote it."""
    context = authorize(CUSTOMERS_MANAGE)
    organization = _organization(context.organization_id)
    document = _document(organization.id, _kind(kind), lock=True)
    _check_version(document, expected_version)
    version = (
        DocumentVersion.all_objects.filter(
            organization_id=organization.id, document=document, number=number
        ).first()
        if document
        else None
    )
    if document is None or version is None:
        raise NotFound("Nie ma takiej wersji dokumentu.")
    assert_content_locale(locale, organization=organization)
    text = _checked_text(text)
    current = _current_texts(version)
    # An accepted translation with the words that already stand is still a new
    # row: it says the text was accepted against the source as it reads now.
    # So is a person's own confirmation of a text whose source was corrected
    # since: the words stay, the row says they were read against the new source.
    if (
        accepted is None
        and locale in current
        and current[locale].text == text
        and not _stale(current[locale], current.get(version.source_locale))
    ):
        raise ValidationError({
            "text": [ErrorDetail("Ten tekst już obowiązuje.", code="text_unchanged")]
        })
    assert_person_required(context, APPROVAL)
    require_step_up(user_id=context.actor_id, reason=STEP_UP_REASON)
    now = timezone.now()
    source = current.get(version.source_locale)
    provenance: dict[str, Any] = {}
    if accepted is not None:
        provenance = {
            **accepted.provenance.as_dict(),
            ACCEPTED_WRITE: [accepted.write_key, accepted.write_digest],
        }
    elif source is not None and locale != version.source_locale:
        provenance = Provenance(
            origin=ORIGIN_HUMAN,
            source_hash=unit_hash(UNIT_KIND, source.text),
            written_hash=unit_hash(UNIT_KIND, text),
            at=now.isoformat(),
        ).as_dict()
    row = DocumentText.all_objects.create(
        organization=organization,
        version=version,
        locale=locale,
        text=text,
        text_hash=text_hash(text),
        provenance=provenance,
        accepted_by=context.actor_id,
        accepted_at=now,
    )
    document.version += 1
    document.save(update_fields=["version", "updated_at"])
    record_audit(
        organization=organization,
        action="customers.document.text_added",
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="customer_document",
        target_id=document.id,
        metadata={
            "kind": kind,
            "number": version.number,
            "locale": locale,
            "text_id": str(row.id),
            "corrects": locale in current,
            # The same words, confirmed against a corrected source.
            "confirms": locale in current and current[locale].text == text,
            "origin": provenance.get("origin", ORIGIN_HUMAN),
        },
    )
    if locale == version.source_locale:
        _source_changed(context, document)
    return _payload(organization, kind, document, with_texts=True)


# --- what other modules read and write ------------------------------------


def current_document(kind: str, locale: str) -> DocumentInForce | None:
    """The company's document in force today, in exactly this language.

    None when no version is in force yet or the version has no text in
    `locale` — never another language instead: a consent to a text the person
    did not choose to read would not be one. The caller holds the company's
    tenant (a public form's context is enough); no permission is asked,
    because the answer is what the company published for everybody.
    """
    context = require_tenant_context()
    organization = _organization(context.organization_id)
    document = _document(organization.id, kind)
    if document is None:
        return None
    version = _in_force(document, organization.local_today())
    if version is None:
        return None
    row = (
        DocumentText.all_objects.filter(
            organization_id=organization.id, version=version, locale=locale
        )
        .order_by("-accepted_at", "-id")
        .first()
    )
    route = DocumentRoute.objects.filter(document_id=document.id).first()
    if row is None or route is None:
        return None
    return DocumentInForce(
        document_id=document.id,
        kind=kind,
        version=version.number,
        effective_from=version.effective_from,
        text_id=row.id,
        locale=locale,
        text=row.text,
        text_hash=row.text_hash,
        url=document_url(route.public_id, locale),
    )


def document_locales(kind: str) -> tuple[str, ...] | None:
    """The languages the company's document in force today has a text in, or
    None when it has none in force — what `current_document` does not tell
    apart: „no such document” from „no text in this language”. The caller
    holds the company's tenant, as for `current_document`."""
    context = require_tenant_context()
    organization = _organization(context.organization_id)
    document = _document(organization.id, kind)
    version = _in_force(document, organization.local_today()) if document else None
    if version is None:
        return None
    return tuple(sorted(_current_texts(version)))


def marketing_wording(locale: str, company: str) -> str:
    """The marketing consent as a customer of `company` reads it in `locale`
    (`MARKETING_WORDING`); empty when that language has no sentence. Pass the
    result to `record_consent(kind="marketing", wording=…)`: the journal keeps
    its hash (`text_hash`), which is how a line is matched to these words."""
    sentence = MARKETING_WORDING.get(locale)
    return sentence.format(company=company) if sentence else ""


def record_consent(
    *,
    source: str,
    source_reference: str,
    customer: Customer | None = None,
    text_id: UUID | None = None,
    kind: str = ConsentKind.DOCUMENT,
    wording: str = "",
    locale: str = "",
    granted: bool = True,
) -> ConsentRecord:
    """One line of the consent journal, inside the caller's transaction and
    tenant: this person — a customer, or whoever the source's record names —
    saw this text row of a document (`text_id`), or agreed to `wording` (a
    marketing consent, a consent field of a form). Nothing is ever changed:
    a withdrawal is the next line with `granted=False`."""
    context = require_tenant_context()
    row: DocumentText | None = None
    if kind == ConsentKind.DOCUMENT:
        row = (
            DocumentText.all_objects.filter(
                organization_id=context.organization_id, pk=text_id
            ).first()
            if text_id
            else None
        )
        if row is None:
            raise ValidationError({
                "text_id": [ErrorDetail("Nie ma takiego tekstu dokumentu.", code="text_unknown")]
            })
    return ConsentRecord.all_objects.create(
        organization_id=context.organization_id,
        customer=customer,
        kind=kind,
        document_text=row,
        text_hash=row.text_hash if row else (text_hash(wording) if wording else ""),
        locale=row.locale if row else locale,
        granted=granted,
        source=source,
        source_reference=source_reference,
    )


def consents_of(source: str, references: Sequence[str]) -> list[dict[str, Any]]:
    """The journal's lines written for these records of a source, oldest
    first: what was shown, in which language and when — for whoever reads the
    record itself (an order shows what its buyer accepted). No person is in
    them; the caller knows whose record it is and holds the tenant."""
    context = require_tenant_context()
    rows = (
        ConsentRecord.all_objects.filter(
            organization_id=context.organization_id,
            source=source,
            source_reference__in=list(references),
        )
        .select_related("document_text__version__document")
        .order_by("created_at", "id")
    )
    return [
        {
            "kind": row.kind,
            "document_kind": row.document_text.version.document.kind if row.document_text else None,
            "version": row.document_text.version.number if row.document_text else None,
            "locale": row.locale,
            "granted": row.granted,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def public_document(public_id: str, locale: str | None) -> dict[str, Any] | None:
    """What the document's public page shows: the version in force in the
    language asked for, or — on a page a person opened to read, where nothing
    is being agreed to — in the version's own language when that one is
    missing. The caller set the tenant the route names."""
    context = require_tenant_context()
    route = DocumentRoute.objects.filter(
        public_id=public_id, organization_id=context.organization_id
    ).first()
    if route is None:
        return None
    document = CustomerDocument.all_objects.filter(
        organization_id=context.organization_id, pk=route.document_id
    ).first()
    organization = _organization(context.organization_id)
    version = _in_force(document, organization.local_today()) if document else None
    if document is None or version is None:
        return None
    texts = _current_texts(version)
    row = texts.get(locale or "") or texts.get(version.source_locale)
    if row is None:
        return None
    return {
        "kind": document.kind,
        "organization_name": organization.name,
        "version": version.number,
        "effective_from": version.effective_from,
        "locale": row.locale,
        "locales": sorted(texts),
        "text": row.text,
        "text_hash": row.text_hash,
    }
