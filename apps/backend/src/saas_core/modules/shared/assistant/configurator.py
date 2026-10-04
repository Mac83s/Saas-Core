"""What to ask and what to do next, worked out from the company's profile (A2).

A pure function: no model, no database, no command run here. It is given the
profile, the account as it is today and the catalogues — all as the outputs of
read commands, because the assistant reaches the other modules only through
the registry (ADR-076 pkt 9) — and the names of the commands it may plan with.
It answers four lists:

- `missing` — what to ask the owner, most useful first, with the allowed
  answers; a value the owner has not confirmed is asked about, never written;
- `plan` — commands that can run now, their arguments ready;
- `blocked` — steps that wait: for an earlier step (`waits`), for a command
  the product does not have yet (`command_missing`), or for the owner's own
  hand (`person_only`);
- `unsupported` — what the owner asked for and the product cannot do yet.

A plan's arguments are fixed before it runs, so a step cannot name what an
earlier step creates: run again after a round, the function answers the next
one, until nothing is left to plan. It only ever adds to the account — a
place, a person or a language the profile does not mention stays. A person's
working week is one value, though: the profile's week replaces the account's.

One thing it takes back: a draft a setup conversation made for an offer the
notes no longer name. Such a draft came from the notes and nobody ever
switched it on, so the owner taking the offer out of the notes — or renaming
it there — plans its removal, as a step of its own that cannot be undone.
What the owner made in the panel, or the assistant in an ordinary
conversation, is never the notes' to remove.

Money is never guessed. A price is planned only as the owner's own confirmed
amount, in the company's currency, for what the offer can charge for and with
the tax rate the owner named; anything of it that is missing is asked. And an
offer that already has a price keeps it: the price list in the account is the
owner's, a note about it never writes over it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Iterator, Mapping
from typing import Any

ORGANIZATION = "organization.read@1"
LANGUAGES = "organization.public_locales.read@1"
CARD = "profiles.organization.read@1"
CARD_OPTIONS = "profiles.catalog_options.read@1"
SETUP = "booking.setup.read@1"
PRESETS = "booking.preset.list@1"
PRICES = "booking.prices.read@1"
SEASONS = "booking.seasons.read@1"
#: The reads `configure` works from, by command; an area whose reads are not
#: given is left alone.
READS = (ORGANIZATION, LANGUAGES, CARD, CARD_OPTIONS, SETUP, PRESETS, PRICES, SEASONS)

_ORGANIZATION_UPDATE = "organization.update@1"
_LANGUAGES_UPDATE = "organization.public_locales.update@1"
_CARD_UPDATE = "profiles.organization.update@1"
_PLACE_SAVE = "booking.location.save@1"
_PERSON_ADD = "booking.staff.add@1"
_PRESET_APPLY = "booking.preset.apply@1"
_OFFER_CREATE = "booking.offer.create@1"
_OFFER_UPDATE = "booking.offer.update@1"
_HOURS_SET = "booking.staff.hours.set@1"
_UNITS_SET = "booking.offer.units.set@1"
_PRICE_SAVE = "booking.price.save@1"
_SEASON_SAVE = "booking.season.save@1"
_OFFER_DISCARD = "booking.offer.discard@1"
#: Every command a plan may hold; one the registry lacks is reported as
#: `command_missing`, never planned.
WRITES = (
    _ORGANIZATION_UPDATE,
    _LANGUAGES_UPDATE,
    _CARD_UPDATE,
    _PLACE_SAVE,
    _PERSON_ADD,
    _PRESET_APPLY,
    _OFFER_CREATE,
    _OFFER_UPDATE,
    _HOURS_SET,
    _UNITS_SET,
    _PRICE_SAVE,
    _SEASON_SAVE,
    _OFFER_DISCARD,
)

#: Every field of a command is sent; null keeps it (the commands' own rule).
_ORGANIZATION_FIELDS = ("name", "default_locale", "timezone", "currency")
_CARD_FIELDS = (
    "display_name",
    "headline",
    "bio",
    "contact_email",
    "contact_phone",
    "contact_address",
    "city_slug",
    "category",
)
_SERVICE_FIELDS = (
    "name",
    "duration_minutes",
    "buffer_before_minutes",
    "buffer_after_minutes",
    "minimum_notice_minutes",
    "staff_count",
    "public_staff_choice",
    "slot_step_minutes",
    "staff_ids",
    "location_ids",
    "resource_ids",
)
_PERSON_FIELDS = ("name", "phone", "service_ids", "hours", "invitation")
#: A price's and a season's fields beside `service_id`, which the step that
#: follows an offer is given (`_follow`).
_PRICE_FIELDS = (
    "price_id",
    "group_id",
    "resource_id",
    "name",
    "starts_on",
    "ends_on",
    "weekdays",
    "local_from",
    "local_to",
    "basis",
    "amount_minor",
    "vat_code",
    "included_people",
    "extra_person_amount_minor",
    "extra_person_per_time_unit",
    "category_prices",
    "length_discounts",
    "active",
)
_SEASON_FIELDS = (
    "season_id",
    "group_id",
    "resource_id",
    "name",
    "starts_on",
    "ends_on",
    "min_length",
    "max_length",
    "length_multiple",
    "start_weekdays",
    "end_weekdays",
    "notice_hours",
    "window_days",
    "closed",
    "buffer_after_minutes",
    "active",
)
#: What a price may be charged for, as the owner says it, with the basis the
#: price list keeps; a night or a day only where the offer counts them.
_PER_LABELS = {
    "booking": {"pl": "za rezerwację", "en": "per booking"},
    "person": {"pl": "za osobę", "en": "per person"},
    "night": {"pl": "za noc", "en": "per night"},
    "day": {"pl": "za dzień", "en": "per day"},
}
_VAT_LABELS = {
    "23": {"pl": "23%", "en": "23%"},
    "8": {"pl": "8%", "en": "8%"},
    "5": {"pl": "5%", "en": "5%"},
    "0": {"pl": "0%", "en": "0%"},
    "zw": {"pl": "zwolnione z VAT", "en": "VAT exempt"},
    "np": {"pl": "nie podlega VAT", "en": "outside VAT"},
}
#: The card's fields and where the profile keeps each.
_CARD_SOURCES = (
    ("display_name", "company", "name"),
    ("headline", "card", "headline"),
    ("bio", "card", "description"),
    ("contact_email", "company", "email"),
    ("contact_phone", "company", "phone"),
    ("contact_address", "company", "address"),
)
_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


def configure(
    profile: Mapping[str, Any],
    reads: Mapping[str, Mapping[str, Any]],
    commands: Collection[str],
    *,
    setup_refs: Collection[str] = (),
    origins: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """`setup_refs` are the company's setup conversations, as a service names
    the one that made it (`origin_ref`): only their drafts are the notes' to
    take back. `origins` says, by a service's id, which offer of the notes a
    setup conversation made it for and under what name: a service renamed in
    the panel since is still that offer."""
    run = _Run(profile, reads, commands, setup_refs, origins or {})
    _company(run)
    _languages(run)
    _card(run)
    _booking(run)
    for key, node in said_values(profile):
        if not node["confirmed"]:
            run.missing.append({
                "key": key,
                "kind": "confirm",
                "reason": node["origin"],
                "proposal": node["value"],
                "options": [],
                "soon": [],
            })
    return {
        "missing": sorted(run.missing, key=lambda question: _rank(question["key"])),
        "plan": run.plan,
        "blocked": run.blocked,
        "unsupported": run.unsupported,
    }


class _Run:
    def __init__(
        self,
        profile: Mapping[str, Any],
        reads: Mapping[str, Mapping[str, Any]],
        commands: Collection[str],
        setup_refs: Collection[str] = (),
        origins: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self.profile = profile
        self.reads = reads
        self.commands = frozenset(commands)
        self.setup_refs = frozenset(setup_refs)
        self.origins = dict(origins or {})
        self.missing: list[dict[str, Any]] = []
        self.plan: list[dict[str, Any]] = []
        self.blocked: list[dict[str, Any]] = []
        self.unsupported: list[dict[str, Any]] = []

    def made_for(self, service: Mapping[str, Any], key: str, name: str) -> bool:
        """Whether a setup conversation made this service for the notes' offer
        `key`, under the name the notes still give it. Renamed in the panel
        since, it stays that offer; an offer the notes call something else by
        now is another offer — its key may have been used again."""
        origin = self.origins.get(service["id"])
        return (
            origin is not None
            and service.get("origin_ref") in self.setup_refs
            and origin["offer"] == key
            and fold(origin["name"]) == fold(name)
        )

    def ask(
        self,
        key: str,
        reason: str,
        *,
        proposal: Any = None,
        options: Collection[Any] = (),
        soon: Collection[Any] = (),
    ) -> None:
        """`soon` are answers the product has announced and cannot take yet:
        named as coming, never offered."""
        if all(question["key"] != key for question in self.missing):
            self.missing.append({
                "key": key,
                "kind": "ask",
                "reason": reason,
                "proposal": proposal,
                "options": list(options),
                "soon": list(soon),
            })

    def step(self, ref: str, command: str, arguments: dict[str, Any], about: str = "") -> None:
        """`about` names what the step is about where the notes no longer do."""
        if command in self.commands:
            named = {"about": about} if about else {}
            self.plan.append({"ref": ref, "command": command, "arguments": arguments, **named})
        else:
            self.wait(ref, command, reason="command_missing")

    def wait(
        self, ref: str, command: str | None, waits_for: Collection[str] = (), reason: str = "waits"
    ) -> None:
        self.blocked.append({
            "ref": ref,
            "reason": reason,
            "command": command,
            "waits_for": list(waits_for),
        })

    def cannot(self, key: str, code: str, detail: str = "") -> None:
        self.unsupported.append({"key": key, "code": code, "detail": detail})

    def said(self, section: str, field: str) -> Any:
        return _confirmed(self.profile.get(section, {}).get(field))


# --- The profile's values ----------------------------------------------------------


def _confirmed(node: Mapping[str, Any] | None) -> Any:
    """The value, once the owner has confirmed it; None otherwise."""
    return node["value"] if node is not None and node["confirmed"] else None


def said_values(profile: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every value of the profile with its path; a list's entry by its key."""
    for section in ("company", "card"):
        for field, node in profile.get(section, {}).items():
            yield f"{section}.{field}", node
    if "languages" in profile:
        yield "languages", profile["languages"]
    for name in ("places", "people", "offers"):
        for entry in profile.get(name, []):
            for field, node in entry.items():
                path = f"{name}.{entry['key']}.{field}"
                if field == "inputs":
                    yield from ((f"{path}.{key}", answer) for key, answer in node.items())
                elif field != "key":
                    yield path, node


