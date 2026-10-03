"""The contract every translation source passes (§11 of
docs/architecture/translation-sources.md), and the doubles it runs on.

A module's test subclasses `TranslationSourceContract` with a `driver` fixture
that implements `SourceDriver` on the module's real tables. The suite plays the
engine with a deterministic fake translator and computes states with the
protocol's own functions, so a source passes without the engine composed.

`FakeDraftSource` (versioned, with a working draft) and `FakeLiveRecordSource`
(a record public on every save) pass the same suite; they also stand in for a
real source in the engine's tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol
from uuid import UUID, uuid4

import pytest

from saas_core.content_protocol import registry
from saas_core.content_protocol.facts import extract_facts
from saas_core.content_protocol.policy import (
    POLICY_OFF,
    REASON_GATE_FAILED,
    REASON_OVERWRITES_HUMAN,
    PublicationFacts,
    TranslationPolicy,
    Trigger,
    WriteTarget,
    decide_publication,
)
from saas_core.content_protocol.provenance import (
    ORIGIN_AI,
    ORIGIN_COPY,
    ORIGIN_HUMAN,
    ORIGIN_INTEGRATION,
    Provenance,
    unit_hash,
)
from saas_core.content_protocol.registry import SourceChangeNotice
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_DELETED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_SOURCE_UNPUBLISHED,
    LIST_LIMIT,
    PERSON_REQUIRED,
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
    TranslationSource,
    WriteBatch,
    WriteItem,
    WriteOutcome,
)
from saas_core.content_protocol.tokens import PLACEHOLDER_PATTERN, validate_tokens
from saas_core.content_protocol.units import (
    DATA_HEALTH,
    DATA_PUBLIC,
    DATA_PUBLIC_PERSONAL,
    UNIT_ADDRESS,
    UNIT_NAME,
    UNIT_TEXT,
    ProtectedMode,
    Selection,
    Target,
    Unit,
    sendable_units,
    unit_state,
)

# --- Registries, restored after the test ------------------------------------


@contextmanager
def registered_translation_source[S: TranslationSource](source: S) -> Iterator[S]:
    present = any(known.key == source.key for known in registry.translation_sources())
    registry.register_translation_source(
        source, _testing=source.key.startswith(registry.TESTING_PREFIX)
    )
    try:
        yield source
    finally:
        if not present:
            registry.unregister_translation_source(source.key)


@dataclass(frozen=True, slots=True)
class _StaticPolicy:
    value: TranslationPolicy

    def policy(self, *, organization_id: UUID) -> TranslationPolicy:
        return self.value


@contextmanager
def translation_policy_override(policy: TranslationPolicy) -> Iterator[None]:
    previous = registry.replace_translation_policy(_StaticPolicy(policy))
    try:
        yield
    finally:
        registry.replace_translation_policy(previous)


@contextmanager
def captured_source_changes() -> Iterator[list[SourceChangeNotice]]:
    notices: list[SourceChangeNotice] = []

    def listener(notice: SourceChangeNotice) -> None:
        notices.append(notice)

    registry.register_source_change_listener(listener)
    try:
        yield notices
    finally:
        registry.unregister_source_change_listener(listener)


@contextmanager
def only_test_listeners() -> Iterator[None]:
    """Only the listeners the test registers hear notices: the engine's own
    (TL21, installed with the translation module) is set aside meanwhile."""
    installed = registry.source_change_listeners()
    for listener in installed:
        registry.unregister_source_change_listener(listener)
    try:
        yield
    finally:
        for listener in registry.source_change_listeners():
            registry.unregister_source_change_listener(listener)
        for listener in installed:
            registry.register_source_change_listener(listener)


def error_code(error: BaseException) -> str | None:
    """The code a module's refusal carries (a DRF exception or a plain one)."""
    code = getattr(error, "code", None) or getattr(getattr(error, "detail", None), "code", None)
    return str(code or getattr(error, "default_code", "") or "") or None


# --- The driver a module implements -----------------------------------------


@dataclass(frozen=True, slots=True)
class UnitSpec:
    text: str
    kind: str = UNIT_TEXT
    data_class: str = DATA_PUBLIC
    max_length: int | None = None
    required: bool = True


class SourceDriver(Protocol):
    """Moves a module's real content through the scenarios of the contract.

    Positions are indexes into the object's current units in order.
    `capabilities` names what the source can hold: `legal`, `placeholder`,
    `name`, `address`, `personal` (public_personal), `health`.
    """

    source: TranslationSource
    # Optional: units the source derives itself on every object, which no
    # scenario creates and the suite does not compare — a page's
    # `meta/title` and `meta/description`, without which its language version
    # is not publishable (ADR-070 pkt 6). They are still sent and written.
    #   extra_unit_keys: frozenset[str]
    # A person with the module's publish right.
    publisher: ContentContext
    # A person who may translate but not publish.
    editor: ContentContext
    capabilities: frozenset[str]

    # The same person acting through a translation job.
    def acting(self, context: ContentContext) -> ContentContext: ...
    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID: ...
    def insert(self, object_id: UUID, index: int, text: str) -> None: ...
    def move(self, object_id: UUID, from_index: int, to_index: int) -> None: ...
    def edit(self, object_id: UUID, index: int, text: str) -> None: ...
    def delete(self, object_id: UUID, index: int) -> None: ...
    # The source as visitors see it (a live record: a no-op that notifies).
    def publish(self, object_id: UUID) -> None: ...
    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None: ...
    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None: ...
    # The source text standing in for a translation (`copy`).
    def copy_source(self, object_id: UUID, locale: str) -> None: ...
    # What visitors read in the locale, in order; None while it is not public.
    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None: ...


