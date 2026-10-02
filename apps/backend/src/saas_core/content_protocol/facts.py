"""Facts a translation must keep: amounts, prices, times, addresses, contacts.

A translation may reword anything except these. They are compared as
normalized values, so the way a language writes them does not count as a
change — `1 200 zł`, `1.200 zł` and `1200 zł` are one price — while a different
value, or a different currency, does: `120 PLN` is not what `120 zł` said, and a
price list checked against its source must keep the owner's own notation.

The same comparison tells when a source changed a fact its translation has not
caught up with yet.
"""

from __future__ import annotations

import re
from collections.abc import Callable

URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"'⟦⟧]*[^\s<>\"'⟦⟧.,;:!?)\]]", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A phone has at least nine digits; shorter runs are amounts and dates.
PHONE_PATTERN = re.compile(r"(?<![\w+])\+?\d[\d \u00a0().-]{7,}\d(?!\w)")
_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
# A separator followed by exactly three digits groups thousands; any other
# separator is the decimal point.
_NUMBER = r"\d{1,3}(?:[ \u00a0\u202f.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_CURRENCY = r"zł|pln|eur|€|usd|\$"
_MONEY = re.compile(
    rf"(?<!\w)(?P<before>{_CURRENCY})\s?(?P<amount_after>{_NUMBER})(?![\w])"
    rf"|(?<![\w.,])(?P<amount>{_NUMBER})\s?(?P<after>{_CURRENCY})(?!\w)",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(rf"(?<![\w.,])(?:{_NUMBER})(?!\w)")
_GROUPED = re.compile(r"(\d+(?:[.,]\d{3})*)(?:[.,](\d+))?")

Fact = tuple[str, str]


def phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def number_value(raw: str) -> str:
    compact = re.sub(r"[ \u00a0\u202f]", "", raw)
    match = _GROUPED.fullmatch(compact)
    if match is None:
        return compact
    whole = re.sub(r"[.,]", "", match.group(1)).lstrip("0") or "0"
    fraction = (match.group(2) or "").rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def _url_value(raw: str) -> str:
    scheme, separator, rest = raw.partition("://")
    if not separator:
        rest, scheme = raw, ""
    host, slash, path = rest.partition("/")
    prefix = f"{scheme.lower()}://" if scheme else ""
    return f"{prefix}{host.lower()}{slash}{path}"


# Mark and mask tokens (`⟦1⟧`, `⟦/1⟧`, `⟦m:1⟧`) carry numbers that are not facts.
_TOKENS = re.compile(r"⟦(?:/?\d{1,3}|m:\d{1,3})⟧")


def extract_facts(text: str) -> frozenset[Fact]:
    facts: set[Fact] = set()
    remaining = _TOKENS.sub(" ", text)

    def take(
        pattern: re.Pattern[str], kind: str, value_of: Callable[[re.Match[str]], str | None]
    ) -> None:
        nonlocal remaining

        def replace(match: re.Match[str]) -> str:
            value = value_of(match)
            if value is None:
                return match.group(0)
            facts.add((kind, value))
            return " "

        remaining = pattern.sub(replace, remaining)

    take(URL_PATTERN, "url", lambda match: _url_value(match.group(0)))
    take(EMAIL_PATTERN, "email", lambda match: match.group(0).casefold())

    def phone(match: re.Match[str]) -> str | None:
        digits = phone_digits(match.group(0))
        if len(digits) < 9:
            return None
        return ("+" if match.group(0).startswith("+") else "") + digits

    take(PHONE_PATTERN, "phone", phone)
    take(_TIME, "time", lambda match: f"{int(match.group(1))}:{match.group(2)}")

    def money(match: re.Match[str]) -> str:
        amount = match.group("amount") or match.group("amount_after")
        currency = match.group("after") or match.group("before")
        return f"{number_value(amount)} {currency.casefold()}"

    take(_MONEY, "money", money)
    take(_BARE_NUMBER, "number", lambda match: number_value(match.group(0)))
    return frozenset(facts)
