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

    # The list itself says whether amounts are net or gross: the setting is not read for it.
    assert offered == ["more_tools", "booking_prices_read_v1"]
    # A sixtieth of the registry's definitions, not all of them.
    assert size(offered) * 60 < size([tool["name"] for tool in ALL])
    # What a booking would cost is a question of its own.
    assert names(said("Policz, ile zapłaci klient za trzy noce"))[1:] == ["booking_quote_read_v1"]


def test_asking_for_a_change_brings_the_tools_that_change() -> None:
    offered = names(said("Zmień cenę Wigwamów na 300 zł"))

    assert offered[:2] == names(said("Ile kosztuje noc w Wigwamach?"))
    assert "booking_price_save_v1" in offered and "booking_extra_save_v1" in offered
    assert {name.split("_")[0] for name in offered[1:]} == {"booking"}
    # „oferty” is too common a word to open the services' area beside the price list…
    assert offered == names(said("Zmień cenę podstawową oferty Wigwamy na 300 zł za noc"))
    assert "booking_offer_update_v1" not in offered
    # …and opens it only while nothing more exact was said.
    assert "booking_offer_create_v1" in names(said("Dodaj usługę strzyżenie, 30 minut"))
    assert "booking_setup_read_v1" not in names(
        said("Ile kosztuje noc?"), said("A jakie mam usługi?")
    )
    # A change asked for later opens the areas already touched; the tools the
    # model was shown before keep their place, so a provider's cache holds.
    later = names(said("Ile kosztuje noc w Wigwamach?"), said("Podnieś ją o 20"))
    assert later == offered


def test_a_polish_ending_that_changes_the_stem_still_names_the_area() -> None:
    def opens(text: str) -> set[str]:
        return {name.split("_")[0] for name in names(said(text))[1:]}

    assert "organization" in opens("W jakiej walucie prowadzę cennik?")
    assert opens("Co jest na wizytówce?") == {"profiles"}
    assert opens("Co jest w regulaminie i w polityce prywatności?") == {"customers"}
    assert opens("Pokaż, co jest w dokumencie dla klientów") == {"customers"}
    assert "booking" in opens("Ile jest po rabacie i po zniżce?")
    assert opens("W jakie dni jest przyjazd, a po przyjeździe?") == {"booking"}
    assert "booking_seasons_read_v1" in names(said("Co ustawiono przy wyjeździe?"))
    # „w ofercie”, „o usłudze”: common words, in any case, and only while nothing is open.
    assert "booking_setup_read_v1" in names(said("Co mam w ofercie?"))
    assert "booking_setup_read_v1" in names(said("Opowiedz o usłudze strzyżenie"))
    assert "booking_setup_read_v1" not in names(said("Ile kosztuje noc?"), said("A w ofercie?"))


def test_a_question_about_a_person_brings_the_tools_that_answer_with_a_handle() -> None:
    """„Karty osób”: the customers' area finds a person and reads the calendar."""
    people = ["customers_find_v1", "booking_appointments_read_v1"]

    asked = names(said("Podaj mi telefon do klienta z jutrzejszej wizyty"))
    assert set(people) <= set(asked)
    assert names(said("Kto przychodzi jutro?"))[1:] == sorted(people)
    # Whether somebody paid is a question about orders, which search by a name.
    paid = names(said("Czy pan Kowalski zapłacił?"))
    assert {"commerce_orders_read_v1", "commerce_order_read_v1"} <= set(paid)
    # „klient” and „dziś” alone open nothing where something more exact was said.
    assert names(said("Policz, ile zapłaci klient za trzy noce"))[1:] == ["booking_quote_read_v1"]
    marked = names(said("Klient zapłacił dziś 300 zł gotówką za zamówienie. Oznacz tę wpłatę."))
    assert not set(people) & set(marked)
    # The documents' area keeps to documents.
    assert "customers_find_v1" not in names(said("Co jest w regulaminie?"))


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
    assert listed[:5] == ["company", "offers", "prices", "quote", "seasons"]
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


def test_orders_and_requests_are_areas_and_an_amount_alone_names_no_price_list() -> None:
    # A question about money that came in reads orders — nothing of the price list.
    assert names(said("Które zamówienia czekają na wpłatę?")) == [
        "more_tools",
        "commerce_order_read_v1",
        "commerce_orders_read_v1",
    ]
    marking = names(said("Oznacz wpłatę 300 zł gotówką do zamówienia R/2026/0007"))
    # „zł” is said about a payment as often as about a price: with the orders
    # named, the price list stays closed and its definitions are not paid for.
    assert marking == [
        "more_tools",
        "commerce_order_read_v1",
        "commerce_orders_read_v1",
        "commerce_payment_record_v1",
        "commerce_payment_void_v1",
    ]
    # Alone, an amount still opens the price list.
    assert "booking_price_save_v1" in names(said("Ustaw 300 zł za noc w Wigwamach"))

    assert names(said("Jakie prośby o rezerwację czekają?")) == [
        "more_tools",
        "booking_requests_read_v1",
    ]
    answering = names(said("Przyjmij prośbę o Domek nad jeziorem"))
    assert answering[1:] == [
        "booking_requests_read_v1",
        "booking_request_accept_v1",
        "booking_request_decline_v1",
    ]
    assert names(said("Odmów tej prośbie")) == answering
    assert names(said("Accept the booking request"))[1:] == answering[1:]