# --- The contract -----------------------------------------------------------

FAKE_MODEL = "testing/fake-translator"
SENDABLE = frozenset({DATA_PUBLIC, DATA_PUBLIC_PERSONAL, DATA_HEALTH})
AUTOMATIC = TranslationPolicy(mode="automatic", reason=None, mass_publication_cap=20)
REVIEW = TranslationPolicy(mode="review", reason=None, mass_publication_cap=20)


def fake_translation(text: str, locale: str) -> str:
    """Keeps tokens and facts, as a good translation does."""
    return f"[{locale}] {text}"


def fixed_translation(text: str) -> Callable[[str, str], str]:
    """A translator that answers `text` whatever it is asked."""

    def translate(_source: str, _locale: str) -> str:
        return text

    return translate


def ai_provenance(unit: Unit, text: str) -> Provenance:
    return Provenance(
        origin=ORIGIN_AI,
        source_hash=unit.source_hash,
        written_hash=unit_hash(unit.kind, text),
        model=FAKE_MODEL,
        at=datetime.now(UTC).isoformat(),
    )


@dataclass(frozen=True, slots=True)
class Translated:
    read: SourceRead
    selection: Selection
    outcomes: tuple[WriteOutcome, ...]

    @property
    def decisions(self) -> list[tuple[str, str | None]]:
        return [(outcome.state, outcome.reason) for outcome in self.outcomes]


def extra_unit_keys(driver: SourceDriver) -> frozenset[str]:
    return frozenset(getattr(driver, "extra_unit_keys", frozenset()))


def own_units(driver: SourceDriver, read: SourceRead) -> SourceRead:
    """The read without the source's own units (`extra_unit_keys`)."""
    extra = extra_unit_keys(driver)
    if not extra:
        return read
    return replace(
        read,
        units=tuple(unit for unit in read.units if unit.key not in extra),
        targets={key: target for key, target in read.targets.items() if key not in extra},
    )


def own_outcomes(
    driver: SourceDriver, outcomes: Sequence[WriteOutcome]
) -> tuple[WriteOutcome, ...]:
    """The outcomes for the units the scenario made: an outcome only for the
    source's own units is left out, and their keys are trimmed from the rest."""
    extra = extra_unit_keys(driver)
    if not extra:
        return tuple(outcomes)
    kept = []
    for outcome in outcomes:
        keys = tuple(key for key in outcome.keys if key not in extra)
        if outcome.keys and not keys:
            continue
        kept.append(replace(outcome, keys=keys))
    return tuple(kept)


