"""`customers.document` keeps the translation source contract (ADR-073 §9 and
„Rozstrzygnięcia plastra 4d-2”; `docs/architecture/translation-sources.md`
§11), plus what only a document does: a machine's text goes out on nothing but
a person's acceptance with a fresh second factor, the accepted row says a
model wrote it, a new version starts without translations, and the panel
learns which version is translated and what waits. Needs no translation
engine (the contract plays it); the product profiles compose customers
without it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import Trigger
from saas_core.content_protocol.registry import WaitingReview
from saas_core.content_protocol.sources import (
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    EXCLUDED_SOURCE_UNPUBLISHED,
    ContentContext,
    WriteBatch,
    WriteItem,
)
from saas_core.content_protocol.units import sendable_units, unit_state
from saas_core.modules.core.identity.models import UserMfaMethod
from saas_core.modules.core.identity.step_up import (
    StepUpMfaSetupRequired,
    StepUpRequired,
    activate_step_up,
)
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.customers.api import current_document
from saas_core.modules.shared.customers.documents import (
    CUSTOMERS_MANAGE,
    add_text,
    approve_draft,
    read_document,
    save_draft,
    translated_version,
)
from saas_core.modules.shared.customers.models import (
    CustomerDocument,
    DocumentKind,
    DocumentText,
)
from saas_core.modules.shared.customers.security import public_documents_context
from saas_core.modules.shared.customers.translation_source import (
    DOCUMENT_SOURCE,
    SOURCE_KEY,
    UNIT_KEY,
)
from saas_core.testing.translation_sources import (
    AUTOMATIC,
    TranslationSourceContract,
    UnitSpec,
    ai_provenance,
    captured_source_changes,
    translation_policy_override,
)
from test_customers_documents import company, stepped_up, with_second_factor

pytestmark = pytest.mark.django_db

LOCALE = "en"


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


class DocumentsDriver:
    """The scenario's object is one of the company's documents and its one
    unit the document's whole text: `create` writes the draft, `publish`
    approves it, `edit` corrects the approved version's own text."""

    source = DOCUMENT_SOURCE
    capabilities = frozenset({"legal", "legal_only", "single_unit", "persons_only"})

    def __init__(self) -> None:
        owner = with_second_factor(company(f"document-source-{uuid4().hex[:10]}"))
        self.membership = owner
        self.organization = owner.organization
        self.publisher = context_from_membership(owner)
        # May read the documents and order a translation; adds no text.
        self.editor = replace(
            self.publisher, permissions=self.publisher.permissions - {CUSTOMERS_MANAGE}
        )
        self._kinds = iter(DocumentKind.values)

    def acting(self, context: ContentContext) -> TenantContext:
        assert isinstance(context, TenantContext)
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid4()}")

    def document(self, object_id: UUID) -> CustomerDocument:
        return CustomerDocument.all_objects.get(organization=self.organization, pk=object_id)

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        [unit] = units
        kind = next(self._kinds)
        with _as(self.publisher):
            save_draft(
                kind,
                text=unit.text if isinstance(unit, UnitSpec) else unit,
                locale="pl",
                expected_version=0,
            )
        return CustomerDocument.all_objects.get(organization=self.organization, kind=kind).id

    def publish(self, object_id: UUID) -> None:
        """Approves the draft; after a correction there is none, and the
        corrected text is public already."""
        with _as(self.publisher):
            document = self.document(object_id)
            if document.draft_text:
                approve_draft(document.kind, expected_version=document.version)

    def _add(self, object_id: UUID, locale: str | None, text: str) -> None:
        with _as(self.publisher):
            document = self.document(object_id)
            version = translated_version(document)
            assert version is not None
            add_text(
                document.kind,
                number=version.number,
                locale=locale or version.source_locale,
                text=text,
                expected_version=document.version,
            )

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        self._add(object_id, None, text)

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        self._add(object_id, locale, text)

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        raise NotImplementedError("A document is one unit.")

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        raise NotImplementedError("A document is one unit.")

    def delete(self, object_id: UUID, index: int) -> None:
        raise NotImplementedError("A document is one unit.")

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        raise NotImplementedError("Only a person adds a document's text.")

    def copy_source(self, object_id: UUID, locale: str) -> None:
        raise NotImplementedError("Only a person adds a document's text.")

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        """What a customer is given to read and agree to in exactly this
        language — the reader the booking form uses."""
        kind = self.document(object_id).kind
        with public_documents_context(self.organization.id):
            found = current_document(kind, locale)
        return [found.text] if found else None


