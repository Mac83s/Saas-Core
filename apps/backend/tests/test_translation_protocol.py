"""The translation protocol's pure parts (TL5, docs/architecture/translation-sources.md §4–§8):
unit states, what is sent, the publication rules and the registry."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import (
    POLICY_OFF,
    PublicationFacts,
    TranslationPolicy,
    Trigger,
    WriteTarget,
    decide_publication,
)
from saas_core.content_protocol.provenance import Provenance, unit_hash
from saas_core.content_protocol.units import (
    Target,
    Unit,
    sendable_units,
    unit_state,
    visible_characters,
)
from saas_core.testing.translation_sources import (
    FakeContext,
    FakeDraftSource,
    FakeLiveRecordSource,
    captured_source_changes,
    only_test_listeners,
    registered_translation_source,
)


def unit(
    text: str = "Strzyżenie psa",
    *,
    key: str = "u0",
    kind: str = "text",
    data_class: str = "public",
    placeholder: bool = False,
) -> Unit:
    return Unit(
        key=key,
        kind=kind,
        text=text,
        data_class=data_class,
        max_length=None,
        placeholder=placeholder,
    )


def target(
    text: str, origin: str = "ai", *, source: Unit | None = None, written: str | None = None
) -> Target:
    source = source or unit()
    return Target(
        text,
        Provenance(
            origin=origin,
            source_hash=source.source_hash,
            written_hash=unit_hash(source.kind, written if written is not None else text),
        ),
    )


# --- States -----------------------------------------------------------------


def test_states_follow_the_provenance_beside_the_target() -> None:
    source = unit()
    edited = unit("Strzyżenie kota")
    assert unit_state(source, None).status == "missing"
    assert unit_state(source, Target("  ", None)).status == "missing"
    assert unit_state(source, target("Hundeschnitt", "copy")).status == "missing"
    assert unit_state(source, target("Hundeschnitt")).status == "fresh"
    assert unit_state(edited, target("Hundeschnitt", source=source)).status == "stale"
    assert unit_state(source, Target("Hundeschnitt", None)) == unit_state(source, Target("x", None))
    assert unit_state(source, Target("Hundeschnitt", None)).status == "unverified"
    assert unit_state(unit("[Uzupełnij: cena]", placeholder=True), None).status == "blocked"
    assert unit_state(unit("Jan Kowalski", kind="name"), None).status == "copied"


def test_a_person_an_integration_or_a_later_edit_protects_a_target() -> None:
    source = unit()
    assert not unit_state(source, target("Hundeschnitt")).protected
    assert unit_state(source, target("Hundeschnitt", "human")).protected
    assert unit_state(source, target("Hundeschnitt", "integration")).protected
    # Written by the engine, then edited where provenance was not updated.
    assert unit_state(source, target("Hundeschnitt!", written="Hundeschnitt")).protected
    assert unit_state(source, Target("Hundeschnitt", None)).protected


def test_a_unit_refuses_an_unknown_kind_or_data_class() -> None:
    with pytest.raises(ValueError):
        unit(kind="slug")
    with pytest.raises(ValueError):
        unit(data_class="secret")


# --- What is sent -----------------------------------------------------------


def test_sendable_units_skips_with_a_reason_and_never_sends_health() -> None:
    fresh = unit("Alfa", key="fresh")
    units = [
        fresh,
        unit("Beta", key="missing"),
        unit("[Uzupełnij: cena]", key="blocked", placeholder=True),
        unit("Jan Kowalski", key="copied", kind="address"),
        unit("Świetnie", key="personal", data_class="public_personal"),
        unit("Alergia", key="health", data_class="health"),
    ]
    selection = sendable_units(
        units,
        {"fresh": target("Alfa de", source=fresh)},
        sendable={"public", "public_personal", "health"},
        protected="propose",
    )
    assert [u.key for u in selection.units] == ["missing", "personal"]
    assert selection.skipped == {
        "fresh": "fresh",
        "blocked": "blocked",
        "copied": "copied",
        "health": "not_sendable",
    }
    public_only = sendable_units(units, {}, sendable={"public"}, protected="propose")
    assert "personal" not in [u.key for u in public_only.units]


def test_protected_targets_are_skipped_proposed_or_overwritten() -> None:
    old = unit("Alfa")
    new = unit("Alfa nowa")
    human = {"u0": target("Alfa (Mensch)", "human", source=old)}
    assert sendable_units([new], human, sendable={"public"}, protected="skip").skipped == {
        "u0": "protected"
    }
    proposed = sendable_units([new], human, sendable={"public"}, protected="propose")
    assert proposed.proposals == {"u0"}
    overwritten = sendable_units([new], human, sendable={"public"}, protected="overwrite")
    assert overwritten.proposals == frozenset() and len(overwritten.units) == 1


def test_unverified_targets_go_only_on_request() -> None:
    legacy = {"u0": Target("Alt", None)}
    source = [unit("Alfa")]
    assert sendable_units(source, legacy, sendable={"public"}, protected="propose").skipped == {
        "u0": "unverified"
    }
    asked = sendable_units(
        source, legacy, sendable={"public"}, protected="propose", include_unverified=True
    )
    assert asked.proposals == {"u0"}
    assert sendable_units(source, legacy, sendable={"public"}, protected="overwrite").units


def test_visible_characters_leave_out_marks_and_contacts() -> None:
    assert visible_characters("⟦1⟧Zadzwoń⟦/1⟧:  +48 600 100 200") == len("Zadzwoń :")
    assert visible_characters("Napisz na biuro@example.test lub www.example.test") == len(
        "Napisz na lub"
    )
    selection = sendable_units([unit("Ala ma kota")], {}, sendable={"public"}, protected="skip")
    assert selection.characters == 11


# --- Publication rules -------------------------------------------------------

AUTOMATIC = TranslationPolicy(mode="automatic", reason=None, mass_publication_cap=2)
CLICK = Trigger(kind="click", job_ref=None, cause="user")
SCHEDULE = Trigger(kind="automatic", job_ref=None, cause="schedule")
FACTS = PublicationFacts(legal_document=False, locale_live=True, actor_may_publish=True)


def decide(
    policy: TranslationPolicy = AUTOMATIC,
    requested: WriteTarget = "live",
    trigger: Trigger = CLICK,
    reason: str | None = None,
    **facts: Any,
) -> tuple[str, str | None]:
    decision = decide_publication(
        policy=policy,
        requested=requested,
        requested_reason=reason,
        trigger=trigger,
        facts=replace(FACTS, **facts),
    )
    return decision.outcome, decision.reason


def test_the_first_matching_rule_decides() -> None:
    off = TranslationPolicy(mode="off", reason="kill_switch", mass_publication_cap=0)
    review = TranslationPolicy(mode="review", reason=None, mass_publication_cap=20)
    forced = TranslationPolicy(
        mode="review", reason="operator_forced_review", mass_publication_cap=20
    )
    acceptance = Trigger(kind="acceptance", job_ref=None, cause="user")
    assert decide(off, trigger=acceptance, legal_document=True) == ("live", None)
    assert decide(off) == ("refused", "kill_switch")
    assert decide(POLICY_OFF) == ("refused", "engine_absent")
    assert decide(requested="draft", legal_document=True) == ("pending", "legal_document")
    assert decide(requested="draft") == ("draft", None)
    assert decide(requested="pending", reason="qa_flagged") == ("pending", "qa_flagged")
    assert decide(review) == ("pending", "review_mode")
    assert decide(forced) == ("pending", "operator_forced_review")
    assert decide(actor_may_publish=False) == ("pending", "publisher_required")
    assert decide(trigger=SCHEDULE, locale_live=False) == ("pending", "locale_first_appearance")
    assert decide(trigger=CLICK, locale_live=False) == ("live", None)
    assert decide(trigger=SCHEDULE, published_in_job=2) == ("pending", "mass_publication")
    assert decide(trigger=SCHEDULE, published_in_job=2, object_published_in_job=True) == (
        "live",
        None,
    )
    assert decide(trigger=CLICK, published_in_job=50) == ("live", None)


# --- Registry ----------------------------------------------------------------


def test_a_broken_declaration_stops_the_start() -> None:
    with pytest.raises(registry.TranslationRegistryError, match="testing"):
        registry.register_translation_source(FakeLiveRecordSource("testing.card"))
    with pytest.raises(registry.TranslationRegistryError, match="testing"):
        registry.register_translation_source(FakeDraftSource("sites.page"), _testing=True)

    broken = FakeLiveRecordSource("testing.broken")
    broken.write_targets = frozenset({"live", "pending"})
    with pytest.raises(registry.TranslationRegistryError, match="live record"):
        registry.register_translation_source(broken, _testing=True)

    draftless = FakeDraftSource("testing.draftless")
    draftless.write_targets = frozenset({"pending", "live"})
    with pytest.raises(registry.TranslationRegistryError, match="draft"):
        registry.register_translation_source(draftless, _testing=True)

    unlabelled = FakeDraftSource("testing.unlabelled")
    unlabelled.labels = {"pl": "Strona"}
    with pytest.raises(registry.TranslationRegistryError, match="'en' label"):
        registry.register_translation_source(unlabelled, _testing=True)


def test_one_key_one_source() -> None:
    first = FakeDraftSource("testing.page")
    with registered_translation_source(first):
        registry.register_translation_source(first, _testing=True)
        with pytest.raises(registry.TranslationRegistryError, match="already"):
            registry.register_translation_source(FakeDraftSource("testing.page"), _testing=True)
        assert registry.translation_source("testing.page") is first
    with pytest.raises(LookupError):
        registry.translation_source("testing.page")


def test_without_the_engine_the_policy_is_off() -> None:
    previous = registry.replace_translation_policy(None)
    try:
        assert registry.translation_policy(organization_id=uuid4()) == POLICY_OFF
    finally:
        registry.replace_translation_policy(previous)


def test_a_change_notice_never_fails_the_save(caplog: pytest.LogCaptureFixture) -> None:
    context = FakeContext(
        organization_id=uuid4(), membership_id=uuid4(), actor_id=uuid4(), permissions=frozenset()
    )
    object_id = uuid4()
    with registered_translation_source(FakeDraftSource("testing.notices")), only_test_listeners():
        # Without a listener nothing happens at all.
        registry.notify_source_changed(
            context=context, source_key="testing.notices", object_ids=[object_id], cause="user"
        )

        def broken(_notice: registry.SourceChangeNotice) -> None:
            raise RuntimeError("listener down")

        registry.register_source_change_listener(broken)
        try:
            with captured_source_changes() as notices, caplog.at_level(logging.WARNING):
                registry.notify_source_changed(
                    context=context,
                    source_key="testing.notices",
                    object_ids=[object_id],
                    change="withdrawn",
                    cause="user",
                )
                registry.notify_source_changed(
                    context=context,
                    source_key="testing.unknown",
                    object_ids=[object_id],
                    cause="user",
                )
                registry.notify_source_changed(
                    context=context,
                    source_key="testing.notices",
                    object_ids=[object_id],
                    change="renamed",  # type: ignore[arg-type]
                    cause="user",
                )
        finally:
            registry.unregister_source_change_listener(broken)
    assert [(n.object_ids, n.change, n.actor_id) for n in notices] == [
        ((object_id,), "withdrawn", context.actor_id)
    ]
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("translation_source_change_failed") == 1
    assert messages.count("translation_source_change_rejected") == 2
