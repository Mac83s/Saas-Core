"""The glossary: terms a translation must keep or render the company's way (ADR-069 pkt 7).

Terms are data. A term reaches the model only when it occurs in the text sent,
inside the same data frame as the segments, and a term is short, one line, with
no control characters and no tokens — so it cannot carry a paragraph of
instructions. The source's own protected terms (the company and page name,
people's names in the text) join the company's glossary here.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from saas_core.content_protocol.sources import ProtectedTerm
from saas_core.content_protocol.tokens import TOKEN_PATTERN
from saas_core.content_protocol.transliteration import transliterate_name

from .models import GlossaryRule

#: A term and its translation, in code points.
TERM_MAX_LENGTH = 120
#: Inflected forms per term.
FORMS_MAX = 10
#: Terms per company: a protective limit, not a business rule.
GLOSSARY_LIMIT = 500

TERM_EMPTY = "glossary_term_empty"
TERM_TOO_LONG = "glossary_term_too_long"
TERM_FORBIDDEN_CHARACTERS = "glossary_term_forbidden_characters"
TERM_TRANSLATION_REQUIRED = "glossary_translation_required"
TERM_TOO_MANY_FORMS = "glossary_too_many_forms"


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    term: str
    rule: str
    source_locale: str
    # Empty: every target language.
    target_locale: str = ""
    translation: str = ""
    forms: tuple[str, ...] = ()


def _text_problem(value: str) -> str | None:
    if not value.strip():
        return TERM_EMPTY
    if len(value) > TERM_MAX_LENGTH:
        return TERM_TOO_LONG
    if TOKEN_PATTERN.search(value) or "⟦" in value or "⟧" in value:
        return TERM_FORBIDDEN_CHARACTERS
    if any(unicodedata.category(char).startswith("C") for char in value):
        return TERM_FORBIDDEN_CHARACTERS
    return None


def entry_problems(entry: GlossaryEntry) -> dict[str, str]:
    """Field → code for what makes the entry unusable (A1a field errors)."""
    problems: dict[str, str] = {}
    term = _text_problem(entry.term)
    if term:
        problems["term"] = term
    if entry.rule == GlossaryRule.TRANSLATE_AS:
        translation = _text_problem(entry.translation)
        if translation == TERM_EMPTY:
            problems["translation"] = TERM_TRANSLATION_REQUIRED
        elif translation:
            problems["translation"] = translation
    if len(entry.forms) > FORMS_MAX:
        problems["forms"] = TERM_TOO_MANY_FORMS
    for index, form in enumerate(entry.forms):
        form_problem = _text_problem(form)
        if form_problem:
            problems[f"forms.{index}"] = form_problem
    return problems


def protected_entries(terms: Iterable[ProtectedTerm], *, source_locale: str) -> list[GlossaryEntry]:
    rules = {"keep": GlossaryRule.KEEP, "name": GlossaryRule.NAME}
    return [
        GlossaryEntry(term=term.text, rule=rules[term.rule], source_locale=source_locale)
        for term in terms
        if not _text_problem(term.text)
    ]


def target_form(entry: GlossaryEntry, *, script: str) -> str:
    """How the term must read in a language written in `script`."""
    if entry.rule == GlossaryRule.TRANSLATE_AS:
        return entry.translation
    if entry.rule == GlossaryRule.NAME:
        return transliterate_name(entry.term, script)
    return entry.term


def _pattern(words: Iterable[str]) -> re.Pattern[str]:
    alternatives = sorted({word.strip() for word in words if word.strip()}, key=len, reverse=True)
    return re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(word) for word in alternatives) + r")(?!\w)",
        re.IGNORECASE,
    )


def occurs(entry: GlossaryEntry, text: str) -> bool:
    return bool(_pattern((entry.term, *entry.forms)).search(text))


def entries_for(
    entries: Iterable[GlossaryEntry],
    *,
    source_locale: str,
    target_locale: str,
    texts: Sequence[str],
) -> tuple[GlossaryEntry, ...]:
    """The entries for this pair of languages that occur in the texts sent.

    A target-specific entry wins over a general one for the same term; the
    forms of both find the term.
    """
    groups: dict[str, list[GlossaryEntry]] = {}
    for entry in entries:
        if entry.source_locale == source_locale and entry.target_locale in ("", target_locale):
            groups.setdefault(entry.term.casefold(), []).append(entry)
    chosen: list[GlossaryEntry] = []
    for key in sorted(groups):
        group = groups[key]
        best = next((entry for entry in group if entry.target_locale), group[0])
        words = {word for entry in group for word in (entry.term, *entry.forms)}
        if any(_pattern(words).search(text) for text in texts):
            chosen.append(best)
    return tuple(chosen)
