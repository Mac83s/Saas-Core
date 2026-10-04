"""Which tools an ordinary conversation gets (ADR-076, uzupełnienie 2026-10-04 L3).

Every tool definition is sent with every call of the model, so a registry of
seventy commands made a plain question cost several cents before anything was
read. A conversation therefore gets the tools of the areas it has touched, and
of an area first only the ones that read:

- an area opens when the person's own words name it („cennik”, „godziny”);
- its tools that change things come once the person asks for a change;
- the model widens either on demand with one tool of the assistant's own,
  `more_tools`, which lists every area there is — so nothing is out of reach,
  it only costs one more call.

The choice is a pure function of the transcript: the same messages always give
the same tools, in the order they were added, so a provider's cache of the
earlier calls stays valid when an area joins. It decides only what a model is
offered — the executor checks every call again, whatever was offered.

Areas are named here by command names, as the configurator names the commands
it plans with. A command no area claims — a product's own — is an area by the
first part of its name, described by its commands' titles and opened on demand.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from saas_core.modules.core.organizations.api import command_for_tool

from .configurator import fold

MORE_TOOLS = "more_tools"
#: With this many commands or fewer, a conversation gets them all.
SELECT_ABOVE = 12
TITLE = {"pl": "Sięgnij po kolejny obszar panelu", "en": "Reach for another area of the panel"}


@dataclass(frozen=True, slots=True)
class Topic:
    key: str
    #: English, for the model: what a person does in this area.
    about: str
    #: Patterns over command names (`booking.price.save`), without versions.
    commands: tuple[str, ...]
    #: Beginnings of the words — folded, in Polish and English — with which a
    #: person names the area.
    words: tuple[str, ...]


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="company",
        about="the company's own data and settings: its name, time zone, currency and "
        "languages, the languages of its public pages, sign-in security, mail to customers",
        commands=("organization.*", "notifications.*"),
        words=(
            "firm",
            "stref",
            "walut",
            "jezyk",
            "bezpieczen",
            "logowan",
            "mail",
            "poczt",
            "nadawc",
            "company",
            "timezone",
            "currency",
            "language",
            "security",
            "sender",
            "email",
        ),
    ),
    Topic(
        key="offers",
        about="services and the schedule: the services (offers) and their kinds, drafts, the "
        "people and their working hours, the places, the units of a stay or a rental",
        commands=(
            "booking.setup.*",
            "booking.offer.*",
            "booking.preset.*",
            "booking.staff.*",
            "booking.location.*",
        ),
        words=(
            "uslug",
            "ofert",
            "grafik",
            "godzin",
            "pracown",
            "zespol",
            "miejsc",
            "lokalizac",
            "jednost",
            "szkic",
            "wizyta",
            "wizyty",
            "wizyte",
            "service",
            "offer",
            "schedule",
            "hours",
            "staff",
            "employee",
            "location",
            "unit",
            "draft",
        ),
    ),
    Topic(
        key="prices",
        about="the price list: prices and seasons' prices, extras and deposits, participant "
        "categories, whether amounts are entered net or gross, what a booking would cost",
        commands=(
            "booking.price.*",
            "booking.prices.*",
            "booking.extra.*",
            "booking.participant_category.*",
            "booking.quote.*",
            "pricing.*",
        ),
        words=(
            "cen",
            "koszt",
            "doplat",
            "kaucj",
            "vat",
            "netto",
            "brutto",
            "wycen",
            "rabat",
            "znizk",
            "zl",
            "pln",
            "price",
            "pricing",
            "cost",
            "deposit",
            "extra",
            "discount",
            "quote",
            "tax",
        ),
    ),
    Topic(
        key="seasons",
        about="seasons of stays and rentals and their booking rules: dates, the shortest and "
        "longest stay, arrival and departure days, closed dates",
        # The services' names and ids come with the setup read.
        commands=("booking.season.*", "booking.seasons.*", "booking.setup.read"),
        words=("sezon", "pobyt", "przyjazd", "wyjazd", "season", "stay", "arrival", "departure"),
    ),
    Topic(
        key="booking_settings",
        about="how bookings work for the whole company: online booking, reminders and "
        "notices, customers' self-service links, how long bookings are kept",
        commands=("booking.settings_*",),
        words=(
            "rezerwacj",
            "przypomn",
            "powiadom",
            "samoobslug",
            "odwol",
            "online",
            "booking",
            "reminder",
            "notice",
            "cancel",
        ),
    ),
    Topic(
        key="card",
        about="the company's public business card and its entry in the company directory",
        commands=("profiles.*",),
        words=("wizytowk", "katalog", "card", "directory"),
    ),
    Topic(
        key="website",
        about="the company's website: pages from templates, a page's text in a language, "
        "how a page looks in search results, inquiries from the site",
        commands=("sites.*",),
        words=(
            "stron",
            "witryn",
            "www",
            "szablon",
            "zapytan",
            "formularz",
            "seo",
            "website",
            "site",
            "page",
            "template",
            "inquir",
        ),
    ),
    Topic(
        key="translation",
        about="AI translation of the website: quotes and orders, the review of translations, "
        "the glossary, the translation settings",
        commands=("translation.*",),
        words=("tlumacz", "przetlumacz", "glosariusz", "slownik", "translat", "glossary"),
    ),
    Topic(
        key="documents",
        about="the documents customers accept: terms and the privacy policy",
        commands=("customers.*",),
        words=("regulamin", "polityk", "dokument", "terms", "privacy", "document"),
    ),
    Topic(
        key="inventory",
        about="the warehouse settings: low-stock alerts, lots, materials",
        commands=("inventory.*",),
        words=("magazyn", "material", "zapas", "parti", "stock", "inventor", "warehouse"),
    ),
)

#: Beginnings of the words with which a person asks for a change. Wide on
#: purpose: a miss costs one more call of the model, a false hit a few tool
#: definitions.
CHANGE_WORDS: tuple[str, ...] = (
    "zmien",
    "ustaw",
    "doda",
    "usun",
    "skasuj",
    "wylacz",
    "wlacz",
    "podnies",
    "podwyz",
    "obniz",
    "zapisz",
    "popraw",
    "utworz",
    "stworz",
    "zaloz",
    "opublikuj",
    "wycofaj",
    "przetlumacz",
    "przenies",
    "nazwij",
    "wpisz",
    "wydluz",
    "skroc",
    "zrob",
    "wroc",
    "przywroc",
    "cofnij",
    "niech",
    "change",
    "set",
    "add",
    "remove",
    "delete",
    "update",
    "raise",
    "lower",
    "increase",
    "decrease",
    "create",
    "make",
    "publish",
    "withdraw",
    "translate",
    "turn",
    "switch",
    "enable",
    "disable",
    "rename",
    "move",
    "save",
    "edit",
    "fix",
)


@dataclass(slots=True)
class _Area:
    """An area as this person has it: only the commands they may be offered."""

    key: str
    about: str
    words: tuple[str, ...]
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)


def said(text: str) -> tuple[str, str]:
    """A message of the person, as `select` reads it."""
    return ("said", text)


def called(name: str, arguments_json: str) -> tuple[str, str, str]:
    """A tool call of the model, as `select` reads it."""
    return ("called", name, arguments_json)


def select(
    available: Sequence[Mapping[str, Any]], events: Iterable[Sequence[str]]
) -> list[Mapping[str, Any]]:
    """The tools for the next call of the model.

    `available` is everything the person may be offered (`command_tools`);
    `events` is the conversation so far, oldest first — `said(text)` for each
    message of the person and `called(name, arguments_json)` for each tool
    call of the model.
    """
    if len(available) <= SELECT_ABOVE:
        return list(available)
    areas = _areas(available)
    writable: dict[str, bool] = {}
    order: list[str] = []

    def open_area(key: str, change: bool) -> None:
        area = areas.get(key)
        if area is None:
            return
        if key not in writable:
            order.extend(name for name in area.reads if name not in order)
        if change and not writable.get(key):
            order.extend(name for name in area.writes if name not in order)
        writable[key] = writable.get(key, False) or change

    by_tool = {
        name: (area.key, name in area.writes)
        for area in areas.values()
        for name in (*area.reads, *area.writes)
    }
    for event in events:
        if event[0] == "said":
            words = fold(event[1]).split()
            change = _names(words, CHANGE_WORDS)
            for area in areas.values():
                if _names(words, area.words):
                    open_area(area.key, change)
            if change:
                for key in list(writable):
                    open_area(key, True)
        elif event[1] == MORE_TOOLS:
            asked = _arguments(event[2])
            for key in asked.get("topics") or ():
                open_area(str(key), asked.get("change") is True)
        elif event[1] in by_tool:
            # Whatever was called is kept: a transcript must never name a tool
            # the model is no longer shown.
            key, writes = by_tool[event[1]]
            open_area(key, writes)
    by_name = {tool["name"]: tool for tool in available}
    return [_more_tools(areas), *(by_name[name] for name in order)]


def opened(arguments_json: str, available: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What a `more_tools` call is answered with: the areas it named that the
    person has, and the ones they do not."""
    asked = _arguments(arguments_json)
    areas = _areas(available)
    keys = [str(key) for key in asked.get("topics") or ()]
    return {
        "opened": [key for key in keys if key in areas],
        "unknown": [key for key in keys if key not in areas],
        "change": asked.get("change") is True,
    }