@pytest.fixture
def driver() -> Iterator[DocumentsDriver]:
    # The acceptance the contract plays is the publisher's, with the fresh
    # second factor every text of a document asks for.
    with stepped_up():
        yield DocumentsDriver()


class TestCustomersDocumentSource(TranslationSourceContract):
    source_key = "customers.document"
    locale = LOCALE


# -- what only a document does ---------------------------------------------------


def _read(driver: DocumentsDriver, object_id: UUID, locale: str = LOCALE):  # type: ignore[no-untyped-def]
    return DOCUMENT_SOURCE.read(
        context=driver.publisher, object_id=object_id, locale=locale, basis="published"
    )


def _batch(
    driver: DocumentsDriver, object_id: UUID, text: str, *, trigger: str, key: str | None = None
) -> WriteBatch:
    read = _read(driver, object_id)
    return WriteBatch(
        source_key=SOURCE_KEY,
        scope=read.scope,
        trigger=Trigger(kind=trigger, job_ref=None, cause="user"),
        protected="propose",
        items=(
            WriteItem(
                object_id=object_id,
                locale=LOCALE,
                basis="published",
                basis_version=read.basis_version,
                target_version=read.target_version,
                texts={UNIT_KEY: (text, ai_provenance(read.units[0], text))},
                requested="live",
            ),
        ),
        idempotency_key=key or f"review:accept:{uuid4()}",
    )


def _approved(driver: DocumentsDriver, text: str = "Regulamin wizyt.") -> UUID:
    object_id = driver.create([text])
    driver.publish(object_id)
    return object_id


def test_an_acceptance_needs_the_person_the_right_and_a_fresh_second_factor(
    driver: DocumentsDriver,
) -> None:
    object_id = _approved(driver)
    accept = _batch(driver, object_id, "Visit terms.", trigger="acceptance")

    with translation_policy_override(AUTOMATIC):
        # No second factor in this run: the same refusal as a text typed by hand.
        with activate_step_up(None), pytest.raises(StepUpRequired):
            DOCUMENT_SOURCE.write(context=driver.publisher, batch=accept)
        # Whoever only reads the documents may order the translation, never accept it.
        with pytest.raises(OrganizationPermissionDenied):
            DOCUMENT_SOURCE.write(context=driver.editor, batch=accept)
        # The assistant holds no consent that opens a document (ADR-076 §6).
        assistant = acting_context(driver.publisher, via="assistant", ref=f"conversation:{uuid4()}")
        with pytest.raises(PersonRequired):
            DOCUMENT_SOURCE.write(context=assistant, batch=accept)
        assert driver.public_texts(object_id, LOCALE) is None

        [outcome] = DOCUMENT_SOURCE.write(context=driver.publisher, batch=accept)

    assert (outcome.state, outcome.reason, outcome.keys) == ("live", None, (UNIT_KEY,))
    assert driver.public_texts(object_id, LOCALE) == ["Visit terms."]
    row = DocumentText.all_objects.get(pk=outcome.target_version)
    # The person stands behind the row; its provenance says a model wrote it.
    assert row.accepted_by == driver.publisher.actor_id
    assert (row.provenance["origin"], row.provenance["model"]) == ("ai", "testing/fake-translator")
    audit = OrganizationAuditEntry.objects.filter(
        organization=driver.organization, action="customers.document.text_added"
    ).latest("occurred_at")
    assert (audit.metadata["locale"], audit.metadata["origin"]) == (LOCALE, "ai")


def test_an_account_without_two_factor_sign_in_is_told_to_turn_it_on() -> None:
    plain = DocumentsDriver()
    with stepped_up():
        object_id = _approved(plain)
    UserMfaMethod.objects.filter(user_id=plain.publisher.actor_id).delete()

    with translation_policy_override(AUTOMATIC), pytest.raises(StepUpMfaSetupRequired):
        DOCUMENT_SOURCE.write(
            context=plain.publisher,
            batch=_batch(plain, object_id, "Visit terms.", trigger="acceptance"),
        )


