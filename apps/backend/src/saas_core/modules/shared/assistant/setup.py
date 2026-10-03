"""The setup conversation's own tools (ADR-076, „rozmowa zakładająca firmę”, A3-2).

A conversation that sets a company up gives its model three tools and no
other: note what the owner said, ask what is next, and offer the plan. The
model never writes a command's arguments — the configurator does — so the only
way from such a conversation to a write on the account is the owner's click
on the configurator's plan.

These are not registry commands: a note changes nothing in the account, and
the registry knows only reads, which write nothing, and writes, which take a
click. So they carry here what the executor would otherwise check: the person
and their permission (the profile's own service), the profile's schema and
size, and how many notes one call may hold.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.api import (
    Invocation,
    command,
    command_for_tool,
    command_tools,
    execute_plan,
)
from saas_core.modules.core.organizations.context import TenantContext

from .configurator import READS, SETUP, configure, fold, said_values
from .profile import ProfileState, read_profile, rewrite_profile

PROFILE_NOTE = "profile_note"
SETUP_STATUS = "setup_status"
SETUP_APPLY = "setup_apply"

#: Notes one call may hold; a turn's model calls are limited too
#: (`assistant.limits.model_steps_per_turn`).
MAX_NOTES = 20
#: Questions the model is shown at once: it asks one at a time anyway.
MAX_QUESTIONS = 6

_NO_INPUT = {"type": "object", "additionalProperties": False, "required": [], "properties": {}}
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": PROFILE_NOTE,
        "description": (
            "Writes facts about the company into its profile. Use it whenever the person "
            "tells you something about the company, before you answer. It changes nothing "
            "in the company's account. Each note names a field and its value:\n"
            "- company.name, company.activity (what the company does, in the person's "
            "words), company.city, company.address, company.phone, company.email: text;\n"
            "- company.category: a category key from the allowed answers of setup_status;\n"
            "- card.headline (one sentence), card.description: text;\n"
            '- languages: a list of two-letter codes, e.g. ["pl", "en"];\n'
            "- places.<key>.name, places.<key>.address: text;\n"
            "- people.<key>.name: text; people.<key>.hours: a list of "
            '{"weekday": 0-6 (0 is Monday), "start": "HH:MM", "end": "HH:MM", '
            '"place": "<place key>"};\n'
            "- offers.<key>.name: text; offers.<key>.preset: a kind of booking from the "
            "allowed answers of setup_status; offers.<key>.duration_minutes, "
            "offers.<key>.units, offers.<key>.capacity: whole numbers; offers.<key>.price: "
            '{"amount": "90.00", "currency": "PLN", "per": '
            '"booking" | "person" | "hour" | "day" | "night"}; offers.<key>.places, '
            "offers.<key>.people: lists of keys; offers.<key>.inputs.<name>: an answer "
            "setup_status asked for.\n"
            "<key> is a short name you choose for a new place, person or offer (lowercase "
            "letters, digits, underscore) and reuse for it afterwards; setup_status lists "
            "the keys in use. A null value removes the field; a null value for "
            "places.<key>, people.<key> or offers.<key> removes the whole entry."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["notes"],
            "properties": {
                "notes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_NOTES,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field", "value", "source"],
                        "properties": {
                            "field": {"type": "string", "description": "Which fact."},
                            "value": {"description": "The value, or null to remove it."},
                            "source": {
                                "type": "string",
                                "enum": ["owner", "assistant"],
                                "description": "owner: the person said exactly this in "
                                "this conversation. assistant: your own proposal or "
                                "inference; the person will be asked to confirm it and it "
                                "is never used before they do.",
                            },
                        },
                    },
                }
            },
        },
    },
    {
        "name": SETUP_STATUS,
        "description": (
            "Returns where the company's setup stands: the next questions to ask the "
            "person (most useful first, with the allowed answers), the steps that are "
            "ready to run, the steps that wait and why, what the product cannot do yet, "
            "and what is already known. Call it at the start of the conversation and after "
            "every note or applied plan, and ask what it says — do not decide yourself "
            "what is missing."
        ),
        "input_schema": _NO_INPUT,
    },
    {
        "name": SETUP_APPLY,
        "description": (
            "Offers the person the steps setup_status lists as ready. They see a preview "
            "of each step and must click to agree; nothing runs before that. Call it when "
            "the person wants to go on with what is ready — after telling them in plain "
            "words what will be set up. The result says which steps were done."
        ),
        "input_schema": _NO_INPUT,
    },
)
TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)
#: What the panel calls a step of the setup conversation.
TITLES = {
    PROFILE_NOTE: {"pl": "Zanotuj w profilu firmy", "en": "Note in the company profile"},
    SETUP_STATUS: {"pl": "Sprawdź, co jeszcze ustalić", "en": "Check what is left to settle"},
    SETUP_APPLY: {"pl": "Przygotuj plan zmian", "en": "Prepare the plan of changes"},
}

_KEY = "[a-z][a-z0-9_]{0,31}"
_FIELD = re.compile(
    "company\\.(?:name|activity|city|category|address|phone|email)"
    "|card\\.(?:headline|description)"
    "|languages"
    f"|places\\.{_KEY}(?:\\.(?:name|address))?"
    f"|people\\.{_KEY}(?:\\.(?:name|hours))?"
    f"|offers\\.{_KEY}(?:\\.(?:name|preset|duration_minutes|units|capacity|price|places|people"
    "|inputs\\.[a-z][a-z0-9_]{0,63}))?"
)
#: What ends up public or is used to reach people: the owner's word for it
#: counts only when they typed it themselves (ADR-076, A3-2 pkt 3).
_TYPED = re.compile(f"company\\.(?:name|address|phone|email)|places\\.{_KEY}\\.address")
#: Sent to the model as known, never as a value: nothing it asks needs them.
_WITHHELD = re.compile(f"company\\.(?:address|phone|email)|places\\.{_KEY}\\.address")
_LISTS = ("places", "people", "offers")


# --- profile_note ------------------------------------------------------------------


def note(arguments: Mapping[str, Any], *, owner_words: str, key: str) -> dict[str, Any]:
    """Writes the notes into the profile. `owner_words` is everything the owner
    wrote in this conversation; `key` makes a repeated call the same save."""
    notes = arguments["notes"]
    proposals: list[str] = []

    def rewrite(document: dict[str, Any]) -> dict[str, Any]:
        proposals.clear()
        changed = copy.deepcopy(document)
        for index, entry in enumerate(notes):
            if _write(changed, entry, owner_words, index):
                proposals.append(entry["field"])
        return changed

    state = rewrite_profile(rewrite=rewrite, request={"notes": notes}, idempotency_key=key)
    return {
        "noted": [entry["field"] for entry in notes],
        # Kept as the assistant's proposal: ask the person, or let them confirm
        # it in the profile beside the conversation.
        "to_confirm": proposals,
        "profile_version": state.version,
    }


def _write(document: dict[str, Any], entry: Mapping[str, Any], owner_words: str, at: int) -> bool:
    """Applies one note; True when it was kept as a proposal although the
    model named the owner as its source."""
    field, value = entry["field"], entry["value"]
    if not _FIELD.fullmatch(field):
        raise ValidationError(
            {"notes": {str(at): {"field": ["Nie ma takiego pola profilu."]}}}, code="unknown_field"
        )
    parts = field.split(".")
    if parts[0] in _LISTS and len(parts) == 2:
        if value is not None:
            raise ValidationError(
                {"notes": {str(at): {"field": ["Podaj pole wpisu, np. offers.<key>.name."]}}},
                code="entry_field_required",
            )
        _remove_entry(document, parts[0], parts[1])
        return False
    node, leaf = _node(document, parts, create=value is not None)
    if value is None:
        if node is not None:
            node.pop(leaf, None)
        _tidy(document)
        return False
    assert node is not None
    by_owner = entry["source"] == "owner"
    typed = not _TYPED.fullmatch(field) or _typed(field, value, owner_words)
    confirmed = by_owner and typed
    node[leaf] = {
        "value": value,
        "origin": "owner" if confirmed else "assistant",
        "confirmed": confirmed,
    }
    return by_owner and not confirmed


def _node(
    document: dict[str, Any], parts: list[str], *, create: bool
) -> tuple[dict[str, Any] | None, str]:
    """The dictionary a field lives in and its name there."""
    if len(parts) == 1:
        return document, parts[0]
    if parts[0] not in _LISTS:
        section = document.setdefault(parts[0], {}) if create else document.get(parts[0])
        return section, parts[1]
    entries = document.setdefault(parts[0], []) if create else document.get(parts[0], [])
    entry = next((item for item in entries if item["key"] == parts[1]), None)
    if entry is None:
        if not create:
            return None, parts[-1]
        entry = {"key": parts[1]}
        entries.append(entry)
    if parts[2] != "inputs":
        return entry, parts[2]
    inputs = entry.setdefault("inputs", {}) if create else entry.get("inputs")
    return inputs, parts[3]


def _remove_entry(document: dict[str, Any], listed: str, key: str) -> None:
    """Takes the entry out with everything that points at it."""
    document[listed] = [item for item in document.get(listed, []) if item["key"] != key]
    for offer in document.get("offers", []) if listed != "offers" else []:
        links = offer.get(listed)
        if links is not None:
            links["value"] = [item for item in links["value"] if item != key]
    for person in document.get("people", []) if listed == "places" else []:
        hours = person.get("hours")
        if hours is not None:
            hours["value"] = [rule for rule in hours["value"] if rule["place"] != key]
    _tidy(document)


def _tidy(document: dict[str, Any]) -> None:
    """No empty sections left behind: the schema has none."""
    for name in ("company", "card", *_LISTS):
        if name in document and not document[name]:
            del document[name]
    for offer in document.get("offers", []):
        if "inputs" in offer and not offer["inputs"]:
            del offer["inputs"]


def _typed(field: str, value: Any, owner_words: str) -> bool:
    """Whether the owner wrote this value themselves, spacing, case and
    punctuation aside — a model that changes one digit does not pass."""
    if not isinstance(value, str):
        return False
    if field == "company.phone":
        digits = "".join(char for char in value if char.isdigit())
        written = "".join(char for char in owner_words if char.isdigit())
        # With or without Poland's prefix, which people rarely type.
        local = digits[2:] if len(digits) == 11 and digits.startswith("48") else digits
        return len(local) >= 7 and local in written
    return f" {fold(value)} " in f" {fold(owner_words)} "


# --- setup_status and setup_apply --------------------------------------------------


def status(context: TenantContext, *, language: str, keep: bool = True) -> dict[str, Any]:
    """Where the setup stands, in what the model needs to ask the next thing.
    `keep=False` leaves the profile as it is (a read by the panel)."""
    profile, answer = _answer(context, keep=keep)
    questions = answer["missing"]
    return {
        "questions": [_question(entry, language) for entry in questions[:MAX_QUESTIONS]],
        "more_questions": max(0, len(questions) - MAX_QUESTIONS),
        "ready": [
            {"step": step["ref"], "action": command(step["command"]).title[language]}
            for step in answer["plan"]
        ],
        "waiting": [
            {"step": step["ref"], "why": step["reason"], "after": step["waits_for"]}
            for step in answer["blocked"]
        ],
        "unsupported": answer["unsupported"],
        "known": [
            {"field": field, "confirmed": node["confirmed"]}
            if _WITHHELD.fullmatch(field)
            else {"field": field, "value": node["value"], "confirmed": node["confirmed"]}
            for field, node in said_values(profile.document)
        ],
    }


def planned(context: TenantContext) -> list[dict[str, Any]]:
    """The steps ready to run now, each with the step id the server gives it."""
    _profile, answer = _answer(context, keep=True)
    return [
        {
            "ref": step["ref"],
            "command": step["command"],
            "arguments": step["arguments"],
            "step_id": str(uuid.uuid4()),
        }
        for step in answer["plan"]
    ]


def invocations(steps: Sequence[Mapping[str, Any]]) -> list[Invocation]:
    return [
        Invocation(command=step["command"], arguments=step["arguments"], step_id=step["step_id"])
        for step in steps
    ]


def _answer(
    context: TenantContext, *, keep: bool
) -> tuple[ProfileState, dict[str, list[dict[str, Any]]]]:
    """The configurator's answer for the profile and the account as they are
    now — the account read through the registry, as the person. What the
    account already has joins the profile first, and stays there with `keep`:
    a note may then point at it by its key."""
    allowed = frozenset(command_for_tool(tool["name"]).key for tool in command_tools(context))
    keys = [key for key in READS if key in allowed]
    results = execute_plan([
        Invocation(command=key, arguments={}, step_id=str(uuid.uuid4())) for key in keys
    ])
    reads = {
        key: result.output
        for key, result in zip(keys, results, strict=True)
        if result.status == "done" and result.output is not None
    }
    profile = read_profile()
    seeded = _seeded(profile.document, reads)
    if seeded != profile.document:
        if keep:
            profile = rewrite_profile(
                rewrite=lambda document: _seeded(document, reads),
                request={"seed": sorted(reads)},
                idempotency_key=f"seed:{uuid.uuid4()}",
            )
        else:
            profile = ProfileState(profile.version, seeded, profile.updated_at)
    return profile, configure(profile.document, reads, allowed)


def _seeded(document: dict[str, Any], reads: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The profile with the places and people the account already has — facts,
    so nobody is asked for a place that exists."""
    setup = reads.get(SETUP)
    if setup is None:
        return document
    seeded = copy.deepcopy(document)
    places = _seed(seeded, "places", setup["locations"], "place")
    for location, key in places.items():
        address = next(item["address"] for item in setup["locations"] if item["id"] == location)
        entry = next(item for item in seeded["places"] if item["key"] == key)
        if address and "address" not in entry:
            entry["address"] = _fact(address)
    people = _seed(seeded, "people", setup["staff"], "person")
    for person in setup["staff"]:
        entry = next(item for item in seeded["people"] if item["key"] == people[person["id"]])
        week = [
            {
                "weekday": rule["weekday"],
                "start": rule["local_start"],
                "end": rule["local_end"],
                "place": places[rule["location_id"]],
            }
            for rule in person.get("hours", [])
            if rule["location_id"] in places
        ]
        if week and "hours" not in entry:
            entry["hours"] = _fact(week)
    _tidy(seeded)
    return seeded


