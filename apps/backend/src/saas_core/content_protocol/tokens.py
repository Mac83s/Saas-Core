"""The token grammar of a translatable text unit.

A unit is the text of one translatable place in content. Inline marks inside it
are numbered paired tokens, `⟦1⟧…⟦/1⟧`: what the mark is — bold, italic, a link
and its target — stays in the structure, keyed by the number, so a translator
may move a mark within the sentence but never change, add or drop one. The
owning module numbers its marks; the protocol only checks them.

Spans that must reach the reader exactly as written — web addresses, e-mail
addresses, phone numbers, the owner's `[Uzupełnij: …]` slots — are masked as
self-closing `⟦m:1⟧` on the way to a model and put back afterwards. Stored text
is never masked; masking is a transport step.

The brackets are U+27E6 and U+27E7. Content practically never contains them;
a bracket that does not form a token is plain text.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .facts import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN, phone_digits

TOKEN_PATTERN = re.compile(r"⟦(?:(/?)(\d{1,3})|m:(\d{1,3}))⟧")
PLACEHOLDER_PATTERN = re.compile(r"\[(?:Uzupełnij|Fill in):[^\]]*\]")

TOKEN_MISSING = "token_missing"
TOKEN_UNEXPECTED = "token_unexpected"
TOKEN_MALFORMED = "token_malformed"
TOKEN_NESTING = "token_nesting"


def open_token(number: int) -> str:
    return f"⟦{number}⟧"


def close_token(number: int) -> str:
    return f"⟦/{number}⟧"


def mask_token(number: int) -> str:
    return f"⟦m:{number}⟧"


class TokenError(ValueError):
    """A unit whose tokens cannot be read back into its structure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of text, inside mark `mark` or outside any mark (`None`)."""

    text: str
    mark: int | None


def tokens(text: str) -> list[str]:
    return [match.group(0) for match in TOKEN_PATTERN.finditer(text)]


def validate_tokens(source: str, candidate: str) -> tuple[str, ...]:
    """What is wrong with the candidate's tokens against the source's.

    Every token of the source must appear in the candidate exactly once, and
    pairs must open before they close and nest properly. The order of pairs
    may change — word order differs between languages.
    """
    expected = Counter(tokens(source))
    found = Counter(tokens(candidate))
    problems: set[str] = set()
    if expected - found:
        problems.add(TOKEN_MISSING)
    if found - expected:
        problems.add(TOKEN_UNEXPECTED)
    if not _well_formed(candidate):
        problems.add(TOKEN_MALFORMED)
    return tuple(sorted(problems))


def _well_formed(text: str) -> bool:
    stack: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        closing, number, _mask = match.groups()
        if number is None:
            continue
        if not closing:
            stack.append(number)
        elif not stack or stack.pop() != number:
            return False
    return not stack


def flat_segments(text: str) -> list[Segment]:
    """Splits a unit into runs, for structures whose marks cannot nest.

    Raises `TokenError` for a token that is unbalanced, nested in another, or a
    mask — stored text never holds one.
    """
    segments: list[Segment] = []
    current: int | None = None
    position = 0
    for match in TOKEN_PATTERN.finditer(text):
        closing, number, mask = match.groups()
        if mask is not None:
            raise TokenError(TOKEN_UNEXPECTED)
        if match.start() > position:
            segments.append(Segment(text[position : match.start()], current))
        position = match.end()
        if not closing:
            if current is not None:
                raise TokenError(TOKEN_NESTING)
            current = int(number)
        elif current != int(number):
            raise TokenError(TOKEN_MALFORMED)
        else:
            current = None
    if current is not None:
        raise TokenError(TOKEN_MALFORMED)
    if position < len(text):
        segments.append(Segment(text[position:], None))
    return segments


_MASKED = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            PLACEHOLDER_PATTERN.pattern,
            URL_PATTERN.pattern,
            EMAIL_PATTERN.pattern,
            PHONE_PATTERN.pattern,
        )
    ),
    re.IGNORECASE,
)


def mask(text: str) -> tuple[str, dict[int, str]]:
    """The unit as a model may see it, and the spans it must not touch."""
    spans: dict[int, str] = {}

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        if PHONE_PATTERN.fullmatch(value) and len(phone_digits(value)) < 9:
            return value
        spans[len(spans) + 1] = value
        return mask_token(len(spans))

    return _MASKED.sub(replace, text), spans


def unmask(text: str, spans: dict[int, str]) -> str:
    """Puts masked spans back. Check the masks with `validate_tokens` first."""

    def replace(match: re.Match[str]) -> str:
        number = match.group(3)
        if number is None:
            return match.group(0)
        return spans.get(int(number), match.group(0))

    return TOKEN_PATTERN.sub(replace, text)