class TranslationSourceContract:
    """Subclass per source: set `source_key`, provide a `driver` fixture."""

    source_key: ClassVar[str]
    locale: ClassVar[str] = "de"

    @pytest.fixture(autouse=True)
    def _automatic_policy(self) -> Iterator[None]:
        with translation_policy_override(AUTOMATIC):
            yield

    # -- the engine's part, played by the suite

    def read(
        self, driver: SourceDriver, object_id: UUID, *, basis: Basis = "published"
    ) -> SourceRead:
        return own_units(
            driver,
            driver.source.read(
                context=driver.acting(driver.publisher),
                object_id=object_id,
                locale=self.locale,
                basis=basis,
            ),
        )

    def translate(
        self,
        driver: SourceDriver,
        object_id: UUID,
        *,
        context: ContentContext | None = None,
        trigger: str = "click",
        protected: ProtectedMode = "propose",
        requested: WriteTarget = "live",
        published_in_job: frozenset[UUID] = frozenset(),
        text: Callable[[str, str], str] = fake_translation,
    ) -> Translated:
        context = context or driver.acting(driver.publisher)
        basis: Basis = "working" if requested == "draft" else "published"
        read = driver.source.read(
            context=context, object_id=object_id, locale=self.locale, basis=basis
        )
        selection = sendable_units(read.units, read.targets, sendable=SENDABLE, protected=protected)
        extra = extra_unit_keys(driver)
        texts: dict[str, tuple[str, Provenance]] = {}
        for unit in selection.units:
            # The source's own units get a faithful translation: the scenario's
            # translator is for the units it made.
            translator = fake_translation if unit.key in extra else text
            translated = translator(unit.text, self.locale)
            texts[unit.key] = (translated, ai_provenance(unit, translated))
        seen = own_units(driver, read)
        own_selection = sendable_units(
            seen.units, seen.targets, sendable=SENDABLE, protected=protected
        )
        if not texts:
            return Translated(seen, own_selection, ())
        job_ref = f"translation_job:{uuid4()}"
        batch = WriteBatch(
            source_key=driver.source.key,
            scope=read.scope,
            trigger=Trigger(kind=trigger, job_ref=job_ref, cause="user"),
            protected=protected,
            items=(
                WriteItem(
                    object_id=object_id,
                    locale=self.locale,
                    basis=basis,
                    basis_version=read.basis_version,
                    target_version=read.target_version,
                    texts=texts,
                    requested=requested,
                ),
            ),
            idempotency_key=f"{job_ref}:1",
            published_in_job=published_in_job,
        )
        outcomes = driver.source.write(context=context, batch=batch)
        sent_extra = extra & set(texts)
        if sent_extra:
            # The source's own units go out with the first translation, or the
            # rule that needs them would pass without them.
            answered = {key for outcome in outcomes for key in outcome.keys}
            assert sent_extra <= answered, (
                f"The source's own units {sorted(sent_extra - answered)} got no outcome."
            )
        if any(outcome.state == "live" for outcome in outcomes):
            driver.source.publish(
                context=context,
                scope=read.scope,
                job_ref=job_ref,
                idempotency_key=f"{job_ref}:publish",
            )
        return Translated(seen, own_selection, own_outcomes(driver, outcomes))

    def translated(self, driver: SourceDriver, texts: Sequence[str | UnitSpec]) -> UUID:
        object_id = driver.create(texts)
        driver.publish(object_id)
        assert self.translate(driver, object_id).decisions == [("live", None)]
        return object_id

    @staticmethod
    def statuses(read: SourceRead) -> dict[str, str]:
        return {
            unit.text: unit_state(unit, read.targets.get(unit.key)).status for unit in read.units
        }

    @staticmethod
    def provenances(read: SourceRead) -> dict[str, Provenance | None]:
        return {
            unit.text: read.targets[unit.key].provenance
            for unit in read.units
            if unit.key in read.targets
        }

    def selection(self, read: SourceRead, protected: ProtectedMode = "propose") -> Selection:
        return sendable_units(read.units, read.targets, sendable=SENDABLE, protected=protected)

    def fake(self, text: str) -> str:
        return fake_translation(text, self.locale)

    # -- scenarios (§11)

    def test_the_source_is_registered_under_its_key(self, driver: SourceDriver) -> None:
        assert driver.source.key == self.source_key
        assert registry.translation_source(self.source_key) is driver.source

    def test_inserting_a_unit_sends_only_that_unit(self, driver: SourceDriver) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta", "Gamma"])
        before = self.provenances(self.read(driver, object_id))
        driver.insert(object_id, 1, "Iks")
        driver.publish(object_id)
        read = self.read(driver, object_id)
        assert self.statuses(read) == {
            "Alfa": "fresh",
            "Iks": "missing",
            "Beta": "fresh",
            "Gamma": "fresh",
        }
        assert self.provenances(read) == before
        assert [unit.text for unit in self.selection(read).units] == ["Iks"]

    def test_moving_a_unit_keeps_every_translation(self, driver: SourceDriver) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta", "Gamma"])
        driver.move(object_id, 2, 0)
        driver.publish(object_id)
        read = self.read(driver, object_id)
        assert set(self.statuses(read).values()) == {"fresh"}
        assert self.selection(read).units == ()
        assert driver.public_texts(object_id, self.locale) == [
            self.fake("Gamma"),
            self.fake("Alfa"),
            self.fake("Beta"),
        ]

    def test_editing_a_unit_sends_only_the_edited_unit(self, driver: SourceDriver) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta", "Gamma"])
        driver.edit(object_id, 1, "Beta nowa")
        driver.publish(object_id)
        read = self.read(driver, object_id)
        assert self.statuses(read) == {"Alfa": "fresh", "Beta nowa": "stale", "Gamma": "fresh"}
        assert [unit.text for unit in self.selection(read).units] == ["Beta nowa"]

    def test_an_edit_under_a_persons_correction_waits_beside_it(self, driver: SourceDriver) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta", "Gamma"])
        driver.write_as_person(object_id, self.locale, 1, "Beta poprawiona")
        driver.edit(object_id, 1, "Beta nowa")
        driver.publish(object_id)
        result = self.translate(driver, object_id, trigger="automatic")
        assert [unit.text for unit in result.selection.units] == ["Beta nowa"]
        assert result.selection.proposals == {result.selection.units[0].key}
        assert result.decisions == [("pending", REASON_OVERWRITES_HUMAN)]
        assert driver.public_texts(object_id, self.locale) == [
            self.fake("Alfa"),
            "Beta poprawiona",
            self.fake("Gamma"),
        ]

    def test_deleting_a_unit_drops_its_target(self, driver: SourceDriver) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta", "Gamma"])
        driver.delete(object_id, 0)
        driver.publish(object_id)
        read = self.read(driver, object_id)
        assert [read.targets[unit.key].text for unit in read.units] == [
            self.fake("Beta"),
            self.fake("Gamma"),
        ]
        assert len(read.targets) == 2
        assert self.selection(read).units == ()
        completeness = driver.source.completeness(
            context=driver.publisher, object_id=object_id, locale=self.locale
        )
        assert completeness.complete

    def test_copied_stand_ins_count_as_missing_and_ai_replaces_them(
        self, driver: SourceDriver
    ) -> None:
        object_id = driver.create(["Alfa", "Beta"])
        driver.publish(object_id)
        driver.copy_source(object_id, self.locale)
        read = self.read(driver, object_id)
        assert set(self.statuses(read).values()) == {"missing"}
        assert driver.public_texts(object_id, self.locale) is None
        assert self.translate(driver, object_id).decisions == [("live", None)]
        assert driver.public_texts(object_id, self.locale) == [
            self.fake("Alfa"),
            self.fake("Beta"),
        ]

    def test_an_integrations_text_is_proposed_over_unless_overwritten(
        self, driver: SourceDriver
    ) -> None:
        object_id = self.translated(driver, ["Alfa", "Beta"])
        driver.write_as_integration(object_id, self.locale, 1, "Beta z integracji")
        driver.edit(object_id, 1, "Beta nowa")
        driver.publish(object_id)
        assert self.translate(driver, object_id).decisions == [("pending", REASON_OVERWRITES_HUMAN)]
        assert driver.public_texts(object_id, self.locale) == [
            self.fake("Alfa"),
            "Beta z integracji",
        ]
        overwritten = self.translate(driver, object_id, protected="overwrite")
        assert overwritten.decisions == [("live", None)]
        assert driver.public_texts(object_id, self.locale) == [
            self.fake("Alfa"),
            self.fake("Beta nowa"),
        ]

    # -- further checks (§11)

    def _write(
        self,
        driver: SourceDriver,
        read: SourceRead,
        texts: Mapping[str, str],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        units = {unit.key: unit for unit in read.units}
        return driver.source.write(
            context=driver.acting(driver.publisher),
            batch=WriteBatch(
                source_key=driver.source.key,
                scope=read.scope,
                trigger=Trigger(kind="click", job_ref=None, cause="user"),
                protected="propose",
                items=(
                    WriteItem(
                        object_id=read.object_id,
                        locale=read.locale,
                        basis=read.basis,
                        basis_version=read.basis_version,
                        target_version=read.target_version,
                        texts={
                            key: (text, ai_provenance(units[key], text))
                            for key, text in texts.items()
                        },
                        requested="live",
                    ),
                ),
                idempotency_key=idempotency_key,
            ),
        )

    def test_a_repeated_write_changes_nothing_and_other_content_conflicts(
        self, driver: SourceDriver
    ) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        read = self.read(driver, object_id)
        key = read.units[0].key
        first = self._write(driver, read, {key: self.fake("Alfa")}, "job:same")
        assert [outcome.state for outcome in first] == ["live"]
        assert self._write(driver, read, {key: self.fake("Alfa")}, "job:same") == first
        other = self._write(driver, read, {key: self.fake("Alfa inna")}, "job:same")
        assert [(outcome.state, outcome.reason) for outcome in other] == [
            ("conflict", CONFLICT_IDEMPOTENCY)
        ]

    def test_stale_version_tokens_conflict(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Alfa", "Beta"])
        driver.publish(object_id)
        old = self.read(driver, object_id)
        driver.edit(object_id, 0, "Alfa nowa")
        driver.publish(object_id)
        texts = {unit.key: self.fake(unit.text) for unit in old.units}
        assert [(o.state, o.reason) for o in self._write(driver, old, texts, "job:old")] == [
            ("conflict", CONFLICT_SOURCE_CHANGED)
        ]
        current = self.read(driver, object_id)
        texts = {unit.key: self.fake(unit.text) for unit in current.units}
        assert [o.state for o in self._write(driver, current, texts, "job:first")] == ["live"]
        assert [(o.state, o.reason) for o in self._write(driver, current, texts, "job:second")] == [
            ("conflict", CONFLICT_TARGET_CHANGED)
        ]

    def test_a_pending_result_does_not_go_out_with_a_publication(
        self, driver: SourceDriver
    ) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        with translation_policy_override(REVIEW):
            assert self.translate(driver, object_id).decisions == [("pending", "review_mode")]
        driver.publish(object_id)
        assert driver.public_texts(object_id, self.locale) is None

    def test_a_legal_document_waits_in_every_mode(self, driver: SourceDriver) -> None:
        if "legal" not in driver.capabilities:
            pytest.skip("The source holds no legal documents.")
        object_id = driver.create(["Regulamin"], legal=True)
        driver.publish(object_id)
        assert self.translate(driver, object_id).decisions == [("pending", "legal_document")]
        if "working" in driver.source.bases:
            draft = self.translate(driver, object_id, requested="draft")
            assert draft.decisions == [("pending", "legal_document")]

    def test_automation_never_brings_a_language_in_first(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        result = self.translate(driver, object_id, trigger="automatic")
        assert result.decisions == [("pending", "locale_first_appearance")]

    def test_a_person_without_the_publish_right_leaves_results_waiting(
        self, driver: SourceDriver
    ) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        result = self.translate(driver, object_id, context=driver.acting(driver.editor))
        assert result.decisions == [("pending", "publisher_required")]

    def test_mass_publication_is_counted_in_objects(self, driver: SourceDriver) -> None:
        capped = TranslationPolicy(mode="automatic", reason=None, mass_publication_cap=1)
        with translation_policy_override(capped):
            first = self.translated(driver, ["Alfa"])
            second = driver.create(["Beta"])
            driver.publish(second)
            held = self.translate(
                driver, second, trigger="automatic", published_in_job=frozenset({first})
            )
            assert held.decisions == [("pending", "mass_publication")]
            driver.edit(first, 0, "Alfa nowa")
            driver.publish(first)
            again = self.translate(
                driver, first, trigger="automatic", published_in_job=frozenset({first})
            )
            assert again.decisions == [("live", None)]

    def test_without_the_engine_ai_writes_are_refused(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        with translation_policy_override(POLICY_OFF):
            assert self.translate(driver, object_id).decisions == [("refused", "engine_absent")]
        assert driver.public_texts(object_id, self.locale) is None

    def test_the_write_gate_keeps_the_facts(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Strzyżenie 120 zł"])
        driver.publish(object_id)
        for wrong in ("Haarschnitt 150 zł", "Haarschnitt 120 PLN"):
            result = self.translate(driver, object_id, text=fixed_translation(wrong))
            assert result.decisions == [("pending", REASON_GATE_FAILED)]
            key = result.read.units[0].key
            assert [error.field for error in result.outcomes[0].errors] == [f"units.{key}"]
        right = self.translate(driver, object_id, text=fixed_translation("Haarschnitt 120 zł"))
        assert right.decisions == [("live", None)]

    def test_what_never_reaches_a_model(self, driver: SourceDriver) -> None:
        wanted = [
            ("placeholder", UnitSpec("Cena: [Uzupełnij: kwota]")),
            ("name", UnitSpec("Jan Kowalski", kind=UNIT_NAME)),
            ("address", UnitSpec("ul. Długa 1, Łódź", kind=UNIT_ADDRESS)),
            ("personal", UnitSpec("Świetna obsługa", data_class=DATA_PUBLIC_PERSONAL)),
            ("health", UnitSpec("Alergia na lateks", data_class=DATA_HEALTH)),
        ]
        specs = [UnitSpec("Alfa")] + [
            spec for capability, spec in wanted if capability in driver.capabilities
        ]
        object_id = driver.create(specs)
        driver.publish(object_id)
        read = self.read(driver, object_id)
        sent = [unit.text for unit in self.selection(read).units]
        expected = ["Alfa"] + (["Świetna obsługa"] if "personal" in driver.capabilities else [])
        assert sent == expected
        only_public = sendable_units(
            read.units, read.targets, sendable={DATA_PUBLIC}, protected="propose"
        )
        assert [unit.text for unit in only_public.units] == ["Alfa"]

    def test_a_publication_is_notified_and_a_translation_write_is_not(
        self, driver: SourceDriver
    ) -> None:
        object_id = driver.create(["Alfa"])
        with captured_source_changes() as notices:
            driver.publish(object_id)
            assert [(n.source_key, n.object_ids, n.change) for n in notices] == [
                (self.source_key, (object_id,), "changed")
            ]
            self.translate(driver, object_id)
            assert len(notices) == 1

    def test_a_translation_write_leaves_the_source_alone(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Alfa", "Beta"])
        driver.publish(object_id)
        before = self.read(driver, object_id)
        self.translate(driver, object_id)
        after = self.read(driver, object_id)
        assert [unit.source_hash for unit in after.units] == [
            unit.source_hash for unit in before.units
        ]
        assert after.basis_version == before.basis_version

    def test_a_job_cannot_take_a_persons_review_decision(self, driver: SourceDriver) -> None:
        object_id = driver.create(["Alfa"])
        driver.publish(object_id)
        with translation_policy_override(REVIEW):
            self.translate(driver, object_id)
        refusal: BaseException | None = None
        try:
            driver.source.review(
                context=driver.acting(driver.publisher),
                action="accept",
                items=[ReviewItem(object_id=object_id, locale=self.locale, expected_version=None)],
                idempotency_key=f"review:{uuid4()}",
            )
        except Exception as error:
            refusal = error
        assert refusal is not None and error_code(refusal) == PERSON_REQUIRED


# --- In-memory sources ------------------------------------------------------

FAKE_EDIT = "testing.edit"
FAKE_PUBLISH = "testing.publish"
FAKE_SOURCE_LOCALE = "pl"
FAKE_SCOPE = "testing-scope"

GATE_REQUIRED = "required"
GATE_TOO_LONG = "too_long"
GATE_FACTS_CHANGED = "facts_changed"
GATE_UNKNOWN_UNIT = "unknown_unit"


class FakeRefusal(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FakeContext:
    organization_id: UUID
    membership_id: UUID | None
    actor_id: UUID | None
    permissions: frozenset[str]
    principal_kind: str = "membership"
    credential_id: UUID | None = None
    acting_via: str = ""
    acting_ref: str = ""
    acting_trigger: str = ""

    def has_permission(self, permission: str, /) -> bool:
        return permission in self.permissions


@dataclass
class _FakeObject:
    object_id: UUID
    label: str
    legal: bool
    # (uid, spec): the uid follows a unit through moves and edits, as a block
    # id does; the key a read reports is the position.
    working: list[tuple[int, UnitSpec]]
    published: list[tuple[int, UnitSpec]] | None = None
    working_version: int = 1
    published_version: int = 0
    deleted: bool = False
    # (locale, basis) → uid → target; "published" holds live texts.
    targets: dict[tuple[str, str], dict[int, Target]] = field(default_factory=dict)
    target_versions: dict[tuple[str, str], int] = field(default_factory=dict)
    # locale → uid → (target, reason): results waiting for a person.
    pending: dict[str, dict[int, tuple[Target, str]]] = field(default_factory=dict)
    public_locales: set[str] = field(default_factory=set)
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _gate(unit: Unit, text: str) -> FieldError | None:
    name = f"units.{unit.key}"
    if not text.strip():
        return FieldError(name, GATE_REQUIRED, "The translation is empty.")
    problems = validate_tokens(unit.text, text)
    if problems:
        return FieldError(name, problems[0], "The marks differ from the source.")
    if unit.max_length is not None and len(text) > unit.max_length:
        return FieldError(name, GATE_TOO_LONG, "The translation is too long.")
    if extract_facts(unit.text) != extract_facts(text):
        return FieldError(name, GATE_FACTS_CHANGED, "A price, time or contact differs.")
    return None


def _item_digest(item: WriteItem) -> str:
    texts = {key: text for key, (text, _provenance) in item.texts.items()}
    payload = json.dumps(
        [str(item.object_id), item.locale, item.basis, item.requested, texts], sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class _FakeSource:
    module_id = "testing"
    labels: Mapping[str, str] = {"pl": "Atrapa źródła", "en": "Fake source"}
    translations_publish_separately = False
    staging: Staging
    bases: frozenset[str]
    write_targets: frozenset[str]

    def __init__(self, key: str) -> None:
        self.key = key
        self.objects: dict[UUID, _FakeObject] = {}
        self.live_locales: set[str] = set()
        self._next_uid = 0
        self._writes: dict[tuple[str, UUID, str], tuple[str, tuple[WriteOutcome, ...]]] = {}
        self._journal: dict[str, list[tuple[UUID, str, str, int, Target | None]]] = {}
        self._to_publish: set[tuple[UUID, str]] = set()
        self._publications: dict[str, str] = {}

    # -- helpers

    def new_uid(self) -> int:
        self._next_uid += 1
        return self._next_uid

    def rows(self, obj: _FakeObject, basis: str) -> list[tuple[int, UnitSpec]]:
        return list(obj.working if basis == "working" else (obj.published or []))

    @staticmethod
    def unit(position: int, spec: UnitSpec) -> Unit:
        return Unit(
            key=f"u{position}",
            kind=spec.kind,
            text=spec.text,
            data_class=spec.data_class,
            max_length=spec.max_length,
            required=spec.required,
            placeholder=PLACEHOLDER_PATTERN.search(spec.text) is not None,
        )

    @staticmethod
    def basis_version(obj: _FakeObject, basis: str) -> str:
        version = obj.working_version if basis == "working" else obj.published_version
        return f"{basis}:{version}"

    @staticmethod
    def target_version(obj: _FakeObject, locale: str, basis: str) -> str:
        return str(obj.target_versions.get((locale, basis), 0))

    @staticmethod
    def target(obj: _FakeObject, locale: str, basis: str, uid: int) -> Target | None:
        if basis == "working":
            draft = obj.targets.get((locale, "working"), {}).get(uid)
            if draft is not None:
                return draft
        return obj.targets.get((locale, "published"), {}).get(uid)

    def facts(self, context: ContentContext, obj: _FakeObject, locale: str) -> PublicationFacts:
        return PublicationFacts(
            legal_document=obj.legal,
            locale_live=locale in self.live_locales,
            actor_may_publish=context.has_permission(FAKE_PUBLISH),
            target_public=locale in obj.public_locales,
        )

    def store(
        self,
        obj: _FakeObject,
        locale: str,
        basis: str,
        texts: Mapping[int, Target],
        job_ref: str | None,
    ) -> None:
        stored = obj.targets.setdefault((locale, basis), {})
        for uid, target in texts.items():
            if job_ref:
                self._journal.setdefault(job_ref, []).append((
                    obj.object_id,
                    locale,
                    basis,
                    uid,
                    stored.get(uid),
                ))
            stored[uid] = target
        obj.target_versions[(locale, basis)] = obj.target_versions.get((locale, basis), 0) + 1

    def went_live(self, obj: _FakeObject, locale: str) -> None:
        self._to_publish.add((obj.object_id, locale))

    def hold(self, obj: _FakeObject, locale: str, texts: Mapping[int, Target], reason: str) -> None:
        held = obj.pending.setdefault(locale, {})
        for uid, target in texts.items():
            held[uid] = (target, reason)

    # -- the protocol

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        needed = FAKE_PUBLISH if action in ("publish", "withdraw") else FAKE_EDIT
        if not context.has_permission(needed):
            raise FakeRefusal("permission_denied")
        if any(object_id not in self.objects for object_id in object_ids):
            raise FakeRefusal("not_found")

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        ordered = sorted(
            (
                obj
                for obj in self.objects.values()
                if not obj.deleted and (changed_since is None or obj.changed_at >= changed_since)
            ),
            key=lambda obj: str(obj.object_id),
        )
        start = int(cursor or 0)
        page = ordered[start : start + min(limit, LIST_LIMIT)]
        end = start + len(page)
        return ObjectPage(
            items=tuple(
                ObjectRef(
                    object_id=obj.object_id,
                    label=obj.label,
                    scope=FAKE_SCOPE,
                    priority=0,
                    public=obj.published is not None,
                    published_version=self.basis_version(obj, "published"),
                    working_version=self.basis_version(obj, "working"),
                    changed_at=obj.changed_at,
                )
                for obj in page
            ),
            next_cursor=str(end) if end < len(ordered) else None,
        )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        self.authorize(context=context, action="read", object_ids=[object_id])
        if basis not in self.bases:
            raise ValueError(f"Source {self.key} has no {basis!r} basis.")
        obj = self.objects[object_id]
        excluded = None
        if obj.deleted:
            excluded = EXCLUDED_DELETED
        elif locale == FAKE_SOURCE_LOCALE:
            excluded = EXCLUDED_LOCALE_IS_SOURCE
        elif basis == "published" and obj.published is None:
            excluded = EXCLUDED_SOURCE_UNPUBLISHED
        rows = [] if excluded else self.rows(obj, basis)
        units = tuple(self.unit(position, spec) for position, (_uid, spec) in enumerate(rows))
        targets: dict[str, Target] = {}
        for unit, (uid, _spec) in zip(units, rows, strict=True):
            target = self.target(obj, locale, basis, uid)
            if target is not None:
                targets[unit.key] = target
        return SourceRead(
            object_id=object_id,
            locale=locale,
            basis=basis,
            scope=FAKE_SCOPE,
            source_locale=FAKE_SOURCE_LOCALE,
            basis_version=self.basis_version(obj, basis),
            target_version=self.target_version(obj, locale, basis),
            units=units,
            targets=targets,
            facts=self.facts(context, obj, locale),
            excluded=excluded,
        )

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        if batch.source_key != self.key:
            raise ValueError("The batch is for another source.")
        self.authorize(
            context=context,
            action="translate",
            object_ids=[item.object_id for item in batch.items],
        )
        published_now = set(batch.published_in_job)
        outcomes: list[WriteOutcome] = []
        for item in batch.items:
            outcomes.extend(self._write_item(context, batch, item, published_now))
        return tuple(outcomes)

    def _write_item(
        self,
        context: ContentContext,
        batch: WriteBatch,
        item: WriteItem,
        published_now: set[UUID],
    ) -> tuple[WriteOutcome, ...]:
        obj = self.objects[item.object_id]
        keys = tuple(sorted(item.texts))

        def outcome(
            state: OutcomeState, chosen: Sequence[str], reason: str | None, **extra: Any
        ) -> WriteOutcome:
            return WriteOutcome(
                object_id=obj.object_id,
                locale=item.locale,
                state=state,
                keys=tuple(sorted(chosen)),
                reason=reason,
                **extra,
            )

        # Idempotency goes first: a repeat would see its own new version.
        stamp = (batch.idempotency_key, item.object_id, item.locale)
        digest = _item_digest(item)
        if stamp in self._writes:
            seen_digest, seen = self._writes[stamp]
            if seen_digest == digest:
                return seen
            return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        if item.basis_version != self.basis_version(obj, item.basis):
            return (outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),)
        if item.target_version != self.target_version(obj, item.locale, item.basis):
            return (outcome("conflict", keys, CONFLICT_TARGET_CHANGED),)
        facts = replace(
            self.facts(context, obj, item.locale),
            object_published_in_job=obj.object_id in published_now,
            published_in_job=len(published_now - {obj.object_id}),
        )
        decision = decide_publication(
            policy=registry.translation_policy(organization_id=context.organization_id),
            requested=item.requested,
            requested_reason=item.reason,
            trigger=batch.trigger,
            facts=facts,
        )
        if decision.outcome == "refused":
            return (outcome("refused", keys, decision.reason),)
        units = {
            f"u{position}": (uid, self.unit(position, spec))
            for position, (uid, spec) in enumerate(self.rows(obj, item.basis))
        }
        written: dict[int, tuple[str, Target]] = {}
        proposals: dict[int, tuple[str, Target]] = {}
        errors: list[FieldError] = []
        for key, (text, provenance) in item.texts.items():
            if key not in units:
                errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
                continue
            uid, unit = units[key]
            error = _gate(unit, text)
            if error is not None:
                errors.append(error)
                continue
            current = self.target(obj, item.locale, item.basis, uid)
            chosen = (key, Target(text, provenance))
            if batch.protected != "overwrite" and unit_state(unit, current).protected:
                proposals[uid] = chosen
            else:
                written[uid] = chosen
        results: list[WriteOutcome] = []
        if written:
            texts = {uid: target for uid, (_key, target) in written.items()}
            state = decision.outcome
            if state == "pending":
                self.hold(obj, item.locale, texts, decision.reason or "")
            else:
                basis = "working" if state == "draft" else "published"
                self.store(obj, item.locale, basis, texts, batch.trigger.job_ref)
                if state == "live":
                    self.went_live(obj, item.locale)
                    published_now.add(obj.object_id)
            results.append(
                outcome(
                    state,
                    [key for key, _target in written.values()],
                    decision.reason,
                    target_version=self.target_version(obj, item.locale, item.basis),
                )
            )
        if proposals:
            self.hold(
                obj,
                item.locale,
                {uid: target for uid, (_key, target) in proposals.items()},
                REASON_OVERWRITES_HUMAN,
            )
            results.append(
                outcome("pending", [key for key, _t in proposals.values()], REASON_OVERWRITES_HUMAN)
            )
        if errors:
            results.append(
                outcome(
                    "pending",
                    [error.field.removeprefix("units.") for error in errors],
                    REASON_GATE_FAILED,
                    errors=tuple(errors),
                )
            )
        stored = tuple(results)
        self._writes[stamp] = (digest, stored)
        return stored

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        if idempotency_key in self._publications:
            return self._publications[idempotency_key]
        if not self._to_publish:
            return None
        for object_id, locale in sorted(self._to_publish, key=str):
            self.objects[object_id].public_locales.add(locale)
            self.live_locales.add(locale)
        self._to_publish.clear()
        publication = f"publication:{len(self._publications) + 1}"
        self._publications[idempotency_key] = publication
        return publication

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        obj = self.objects[object_id]
        untranslated: list[str] = []
        for position, (uid, spec) in enumerate(obj.published or []):
            unit = self.unit(position, spec)
            state = unit_state(unit, self.target(obj, locale, "published", uid))
            if unit.required and state.status in ("missing", "blocked"):
                untranslated.append(unit.key)
        complete = obj.published is not None and not untranslated
        return Completeness(
            complete=complete,
            publishable=complete,
            untranslated=tuple(untranslated),
            reasons=() if complete else ("untranslated_units",),
        )

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]:
        return (ProtectedTerm(text=self.objects[object_id].label, rule="keep"),)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        # A person's decision: a job or the assistant acting for one is refused.
        if context.acting_via:
            raise FakeRefusal(PERSON_REQUIRED)
        self.authorize(
            context=context, action="publish", object_ids=[item.object_id for item in items]
        )
        outcomes: list[WriteOutcome] = []
        for item in items:
            obj = self.objects[item.object_id]
            held = obj.pending.pop(item.locale, {})
            if action == "accept" and held:
                self.store(
                    obj,
                    item.locale,
                    "published",
                    {uid: target for uid, (target, _reason) in held.items()},
                    job_ref=None,
                )
                self.went_live(obj, item.locale)
                outcomes.append(
                    WriteOutcome(obj.object_id, item.locale, "live", keys=(), reason=None)
                )
            elif action == "withdraw":
                obj.public_locales.discard(item.locale)
        self.publish(context=context, scope=FAKE_SCOPE, job_ref="", idempotency_key=idempotency_key)
        return tuple(outcomes)

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        touched: set[tuple[UUID, str]] = set()
        for object_id, locale, basis, uid, previous in reversed(self._journal.pop(job_ref, [])):
            stored = self.objects[object_id].targets.setdefault((locale, basis), {})
            if previous is None:
                stored.pop(uid, None)
            else:
                stored[uid] = previous
            touched.add((object_id, locale))
        return tuple(
            WriteOutcome(object_id, locale, "live", keys=(), reason=None)
            for object_id, locale in sorted(touched, key=str)
        )


class FakeDraftSource(_FakeSource):
    """A versioned source with a working draft, like a page of a site."""

    staging: Staging = "versioned"
    bases = frozenset({"published", "working"})
    write_targets = frozenset({"draft", "pending", "live"})


class FakeLiveRecordSource(_FakeSource):
    """A record public on every save, like a company's directory card.

    Pending results are not stored here — the engine's review queue holds them.
    """

    staging: Staging = "live_record"
    bases = frozenset({"published"})
    write_targets = frozenset({"live"})

    def went_live(self, obj: _FakeObject, locale: str) -> None:
        obj.public_locales.add(locale)
        self.live_locales.add(locale)

    def hold(self, obj: _FakeObject, locale: str, texts: Mapping[int, Target], reason: str) -> None:
        return None

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        return None


class FakeSourceDriver:
    """`SourceDriver` for the in-memory sources."""

    capabilities = frozenset({"legal", "placeholder", "name", "address", "personal", "health"})

    def __init__(self, source: _FakeSource) -> None:
        self.source = source
        organization_id = uuid4()
        self.publisher = FakeContext(
            organization_id=organization_id,
            membership_id=uuid4(),
            actor_id=uuid4(),
            permissions=frozenset({FAKE_EDIT, FAKE_PUBLISH}),
        )
        self.editor = FakeContext(
            organization_id=organization_id,
            membership_id=uuid4(),
            actor_id=uuid4(),
            permissions=frozenset({FAKE_EDIT}),
        )

    @property
    def _live(self) -> bool:
        return self.source.staging == "live_record"

    def acting(self, context: ContentContext) -> ContentContext:
        assert isinstance(context, FakeContext)
        return replace(
            context, acting_via="ai_translation", acting_ref=f"translation_job:{uuid4()}"
        )

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        rows = [
            (self.source.new_uid(), unit if isinstance(unit, UnitSpec) else UnitSpec(unit))
            for unit in units
        ]
        obj = _FakeObject(object_id=uuid4(), label="Studio Testowe", legal=legal, working=rows)
        if self._live:
            obj.published, obj.published_version = list(rows), 1
        self.source.objects[obj.object_id] = obj
        return obj.object_id

    def _change(
        self, object_id: UUID, change: Callable[[list[tuple[int, UnitSpec]]], object]
    ) -> None:
        obj = self.source.objects[object_id]
        change(obj.working)
        obj.working_version += 1
        obj.changed_at = datetime.now(UTC)
        if self._live:
            obj.published = list(obj.working)
            obj.published_version += 1

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        uid = self.source.new_uid()
        self._change(object_id, lambda rows: rows.insert(index, (uid, UnitSpec(text))))

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        self._change(object_id, lambda rows: rows.insert(to_index, rows.pop(from_index)))

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        def change(rows: list[tuple[int, UnitSpec]]) -> None:
            uid, spec = rows[index]
            rows[index] = (uid, replace(spec, text=text))

        self._change(object_id, change)

    def delete(self, object_id: UUID, index: int) -> None:
        self._change(object_id, lambda rows: rows.pop(index))

    def publish(self, object_id: UUID) -> None:
        obj = self.source.objects[object_id]
        if not self._live:
            obj.published = list(obj.working)
            obj.published_version += 1
        registry.notify_source_changed(
            context=self.publisher,
            source_key=self.source.key,
            object_ids=[object_id],
            change="changed",
            cause="user",
        )

    def _write_as(self, origin: str, object_id: UUID, locale: str, index: int, text: str) -> None:
        obj = self.source.objects[object_id]
        uid, spec = (obj.published or [])[index]
        unit = self.source.unit(index, spec)
        provenance = Provenance(
            origin=origin, source_hash=unit.source_hash, written_hash=unit_hash(unit.kind, text)
        )
        self.source.store(obj, locale, "published", {uid: Target(text, provenance)}, job_ref=None)
        obj.public_locales.add(locale)
        self.source.live_locales.add(locale)

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        self._write_as(ORIGIN_HUMAN, object_id, locale, index, text)

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        self._write_as(ORIGIN_INTEGRATION, object_id, locale, index, text)

    def copy_source(self, object_id: UUID, locale: str) -> None:
        obj = self.source.objects[object_id]
        copies = {
            uid: Target(
                spec.text,
                Provenance(origin=ORIGIN_COPY, source_hash=self.source.unit(i, spec).source_hash),
            )
            for i, (uid, spec) in enumerate(obj.published or [])
        }
        self.source.store(obj, locale, "published", copies, job_ref=None)
        obj.public_locales.add(locale)

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        obj = self.source.objects[object_id]
        if locale not in obj.public_locales:
            return None
        if not self.source.completeness(
            context=self.publisher, object_id=object_id, locale=locale
        ).complete:
            return None
        texts: list[str] = []
        for uid, spec in obj.published or []:
            target = self.source.target(obj, locale, "published", uid)
            texts.append(
                spec.text
                if spec.kind in (UNIT_NAME, UNIT_ADDRESS) or target is None
                else target.text
            )
        return texts
