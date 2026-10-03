"""The configurator (A2): from what the owner said and what the account is, what
to ask, what to run now, what waits and what the product cannot do yet.

Four businesses, the same four as the plan names: a hairdresser, a plumber,
cottages and a kayak rental. Each golden test gives the whole answer for a
company that has just registered, against frozen catalogues
(`assistant_setup`), so a rule that changes shows as a changed answer.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from assistant_setup import (
    CARD_FIELDS,
    CATEGORY_OPTIONS,
    COMMANDS,
    CONTRACTS,
    EXAMPLES,
    PERSON_FIELDS,
    PRESET_LIST,
    PRESET_OPTIONS,
    SERVICE_FIELDS,
    catalog_from_contract,
    example,
    new_company,
)
from assistant_setup.report import render
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan
from saas_core.modules.core.organizations.command_registry import command, registered_commands
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.shared.assistant.configurator import (
    CARD,
    CARD_OPTIONS,
    ORGANIZATION,
    PRESETS,
    READS,
    SETUP,
    WRITES,
    configure,
)
from saas_core.modules.shared.assistant.profile_schema import PROFILE_SCHEMA, validate_profile
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from test_command_evals import assistant, invocation, owner


def ask(key: str, reason: str, proposal: Any = None, options: Any = ()) -> dict[str, Any]:
    return {
        "key": key,
        "kind": "ask",
        "reason": reason,
        "proposal": proposal,
        "options": list(options),
    }


def confirm(key: str, origin: str, proposal: Any) -> dict[str, Any]:
    return {"key": key, "kind": "confirm", "reason": origin, "proposal": proposal, "options": []}


def step(ref: str, command: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ref": ref, "command": command, "arguments": arguments}


def waits(ref: str, command: str, *waits_for: str) -> dict[str, Any]:
    return {"ref": ref, "reason": "waits", "command": command, "waits_for": list(waits_for)}


def no_command(ref: str, command: str) -> dict[str, Any]:
    return {"ref": ref, "reason": "command_missing", "command": command, "waits_for": []}


def cannot(key: str, code: str, detail: str = "") -> dict[str, Any]:
    return {"key": key, "code": code, "detail": detail}


def card(**given: Any) -> dict[str, Any]:
    return step("card", "profiles.organization.update@1", {**dict.fromkeys(CARD_FIELDS), **given})


def person(key: str, name: str) -> dict[str, Any]:
    return step(
        f"person:{key}", "booking.staff.add@1", {**dict.fromkeys(PERSON_FIELDS), "name": name}
    )


def from_preset(key: str, preset_id: str, name: str, **given: Any) -> dict[str, Any]:
    arguments = {
        "preset_id": preset_id,
        "version": None,
        "name": name,
        "duration_minutes": None,
        "staff_ids": None,
        "location_ids": None,
    }
    return step(f"offer:{key}", "booking.preset.apply@1", {**arguments, **given})


def with_ready(*preset_ids: str) -> dict[str, Any]:
    """The frozen list of kinds with some of the announced ones made ready."""
    return {
        "presets": [
            {**preset, "readiness": "ready"} if preset["id"] in preset_ids else preset
            for preset in PRESET_LIST["presets"]
        ]
    }


@pytest.mark.parametrize("name", EXAMPLES)
def test_the_examples_are_profiles(name: str) -> None:
    validate_profile(example(name))


def test_the_hairdresser_gets_a_place_now_and_the_rest_in_rounds() -> None:
    answer = configure(example("hairdresser"), new_company("Salon Ania"), COMMANDS)

    assert answer == {
        "missing": [
            # What the assistant guessed is asked about, never written.
            confirm("offers.colour.preset", "assistant", "core.specialist_visit"),
            ask("people.ola.hours", "person_needs_hours"),
            ask("company.category", "card_needs_category", "uroda-i-zdrowie", CATEGORY_OPTIONS),
            confirm("card.headline", "assistant", "Strzyżenie i koloryzacja w centrum Olsztyna"),
        ],
        "plan": [
            step(
                "organization",
                "organization.update@1",
                {
                    "name": "Salon Fryzjerski Ania",
                    "default_locale": None,
                    "timezone": None,
                    "currency": None,
                },
            ),
            card(
                display_name="Salon Fryzjerski Ania",
                contact_phone="+48 600 100 200",
                contact_address="ul. Mazurska 4, 10-520 Olsztyn",
                city_slug="olsztyn",
            ),
            step(
                "place:salon",
                "booking.location.save@1",
                {
                    "location_id": None,
                    "name": "Salon na Mazurskiej",
                    "address": "ul. Mazurska 4, Olsztyn",
                },
            ),
            person("ania", "Ania"),
            person("ola", "Ola"),
        ],
        "blocked": [
            # A plan's arguments are fixed before it runs: the service needs
            # the ids of the place and the people, so it is the next round's.
            waits(
                "offer:cut", "booking.preset.apply@1", "place:salon", "person:ania", "person:ola"
            ),
            waits("hours:ania", "booking.staff.hours.set@1", "person:ania", "place:salon"),
        ],
        "unsupported": [cannot("offers.cut.price", "price_list")],
    }


def test_a_step_without_its_command_is_reported_never_planned() -> None:
    commands = COMMANDS - {"booking.staff.add@1"}

    answer = configure(example("hairdresser"), new_company("Salon Ania"), commands)

    assert [entry["ref"] for entry in answer["plan"]] == ["organization", "card", "place:salon"]
    assert answer["blocked"][:2] == [
        no_command("person:ania", "booking.staff.add@1"),
        no_command("person:ola", "booking.staff.add@1"),
    ]


def test_the_plumber_waits_for_visits_at_the_customers() -> None:
    answer = configure(example("plumber"), new_company("Hydraulik Kowalski"), COMMANDS)

    assert answer == {
        "missing": [
            ask("company.category", "card_needs_category", "uslugi-dla-domu", CATEGORY_OPTIONS),
        ],
        "plan": [
            card(
                display_name="Hydraulik Kowalski",
                contact_phone="+48 601 200 300",
                city_slug="mragowo",
            ),
            person("jan", "Jan Kowalski"),
        ],
        "blocked": [],
        "unsupported": [
            cannot("offers.repair", "preset_not_ready", "core.service_at_customer"),
            cannot("offers.install", "preset_not_ready", "core.service_at_customer"),
        ],
    }


def test_work_at_the_customers_still_needs_a_place_to_set_out_from() -> None:
    """A visit by the clock is booked in a person's hours, and hours are kept
    at a place — the plumber is asked for his base, not where he receives."""
    reads = new_company("Hydraulik Kowalski")
    reads[PRESETS] = with_ready("core.service_at_customer")

    answer = configure(example("plumber"), reads, COMMANDS)

    assert [entry["key"] for entry in answer["missing"]] == [
        "offers.install.duration_minutes",
        "places",
        "people.jan.hours",
        "company.category",
    ]
    assert ask("places", "offer_needs_base") in answer["missing"]
    assert [entry["ref"] for entry in answer["plan"]] == ["card", "person:jan"]
    # Nothing of the offers runs before the base is there.
    assert answer["blocked"] == []
    assert answer["unsupported"] == [cannot("offers.repair.price", "price_list")]

    # The base named and added, the person added: the offer starts from its preset.
    profile = example("plumber")
    profile["places"] = [
        {"key": "base", "name": {"value": "Baza Mrągowo", "origin": "owner", "confirmed": True}}
    ]
    reads[SETUP] = {
        "services": [],
        "locations": [
            {"id": "L1", "name": "Baza Mrągowo", "address": "", "active": True, "online": True}
        ],
        "resources": [],
        "staff": [{"id": "S1", "name": "Jan Kowalski", "hours_version": 1, "hours": []}],
    }
    answer = configure(profile, reads, COMMANDS)
    assert (
        from_preset(
            "repair",
            "core.service_at_customer",
            "Usuwanie awarii",
            duration_minutes=60,
            staff_ids=["S1"],
            location_ids=["L1"],
        )
        in answer["plan"]
    )


def test_the_cottages_get_a_card_and_a_language_and_wait_for_stays() -> None:
    answer = configure(example("cottages"), new_company("Domki nad Jeziorem"), COMMANDS)

    assert answer == {
        "missing": [
            # The preset names the category; the owner still says yes.
            ask("company.category", "card_needs_category", "turystyka-i-noclegi", CATEGORY_OPTIONS),
        ],
        "plan": [
            step(
                "languages",
                "organization.public_locales.update@1",
                {"public_locales": ["pl", "en"]},
            ),
            card(
                display_name="Domki nad Jeziorem",
                bio="Trzy całoroczne domki z własnym pomostem, 200 m od plaży.",
                contact_email="kontakt@domki-nad-jeziorem.test",
            ),
        ],
        "blocked": [],
        "unsupported": [
            cannot("company.city", "city_not_in_catalog", "Mikołajki"),
            cannot("offers.cottage", "preset_not_ready", "core.lodging"),
        ],
    }


def test_the_kayak_rental_gets_its_base_and_is_asked_what_transport_is() -> None:
    answer = configure(example("kayak-rental"), new_company("Kajaki Krutynia"), COMMANDS)

    assert answer == {
        "missing": [
            ask("offers.transport.preset", "offer_needs_kind", None, PRESET_OPTIONS),
            ask("company.category", "card_needs_category", "turystyka-i-noclegi", CATEGORY_OPTIONS),
        ],
        "plan": [
            card(
                display_name="Kajaki Krutynia",
                contact_phone="+48 602 300 400",
                city_slug="mragowo",
            ),
            step(
                "place:base",
                "booking.location.save@1",
                {
                    "location_id": None,
                    "name": "Przystań",
                    "address": "ul. Nadbrzeżna 2, Mrągowo",
                },
            ),
        ],
        "blocked": [],
        "unsupported": [cannot("offers.kayak", "preset_not_ready", "core.rental")],
    }


def test_a_stay_or_a_rental_starts_from_its_preset_without_a_duration() -> None:
    reads = new_company("Kajaki Krutynia")
    reads[PRESETS] = with_ready("core.rental")

    answer = configure(example("kayak-rental"), reads, COMMANDS)

    # The offer waits for the only place there is, and takes nobody's time.
    assert answer["blocked"] == [waits("offer:kayak", "booking.preset.apply@1", "place:base")]
    assert answer["unsupported"] == [cannot("offers.kayak.price", "price_list")]

    reads[SETUP] = {
        "services": [],
        "locations": [
            {
                "id": "L1",
                "name": "Przystań",
                "address": "ul. Nadbrzeżna 2, Mrągowo",
                "active": True,
                "online": True,
            }
        ],
        "resources": [],
        "staff": [],
    }
    answer = configure(example("kayak-rental"), reads, COMMANDS)
    assert (
        from_preset("kayak", "core.rental", "Kajak dwuosobowy", location_ids=["L1"])
        in answer["plan"]
    )


# --- Round after round -------------------------------------------------------------

WEEK = [
    {"weekday": day, "local_start": "09:00", "local_end": "17:00", "location_id": "L1"}
    for day in (1, 2, 3, 4, 5)
]


def _after_the_first_round(**service: Any) -> dict[str, dict[str, Any]]:
    """The hairdresser's account once the place and the people are there."""
    reads = new_company("Salon Fryzjerski Ania")
    reads[SETUP] = {
        "services": [service] if service else [],
        "locations": [
            {
                "id": "L1",
                "name": "Salon na Mazurskiej",
                "address": "ul. Mazurska 4, Olsztyn",
                "active": True,
                "online": True,
                "version": 1,
            }
        ],
        "resources": [],
        "staff": [
            {"id": "S1", "name": "Ania", "hours_version": 1, "hours": []},
            {"id": "S2", "name": "Ola", "hours_version": 1, "hours": []},
        ],
    }
    return reads


