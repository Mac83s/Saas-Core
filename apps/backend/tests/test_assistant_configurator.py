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
from rest_framework.exceptions import ValidationError

from assistant_setup import (
    CARD_FIELDS,
    CATEGORY_OPTIONS,
    COMMANDS,
    CONTRACTS,
    EXAMPLES,
    PERSON_FIELDS,
    PRESET_LIST,
    PRICE_FIELDS,
    SEASON_FIELDS,
    SERVICE_FIELDS,
    VAT_OPTIONS,
    catalog_from_contract,
    example,
    kinds,
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
    PRICES,
    READS,
    SEASONS,
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


def ask(
    key: str, reason: str, proposal: Any = None, options: Any = (), soon: Any = ()
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": "ask",
        "reason": reason,
        "proposal": proposal,
        "options": list(options),
        "soon": list(soon),
    }


def confirm(key: str, origin: str, proposal: Any) -> dict[str, Any]:
    return {
        "key": key,
        "kind": "confirm",
        "reason": origin,
        "proposal": proposal,
        "options": [],
        "soon": [],
    }


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
            # The price is the owner's; its tax rate nobody said, so it is asked.
            ask("offers.cut.vat", "price_needs_vat", None, VAT_OPTIONS),
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
        "unsupported": [],
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
        "offers.repair.vat",
        "offers.install.duration_minutes",
        "places",
        "people.jan.hours",
        "company.category",
    ]
    assert ask("places", "offer_needs_base") in answer["missing"]
    assert [entry["ref"] for entry in answer["plan"]] == ["card", "person:jan"]
    # Nothing of the offers runs before the base is there.
    assert answer["blocked"] == []
    assert answer["unsupported"] == []

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
            # Only the kind that is ready is an answer; the rest are coming.
            ask(
                "offers.transport.preset",
                "offer_needs_kind",
                None,
                kinds(PRESET_LIST, ready=True),
                kinds(PRESET_LIST, ready=False),
            ),
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

    # The offer waits for the only place there is, and takes nobody's time;
    # its units and its price need its id, so they wait for the offer.
    assert answer["blocked"] == [
        waits("offer:kayak", "booking.preset.apply@1", "place:base"),
        waits("units:kayak", "booking.offer.units.set@1", "offer:kayak"),
        waits("price:kayak", "booking.price.save@1", "offer:kayak"),
    ]
    assert answer["unsupported"] == []

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
        "groups": [],
        "staff": [],
    }
    answer = configure(example("kayak-rental"), reads, COMMANDS)
    assert (
        from_preset("kayak", "core.rental", "Kajak dwuosobowy", location_ids=["L1"])
        in answer["plan"]
    )


# --- Units and prices ---------------------------------------------------------------


def units(key: str, service_id: str, count: int, capacity: int | None) -> dict[str, Any]:
    return step(
        f"units:{key}",
        "booking.offer.units.set@1",
        {"service_id": service_id, "count": count, "capacity": capacity, "location_id": None},
    )


def price(key: str, service_id: str, basis: str, amount_minor: int, vat: str) -> dict[str, Any]:
    return step(
        f"price:{key}",
        "booking.price.save@1",
        {
            **dict.fromkeys(PRICE_FIELDS),
            "service_id": service_id,
            "basis": basis,
            "amount_minor": amount_minor,
            "vat_code": vat,
        },
    )


SWITCH_ON = {
    "ref": "offer:cottage:switch_on",
    "reason": "person_only",
    "command": None,
    "waits_for": [],
}