def test_a_job_writes_nothing_in_any_mode_and_repeats_its_answer(driver: DocumentsDriver) -> None:
    object_id = _approved(driver)
    click = _batch(driver, object_id, "Visit terms.", trigger="click", key="job:1")
    rows = DocumentText.all_objects.filter(organization=driver.organization).count()

    with translation_policy_override(AUTOMATIC):
        job = driver.acting(driver.publisher)
        first = DOCUMENT_SOURCE.write(context=job, batch=click)
        assert DOCUMENT_SOURCE.write(context=job, batch=click) == first
        automatic = replace(click, trigger=Trigger(kind="automatic", job_ref=None, cause="user"))
        assert DOCUMENT_SOURCE.write(context=job, batch=automatic) == first

    assert [(o.state, o.reason) for o in first] == [("pending", "legal_document")]
    assert DocumentText.all_objects.filter(organization=driver.organization).count() == rows
    # Nothing went out, so there is nothing to take back.
    assert (
        DOCUMENT_SOURCE.revert(context=driver.publisher, job_ref="job:1", idempotency_key="r") == ()
    )


def test_a_new_version_starts_without_translations_and_the_next_one_is_translated(
    driver: DocumentsDriver,
) -> None:
    object_id = _approved(driver, "Regulamin wizyt.")
    with translation_policy_override(AUTOMATIC):
        DOCUMENT_SOURCE.write(
            context=driver.publisher,
            batch=_batch(driver, object_id, "Visit terms.", trigger="acceptance"),
        )
    first = _read(driver, object_id)
    assert first.targets[UNIT_KEY].text == "Visit terms."
    assert first.facts.legal_document and first.facts.locale_live and first.facts.target_public

    # The next version, approved for a later day: it is the one to translate now,
    # while customers keep reading the version in force — in English too.
    document = driver.document(object_id)
    with _as(driver.publisher), captured_source_changes() as notices:
        saved = save_draft(
            document.kind,
            text="Regulamin wizyt i pobytów.",
            locale="pl",
            expected_version=document.version,
        )
        approve_draft(
            document.kind,
            expected_version=saved["version"],
            effective_from=driver.organization.local_today() + timedelta(days=30),
        )
    assert [(n.source_key, n.object_ids, n.change) for n in notices] == [
        (SOURCE_KEY, (object_id,), "changed")
    ]
    second = _read(driver, object_id)
    assert second.units[0].text == "Regulamin wizyt i pobytów."
    assert (second.targets, second.target_version) == ({}, "0")
    assert second.basis_version != first.basis_version
    # The document spoke English before: automation may offer the new version in it.
    assert second.facts.locale_live and not second.facts.target_public
    assert driver.public_texts(object_id, LOCALE) == ["Visit terms."]
    completeness = DOCUMENT_SOURCE.completeness(
        context=driver.publisher, object_id=object_id, locale=LOCALE
    )
    assert (completeness.complete, completeness.untranslated) == (False, (UNIT_KEY,))

    # What was made for the first version no longer fits.
    with translation_policy_override(AUTOMATIC):
        stale = replace(
            _batch(driver, object_id, "Visit and stay terms.", trigger="acceptance").items[0],
            basis_version=first.basis_version,
        )
        [outcome] = DOCUMENT_SOURCE.write(
            context=driver.publisher,
            batch=replace(_batch(driver, object_id, "x", trigger="acceptance"), items=(stale,)),
        )
    assert (outcome.state, outcome.reason) == ("conflict", "source_changed")


def test_a_corrected_source_whose_translation_reads_the_same_is_accepted_as_a_new_row(
    driver: DocumentsDriver,
) -> None:
    """A typo fixed in the Polish text may leave the English words as they
    were. The acceptance is still a row of its own — against the corrected
    source — or the text would read as out of date for good."""
    object_id = _approved(driver, "Regulamin wizytt.")
    with translation_policy_override(AUTOMATIC):
        DOCUMENT_SOURCE.write(
            context=driver.publisher,
            batch=_batch(driver, object_id, "Visit terms.", trigger="acceptance"),
        )
        driver.edit(object_id, 0, "Regulamin wizyt.")
        stale = _read(driver, object_id)
        assert unit_state(stale.units[0], stale.targets[UNIT_KEY]).status == "stale"

        [outcome] = DOCUMENT_SOURCE.write(
            context=driver.publisher,
            batch=_batch(driver, object_id, "Visit terms.", trigger="acceptance"),
        )

    assert outcome.state == "live"
    fresh = _read(driver, object_id)
    assert unit_state(fresh.units[0], fresh.targets[UNIT_KEY]).status == "fresh"
    assert fresh.target_version == outcome.target_version != stale.target_version
    # A person typing the words that already stand is still told so.
    with _as(driver.publisher), pytest.raises(ValidationError) as refused:
        driver._add(object_id, LOCALE, "Visit terms.")
    assert refused.value.detail["text"][0].code == "text_unchanged"