def test_run_again_after_a_round_it_answers_the_next_one() -> None:
    answer = configure(example("hairdresser"), _after_the_first_round(), COMMANDS)

    assert answer["blocked"] == []
    assert answer["plan"][-2:] == [
        from_preset(
            "cut",
            "core.specialist_visit",
            "Strzyżenie damskie",
            duration_minutes=45,
            staff_ids=["S1", "S2"],
            location_ids=["L1"],
        ),
        step("hours:ania", "booking.staff.hours.set@1", {"staff_id": "S1", "rules": WEEK}),
    ]


def test_without_the_preset_command_a_visit_by_the_clock_is_a_plain_service() -> None:
    commands = COMMANDS - {"booking.preset.apply@1"}

    answer = configure(example("hairdresser"), _after_the_first_round(), commands)

    assert (
        step(
            "offer:cut",
            "booking.offer.create@1",
            {
                **dict.fromkeys(SERVICE_FIELDS),
                "name": "Strzyżenie damskie",
                "duration_minutes": 45,
                "staff_ids": ["S1", "S2"],
                "location_ids": ["L1"],
            },
        )
        in answer["plan"]
    )


def test_when_the_account_matches_the_profile_only_the_owners_step_is_left() -> None:
    reads = _after_the_first_round(
        id="V1",
        name="strzyżenie  DAMSKIE",
        duration_minutes=45,
        staff_ids=["S1", "S2"],
        location_ids=["L1"],
        active=False,
    )
    reads[SETUP]["staff"][0]["hours"] = WEEK
    reads[ORGANIZATION]["name"] = "Salon Fryzjerski Ania"

    answer = configure(example("hairdresser"), reads, COMMANDS)

    # The card is still to write here; nothing is planned for bookings, and the
    # service is found by its name however it is spelt.
    assert [entry["ref"] for entry in answer["plan"]] == ["card"]
    assert answer["blocked"] == [
        {"ref": "offer:cut:switch_on", "reason": "person_only", "command": None, "waits_for": []}
    ]