def _seed(
    document: dict[str, Any], listed: str, items: Sequence[Mapping[str, Any]], prefix: str
) -> dict[str, str]:
    """Adds the account's items the profile does not name yet; answers each
    item's key in the profile by its id in the account."""
    entries = document.setdefault(listed, [])
    by_name = {fold(entry["name"]["value"]): entry["key"] for entry in entries if "name" in entry}
    taken = {entry["key"] for entry in entries}
    keys: dict[str, str] = {}
    for item in items:
        key = by_name.get(fold(item["name"]))
        if key is None:
            key = next(
                candidate
                for number in range(1, len(taken) + 2)
                if (candidate := f"{prefix}_{number}") not in taken
            )
            taken.add(key)
            entries.append({"key": key, "name": _fact(item["name"])})
        keys[item["id"]] = key
    return keys


def _fact(value: Any) -> dict[str, Any]:
    return {"value": value, "origin": "account", "confirmed": True}


def _question(entry: Mapping[str, Any], language: str) -> dict[str, Any]:
    return {
        "field": entry["key"],
        "kind": entry["kind"],
        "why": entry["reason"],
        "proposal": entry["proposal"],
        "allowed": [
            {"value": option["value"], "label": option["label"].get(language, "")}
            for option in entry["options"]
        ],
    }