def _rank(key: str) -> int:
    """What the company does and sells first: the rest follows from it."""
    order = (
        (key == "company.activity"),
        (key == "offers"),
        key.startswith("offers."),
        key.startswith("places"),
        key.startswith("people") and not key.endswith(".hours"),
        key.startswith("people"),
        (key == "company.city"),
        (key == "company.category"),
    )
    return order.index(True) if True in order else len(order)


def fold(text: str) -> str:
    """A name as people compare it: case, accents, punctuation and spacing aside."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD))
    plain = "".join(
        char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(plain.casefold().split())


def _label(text: str) -> dict[str, str]:
    return {"pl": text, "en": text}


# --- The company, its languages and its card ---------------------------------------


def _company(run: _Run) -> None:
    if "activity" not in run.profile.get("company", {}):
        # Where every setup starts, whatever the product then holds of it.
        run.ask("company.activity", "what_company_does")
    account = run.reads.get(ORGANIZATION)
    name = run.said("company", "name")
    if account is not None and name is not None and name != account["name"]:
        run.step(
            "organization",
            _ORGANIZATION_UPDATE,
            {**dict.fromkeys(_ORGANIZATION_FIELDS), "name": name},
        )


def _languages(run: _Run) -> None:
    state = run.reads.get(LANGUAGES)
    wanted = _confirmed(run.profile.get("languages"))
    if state is None or wanted is None:
        return
    current = list(state["public_locales"])
    new = [language for language in wanted if language not in current]
    for language in new:
        if language not in state["offered"]:
            run.cannot("languages", "language_not_offered", language)
    addable = [language for language in new if language in state["offered"]]
    if not addable:
        return
    limit = state["additional_max"]
    after = [*current, *addable]
    if not state["adding_allowed"] or (limit is not None and len(after) - 1 > limit):
        run.cannot("languages", "language_limit", ", ".join(addable))
    else:
        run.step("languages", _LANGUAGES_UPDATE, {"public_locales": after})


def _card(run: _Run) -> None:
    card, options = run.reads.get(CARD), run.reads.get(CARD_OPTIONS)
    if card is None or options is None:
        return
    wanted = {
        field: value
        for field, section, name in _CARD_SOURCES
        if (value := run.said(section, name)) is not None
    }
    city = run.profile.get("company", {}).get("city")
    if city is None:
        # What the card already says is not asked about again.
        if not card.get("city_slug"):
            run.ask("company.city", "card_needs_city")
    elif (name := _confirmed(city)) is not None:
        slug = next(
            (entry["slug"] for entry in options["cities"] if fold(entry["name"]) == fold(name)),
            None,
        )
        if slug is None:
            run.cannot("company.city", "city_not_in_catalog", name)
        else:
            wanted["city_slug"] = slug
    category = run.profile.get("company", {}).get("category")
    keys = [entry["key"] for entry in options["categories"]]
    if category is None and keys and not card.get("category"):
        run.ask(
            "company.category",
            "card_needs_category",
            proposal=_proposed_category(run, options["categories"]),
            options=[
                {"value": entry["key"], "label": entry["label"]} for entry in options["categories"]
            ],
        )
    elif category is not None and (key := _confirmed(category)) is not None:
        if key in keys:
            wanted["category"] = key
        else:
            run.cannot("company.category", "category_unknown", key)
    changes = {field: value for field, value in wanted.items() if card.get(field) != value}
    if changes:
        run.step("card", _CARD_UPDATE, {**dict.fromkeys(_CARD_FIELDS), **changes})


def _proposed_category(run: _Run, categories: list[Mapping[str, Any]]) -> str | None:
    """The category an offer's preset names; else the one whose keyword comes
    first in what the owner said the company does and then sells — a trade is
    named before its details ("hydraulik: awarie, instalacje") — and, of two
    that begin at the same word, the longer ("fotograf ślubny" over "fotograf")."""
    keys = [entry["key"] for entry in categories]
    presets = {entry["id"]: entry for entry in (run.reads.get(PRESETS) or {}).get("presets", [])}
    offers = run.profile.get("offers", [])
    for offer in offers:
        hint = presets.get(_confirmed(offer.get("preset")), {}).get("catalog_category")
        if hint in keys:
            return str(hint)
    said = [run.said("company", "activity"), *(_confirmed(offer.get("name")) for offer in offers)]
    words = f" {fold(' '.join(text for text in said if text))} "
    best: dict[str, tuple[int, int]] = {}
    for entry in categories:
        found = [
            (at, -len(folded))
            for keywords in entry["keywords"].values()
            for keyword in keywords
            if (at := words.find(f" {(folded := fold(keyword))} ")) >= 0
        ]
        if found:
            best[entry["key"]] = min(found)
    leading = [key for key, match in best.items() if match == min(best.values())]
    # The same keyword in two categories says nothing about which it is.
    return leading[0] if len(leading) == 1 else None


# --- Places, people, offers and hours ----------------------------------------------


def _booking(run: _Run) -> None:
    setup, presets = run.reads.get(SETUP), run.reads.get(PRESETS)
    offers = run.profile.get("offers", [])
    if setup is None:
        for offer in offers:
            run.cannot(f"offers.{offer['key']}", "booking_unavailable")
        return
    if not offers:
        run.ask("offers", "nothing_to_sell")
    places = _places(run, setup)
    people = _people(run, setup)
    working: set[str] = set()
    if presets is None:
        # Places and people need no kind of booking; an offer cannot be told
        # from another without the list of kinds.
        for offer in offers:
            run.cannot(f"offers.{offer['key']}", "presets_unavailable")
    else:
        working = _offers(run, setup, presets, places, people)
    _hours(run, setup, places, people, working)
    _withdrawn(run, setup)


def _places(run: _Run, setup: Mapping[str, Any]) -> dict[str, str | None]:
    """Each named place of the profile with its id in the account, or None
    while it is still to be added."""
    existing = {fold(place["name"]): place for place in setup["locations"]}
    ids: dict[str, str | None] = {}
    for place in run.profile.get("places", []):
        key = place["key"]
        if "name" not in place:
            run.ask(f"places.{key}.name", "place_needs_name")
        name = _confirmed(place.get("name"))
        if name is None:
            continue
        address = _confirmed(place.get("address"))
        found = existing.get(fold(name))
        ids[key] = found["id"] if found is not None else None
        if found is None:
            run.step(
                f"place:{key}", _PLACE_SAVE, {"location_id": None, "name": name, "address": address}
            )
        elif address is not None and address != found["address"]:
            run.step(
                f"place:{key}",
                _PLACE_SAVE,
                {"location_id": found["id"], "name": None, "address": address},
            )
    return ids


def _people(run: _Run, setup: Mapping[str, Any]) -> dict[str, str | None]:
    existing = {fold(person["name"]): person for person in setup["staff"]}
    ids: dict[str, str | None] = {}
    for person in run.profile.get("people", []):
        key = person["key"]
        if "name" not in person:
            run.ask(f"people.{key}.name", "person_needs_name")
        name = _confirmed(person.get("name"))
        if name is None:
            continue
        found = existing.get(fold(name))
        ids[key] = found["id"] if found is not None else None
        if found is None:
            run.step(f"person:{key}", _PERSON_ADD, {**dict.fromkeys(_PERSON_FIELDS), "name": name})
    return ids


def _offers(
    run: _Run,
    setup: Mapping[str, Any],
    presets: Mapping[str, Any],
    places: dict[str, str | None],
    people: dict[str, str | None],
) -> set[str]:
    """Plans each offer the product can hold; answers the keys of the people
    who do one, so their hours are asked for."""
    known = {preset["id"]: preset for preset in presets["presets"]}
    services = {fold(service["name"]): service for service in setup["services"]}
    working: set[str] = set()
    for offer in run.profile.get("offers", []):
        path = f"offers.{offer['key']}"
        if "preset" not in offer:
            # Only a kind that is ready is an answer; an announced one is
            # named as coming, so nobody picks what cannot be set up.
            kinds = [
                (
                    preset["readiness"] == "ready",
                    {
                        "value": preset["id"],
                        "label": {
                            language: words["name"] for language, words in preset["labels"].items()
                        },
                    },
                )
                for preset in presets["presets"]
            ]
            run.ask(
                f"{path}.preset",
                "offer_needs_kind",
                options=[kind for ready, kind in kinds if ready],
                soon=[kind for ready, kind in kinds if not ready],
            )
        preset_id = _confirmed(offer.get("preset"))
        if preset_id is None:
            continue
        preset = known.get(preset_id)
        if preset is None:
            run.cannot(f"{path}.preset", "preset_unknown", preset_id)
            continue
        if preset["readiness"] != "ready":
            run.cannot(path, "preset_not_ready", preset_id)
            continue
        slot = preset["time_model"] == "slot"
        for field in ("name", *(("duration_minutes",) if slot else ())):
            if field not in offer:
                run.ask(f"{path}.{field}", "preset_requires")
        inputs = offer.get("inputs", {})
        for key in preset["required_inputs"]:
            if key not in inputs:
                run.ask(f"{path}.inputs.{key}", "preset_requires")
        # A visit by the clock is booked in a person's hours, and hours are
        # kept at a place — also when the work is done at the customer's:
        # the place is then where the company sets out from.
        where = _linked(
            run,
            offer,
            "places",
            places,
            slot or preset["place"] == "business",
            "offer_needs_base" if preset["place"] == "customer" else "offer_needs_place",
        )
        who = _linked(
            run, offer, "people", people, preset["booked_staff"] == "required", "offer_needs_person"
        )
        working |= set(who or ())
        name = _confirmed(offer.get("name"))
        duration = _confirmed(offer.get("duration_minutes"))
        answered = all(_confirmed(inputs.get(key)) is not None for key in preset["required_inputs"])
        if name is None or (slot and duration is None) or not answered:
            # Still asked for, so the owner hears all of it at once.
            _units(run, offer, preset, None, setup)
            _price(run, offer, preset, None, setup)
            _seasons(run, offer, preset, None)
            continue
        service = services.get(fold(name)) or next(
            # Not under that name any more: renamed in the panel, and still
            # the service this offer was set up as.
            (item for item in setup["services"] if run.made_for(item, offer["key"], name)),
            None,
        )
        units = _units(run, offer, preset, service, setup)
        price = _price(run, offer, preset, service, setup)
        seasons = _seasons(run, offer, preset, service)
        if where is None or who is None:
            continue
        then = [*(step for step in (units, price) if step is not None), *seasons]
        _offer(
            run, offer["key"], preset, name, duration, service, (where, who), places, people, then
        )
    return working


def _linked(
    run: _Run,
    offer: Mapping[str, Any],
    field: str,
    ids: dict[str, str | None],
    needed: bool,
    reason: str,
) -> list[str] | None:
    """The keys of the offer's places (or people) that can be planned with;
    None while that is still to be asked or confirmed."""
    listed = run.profile.get(field, [])
    path = f"offers.{offer['key']}.{field}"
    if field in offer:
        keys = _confirmed(offer[field])
        if keys is None or any(key not in ids for key in keys):
            return None
        if keys or not needed:
            return list(keys)
    if len(listed) == 1 and listed[0]["key"] in ids:
        # The only one there is: no need to ask which.
        return [listed[0]["key"]]
    if not needed:
        return []
    if not listed:
        run.ask(field, reason)
    elif len(listed) > 1:
        run.ask(
            path,
            reason,
            options=[
                {"value": entry["key"], "label": _label(name)}
                for entry in listed
                if (name := _confirmed(entry.get("name"))) is not None
            ],
        )
    return None


def _pool(service: Mapping[str, Any], setup: Mapping[str, Any]) -> tuple[bool, int] | None:
    """Whether the offer has its pool of units and how many switched-on units
    that pool has — the one it is linked to, or the company's group under the
    offer's name, which the units command would take. None where the units
    are arranged another way in the panel: single units, or several groups."""
    linked = list(service.get("group_ids", []))
    if service.get("resource_ids") or len(linked) > 1:
        return None
    pool = linked or [
        group["id"]
        for group in setup.get("groups", [])
        if fold(group["name"]) == fold(service["name"])
    ]
    count = sum(
        1 for unit in setup["resources"] if unit.get("group_id") in pool and unit.get("active")
    )
    return bool(linked), count


def _units(
    run: _Run,
    offer: Mapping[str, Any],
    preset: Mapping[str, Any],
    service: Mapping[str, Any] | None,
    setup: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The step that brings a stay's or a rental's pool up to the count the
    owner gave; asks for the count where the offer has no unit to book."""
    if preset["time_model"] != "range" or _UNITS_SET not in run.commands:
        return None
    key = offer["key"]
    pool = _pool(service, setup) if service is not None else (False, 0)
    if pool is None:
        return None
    linked, there = pool
    if "units" not in offer:
        if not (linked and there):
            run.ask(f"offers.{key}.units", "offer_needs_units")
        return None
    wanted = _confirmed(offer["units"])
    if wanted is None or (linked and there >= wanted):
        return None
    return {
        "ref": f"units:{key}",
        "command": _UNITS_SET,
        "arguments": {
            # Units are only ever added: the pool keeps what it has.
            "count": max(wanted, there),
            "capacity": _confirmed(offer.get("capacity")),
            "location_id": None,
        },
    }