def test_it_adds_to_a_service_and_never_takes_away() -> None:
    reads = _after_the_first_round(
        id="V1",
        name="Strzyżenie damskie",
        duration_minutes=30,
        staff_ids=["S9", "S1"],
        location_ids=["L1"],
        active=True,
    )

    answer = configure(example("hairdresser"), reads, COMMANDS)

    assert (
        step(
            "offer:cut",
            "booking.offer.update@1",
            {
                "service_id": "V1",
                **dict.fromkeys(SERVICE_FIELDS),
                "duration_minutes": 45,
                # S9 was put there by hand; the profile knows nothing of them.
                "staff_ids": ["S9", "S1", "S2"],
            },
        )
        in answer["plan"]
    )


def test_an_empty_profile_asks_what_the_company_does_and_sells() -> None:
    answer = configure({"schema": "company-profile.v1"}, new_company("Nowa firma"), COMMANDS)

    assert [(question["key"], question["reason"]) for question in answer["missing"]] == [
        ("company.activity", "what_company_does"),
        ("offers", "nothing_to_sell"),
        ("company.city", "card_needs_city"),
        ("company.category", "card_needs_category"),
    ]
    assert (answer["plan"], answer["blocked"], answer["unsupported"]) == ([], [], [])


def test_what_the_card_already_says_is_not_asked_about() -> None:
    reads = new_company("Nowa firma")
    reads[CARD] |= {"exists": True, "city_slug": "olsztyn", "category": "uroda-i-zdrowie"}

    answer = configure({"schema": "company-profile.v1"}, reads, COMMANDS)

    assert [question["key"] for question in answer["missing"]] == ["company.activity", "offers"]


