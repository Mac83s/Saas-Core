"""Which tools an ordinary conversation gets (ADR-076, uzupełnienie 2026-10-04 L3).

Every tool definition is sent with every call of the model, so a registry of
seventy commands made a plain question cost several cents before anything was
read. A conversation therefore gets the tools of the areas it has touched, and
of an area first only the ones that read:

- an area opens when the person's own words name it („cennik”, „godziny”);
  words too common to mean one („usługa”, „firma”, an amount in „zł”) count
  only while nothing is open;
- its tools that change things come once the person asks for a change;
- the model widens either on demand with one tool of the assistant's own,
  `more_tools`, which lists every area there is — so nothing is out of reach,
  it only costs one more call.

Widening is not free: a provider caches a request from its tools on, so a
tool added in the middle of a conversation has the whole conversation written
to the cache again. Hence the exact words, and hence no narrowing ever.

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
    #: English, for the model: what a person does in this area. Short — every
    #: call of the model carries all of them.
    about: str
    #: Patterns over command names (`booking.price.save`), without versions.
    commands: tuple[str, ...]
    #: Beginnings of the words — folded, in Polish and English — with which a
    #: person names the area; where a Polish ending changes the stem („waluta”,
    #: „w walucie”), both.
    words: tuple[str, ...]
    #: Words too common to open an area in the middle of a conversation
    #: („usługa”, „firma”, „strona”): they count only while no area is open.
    weak: tuple[str, ...] = ()


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="company",
        about="the company's name, time zone, currency and languages, sign-in security, "
        "mail to customers",
        commands=("organization.*", "notifications.*"),
        words=(
            "stref",
            "walut",
            "waluc",
            "jezyk",
            "bezpieczen",
            "logowan",
            "mail",
            "poczt",
            "nadawc",
            "timezone",
            "currency",
            "language",
            "security",
            "sender",
            "email",
        ),
        weak=("firm", "company"),
    ),
    Topic(
        key="offers",
        about="services (offers) and their kinds, drafts, people and working hours, places, "
        "units of a stay or a rental",
        commands=(
            "booking.setup.*",
            "booking.offer.*",
            "booking.preset.*",
            "booking.staff.*",
            "booking.location.*",
        ),
        words=(
            "grafik",
            "godzin",
            "pracown",
            "zespol",
            "lokalizac",
            "jednost",
            "szkic",
            "wizyta",
            "wizyty",
            "wizyte",
            "wizycie",
            "schedule",
            "hours",
            "staff",
            "employee",
            "location",
            "unit",
            "draft",
        ),
        weak=("uslug", "usludz", "ofert", "oferc", "miejsc", "service", "offer", "place"),
    ),
    Topic(
        key="prices",
        about="the price list: prices, season prices, extras, deposits, participant categories",
        commands=(
            "booking.price.*",
            "booking.prices.*",
            "booking.extra.*",
            "booking.participant_category.*",
        ),
        words=(
            "cen",
            "koszt",
            "doplat",
            "doplac",
            "kaucj",
            "vat",
            "netto",
            "brutto",
            "rabat",
            "rabac",
            "znizk",
            "znizc",
            "price",
            "pricing",
            "cost",
            "deposit",
            "extra",
            "discount",
            "tax",
        ),
        # An amount is said about a payment as often as about a price: alone
        # it names the price list only while nothing more exact is open.
        weak=("zl", "pln"),
    ),
    Topic(
        key="quote",
        about="what one booking would cost, for given dates, people and extras",
        commands=("booking.quote.*",),
        words=("wycen", "wylicz", "policz", "zaplac", "quote", "estimate"),
    ),
    Topic(
        key="seasons",
        about="seasons of stays and rentals: dates, shortest and longest stay, arrival and "
        "departure days, closed dates",
        commands=("booking.season.*", "booking.seasons.*"),
        words=(
            "sezon",
            "przyjazd",
            "przyjezd",
            "wyjazd",
            "wyjezd",
            "season",
            "arrival",
            "departure",
        ),
    ),
    Topic(
        key="requests",
        about="customers' booking requests that wait for the company's answer: reading "
        "them, accepting, declining",
        commands=("booking.request.*", "booking.requests.*"),
        words=("prosb", "odmow", "odmaw", "request", "declin"),
    ),
    Topic(
        key="orders",
        about="customers' orders and what was paid for them: reading an order, marking a "
        "payment the company received, taking back one marked by mistake",
        commands=("commerce.*",),
        words=(
            "zamowien",
            "wplat",
            "wplac",
            "platnos",
            "przelew",
            "przedplat",
            "zadatk",
            "zadatek",
            "zaliczk",
            "zwrot",
            "order",
            "payment",
            "paid",
            "refund",
            "transfer",
        ),
    ),
    Topic(
        key="booking_settings",
        about="booking settings of the whole company: online booking, reminders, notices, "
        "self-service links, how long bookings are kept, prices entered net or gross",
        # Net or gross is said by the price list itself (`amounts`); the setting
        # that changes it is asked for seldom.
        commands=("booking.settings_*", "pricing.*"),
        words=(
            "przypomn",
            "powiadom",
            "samoobslug",
            "samoobsludz",
            "odwol",
            "reminder",
            "notice",
            "cancel",
        ),
        weak=("rezerwacj", "booking", "online"),
    ),
    Topic(
        key="card",
        about="the public business card and the entry in the company directory",
        commands=("profiles.*",),
        words=("wizytowk", "wizytowc", "katalog", "card", "directory"),
    ),
    Topic(
        key="website",
        about="the website: pages from templates, texts per language, the search preview, "
        "inquiries from the site",
        commands=("sites.*",),
        words=(
            "witryn",
            "www",
            "szablon",
            "zapytan",
            "formularz",
            "seo",
            "podstron",
            "website",
            "template",
            "inquir",
        ),
        weak=("stron", "site", "page"),
    ),
    Topic(
        key="translation",
        about="AI translation of the website: quotes, orders, review, glossary, settings",
        commands=("translation.*",),
        words=("tlumacz", "przetlumacz", "glosariusz", "slownik", "translat", "glossary"),
    ),
    Topic(
        key="documents",
        about="documents customers accept: terms, privacy policy",
        commands=("customers.*",),
        words=(
            "regulamin",
            "polityk",
            "polityc",
            "dokument",
            "dokumenc",
            "terms",
            "privacy",
            "document",
        ),
    ),
    Topic(
        key="inventory",
        about="warehouse settings: low-stock alerts, lots, materials",
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
    "wycof",
    "oznacz",
    "zaznacz",
    "odnotuj",
    "przyjm",
    "zaakcept",
    "akceptuj",
    "odrzuc",
    "odmow",
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
    "mark",
    "record",
    "accept",
    "declin",
    "reject",
    "refus",
    "void",
)


@dataclass(slots=True)
class _Area:
    """An area as this person has it: only the commands they may be offered."""

    key: str
    about: str
    words: tuple[str, ...]
    weak: tuple[str, ...] = ()
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
            if not writable:
                # Nothing more exact was said, and nothing is open yet.
                for area in areas.values():
                    if _names(words, area.weak):
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
                areas.setdefault(topic.key, _Area(topic.key, topic.about, topic.words, topic.weak))
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
            "Gives you tools you do not have yet. Use a tool you already have whenever one "
            "fits; call this only when none does — for the tools of another area (`topics`), "
            "or for the tools that change things where yours only read (`change`: true; a "
            "change still waits for the person's click). The new tools come with your next "
            "step; nothing in the company's account changes. Areas:\n" + listing
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
