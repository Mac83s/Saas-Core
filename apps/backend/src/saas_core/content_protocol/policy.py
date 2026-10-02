"""Whether an AI translation goes out now or waits for a person (ADR-069 pkt 12, 16, 21).

The engine registers the policy — the company's mode, the operator's override
and the deployment ceiling folded into one — and a content module reads it on
every AI write, so a stricter mode reaches jobs already queued.
`decide_publication` is the one implementation of the rules; the engine runs
it earlier to warn in the quote, the module runs it at write time and may only
make the answer stricter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type WriteTarget = Literal["draft", "pending", "live"]
type TriggerKind = Literal["click", "automatic", "acceptance"]
type PolicyMode = Literal["off", "review", "automatic"]
type DecisionOutcome = Literal["draft", "pending", "live", "refused"]

WRITE_TARGETS = frozenset({"draft", "pending", "live"})
TRIGGER_KINDS = frozenset({"click", "automatic", "acceptance"})
POLICY_MODES = frozenset({"off", "review", "automatic"})

# Why a result waits (ADR-069 pkt 21).
REASON_LEGAL_DOCUMENT = "legal_document"
REASON_REVIEW_MODE = "review_mode"
REASON_OPERATOR_FORCED_REVIEW = "operator_forced_review"
REASON_PUBLISHER_REQUIRED = "publisher_required"
REASON_LOCALE_FIRST_APPEARANCE = "locale_first_appearance"
REASON_MASS_PUBLICATION = "mass_publication"
REASON_OVERWRITES_HUMAN = "overwrites_human"
REASON_QA_FLAGGED = "qa_flagged"
REASON_GATE_FAILED = "gate_failed"
# Why AI writes are refused outright.
REASON_ENGINE_ABSENT = "engine_absent"

DEFAULT_MASS_PUBLICATION_CAP = 20


@dataclass(frozen=True, slots=True)
class Trigger:
    kind: str
    # "translation_job:<uuid>".
    job_ref: str | None
    # user | api_key | schedule | conversation:<uuid> (A1a `acting_trigger`).
    cause: str

    def __post_init__(self) -> None:
        if self.kind not in TRIGGER_KINDS:
            raise ValueError(f"Unknown trigger kind: {self.kind!r}")


@dataclass(frozen=True, slots=True)
class PublicationFacts:
    # Waits for a person in every mode.
    legal_document: bool
    # The language is already public in the object's publication scope.
    locale_live: bool
    # The acting person holds the module's publish right.
    actor_may_publish: bool
    object_published_in_job: bool = False
    # Other objects this job made public.
    published_in_job: int = 0


@dataclass(frozen=True, slots=True)
class TranslationPolicy:
    # Strictest of the company mode, the operator override and the ceiling.
    mode: str
    # engine_absent, kill_switch, organization_paused, processor_not_listed,
    # operator_forced_review.
    reason: str | None
    # Operator setting: objects one job without a click may publish.
    mass_publication_cap: int

    def __post_init__(self) -> None:
        if self.mode not in POLICY_MODES:
            raise ValueError(f"Unknown policy mode: {self.mode!r}")
        if self.mass_publication_cap < 0:
            raise ValueError("The mass publication cap cannot be negative.")


POLICY_OFF = TranslationPolicy(mode="off", reason=REASON_ENGINE_ABSENT, mass_publication_cap=0)


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    outcome: DecisionOutcome
    reason: str | None = None


def decide_publication(
    *,
    policy: TranslationPolicy,
    requested: WriteTarget,
    requested_reason: str | None,
    trigger: Trigger,
    facts: PublicationFacts,
) -> PublicationDecision:
    """Where an AI result lands; the first rule that matches wins."""
    if requested not in WRITE_TARGETS:
        raise ValueError(f"Unknown write target: {requested!r}")
    # A person's acceptance: the kill switch stops the model and automation,
    # never people's decisions.
    if trigger.kind == "acceptance":
        return PublicationDecision(requested)
    if policy.mode == "off":
        return PublicationDecision("refused", policy.reason or REASON_ENGINE_ABSENT)
    # Before the draft rule, so a translated draft of a legal page does not go
    # out with the next whole-site publication unreviewed.
    if facts.legal_document:
        return PublicationDecision("pending", REASON_LEGAL_DOCUMENT)
    if requested == "draft":
        return PublicationDecision("draft")
    if requested == "pending":
        return PublicationDecision("pending", requested_reason or REASON_QA_FLAGGED)
    if policy.mode == "review":
        forced = policy.reason == REASON_OPERATOR_FORCED_REVIEW
        return PublicationDecision(
            "pending", REASON_OPERATOR_FORCED_REVIEW if forced else REASON_REVIEW_MODE
        )
    if not facts.actor_may_publish:
        return PublicationDecision("pending", REASON_PUBLISHER_REQUIRED)
    if trigger.kind == "automatic":
        # Adding a language translates nothing; the first appearance of a
        # language is a person's click on "Translate" with a quote.
        if not facts.locale_live:
            return PublicationDecision("pending", REASON_LOCALE_FIRST_APPEARANCE)
        # Counted in objects, not (object, language) pairs.
        if (
            not facts.object_published_in_job
            and facts.published_in_job >= policy.mass_publication_cap
        ):
            return PublicationDecision("pending", REASON_MASS_PUBLICATION)
    return PublicationDecision("live")