def _cottages(**stay: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The cottages once their place and their stay are in the account: the
    stay from its preset, switched off, with nothing to book and no price."""
    profile = example("cottages")
    profile["places"] = [
        {"key": "site", "name": {"value": "Nad jeziorem", "origin": "owner", "confirmed": True}}
    ]
    reads = new_company("Domki nad Jeziorem")
    reads[PRESETS] = with_ready("core.lodging")
    reads[PRESETS]["presets"][2]["required_inputs"] = []
    reads[SETUP] = {
        "services": [
            {
                "id": "V1",
                "name": "Domek 6-osobowy",
                "time_model": "range",
                "range_unit": "night",
                "duration_minutes": None,
                "staff_ids": [],
                "location_ids": ["L1"],
                "resource_ids": [],
                "group_ids": [],
                "active": False,
                **stay,
            }
        ],
        "locations": [
            {"id": "L1", "name": "Nad jeziorem", "address": "", "active": True, "online": True}
        ],
        "resources": [],
        "groups": [],
        "staff": [],
    }
    return profile, reads


def _pool(count: int, group: str = "G1", name: str = "Domek 6-osobowy") -> dict[str, Any]:
    return {
        "groups": [{"id": group, "name": name, "active": True}],
        "resources": [
            {"id": f"U{number}", "name": f"{name} {number}", "group_id": group, "active": True}
            for number in range(1, count + 1)
        ],
    }


def test_a_stay_gets_its_units_and_its_price_once_it_exists() -> None:
    profile, reads = _cottages()

    answer = configure(profile, reads, COMMANDS)

    assert answer["plan"][-2:] == [
        units("cottage", "V1", 3, 6),
        # 450.00 a night as the owner said it, with the rate the owner named.
        price("cottage", "V1", "per_time_unit", 45000, "8"),
    ]
    # Switching it on is offered only once nothing of the offer is left to set up.
    assert answer["blocked"] == []

    reads[SETUP].update(_pool(3))
    reads[SETUP]["services"][0]["group_ids"] = ["G1"]
    reads[PRICES]["prices"] = [{"id": "P1", "service_id": "V1", "group_id": None}]
    answer = configure(profile, reads, COMMANDS)

    assert [entry["ref"] for entry in answer["plan"] if ":" in entry["ref"]] == []
    assert answer["blocked"] == [SWITCH_ON]


def test_a_stay_without_units_or_a_price_is_asked_for_them() -> None:
    profile, reads = _cottages()
    for field in ("units", "capacity", "price", "vat"):
        del profile["offers"][0][field]

    answer = configure(profile, reads, COMMANDS)

    assert answer["missing"][:2] == [
        ask("offers.cottage.units", "offer_needs_units"),
        ask("offers.cottage.price", "offer_needs_price"),
    ]
    assert [entry["ref"] for entry in answer["plan"] if entry["ref"].endswith(":cottage")] == []

    # A visit by the clock often has no price: nobody is asked for one.
    answer = configure(example("hairdresser"), new_company("Salon Ania"), COMMANDS)
    assert "offers.colour.price" not in [entry["key"] for entry in answer["missing"]]


def test_units_are_only_ever_added() -> None:
    profile, reads = _cottages(group_ids=["G1"])
    reads[SETUP].update(_pool(5))

    # Five in the pool, three in the notes: the two more stay.
    answer = configure(profile, reads, COMMANDS)
    assert "units:cottage" not in [entry["ref"] for entry in answer["plan"]]

    # A pool under the offer's name that the offer is not linked to — as after
    # a draft removed and made again — is the offer's: linked, never cut.
    reads[SETUP]["services"][0]["group_ids"] = []
    answer = configure(profile, reads, COMMANDS)
    assert units("cottage", "V1", 5, 6) in answer["plan"]

    # Units arranged in the panel one by one are the panel's.
    reads[SETUP]["services"][0]["resource_ids"] = ["U1"]
    answer = configure(profile, reads, COMMANDS)
    assert "units:cottage" not in [entry["ref"] for entry in answer["plan"]]


def _priced(profile: dict[str, Any], reads: dict[str, dict[str, Any]]) -> list[str]:
    return [entry["ref"] for entry in configure(profile, reads, COMMANDS)["plan"]]


def test_money_is_never_guessed() -> None:
    profile, reads = _cottages()
    offer = profile["offers"][0]

    # The assistant's own number is asked about, never written.
    offer["price"] = {**offer["price"], "origin": "assistant", "confirmed": False}
    answer = configure(profile, reads, COMMANDS)
    assert "price:cottage" not in [entry["ref"] for entry in answer["plan"]]
    assert (
        confirm("offers.cottage.price", "assistant", offer["price"]["value"]) in (answer["missing"])
    )

    # Neither is the tax rate: without the owner's answer the price waits.
    profile, reads = _cottages()
    del profile["offers"][0]["vat"]
    answer = configure(profile, reads, COMMANDS)
    assert "price:cottage" not in [entry["ref"] for entry in answer["plan"]]
    assert ask("offers.cottage.vat", "price_needs_vat", None, VAT_OPTIONS) in answer["missing"]

    # A night is what this offer counts; a price for a day is asked about
    # again, never read as one for a night.
    profile, reads = _cottages()
    profile["offers"][0]["price"]["value"]["per"] = "day"
    answer = configure(profile, reads, COMMANDS)
    assert "price:cottage" not in [entry["ref"] for entry in answer["plan"]]
    (question,) = [q for q in answer["missing"] if q["key"] == "offers.cottage.price"]
    assert question["reason"] == "price_per_not_offered"
    assert [option["value"] for option in question["options"]] == ["booking", "person", "night"]

    # Another currency than the company's is not converted.
    profile, reads = _cottages()
    profile["offers"][0]["price"]["value"]["currency"] = "EUR"
    answer = configure(profile, reads, COMMANDS)
    assert "price:cottage" not in [entry["ref"] for entry in answer["plan"]]
    assert answer["unsupported"][-1] == cannot("offers.cottage.price", "price_currency", "PLN")


def test_an_offer_that_has_a_price_keeps_it() -> None:
    """The price list in the account is the owner's: changed in the panel
    since, it is not planned back to what the notes say."""
    profile, reads = _cottages(group_ids=["G1"])
    reads[SETUP].update(_pool(3))
    reads[PRICES]["prices"] = [
        {"id": "P1", "service_id": None, "group_id": "G1", "amount_minor": 50000}
    ]

    assert "price:cottage" not in _priced(profile, reads)


# --- Seasons ------------------------------------------------------------------------

SUMMER = {"name": "Wakacje", "starts_on": "2027-07-01", "ends_on": "2027-08-31", "min_stay": 7}
MAY = {"starts_on": "2027-05-01", "ends_on": "2027-05-03", "arrival_days": [4, 5]}


def said(value: Any, origin: str = "owner", confirmed: bool = True) -> dict[str, Any]:
    return {"value": value, "origin": origin, "confirmed": confirmed}


def season(key: str, service_id: str | None, **rules: Any) -> dict[str, Any]:
    return step(
        f"season:{key}:{rules['starts_on']}",
        "booking.season.save@1",
        {**dict.fromkeys(SEASON_FIELDS), "service_id": service_id, **rules},
    )


def test_a_stay_gets_the_seasons_the_owner_named_and_no_rule_nobody_said() -> None:
    profile, reads = _cottages()
    profile["offers"][0]["seasons"] = said([SUMMER, MAY])

    answer = configure(profile, reads, COMMANDS)

    # After the units and the price, each season with what was said of it:
    # the summer has no day of arrival, the long weekend no shortest stay.
    assert answer["plan"][-2:] == [
        season(
            "cottage",
            "V1",
            name="Wakacje",
            starts_on="2027-07-01",
            ends_on="2027-08-31",
            min_length=7,
        ),
        season(
            "cottage", "V1", starts_on="2027-05-01", ends_on="2027-05-03", start_weekdays=[4, 5]
        ),
    ]
    assert validate_profile(profile) is None
    # Nobody is asked for a season: one is planned only once the owner spoke of it.
    assert [q["key"] for q in answer["missing"] if "season" in q["key"]] == []


def test_a_season_waits_for_its_offer_like_the_units_and_the_price() -> None:
    profile, reads = _cottages()
    profile["offers"][0]["seasons"] = said([SUMMER])
    reads[SETUP]["services"] = []

    answer = configure(profile, reads, COMMANDS)

    assert answer["blocked"][-1] == waits(
        "season:cottage:2027-07-01", "booking.season.save@1", "offer:cottage"
    )


def test_a_season_the_offer_has_for_those_dates_is_left_alone() -> None:
    """Like a price: changed in the panel since, it is not planned back."""
    profile, reads = _cottages(group_ids=["G1"])
    profile["offers"][0]["seasons"] = said([SUMMER, MAY])
    reads[SEASONS]["seasons"] = [
        # The offer's own, with another shortest stay than the notes say.
        {"id": "R1", "service_id": "V1", "group_id": None, "min_length": 5, **_dates(SUMMER)},
        # Its pool's.
        {"id": "R2", "service_id": None, "group_id": "G1", **_dates(MAY)},
        # Another offer's season of the same dates says nothing about this one.
        {"id": "R3", "service_id": "V9", "group_id": None, **_dates(MAY)},
    ]

    refs = [entry["ref"] for entry in configure(profile, reads, COMMANDS)["plan"]]

    assert [ref for ref in refs if ref.startswith("season:")] == []


def _dates(season: dict[str, Any]) -> dict[str, Any]:
    return {"starts_on": season["starts_on"], "ends_on": season["ends_on"]}


def test_a_season_the_assistant_proposed_is_asked_about_never_written() -> None:
    profile, reads = _cottages()
    profile["offers"][0]["seasons"] = said([SUMMER], "assistant", False)

    answer = configure(profile, reads, COMMANDS)

    assert [e["ref"] for e in answer["plan"] if e["ref"].startswith("season:")] == []
    assert confirm("offers.cottage.seasons", "assistant", [SUMMER]) in answer["missing"]


def test_seasons_are_for_stays_and_need_their_commands() -> None:
    # A visit by the clock has no nights to count.
    profile = example("hairdresser")
    profile["offers"][0]["seasons"] = said([SUMMER])
    answer = configure(profile, _after_the_first_round(), COMMANDS)
    assert cannot("offers.cut.seasons", "seasons_for_stays") in answer["unsupported"]

    # The registry before the seasons' commands: said to be the panel's.
    profile, reads = _cottages()
    profile["offers"][0]["seasons"] = said([SUMMER])
    answer = configure(profile, reads, COMMANDS - {"booking.season.save@1"})
    assert answer["unsupported"][-1] == cannot("offers.cottage.seasons", "season_rules")
    del reads[SEASONS]
    answer = configure(profile, reads, COMMANDS)
    assert answer["unsupported"][-1] == cannot("offers.cottage.seasons", "season_rules")


def test_a_seasons_days_are_days_of_the_calendar() -> None:
    profile, _reads = _cottages()
    for wrong, field in (
        ({**SUMMER, "starts_on": "2027-02-30"}, "starts_on"),
        ({**SUMMER, "ends_on": "2027-06-30"}, "ends_on"),
    ):
        profile["offers"][0]["seasons"] = said([wrong])
        with pytest.raises(ValidationError) as refused:
            validate_profile(profile)
        detail = refused.value.detail["changes"]["offers"]["0"]["seasons"]["value"]["0"]
        assert list(detail) == [field]


# --- The undo of a draft --------------------------------------------------------------

MADE_HERE = "conversation:0199a0c0-0000-7000-8000-000000000001"


def _draft(**given: Any) -> dict[str, Any]:
    """A stay a setup conversation made and nobody switched on."""
    return {
        "id": "V2",
        "name": "Chata nad stawem",
        "time_model": "range",
        "range_unit": "night",
        "duration_minutes": None,
        "staff_ids": [],
        "location_ids": ["L1"],
        "resource_ids": [],
        "group_ids": [],
        "active": False,
        "draft": True,
        "origin_ref": MADE_HERE,
        **given,
    }


def discard(service_id: str, name: str) -> dict[str, Any]:
    return {
        **step(f"discard:{service_id}", "booking.offer.discard@1", {"service_id": service_id}),
        "about": name,
    }


def _discards(profile: dict[str, Any], reads: dict[str, Any], **more: Any) -> list[Any]:
    answer = configure(profile, reads, more.pop("commands", COMMANDS), **more)
    return [entry for entry in answer["plan"] if entry["ref"].startswith("discard:")]


def test_a_draft_whose_offer_left_the_notes_is_taken_back() -> None:
    profile, reads = _cottages(draft=True, origin_ref=MADE_HERE)
    reads[SETUP]["services"].append(_draft())

    # „Domek 6-osobowy” is still in the notes; „Chata nad stawem” no longer is.
    # The step is the last of the plan and names the draft, which the notes cannot.
    answer = configure(profile, reads, COMMANDS, setup_refs=[MADE_HERE])
    assert answer["plan"][-1] == discard("V2", "Chata nad stawem")

    # The same once the owner renamed the offer in the notes: the old draft
    # goes, and the offer is planned under its new name.
    profile["offers"][0]["name"]["value"] = "Domek letni"
    refs = [e["ref"] for e in configure(profile, reads, COMMANDS, setup_refs=[MADE_HERE])["plan"]]
    assert refs[-3:] == ["offer:cottage", "discard:V1", "discard:V2"]


def test_a_draft_renamed_in_the_panel_is_still_the_notes_offer() -> None:
    """Known by where it came from, not by what it is called: the notes keep
    the name they gave the offer, and the panel has renamed its draft."""
    profile, reads = _cottages(draft=True, origin_ref=MADE_HERE)
    reads[SETUP]["services"][0]["name"] = "Domek rodzinny"

    def refs(**more: Any) -> list[str]:
        answer = configure(profile, reads, COMMANDS, setup_refs=[MADE_HERE], **more)
        return [entry["ref"] for entry in answer["plan"]]

    # By its name alone the draft would be removed and the offer set up again.
    assert [ref for ref in refs() if ref in ("offer:cottage", "discard:V1")] == [
        "offer:cottage",
        "discard:V1",
    ]

    # The plan that made it says which offer it was made for, and under what name.
    made = {"V1": {"offer": "cottage", "name": "Domek 6-osobowy"}}
    planned = refs(origins=made)
    assert "discard:V1" not in planned and "offer:cottage" not in planned
    # What the offer still lacks is planned for the renamed draft itself.
    answer = configure(profile, reads, COMMANDS, setup_refs=[MADE_HERE], origins=made)
    assert {
        entry["arguments"]["service_id"]
        for entry in answer["plan"]
        if entry["ref"].split(":")[0] in ("units", "price", "season")
    } <= {"V1"}

    # The notes call the offer something else by now: another offer — its key
    # may have been used again — so the old draft goes and the new one is set up.
    profile["offers"][0]["name"]["value"] = "Domek letni"
    assert [ref for ref in refs(origins=made) if ref in ("offer:cottage", "discard:V1")] == [
        "offer:cottage",
        "discard:V1",
    ]
    profile["offers"][0]["name"]["value"] = "Domek 6-osobowy"

    # Made for another offer of the notes, or by a conversation that is not a
    # setup one: the name alone decides, as before.
    assert "discard:V1" in refs(origins={"V1": {"offer": "hut", "name": "Domek 6-osobowy"}})
    answer = configure(profile, reads, COMMANDS, setup_refs=[], origins=made)
    assert "offer:cottage" in [entry["ref"] for entry in answer["plan"]]

    # The offer left the notes: its draft is offered for removal under the
    # name it has now.
    profile["offers"] = []
    assert _discards(profile, reads, setup_refs=[MADE_HERE], origins=made) == [
        discard("V1", "Domek rodzinny")
    ]


def test_only_a_draft_the_setup_conversation_made_is_the_notes_to_take_back() -> None:
    profile, reads = _cottages()

    # Made in the panel, or by the assistant in an ordinary conversation.
    for origin in ("", "conversation:0199a0c0-0000-7000-8000-000000000009"):
        reads[SETUP]["services"] = [reads[SETUP]["services"][0], _draft(origin_ref=origin)]
        assert _discards(profile, reads, setup_refs=[MADE_HERE]) == []

    # Ever switched on: customers, the site and the history may name it.
    reads[SETUP]["services"][1] = _draft(draft=False)
    assert _discards(profile, reads, setup_refs=[MADE_HERE]) == []

    # A name the notes still hold keeps its draft, confirmed or not, however it is written.
    reads[SETUP]["services"][1] = _draft()
    profile["offers"].append({"key": "hut", "name": said("chata nad stawem", "assistant", False)})
    assert _discards(profile, reads, setup_refs=[MADE_HERE]) == []

    # Without the command nothing is said of it: the account stays as it is.
    del profile["offers"][1]
    commands = COMMANDS - {"booking.offer.discard@1"}
    answer = configure(profile, reads, commands, setup_refs=[MADE_HERE])
    assert [entry["ref"] for entry in answer["blocked"] if "discard" in entry["ref"]] == []
    assert _discards(profile, reads, setup_refs=[MADE_HERE]) == [discard("V2", "Chata nad stawem")]


# --- The kinds of booking --------------------------------------------------------------


def test_only_a_ready_kind_is_an_answer_and_an_announced_one_is_named_as_coming() -> None:
    reads = new_company("Kajaki Krutynia")
    reads[PRESETS] = with_ready("core.rental")

    answer = configure(example("kayak-rental"), reads, COMMANDS)

    (question,) = [q for q in answer["missing"] if q["key"] == "offers.transport.preset"]
    assert [option["value"] for option in question["options"]] == [
        "core.specialist_visit",
        "core.rental",
    ]
    assert [option["label"]["pl"] for option in question["soon"]] == ["Usługa u klienta", "Nocleg"]
    # Every other question has nothing to announce.
    assert {len(q["soon"]) for q in answer["missing"] if q is not question} == {0}


def test_before_the_price_commands_a_price_is_said_to_be_the_panels() -> None:
    commands = COMMANDS - {"booking.price.save@1", "booking.offer.units.set@1"}
    reads = new_company("Kajaki Krutynia")
    reads[PRESETS] = with_ready("core.rental")

    answer = configure(example("kayak-rental"), reads, commands)

    assert answer["unsupported"] == [cannot("offers.kayak.price", "price_list")]
    assert answer["blocked"] == [waits("offer:kayak", "booking.preset.apply@1", "place:base")]


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
    # The price list's commands are registered: a price the owner gave is a
    # plan step, never a line of what the product cannot do.
    "no_price_list": [],
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