def test_an_area_whose_reads_are_not_given_is_left_alone() -> None:
    """A product without bookings or without the directory: the configurator
    plans nothing there and says the offers cannot be set up."""
    reads = {ORGANIZATION: new_company("Salon Ania")[ORGANIZATION]}

    answer = configure(example("hairdresser"), reads, COMMANDS)

    assert [entry["ref"] for entry in answer["plan"]] == ["organization"]
    assert answer["unsupported"] == [
        cannot("offers.cut", "booking_unavailable"),
        cannot("offers.colour", "booking_unavailable"),
    ]


def test_without_the_list_of_kinds_places_are_set_up_and_offers_wait() -> None:
    """The registry before `booking.preset.list@1`: a place and a person need
    no kind of booking, an offer cannot be planned without one."""
    reads = new_company("Salon Fryzjerski Ania")
    del reads[PRESETS]

    answer = configure(example("hairdresser"), reads, COMMANDS)

    assert [entry["ref"] for entry in answer["plan"]] == [
        "card",
        "place:salon",
        "person:ania",
        "person:ola",
    ]
    assert answer["unsupported"] == [
        cannot("offers.cut", "presets_unavailable"),
        cannot("offers.colour", "presets_unavailable"),
    ]
    # Nobody's hours are asked for while no offer says who works.
    assert "people.ola.hours" not in [question["key"] for question in answer["missing"]]


