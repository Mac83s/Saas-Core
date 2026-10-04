"""Which tools an ordinary conversation is offered (ADR-076, 2026-10-04 L3): a
pure function of what the person wrote and what the model called."""

from __future__ import annotations

import json
from typing import Any

import pytest

from saas_core.modules.shared.assistant import topics
from saas_core.modules.shared.assistant.evals.runner import assistant_tools
from saas_core.modules.shared.assistant.topics import called, said, select

ALL: list[dict[str, Any]] = [
    {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
    for tool in assistant_tools()
]


def names(*events: Any) -> list[str]:
    return [tool["name"] for tool in select(ALL, events)]


def size(tools: list[str]) -> int:
    by_name = {tool["name"]: tool for tool in ALL}
    return sum(
        len(json.dumps(by_name[name], ensure_ascii=False)) for name in tools if name in by_name
    )


def test_a_question_brings_the_tools_that_read_its_area_and_nothing_else() -> None:
    offered = names(said("Ile kosztuje noc w Wigwamach?"))

    assert offered == [
        "more_tools",
        "booking_prices_read_v1",
        "booking_quote_read_v1",
        "pricing_settings_entry_read_v1",
    ]
    # A twentieth of the registry's definitions, not all of them.
    assert size(offered) * 15 < size([tool["name"] for tool in ALL])


def test_asking_for_a_change_brings_the_tools_that_change() -> None:
    offered = names(said("Zmień cenę Wigwamów na 300 zł"))

    assert offered[:4] == names(said("Ile kosztuje noc w Wigwamach?"))
    assert "booking_price_save_v1" in offered and "booking_extra_save_v1" in offered
    assert not [name for name in offered if name.startswith(("sites_", "translation_"))]
    # A change asked for later opens the areas already touched; the tools the
    # model was shown before keep their place, so a provider's cache holds.
    later = names(said("Ile kosztuje noc w Wigwamach?"), said("Podnieś ją o 20"))
    assert later == offered


def test_the_model_widens_on_demand_and_what_it_called_stays() -> None:
    opening = json.dumps({"topics": ["offers"], "change": False})
    offered = names(said("Cześć"), called("more_tools", opening))

    assert offered == ["more_tools", "booking_preset_list_v1", "booking_setup_read_v1"]
    with_change = names(
        said("Cześć"),
        called("more_tools", opening),
        called("more_tools", json.dumps({"topics": ["offers"], "change": True})),
    )
    assert with_change[:3] == offered and "booking_offer_discard_v1" in with_change
    # A conversation from before the selection: the area of every tool it
    # called is open, with the tools that change where it changed something.
    old = names(said("Hej"), called("organization_update_v1", "{}"))
    assert "organization_update_v1" in old and "organization_read_v1" in old
    # Arguments that are not what the tool takes open nothing and break nothing.
    assert names(called("more_tools", "not json"), called("more_tools", "[1]")) == ["more_tools"]
    assert names(called("more_tools", json.dumps({"topics": ["nope"]}))) == ["more_tools"]


def test_words_that_name_no_area_leave_the_one_tool_that_lists_them() -> None:
    (more,) = select(ALL, [said("Dzień dobry, co potrafisz?")])

    assert more["name"] == "more_tools"
    listed = more["input_schema"]["properties"]["topics"]["items"]["enum"]
    assert listed[:4] == ["company", "offers", "prices", "seasons"]
    for key in listed:
        assert f"- {key}: " in more["description"]
    # Every command the person has is within reach of some area.
    reach = {
        tool["name"]
        for key in listed
        for tool in select(
            ALL, [called("more_tools", json.dumps({"topics": [key], "change": True}))]
        )
    }
    assert reach == {tool["name"] for tool in ALL} | {"more_tools"}
    assert topics.opened(json.dumps({"topics": ["prices", "nope"], "change": True}), ALL) == {
        "opened": ["prices"],
        "unknown": ["nope"],
        "change": True,
    }


def test_a_command_no_area_claims_is_an_area_by_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A product's own commands: reachable on demand, described by their titles."""
    monkeypatch.setattr(topics, "TOPICS", tuple(t for t in topics.TOPICS if t.key != "inventory"))

    more = select(ALL, [said("Cześć")])[0]

    assert "- inventory: " in more["description"]
    opened = names(called("more_tools", json.dumps({"topics": ["inventory"], "change": False})))
    assert opened[1:] and all(name.startswith("inventory_") for name in opened[1:])


def test_a_small_registry_is_offered_whole() -> None:
    few = ALL[: topics.SELECT_ABOVE]

    assert select(few, [said("Cześć")]) == few
