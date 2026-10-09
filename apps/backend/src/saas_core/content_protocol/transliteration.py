"""Letters across scripts, by code (ADR-069 pkt 5 and 7, ADR-070 pkt 18).

A person's name is never sent to a model: a Latin-script language keeps it as
written, a Cyrillic one gets a transliteration. A language version's slug is
made from its translated title, never by a model, and is ASCII.

The rules read Polish spelling, the source language of most content here;
another Latin name comes out close enough, and a company that wants a
particular form says so in its glossary (`translate_as`).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

SCRIPT_LATIN = "Latn"
SCRIPT_CYRILLIC = "Cyrl"

_VOWELS = "aąeęioóuy"

# Longest first; lowercase, the case of the first letter is put back.
_POLISH_TO_CYRILLIC: tuple[tuple[str, str], ...] = (
    ("szcz", "щ"),
    ("dż", "дж"),
    ("dź", "дзь"),
    ("sz", "ш"),
    ("cz", "ч"),
    ("rz", "ж"),
    ("ch", "х"),
    ("ja", "я"),
    ("je", "е"),
    ("ju", "ю"),
    ("jo", "йо"),
    ("ia", "я"),
    ("ie", "е"),
    ("iu", "ю"),
    ("io", "ё"),
    ("a", "а"),
    ("ą", "он"),
    ("b", "б"),
    ("c", "ц"),
    ("ć", "ць"),
    ("d", "д"),
    ("e", "е"),
    ("ę", "ен"),
    ("f", "ф"),
    ("g", "г"),
    ("h", "х"),
    ("i", "и"),
    ("j", "й"),
    ("k", "к"),
    ("l", "ль"),
    ("ł", "л"),
    ("m", "м"),
    ("n", "н"),
    ("ń", "нь"),
    ("o", "о"),
    ("ó", "у"),
    ("p", "п"),
    ("q", "к"),
    ("r", "р"),
    ("s", "с"),
    ("ś", "сь"),
    ("t", "т"),
    ("u", "у"),
    ("v", "в"),
    ("w", "в"),
    ("x", "кс"),
    ("y", "ы"),
    ("z", "з"),
    ("ź", "зь"),
    ("ż", "ж"),
)
_CYRILLIC_SOFT_ENDINGS = re.compile(r"ль(?=[аеёиоуыэюя])")

_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
# Letters NFKD does not take apart into a base and a mark, and the German
# umlauts, which are written out rather than dropped (ADR-070 pkt 18).
_LATIN_FOLDS = str.maketrans({
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ø": "o",
    "Ø": "O",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ı": "i",
    "þ": "th",
    "Þ": "TH",
    "ð": "d",
    "Ð": "D",
})


def _word_to_cyrillic(word: str) -> str:
    lower = word.lower()
    out: list[str] = []
    position = 0
    while position < len(lower):
        for latin, cyrillic in _POLISH_TO_CYRILLIC:
            if not lower.startswith(latin, position):
                continue
            # `ia`, `ie`… soften the consonant before them; at a word's start or
            # after a vowel the `i` is a vowel of its own.
            if (
                latin[0] == "i"
                and len(latin) == 2
                and (position == 0 or lower[position - 1] in _VOWELS)
            ):
                continue
            # `ja`, `je`… after a consonant keep the consonant hard: "zje" → "зье".
            if (
                latin[0] == "j"
                and len(latin) == 2
                and position
                and lower[position - 1] not in _VOWELS
            ):
                out.append("ь")
            out.append(cyrillic)
            position += len(latin)
            break
        else:
            out.append(lower[position])
            position += 1
    result = _CYRILLIC_SOFT_ENDINGS.sub("л", "".join(out))
    if word[:1].isupper():
        result = result[:1].upper() + result[1:]
    return result


def transliterate_name(text: str, script: str) -> str:
    """A name as a reader of `script` should see it; Latin keeps it as written."""
    if script != SCRIPT_CYRILLIC:
        return text
    return re.sub(r"[^\W\d_]+", lambda match: _word_to_cyrillic(match.group(0)), text)


#: An apostrophe stands inside a word, straight or curly: „Owner's” is one.
_APOSTROPHES = re.compile("['\u2019\u2018\u02bc]")


def slug_from_title(title: str, *, max_length: int = 100, apostrophes: str = "") -> str:
    """An ASCII slug made from a title in any script the registry offers.

    An apostrophe is dropped, so „Dog Owner's Guide” is `dog-owners-guide`.
    Until 2026-10-09 it broke the word (`dog-owner-s-guide`), and
    `apostrophes="-"` still gives that spelling — for the two things that
    need it: recognising what was stored while the rule was the other one
    (`following_slug`; a tag's name typed again), and a heading's anchor,
    which the editor makes that way."""
    latin = "".join(_CYRILLIC_TO_LATIN.get(char, char) for char in title.lower())
    decomposed = unicodedata.normalize("NFKD", latin.translate(_LATIN_FOLDS))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    spelled = _APOSTROPHES.sub(apostrophes, ascii_text.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", spelled).strip("-")
    return slug[:max_length].rstrip("-")


def following_slug(
    title: str,
    *,
    stored: str,
    free: Callable[[str], str],
    fallback: str = "",
    max_length: int = 100,
) -> str:
    """The address of something whose address still follows its title or
    name: the first free one the title gives (`free` picks it; `fallback`
    where the title gives none) — unless `stored`, the address it has, is
    what the rule made from this very title while apostrophes still broke a
    word. Then it stays: an address made once does not move because the
    rule did, only when the title does."""
    slug = slug_from_title(title, max_length=max_length)
    earlier = slug_from_title(title, max_length=max_length, apostrophes="-")
    if earlier != slug and stored and free(earlier) == stored:
        return stored
    return free(slug or fallback)