def test_a_language_the_plan_does_not_allow_is_not_planned() -> None:
    reads = new_company("Domki nad Jeziorem")
    reads["organization.public_locales.read@1"]["additional_max"] = 0
    profile = example("cottages")
    profile["languages"]["value"] = ["pl", "de", "fr"]

    answer = configure(profile, reads, COMMANDS)

    assert "languages" not in [entry["ref"] for entry in answer["plan"]]
    assert answer["unsupported"][:2] == [
        cannot("languages", "language_not_offered", "fr"),
        cannot("languages", "language_limit", "de"),
    ]


def test_several_places_and_people_are_asked_about_by_name() -> None:
    profile = example("hairdresser")
    profile["places"].append({"key": "second", "name": {**profile["places"][0]["name"]}})
    profile["places"][1]["name"]["value"] = "Salon na Kołobrzeskiej"
    del profile["offers"][0]["people"]

    answer = configure(profile, new_company("Salon Ania"), COMMANDS)

    assert answer["missing"][:2] == [
        ask(
            "offers.cut.places",
            "offer_needs_place",
            None,
            [
                {"value": "salon", "label": dict.fromkeys(("pl", "en"), "Salon na Mazurskiej")},
                {"value": "second", "label": dict.fromkeys(("pl", "en"), "Salon na Kołobrzeskiej")},
            ],
        ),
        ask(
            "offers.cut.people",
            "offer_needs_person",
            None,
            [
                {"value": "ania", "label": dict.fromkeys(("pl", "en"), "Ania")},
                {"value": "ola", "label": dict.fromkeys(("pl", "en"), "Ola")},
            ],
        ),
    ]
    assert "offer:cut" not in [entry["ref"] for entry in answer["blocked"]]


# --- The directory's words ---------------------------------------------------------


@pytest.mark.parametrize(
    ("activity", "category"),
    [
        ("fryzjerka", "uroda-i-zdrowie"),
        ("hydraulik: awarie, instalacje wodne", "uslugi-dla-domu"),
        ("domki letniskowe nad jeziorem", "turystyka-i-noclegi"),
        ("Wypożyczalnia kajaków i transport na Krutyni", "turystyka-i-noclegi"),
        ("koszenie trawy i pielęgnacja ogrodów", "uslugi-dla-domu"),
        # The longer keyword is the more exact one.
        ("fotograf ślubny", "wydarzenia"),
        ("elektryk samochodowy", "motoryzacja"),
        ("gabinet weterynaryjny dla psów i kotów", "zwierzeta"),
        ("psi fryzjer", "zwierzeta"),
        # Two categories own the word: no guess.
        ("przeprowadzki", None),
        ("naprawa zegarków", None),
    ],
)
def test_the_directorys_keywords_name_a_category_for_what_owners_say(
    activity: str, category: str | None
) -> None:
    """Against the real directory (`packages/contracts/catalog/manifest.json`):
    its keywords are what the suggestion — and the directory's search — go by."""
    profile = {
        "schema": "company-profile.v1",
        "company": {"activity": {"value": activity, "origin": "owner", "confirmed": True}},
    }
    reads = new_company("Nowa firma")
    reads[CARD_OPTIONS] = catalog_from_contract()

    answer = configure(profile, reads, COMMANDS)

    (question,) = [entry for entry in answer["missing"] if entry["key"] == "company.category"]
    assert question["proposal"] == category


# --- The contract ------------------------------------------------------------------

SCHEMA_FILE = CONTRACTS / "assistant" / "company-profile.v1.schema.json"


