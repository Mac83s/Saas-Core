"""Quality checks without a model call (ADR-069 pkt 8).

Hard: every segment, token and mask comes back exactly once, the text is not
empty and fits its limit, and no web address, e-mail or phone appears outside
the masks — a model that adds a link or a contact, whatever a segment asked
it to do, is stopped here. A failed segment is retried once, then waits for a
person (`qa_failed`) and is never billed.

Soft: source-language words left in a longer segment (glossary terms and the
source's proper nouns do not count, so "ul. Wójcika, Łódź" in English is
fine), a glossary term missing from the result, a result more than 2.5 times
the source. A flagged segment waits for review (`qa_flagged`), in automatic
mode too, and is not billed. The leftover threshold is a starting value until
the evals calibrate it per language pair (TL7).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from saas_core.content_protocol.facts import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN, phone_digits
from saas_core.content_protocol.tokens import TOKEN_PATTERN, unmask, validate_tokens
from saas_core.content_protocol.units import visible_characters

from .glossary import GlossaryEntry, occurs, target_form
from .segments import Call, Segment

QA_SEGMENT_MISSING = "segment_missing"
QA_SEGMENT_REPEATED = "segment_repeated"
QA_EMPTY = "empty"
QA_TOO_LONG = "too_long"
QA_CONTACT_INTRODUCED = "contact_introduced"

QA_SOURCE_LEFTOVERS = "source_leftovers"
QA_GLOSSARY_MISSING = "glossary_term_missing"
QA_LENGTH_RATIO = "length_ratio"

#: Segments shorter than this, in words, are not checked for leftovers: a
#: heading or a label may well read the same in both languages.
LEFTOVER_MIN_WORDS = 8
#: Words shorter than this are not counted either way.
LEFTOVER_MIN_LETTERS = 4
#: Below this many source characters a long translation is no warning sign.
LENGTH_RATIO_MIN_SOURCE = 20


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """What the soft checks flag at. The defaults are the code's; the platform
    sets its own (`translation.engine.*`, TL22), which the worker reads once
    per run (`settings_spec.quality_thresholds`) and passes in."""

    #: Share of the result's words copied from the source's lowercase words.
    leftover_share: float = 0.3
    #: A translation longer than this many times its source.
    length_ratio: float = 2.5


DEFAULT_THRESHOLDS = QualityThresholds()

_WORD = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True, slots=True)
class Checked:
    # Segment id → the translation with masks put back, past the hard checks.
    passed: dict[str, str]
    # Segment id → hard check codes.
    failed: dict[str, tuple[str, ...]]
    # Ids the model invented.
    unexpected: tuple[str, ...]


def _introduces_contact(text: str) -> bool:
    plain = TOKEN_PATTERN.sub(" ", text)
    if URL_PATTERN.search(plain) or EMAIL_PATTERN.search(plain):
        return True
    return any(len(phone_digits(match.group(0))) >= 9 for match in PHONE_PATTERN.finditer(plain))


def check_hard(call: Call, answers: Sequence[tuple[str, str]]) -> Checked:
    by_id = {segment.id: segment for segment in call.segments}
    counts = Counter(segment_id for segment_id, _text in answers)
    passed: dict[str, str] = {}
    failed: dict[str, tuple[str, ...]] = {}
    for segment in call.segments:
        if counts[segment.id] == 0:
            failed[segment.id] = (QA_SEGMENT_MISSING,)
        elif counts[segment.id] > 1:
            failed[segment.id] = (QA_SEGMENT_REPEATED,)
    for segment_id, text in answers:
        answered = by_id.get(segment_id)
        if answered is None or segment_id in failed:
            continue
        problems = list(validate_tokens(answered.masked, text))
        if not TOKEN_PATTERN.sub("", text).strip():
            problems.append(QA_EMPTY)
        if _introduces_contact(text):
            problems.append(QA_CONTACT_INTRODUCED)
        restored = unmask(text, answered.spans)
        limit = answered.unit.max_length
        if limit is not None and len(restored) > limit:
            problems.append(QA_TOO_LONG)
        if problems:
            failed[segment_id] = tuple(sorted(set(problems)))
        else:
            passed[segment_id] = restored
    unexpected = tuple(sorted(segment_id for segment_id in counts if segment_id not in by_id))
    return Checked(passed=passed, failed=failed, unexpected=unexpected)


def _words(text: str) -> list[str]:
    return _WORD.findall(TOKEN_PATTERN.sub(" ", text))


def leftover_share(source: str, translation: str, *, glossary: Sequence[GlossaryEntry]) -> float:
    """The share of the translation's words copied from the source's common words.

    Capitalised source words are taken for proper nouns and left out, as are
    glossary terms; so are short words, which collide across languages.
    """
    source_words = _words(source)
    if len(source_words) < LEFTOVER_MIN_WORDS:
        return 0.0
    kept = {
        word.casefold()
        for entry in glossary
        for phrase in (entry.term, *entry.forms)
        for word in _words(phrase)
    }
    common = {
        word.casefold()
        for word in source_words
        if word[:1].islower() and len(word) >= LEFTOVER_MIN_LETTERS
    } - kept
    words = [word for word in _words(translation) if len(word) >= LEFTOVER_MIN_LETTERS]
    if not words:
        return 0.0
    return sum(word.casefold() in common for word in words) / len(words)


def _has_form(form: str, text: str) -> bool:
    # The target form, or an inflection of it: its stem as the start of a word.
    stem = form if len(form) <= 4 else form[: max(4, len(form) - 2)]
    return re.search(r"(?<!\w)" + re.escape(stem), text, re.IGNORECASE) is not None


def check_soft(
    segment: Segment,
    translation: str,
    *,
    glossary: Sequence[GlossaryEntry],
    target_script: str,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> tuple[str, ...]:
    flags: list[str] = []
    source = segment.unit.text
    if leftover_share(source, translation, glossary=glossary) >= thresholds.leftover_share:
        flags.append(QA_SOURCE_LEFTOVERS)
    for entry in glossary:
        if occurs(entry, source) and not _has_form(
            target_form(entry, script=target_script), translation
        ):
            flags.append(QA_GLOSSARY_MISSING)
            break
    source_length = visible_characters(source)
    if (
        source_length >= LENGTH_RATIO_MIN_SOURCE
        and visible_characters(translation) > thresholds.length_ratio * source_length
    ):
        flags.append(QA_LENGTH_RATIO)
    return tuple(flags)
