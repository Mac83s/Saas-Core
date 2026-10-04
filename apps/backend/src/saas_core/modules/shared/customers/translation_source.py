"""The company's documents for its customers as a translation source:
`customers.document` (ADR-073 §9 and „Rozstrzygnięcia plastra 4d-2”;
docs/architecture/translation-sources.md).

A document is a live record whose every object is a legal document. A text
row is public the moment it is written and binds whoever agrees to it, so a
machine's version never goes out by itself, whatever the company's
translation mode says: a job's write answers `pending / legal_document` and
writes nothing — the text waits in the engine's review queue — and a person's
acceptance is a write with the `acceptance` trigger that appends the row
through `documents.add_text`, behind the same person gate and the same fresh
second factor as a text typed by hand.

- **Objects** are the documents with an approved version; the source is the
  version that takes force last (`documents.translated_version`), in the
  language it was approved in.
- **One unit**, `text`: the whole text, as the row keeps its provenance. A
  new version starts without translations; a corrected source text makes
  them stale.
- **Targets** are that version's current row per language.
- **Scope** is the document: a language it has had a text in is live for it,
  so automation offers its next version in that language and never brings a
  new language in.
- **Nothing is kept for a job's write.** An accepted row remembers the write
  that made it (`provenance.write`), which answers a repeat; a job's writes
  put nothing out, so there is nothing for `revert` to take back.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import (
    REASON_GATE_FAILED,
    REASON_OVERWRITES_HUMAN,
    PublicationFacts,
    decide_publication,
)
from saas_core.content_protocol.provenance import Provenance
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
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
    OutcomeState,
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
from saas_core.content_protocol.tokens import PLACEHOLDER_PATTERN
from saas_core.content_protocol.units import DATA_PUBLIC, Target, Unit, unit_state
from saas_core.content_protocol.writes import GATE_UNKNOWN_UNIT, item_digest, write_gate
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required

from .documents import (
    ACCEPTED_WRITE,
    CUSTOMERS_MANAGE,
    CUSTOMERS_READ,
    DOCUMENT_TEXT_MAX,
    TRANSLATION_SOURCE,
    UNIT_KIND,
    AcceptedTranslation,
    _current_texts,
    add_text,
    translated_version,
)
from .models import CustomerDocument, DocumentKind, DocumentText, DocumentVersion

SOURCE_KEY = TRANSLATION_SOURCE
#: The document's one unit: its whole text.
UNIT_KEY = "text"
#: The target version of a language the version has no text in yet.
NO_TARGET = "0"
#: A person's decision on a translation (the same label as pages and cards).
REVIEW_GATE = "Decyzja o tłumaczeniu AI"


@contextmanager
def _tenant(context: ContentContext) -> Iterator[None]:
    """The engine passes the context explicitly; the tables force RLS."""
    if not isinstance(context, TenantContext):
        raise TypeError("A documents translation call needs a tenant context.")
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _document(context: ContentContext, object_id: UUID, *, lock: bool = False) -> CustomerDocument:
    rows = CustomerDocument.all_objects.filter(
        organization_id=context.organization_id, pk=object_id
    )
    document = (rows.select_for_update() if lock else rows).first()
    if document is None:
        raise NotFound("Nie ma takiego dokumentu.")
    return document


def _unit(source: DocumentText) -> Unit:
    return Unit(
        key=UNIT_KEY,
        kind=UNIT_KIND,
        text=source.text,
        data_class=DATA_PUBLIC,
        max_length=DOCUMENT_TEXT_MAX,
        # A document with a slot nobody filled in is not one to translate yet.
        placeholder=PLACEHOLDER_PATTERN.search(source.text) is not None,
    )


def _target(row: DocumentText | None) -> Target | None:
    if row is None:
        return None
    return Target(row.text, Provenance.from_dict(row.provenance) if row.provenance else None)


def _basis_version(version: DocumentVersion | None, source: DocumentText | None) -> str:
    """The version and the row of its own language: a correction of the source
    text is a new row, and what was translated from the old one no longer fits."""
    if version is None or source is None:
        return "none"
    return f"{version.number}:{source.id}"


def _target_version(row: DocumentText | None) -> str:
    return str(row.id) if row is not None else NO_TARGET


class _State:
    """The document's translated version as one read sees it."""

    def __init__(self, document: CustomerDocument) -> None:
        self.document = document
        self.version = translated_version(document)
        self.texts = _current_texts(self.version) if self.version else {}
        self.source = self.texts.get(self.version.source_locale) if self.version else None

    @property
    def basis_version(self) -> str:
        return _basis_version(self.version, self.source)

    def facts(self, context: ContentContext, locale: str) -> PublicationFacts:
        return PublicationFacts(
            legal_document=True,
            # The document has spoken this language, in this version or an earlier one.
            locale_live=DocumentText.all_objects.filter(
                organization_id=self.document.organization_id,
                version__document=self.document,
                locale=locale,
            ).exists(),
            actor_may_publish=context.has_permission(CUSTOMERS_MANAGE),
            target_public=locale in self.texts,
        )