def _names(words: Sequence[str], stems: Sequence[str]) -> bool:
    return any(word.startswith(stem) for word in words for stem in stems)


def _arguments(arguments_json: str) -> Mapping[str, Any]:
    try:
        found = json.loads(arguments_json or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, Mapping) else {}


def _areas(available: Sequence[Mapping[str, Any]]) -> dict[str, _Area]:
    """The areas this person has a command in, in the order of `TOPICS`, then
    the ones no topic claims."""
    areas: dict[str, _Area] = {}
    unclaimed: dict[str, _Area] = {}
    titles: dict[str, list[str]] = {}
    for tool in available:
        spec = command_for_tool(tool["name"])
        claimed = [
            topic
            for topic in TOPICS
            if any(fnmatchcase(spec.name, pattern) for pattern in topic.commands)
        ]
        if claimed:
            targets = [
                areas.setdefault(topic.key, _Area(topic.key, topic.about, topic.words))
                for topic in claimed
            ]
        else:
            key = spec.name.split(".", 1)[0]
            targets = [unclaimed.setdefault(key, _Area(key, "", ()))]
            titles.setdefault(key, []).append(spec.title["en"])
        for area in targets:
            (area.reads if spec.risk == "read" else area.writes).append(tool["name"])
    for key, area in unclaimed.items():
        area.about = "; ".join(titles[key])
    ordered = {topic.key: areas[topic.key] for topic in TOPICS if topic.key in areas}
    return {**ordered, **{key: unclaimed[key] for key in sorted(unclaimed) if key not in ordered}}


def _more_tools(areas: Mapping[str, _Area]) -> dict[str, Any]:
    listing = "\n".join(f"- {area.key}: {area.about}" for area in areas.values())
    return {
        "name": MORE_TOOLS,
        "description": (
            "You are given the tools of the areas this conversation has touched so far, and "
            "of an area at first only the tools that read. Call this before you answer that "
            "something cannot be done here: `topics` are the areas you need, and `change` is "
            "true when the person wants something changed there — you then get the tools "
            "that change things, and every change still waits for the person's click. The "
            "tools come with your next step. It changes nothing in the company's account. "
            "The areas:\n" + listing
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["topics", "change"],
            "properties": {
                "topics": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "enum": list(areas)},
                    "description": "The areas to get the tools of.",
                },
                "change": {
                    "type": "boolean",
                    "description": "True to get the tools that change things as well.",
                },
            },
        },
    }