def test_the_contract_file_is_the_schema() -> None:
    """`packages/contracts/assistant/` is written from the code, never by hand."""
    written = SCHEMA_FILE.exists() and json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    # Only when it differs: the file is kept as prettier formats it.
    if os.environ.get("ASSISTANT_CONTRACT_WRITE") and written != PROFILE_SCHEMA:
        SCHEMA_FILE.write_text(
            json.dumps(PROFILE_SCHEMA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == PROFILE_SCHEMA, (
        "The profile's schema changed. Write the contract again: "
        "ASSISTANT_CONTRACT_WRITE=1 uv run pytest tests/test_assistant_configurator.py, "
        "then `pnpm exec prettier --write packages/contracts/assistant`."
    )


# --- The product as it is today ----------------------------------------------------

REPORT_FILE = CONTRACTS.parent.parent / "docs" / "assistant" / "co-asystent-zalozy-dzis.md"
#: What stands between the four examples and a finished setup, today. Every
#: line is somebody's work in progress: when it lands, this is where it shows.
TODAY: dict[str, list[str]] = {
    # Every command the configurator plans with is registered.
    "commands_missing": [],
    # Stays, rentals and the visit at the customer's are ready (owner
    # decisions 67a and 68a); none of the four examples needs an announced kind.
    "presets_not_ready": [],
    # The price list is in the product; no command of the assistant writes to it.
    "no_price_list": [
        "cottages:offers.cottage.price",
        "hairdresser:offers.cut.price",
        "kayak-rental:offers.kayak.price",
        "plumber:offers.repair.price",
    ],
    "cities_not_in_catalog": [],
}
MOVED = (
    "The product moved, and this is the one test bound to the real contract. In one commit: "
    "(1) bring TODAY above in line with what is true now; (2) a command the configurator "
    "plans with joins `assistant_setup.COMMANDS` and the golden answers once it is "
    "registered; (3) write the report again: ASSISTANT_CONTRACT_WRITE=1 uv run pytest "
    "tests/test_assistant_configurator.py."
)


def _unsupported(answers: dict[str, Any], code: str, field: str) -> list[str]:
    return sorted({
        f"{name}:{entry['key']}" if field == "key" else entry[field]
        for name, (_profile, answer) in answers.items()
        for entry in answer["unsupported"]
        if entry["code"] == code
    })


@pytest.mark.django_db
def test_what_the_product_can_do_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """The four examples against the real registry, the real preset catalogue
    and the real directory, for a company that has just registered. The golden
    tests above pin the rules; this one pins the product, and writes the report
    the owner reads."""
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    registered = {spec.key for spec in registered_commands()}
    person = owner("today", ORGANIZATION)
    EntitlementSnapshot.all_objects.create(
        organization_id=person.organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"booking.enabled": True, "profiles.enabled": True},
        quotas={},
        sources={},
    )
    keys = [key for key in READS if key in registered]
    with activate_tenant_context(assistant(person)):
        results = execute_plan([invocation(key, {}) for key in keys])
    assert [result.status for result in results] == ["done"] * len(keys), results
    reads = {key: result.output for key, result in zip(keys, results, strict=True)}

    answers: dict[str, Any] = {}
    for name in EXAMPLES:
        profile = example(name)
        account = {
            **reads,
            # As the company registered: under the name its owner uses.
            ORGANIZATION: {**reads[ORGANIZATION], "name": profile["company"]["name"]["value"]},
        }
        answer = configure(profile, account, registered)
        for planned in answer["plan"]:
            # What it plans is what the command takes, field for field.
            schema = command(planned["command"]).input_schema
            assert not list(Draft202012Validator(schema).iter_errors(planned["arguments"])), planned
        answers[name] = (profile, answer)
        # Each of the four is told its category, not handed the whole list.
        (category,) = [q for q in answer["missing"] if q["key"] == "company.category"]
        assert category["proposal"], name

    missing_commands = sorted({*READS, *WRITES} - registered)
    assert {
        "commands_missing": missing_commands,
        "presets_not_ready": _unsupported(answers, "preset_not_ready", "detail"),
        "no_price_list": _unsupported(answers, "price_list", "key"),
        "cities_not_in_catalog": _unsupported(answers, "city_not_in_catalog", "detail"),
    } == TODAY, MOVED

    report = render(answers, reads[PRESETS], missing_commands)
    if os.environ.get("ASSISTANT_CONTRACT_WRITE"):
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(report, encoding="utf-8")
    assert REPORT_FILE.read_text(encoding="utf-8") == report, MOVED