class DocumentTranslationSource:
    key = SOURCE_KEY
    module_id = "shared.customers"
    labels: Mapping[str, str] = {"pl": "Dokumenty dla klientów", "en": "Customer documents"}
    staging: Staging = "live_record"
    bases = frozenset({"published"})
    write_targets = frozenset({"live"})
    translations_publish_separately = False
    #: The acceptance takes a fresh second factor, which only the panel asks
    #: for: the assistant's command says so before the person's click (§6.6).
    accepted_in_panel_only = True

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        with _tenant(context):
            # Ordering a translation needs only the right to read the documents:
            # its result waits for whoever may add a text to one.
            needed = CUSTOMERS_MANAGE if action in ("publish", "withdraw") else CUSTOMERS_READ
            if not context.has_permission(needed):
                raise PermissionDenied("Brak uprawnienia do dokumentów dla klientów.")
            found = CustomerDocument.all_objects.filter(
                organization_id=context.organization_id, pk__in=list(object_ids)
            ).count()
            if found != len(set(object_ids)):
                raise NotFound("Nie ma takiego dokumentu.")

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        with _tenant(context):
            rows = CustomerDocument.all_objects.filter(
                organization_id=context.organization_id, versions__isnull=False
            ).distinct()
            if changed_since is not None:
                rows = rows.filter(updated_at__gte=changed_since)
            order = list(DocumentKind.values)
            ordered = sorted(rows, key=lambda document: order.index(document.kind))
            start = int(cursor or 0)
            page = ordered[start : start + min(limit, LIST_LIMIT)]
            end = start + len(page)
            items = []
            for document in page:
                version = _State(document).basis_version
                items.append(
                    ObjectRef(
                        object_id=document.id,
                        label=str(DocumentKind(document.kind).label),
                        scope=document.kind,
                        priority=0,
                        # An approved version has its public page.
                        public=True,
                        published_version=version,
                        working_version=version,
                        changed_at=document.updated_at,
                    )
                )
            return ObjectPage(
                items=tuple(items), next_cursor=str(end) if end < len(ordered) else None
            )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        if basis not in self.bases:
            raise ValueError(f"Source {self.key} has no {basis!r} basis.")
        with _tenant(context):
            state = _State(_document(context, object_id))
            organization = Organization.objects.get(pk=context.organization_id)
            excluded = None
            if state.version is None or state.source is None:
                excluded = EXCLUDED_SOURCE_UNPUBLISHED
            elif locale == state.version.source_locale:
                excluded = EXCLUDED_LOCALE_IS_SOURCE
            elif locale not in organization_content_locales(organization):
                excluded = EXCLUDED_LOCALE_NOT_ENABLED
            row = None if excluded else state.texts.get(locale)
            target = _target(row)
            return SourceRead(
                object_id=state.document.id,
                locale=locale,
                basis="published",
                scope=state.document.kind,
                source_locale=state.version.source_locale if state.version else "",
                basis_version=state.basis_version,
                target_version=_target_version(row),
                units=(_unit(state.source),) if state.source and not excluded else (),
                targets={UNIT_KEY: target} if target else {},
                facts=state.facts(context, locale),
                excluded=excluded,
            )

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        if batch.source_key != self.key:
            raise ValueError("The batch is for another source.")
        self.authorize(
            context=context, action="translate", object_ids=[i.object_id for i in batch.items]
        )
        with _tenant(context):
            outcomes: list[WriteOutcome] = []
            for item in batch.items:
                outcomes.extend(self._write_item(context, batch, item))
            return tuple(outcomes)

    def _write_item(
        self, context: ContentContext, batch: WriteBatch, item: WriteItem
    ) -> tuple[WriteOutcome, ...]:
        document = _document(context, item.object_id, lock=True)
        keys = tuple(sorted(item.texts))

        def outcome(
            state: OutcomeState, chosen: Sequence[str], reason: str | None, **extra: Any
        ) -> WriteOutcome:
            return WriteOutcome(
                object_id=document.id,
                locale=item.locale,
                state=state,
                keys=tuple(sorted(chosen)),
                reason=reason,
                **extra,
            )

        # Only an acceptance writes, and the row it wrote remembers it: a
        # repeat is answered before the versions, which the write itself moved.
        digest = item_digest(item)
        if batch.trigger.kind == "acceptance":
            seen = DocumentText.all_objects.filter(
                organization_id=document.organization_id,
                version__document=document,
                locale=item.locale,
                **{f"provenance__{ACCEPTED_WRITE}__0": batch.idempotency_key},
            ).first()
            if seen is not None:
                if seen.provenance[ACCEPTED_WRITE][1] == digest:
                    return (outcome("live", keys, None, target_version=str(seen.id)),)
                return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        state = _State(document)
        if state.version is None or state.source is None:
            return (outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),)
        if item.basis_version != state.basis_version:
            return (outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),)
        # A read leaves the version's own language out; a write that names it
        # anyway would put a machine's text where the approved one stands.
        if item.locale == state.version.source_locale:
            return (outcome("refused", keys, EXCLUDED_LOCALE_IS_SOURCE),)
        row = state.texts.get(item.locale)
        if (item.target_version or NO_TARGET) != _target_version(row):
            return (outcome("conflict", keys, CONFLICT_TARGET_CHANGED),)
        decision = decide_publication(
            policy=registry.translation_policy(organization_id=context.organization_id),
            requested=item.requested,
            requested_reason=item.reason,
            trigger=batch.trigger,
            facts=state.facts(context, item.locale),
        )
        if decision.outcome == "refused":
            return (outcome("refused", keys, decision.reason),)
        unit = _unit(state.source)
        terms = self.protected_terms(context=context, object_id=document.id)
        protected = unit_state(unit, _target(row)).protected
        written: dict[str, tuple[str, Provenance]] = {}
        proposals: list[str] = []
        errors: list[FieldError] = []
        for key, (text, provenance) in item.texts.items():
            if key != UNIT_KEY:
                errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
                continue
            error = write_gate(unit, text, terms)
            if error is not None:
                errors.append(error)
            elif batch.protected != "overwrite" and protected:
                proposals.append(key)
            else:
                written[key] = (text, provenance)
        results: list[WriteOutcome] = []
        if written:
            target_version = _target_version(row)
            # `live` is a person's acceptance alone: every other trigger was
            # answered `pending` above (a legal document, in every mode), and
            # `add_text` asks for the person and the second factor itself.
            if decision.outcome == "live":
                text, provenance = written[UNIT_KEY]
                add_text(
                    document.kind,
                    number=state.version.number,
                    locale=item.locale,
                    text=text,
                    expected_version=document.version,
                    accepted=AcceptedTranslation(
                        provenance=provenance,
                        write_key=batch.idempotency_key,
                        write_digest=digest,
                    ),
                )
                target_version = _target_version(_current_texts(state.version).get(item.locale))
            results.append(
                outcome(
                    decision.outcome, list(written), decision.reason, target_version=target_version
                )
            )
        if proposals:
            results.append(outcome("pending", proposals, REASON_OVERWRITES_HUMAN))
        if errors:
            results.append(
                outcome(
                    "pending",
                    [error.field.removeprefix("units.") for error in errors],
                    REASON_GATE_FAILED,
                    errors=tuple(errors),
                )
            )
        return tuple(results)

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        return None  # A text row is public the moment it is written.

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        with _tenant(context):
            state = _State(_document(context, object_id))
            missing = state.source is None or unit_state(
                _unit(state.source), _target(state.texts.get(locale))
            ).status in ("missing", "blocked")
            return Completeness(
                complete=not missing,
                publishable=not missing,
                untranslated=(UNIT_KEY,) if missing else (),
                reasons=("untranslated_units",) if missing else (),
            )

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]:
        """The company's name, kept as written: it is who the document binds."""
        name = (
            Organization.objects.filter(pk=context.organization_id)
            .values_list("name", flat=True)
            .first()
            or ""
        ).strip()
        return (ProtectedTerm(text=name, rule="keep"),) if name else ()

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision. Accepting is the engine's write with the
        `acceptance` trigger; nothing waits here to discard, and a text row is
        never taken back — the next version or a correction replaces it."""
        with _tenant(context):
            assert_person_required(context, REVIEW_GATE)  # type: ignore[arg-type]
        self.authorize(context=context, action="publish", object_ids=[i.object_id for i in items])
        return ()

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """A job puts nothing out here, and a person's acceptance is not a
        job's write to take back (§6.6)."""
        return ()


DOCUMENT_SOURCE = DocumentTranslationSource()


def register_document_source() -> None:
    registry.register_translation_source(DOCUMENT_SOURCE)