def _basis(per: str, preset: Mapping[str, Any], service: Mapping[str, Any] | None) -> str | None:
    """The price list's basis for what the owner said the price is for; None
    where the offer cannot charge for that."""
    if per == "booking":
        return "per_booking"
    if per == "person":
        return "per_person"
    unit = (service or preset).get("range_unit")
    return "per_time_unit" if per in ("night", "day") and per == unit else None


def _price(
    run: _Run,
    offer: Mapping[str, Any],
    preset: Mapping[str, Any],
    service: Mapping[str, Any] | None,
    setup: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The step that saves the offer's base price, once the owner gave every
    part of it; asks for what is missing. An offer that has a price is left
    alone."""
    path = f"offers.{offer['key']}"
    account, prices = run.reads.get(ORGANIZATION), run.reads.get(PRICES)
    if _PRICE_SAVE not in run.commands or prices is None:
        if "price" in offer:
            # The registry before the price list's commands.
            run.cannot(f"{path}.price", "price_list")
        return None
    if account is None:
        return None
    if service is not None:
        scopes = {service["id"], *service.get("group_ids", [])}
        if any(
            rule.get("service_id") in scopes or rule.get("group_id") in scopes
            for rule in prices["prices"]
        ):
            return None
    if "price" not in offer:
        if preset["time_model"] == "range":
            # A stay or a rental is sold by its price; a visit often has none.
            run.ask(f"{path}.price", "offer_needs_price")
        return None
    price = offer["price"]["value"]
    if price["currency"] != account["currency"]:
        run.cannot(f"{path}.price", "price_currency", account["currency"])
        return None
    known = service is not None or "range_unit" in preset or preset["time_model"] != "range"
    basis = _basis(price["per"], preset, service)
    if basis is None and known:
        unit = (service or preset).get("range_unit")
        allowed = ["booking", "person", *([unit] if unit in ("night", "day") else [])]
        run.ask(
            f"{path}.price",
            "price_per_not_offered",
            options=[{"value": per, "label": _PER_LABELS[per]} for per in allowed],
        )
        return None
    if "vat" not in offer:
        run.ask(
            f"{path}.vat",
            "price_needs_vat",
            options=[{"value": code, "label": label} for code, label in _VAT_LABELS.items()],
        )
    vat = _confirmed(offer.get("vat"))
    if _confirmed(offer["price"]) is None or vat is None or basis is None:
        return None
    whole, _, cents = price["amount"].partition(".")
    return {
        "ref": f"price:{offer['key']}",
        "command": _PRICE_SAVE,
        "arguments": {
            **dict.fromkeys(_PRICE_FIELDS),
            "basis": basis,
            "amount_minor": int(whole) * 100 + int(cents or 0),
            "vat_code": vat,
        },
    }


def _seasons(
    run: _Run,
    offer: Mapping[str, Any],
    preset: Mapping[str, Any],
    service: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """The steps that save a stay's seasons as the owner said them: the dates,
    the shortest stay, the arrival days — and no rule nobody named. Nothing
    is asked: a season is planned only once the owner spoke of one. A season
    the offer already has for the same dates is left alone, like a price:
    changed in the panel since, it is not planned back to what the notes say."""
    path = f"offers.{offer['key']}.seasons"
    if "seasons" not in offer:
        return []
    if preset["time_model"] != "range":
        # A visit by the clock has no nights to count and no day of arrival.
        run.cannot(path, "seasons_for_stays")
        return []
    account = run.reads.get(SEASONS)
    if _SEASON_SAVE not in run.commands or account is None:
        # The registry before the seasons' commands.
        run.cannot(path, "season_rules")
        return []
    scopes = {service["id"], *service.get("group_ids", [])} if service is not None else set()
    there = {
        (season["starts_on"], season["ends_on"])
        for season in account["seasons"]
        if season.get("service_id") in scopes or season.get("group_id") in scopes
    }
    steps: list[dict[str, Any]] = []
    for season in _confirmed(offer["seasons"]) or []:
        dates = (season["starts_on"], season["ends_on"])
        if dates in there:
            continue
        there.add(dates)
        steps.append({
            "ref": f"season:{offer['key']}:{season['starts_on']}",
            "command": _SEASON_SAVE,
            "arguments": {
                **dict.fromkeys(_SEASON_FIELDS),
                "name": season.get("name"),
                "starts_on": season["starts_on"],
                "ends_on": season["ends_on"],
                "min_length": season.get("min_stay"),
                "start_weekdays": season.get("arrival_days"),
            },
        })
    return steps


def _follow(run: _Run, key: str, service_id: str | None, steps: list[dict[str, Any]]) -> None:
    """The offer's units, price and seasons: planned once the offer has its
    id, waiting for the offer until then."""
    for step in steps:
        if service_id is None:
            run.wait(step["ref"], step["command"], [f"offer:{key}"])
        else:
            run.step(step["ref"], step["command"], {"service_id": service_id, **step["arguments"]})


def _withdrawn(run: _Run, setup: Mapping[str, Any]) -> None:
    """The undo of a draft: an offer a setup conversation made, never switched
    on, that the notes no longer hold. A name the notes still have — confirmed
    or not — keeps its draft, and so does the offer the draft was made for
    while the notes call it what they called it then: a draft renamed in the
    panel is the same offer, not one to remove."""
    if _OFFER_DISCARD not in run.commands:
        return
    notes = {
        offer["key"]: offer["name"]["value"]
        for offer in run.profile.get("offers", [])
        if "name" in offer
    }
    named = {fold(name) for name in notes.values()}
    for service in setup["services"]:
        if (
            service.get("draft")
            and service.get("origin_ref") in run.setup_refs
            and fold(service["name"]) not in named
            and not any(run.made_for(service, key, name) for key, name in notes.items())
        ):
            run.step(
                f"discard:{service['id']}",
                _OFFER_DISCARD,
                {"service_id": service["id"]},
                about=service["name"],
            )


def _offer(
    run: _Run,
    key: str,
    preset: Mapping[str, Any],
    name: str,
    duration: int | None,
    service: Mapping[str, Any] | None,
    linked: tuple[list[str], list[str]],
    places: dict[str, str | None],
    people: dict[str, str | None],
    then: list[dict[str, Any]],
) -> None:
    """Plans the offer, and after it the steps that need its id (`then`)."""
    where, who = linked
    ref = f"offer:{key}"
    waits = [
        *(f"place:{place}" for place in where if places[place] is None),
        *(f"person:{person}" for person in who if people[person] is None),
    ]
    if service is None:
        # Through the preset once the product has the command; until then a
        # visit by the clock can be created as a plain service.
        plain = _PRESET_APPLY not in run.commands and preset["time_model"] == "slot"
        command = _OFFER_CREATE if plain else _PRESET_APPLY
        if waits:
            run.wait(ref, command, waits)
        else:
            links = {
                "staff_ids": [people[person] for person in who] or None,
                "location_ids": [places[place] for place in where] or None,
            }
            arguments: dict[str, Any]
            if plain:
                arguments = {
                    **dict.fromkeys(_SERVICE_FIELDS),
                    "name": name,
                    "duration_minutes": duration,
                    **links,
                }
            else:
                arguments = {
                    "preset_id": preset["id"],
                    "version": None,
                    "name": name,
                    "duration_minutes": duration,
                    **links,
                }
            run.step(ref, command, arguments)
        _follow(run, key, None, then)
        return
    if waits:
        run.wait(ref, _OFFER_UPDATE, waits)
    else:
        changes: dict[str, Any] = {}
        if duration is not None and service["duration_minutes"] != duration:
            changes["duration_minutes"] = duration
        for field, wanted in (
            ("staff_ids", [people[person] for person in who]),
            ("location_ids", [places[place] for place in where]),
        ):
            added = [item for item in wanted if item not in service[field]]
            if added:
                changes[field] = [*service[field], *added]
        if changes:
            run.step(
                ref,
                _OFFER_UPDATE,
                {"service_id": service["id"], **dict.fromkeys(_SERVICE_FIELDS), **changes},
            )
        elif not service["active"] and not then:
            # Making it bookable by the public is the owner's own step, once
            # nothing of the offer is left to set up.
            run.wait(f"{ref}:switch_on", None, reason="person_only")
    _follow(run, key, service["id"], then)


def _hours(
    run: _Run,
    setup: Mapping[str, Any],
    places: dict[str, str | None],
    people: dict[str, str | None],
    working: set[str],
) -> None:
    current = {person["id"]: person["hours"] for person in setup["staff"]}
    for person in run.profile.get("people", []):
        key = person["key"]
        if key not in people:
            continue
        if "hours" not in person:
            if key in working:
                run.ask(f"people.{key}.hours", "person_needs_hours")
            continue
        week = _confirmed(person["hours"])
        if week is None or any(rule["place"] not in places for rule in week):
            continue
        waits = [
            *([f"person:{key}"] if people[key] is None else []),
            *dict.fromkeys(
                f"place:{rule['place']}" for rule in week if places[rule["place"]] is None
            ),
        ]
        if waits:
            run.wait(f"hours:{key}", _HOURS_SET, waits)
            continue
        rules = sorted(
            (
                {
                    "weekday": rule["weekday"],
                    "local_start": rule["start"],
                    "local_end": rule["end"],
                    "location_id": places[rule["place"]],
                }
                for rule in week
            ),
            key=lambda rule: (rule["weekday"], rule["local_start"]),
        )
        if rules != current[people[key]]:
            run.step(f"hours:{key}", _HOURS_SET, {"staff_id": people[key], "rules": rules})