def test_what_cannot_be_translated_and_what_is_never_sent(driver: DocumentsDriver) -> None:
    drafted = driver.create(["Sam szkic."])
    assert _read(driver, drafted).excluded == EXCLUDED_SOURCE_UNPUBLISHED
    listed = DOCUMENT_SOURCE.list_objects(context=driver.publisher, cursor=None, limit=50)
    assert listed.items == ()

    object_id = _approved(driver, "Cena pobytu: [Uzupełnij: kwota] zł.")
    assert _read(driver, object_id, "pl").excluded == EXCLUDED_LOCALE_IS_SOURCE
    assert _read(driver, object_id, "de").excluded == EXCLUDED_LOCALE_NOT_ENABLED
    read = _read(driver, object_id)
    # A slot nobody filled in: the document is not one to translate yet.
    assert read.units[0].placeholder
    sent = sendable_units(read.units, read.targets, sendable={"public"}, protected="propose")
    assert sent.units == () and sent.skipped == {UNIT_KEY: "blocked"}

    [ref] = DOCUMENT_SOURCE.list_objects(context=driver.publisher, cursor=None, limit=50).items
    kind = driver.document(object_id).kind
    assert (ref.object_id, ref.scope, ref.public) == (object_id, kind, True)
    assert ref.label == DocumentKind(kind).label
    assert ref.published_version == read.basis_version
    # The company's own name stays as written.
    [term] = DOCUMENT_SOURCE.protected_terms(context=driver.publisher, object_id=object_id)
    assert (term.text, term.rule) == (driver.organization.name, "keep")

    # Nor is the version's own language ever written as a translation.
    rules = _approved(driver, "Zasady.")
    accept = _batch(driver, rules, "Rules.", trigger="acceptance")
    polish = replace(accept.items[0], locale="pl", target_version=None)
    with translation_policy_override(AUTOMATIC):
        [refused] = DOCUMENT_SOURCE.write(
            context=driver.publisher, batch=replace(accept, items=(polish,))
        )
    assert (refused.state, refused.reason) == ("refused", EXCLUDED_LOCALE_IS_SOURCE)
    assert driver.public_texts(rules, "pl") == ["Zasady."]

    stranger = replace(driver.publisher, permissions=frozenset())
    with pytest.raises(PermissionDenied):
        DOCUMENT_SOURCE.authorize(context=stranger, action="read", object_ids=[object_id])
    with pytest.raises(PermissionDenied):
        DOCUMENT_SOURCE.authorize(context=driver.editor, action="publish", object_ids=[object_id])


def test_the_panel_learns_what_is_translated_and_what_waits(
    driver: DocumentsDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id = _approved(driver)
    kind = driver.document(object_id).kind
    with _as(driver.publisher):
        before = read_document(kind)["document"]["translation"]
        unwritten = read_document(DocumentKind.SHOP_TERMS)["document"]["translation"]
    assert before == {"object_id": object_id, "version": 1, "waiting": []}
    assert unwritten is None

    # The engine's review queue, asked through the registry (no engine import).
    def waiting(context: ContentContext) -> dict[tuple[str, UUID, str], WaitingReview]:
        return {
            (SOURCE_KEY, object_id, "en"): WaitingReview(uuid4(), 1, comparable=True),
            ("profiles.public_profile", uuid4(), "de"): WaitingReview(uuid4(), 1),
        }

    monkeypatch.setattr(registry, "_review_readers", [waiting])
    with _as(driver.publisher):
        assert read_document(kind)["document"]["translation"]["waiting"] == ["en"]
