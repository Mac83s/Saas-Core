"""What is particular to the assistant's commands for an offer's units and its
price list (`shared/booking/pricing_commands.py`): the pool is brought up to a
count and never cut; a price, an extra or a unit of an offer nobody can book
yet is a draft, and the same write on a switched-on offer is not; the words
the person agrees to carry the amount, how it is read and the tax; and only a
draft is ever removed."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from command_evals.booking import _extra_fields, _price_fields, _quote_fields, _stay
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.shared.booking.models import (
    BookingSetupMutation,
    Extra,
    PriceRule,
    Resource,
    ResourceGroup,
    Service,
    ServiceGroup,
)
from test_command_evals import assistant, clicked, invocation, owner

pytestmark = pytest.mark.django_db

UNITS = "booking.offer.units.set@1"
PRICE = "booking.price.save@1"
EXTRA = "booking.extra.save@1"
DISCARD = "booking.offer.discard@1"


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def units(person: TenantContext, count: int, **more: Any) -> list[Any]:
    arguments = {
        "service_id": str(_stay(person).id),
        "count": count,
        "capacity": None,
        "location_id": None,
        **more,
    }
    return [invocation(UNITS, arguments)]


def run(person: TenantContext, plan: list[Any]) -> Any:
    acting = assistant(person)
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)
    return result


def shown(person: TenantContext, plan: list[Any]) -> tuple[str, str]:
    """The class of the click and the words the person agrees to."""
    with activate_tenant_context(assistant(person)):
        previewed = preview_plan(plan)
    assert previewed.refusals == (), previewed.refusals
    (group,) = previewed.groups
    (effect,) = group.calls[0].preview.effects
    return group.risk, effect.summary["pl"]


def refused(person: TenantContext, plan: list[Any]) -> tuple[str | None, str]:
    with activate_tenant_context(assistant(person)):
        (refusal,) = preview_plan(plan).refusals
    (error,) = refusal.errors
    return error["field"], str(error["code"])


def names(person: TenantContext) -> list[str]:
    return sorted(
        Resource.all_objects.filter(
            organization_id=person.organization_id, active=True
        ).values_list("name", flat=True)
    )


# --- Units --------------------------------------------------------------------------


def test_a_stay_is_brought_up_to_its_count_and_the_words_name_the_new_units() -> None:
    person = owner("units-add", UNITS)

    risk, words = shown(person, units(person, 3, capacity=6))
    # The offer is still switched off: nobody can book a unit of it.
    assert risk == "draft"
    assert "3 jednostki w grupie „Domki”" in words
    assert "„Domki 2”, „Domki 3”" in words

    result = run(person, units(person, 3, capacity=6))

    assert result.status == "done", result
    assert result.output["added"] == ["Domki 2", "Domki 3"]
    assert names(person) == ["Domki 1", "Domki 2", "Domki 3"]
    added = Resource.all_objects.filter(name__in=["Domki 2", "Domki 3"])
    # The unit that was there stays as it was.
    assert {unit.capacity for unit in added} == {6}
    assert Resource.all_objects.get(name="Domki 1").capacity is None
    assert _stay(person).version == 2


def test_the_count_is_the_whole_pool_so_the_same_count_again_changes_nothing() -> None:
    person = owner("units-same", UNITS)
    run(person, units(person, 3))

    risk, words = shown(person, units(person, 3))
    again = run(person, units(person, 3))

    assert "bez zmian" in words
    assert (again.status, again.output["added"]) == ("done", [])
    assert names(person) == ["Domki 1", "Domki 2", "Domki 3"]
    assert _stay(person).version == 2


def test_units_are_never_removed_by_a_count() -> None:
    person = owner("units-fewer", UNITS)
    run(person, units(person, 3))

    assert refused(person, units(person, 2)) == ("count", "units_cannot_be_removed")
    assert names(person) == ["Domki 1", "Domki 2", "Domki 3"]


def test_a_pool_that_is_switched_off_is_not_added_to() -> None:
    person = owner("units-off", UNITS)
    ResourceGroup.all_objects.filter(organization_id=person.organization_id).update(active=False)

    assert refused(person, units(person, 3)) == ("service_id", "unit_group_switched_off")
    assert names(person) == ["Domki 1"]


def test_a_units_capacity_is_bounded_as_in_the_panel() -> None:
    person = owner("units-capacity", UNITS)

    assert refused(person, units(person, 3, capacity=0))[0] == "capacity"


def test_a_visit_by_the_clock_has_no_units() -> None:
    person = owner("units-slot", UNITS)
    visit = Service.all_objects.get(organization_id=person.organization_id, name="Konsultacja")
    plan = [
        invocation(
            UNITS,
            {"service_id": str(visit.id), "count": 2, "capacity": None, "location_id": None},
        )
    ]

    assert refused(person, plan) == ("service_id", "units_need_range_offer")


def test_an_offer_without_a_pool_gets_one_under_its_name_or_finds_the_one_there() -> None:
    person = owner("units-pool", UNITS)
    stay = _stay(person)
    # As after a discarded draft made again: the group and its unit are the
    # company's still, the new offer is linked to nothing.
    ServiceGroup.all_objects.filter(service=stay).delete()

    risk, words = shown(person, units(person, 1))
    assert "będzie rezerwowana w grupie „Domki”" in words
    result = run(person, units(person, 2))

    assert result.status == "done", result
    assert result.output["added"] == ["Domki 2"]
    assert ResourceGroup.all_objects.filter(organization_id=person.organization_id).count() == 1
    assert ServiceGroup.all_objects.filter(service=stay).count() == 1

    # With no group of that name the pool is made, in the same step.
    ServiceGroup.all_objects.filter(service=stay).delete()
    Service.all_objects.filter(pk=stay.pk).update(name="Chaty")
    made = run(
        person,
        [
            invocation(
                UNITS,
                {"service_id": str(stay.id), "count": 2, "capacity": None, "location_id": None},
            )
        ],
    )
    assert made.status == "done", made
    assert (made.output["group_name"], made.output["added"]) == ("Chaty", ["Chaty 1", "Chaty 2"])


def test_units_of_an_offer_customers_can_book_are_more_than_a_draft() -> None:
    person = owner("units-live", UNITS)
    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)

    risk, _words = shown(person, units(person, 2))

    assert risk == "apply"


def test_one_key_is_one_receipt_and_the_draft_takes_it_away() -> None:
    person = owner("units-receipt", UNITS)
    plan = units(person, 2)
    acting = assistant(person)
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        first = execute_plan(plan, tokens)
        again = execute_plan(plan, tokens)

    assert again == first
    assert names(person) == ["Domki 1", "Domki 2"]
    assert BookingSetupMutation.all_objects.filter(action="service.units").count() == 1

    assert run(person, [invocation(DISCARD, {"service_id": str(_stay(person).id)})]).status == (
        "done"
    )
    assert not BookingSetupMutation.all_objects.filter(action="service.units").exists()


# --- Prices -------------------------------------------------------------------------


def new_price(person: TenantContext, **given: Any) -> list[Any]:
    fields = {
        "service_id": str(_stay(person).id),
        "basis": "per_time_unit",
        "amount_minor": 45000,
        "vat_code": "8",
        "starts_on": "2027-07-01",
        "ends_on": "2027-08-31",
        **given,
    }
    return [invocation(PRICE, _price_fields(**fields))]


def test_the_words_of_a_price_carry_the_amount_how_it_is_read_and_the_tax() -> None:
    person = owner("price-words", PRICE)

    risk, words = shown(person, new_price(person))

    # A draft: the offer is switched off, so no customer sees this price yet.
    assert risk == "draft"
    assert words == (
        "Nowa cena usługi „Domki”: 450,00 PLN za noc, brutto, VAT 8%, "
        "w sezonie 2027-07-01 – 2027-08-31"
    )

    result = run(person, new_price(person))
    assert result.status == "done", result
    saved = PriceRule.all_objects.get(pk=result.output["price_id"])
    assert (saved.amount_minor, saved.currency, saved.vat_code) == (45000, "PLN", "8")


def test_a_price_a_customer_will_see_is_not_a_draft() -> None:
    person = owner("price-live", PRICE)
    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)

    risk, words = shown(person, new_price(person))

    assert risk == "apply"
    assert words.endswith("— obowiązuje od razu, dla nowych rezerwacji")


def test_a_price_of_a_group_follows_the_offers_that_book_it() -> None:
    person = owner("price-group", PRICE)
    group = ResourceGroup.all_objects.get(organization_id=person.organization_id)
    plan = new_price(person, service_id=None, group_id=str(group.id), starts_on=None, ends_on=None)

    risk, words = shown(person, plan)
    assert risk == "draft"
    assert words.startswith("Nowa cena grupy jednostek „Domki”: 450,00 PLN za jednostkę czasu")

    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)
    assert shown(person, plan)[0] == "apply"


def test_a_price_is_changed_at_the_version_the_person_saw() -> None:
    person = owner("price-change", PRICE)
    price = PriceRule.all_objects.get(organization_id=person.organization_id)
    plan = [invocation(PRICE, _price_fields(price_id=str(price.id), amount_minor=50000))]

    risk, words = shown(person, plan)
    assert words == (
        "Cena usługi „Domki” po zmianie: 500,00 PLN za noc, brutto, VAT 8%, cena podstawowa"
    )
    result = run(person, plan)

    assert (result.status, result.output["version"]) == ("done", 2)
    price.refresh_from_db()
    assert price.amount_minor == 50000


def test_a_price_without_its_amount_is_refused_never_given_a_default() -> None:
    person = owner("price-none", PRICE)
    plan = new_price(person, amount_minor=None)

    assert refused(person, plan) == ("amount_minor", "required")


def test_a_night_does_not_price_a_visit_by_the_clock() -> None:
    person = owner("price-slot", PRICE)
    visit = Service.all_objects.get(organization_id=person.organization_id, name="Konsultacja")
    plan = new_price(person, service_id=str(visit.id), starts_on=None, ends_on=None)

    assert refused(person, plan) == ("basis", "basis_needs_time_unit")


# --- Extras, the deposit, the quote and the read --------------------------------------


def test_a_deposit_is_held_and_given_back_and_said_so() -> None:
    person = owner("deposit", EXTRA)
    plan = [
        invocation(
            EXTRA,
            _extra_fields(
                service_id=str(_stay(person).id),
                name="Kaucja",
                kind="security_deposit",
                amount_minor=50000,
            ),
        )
    ]

    risk, words = shown(person, plan)
    assert risk == "draft"
    assert words == (
        "Nowa kaucja „Kaucja” usługi „Domki”: 500,00 PLN — pobierana przy rezerwacji i "
        "zwracana, bez podatku, poza ceną"
    )

    result = run(person, plan)
    assert result.status == "done", result
    deposit = Extra.all_objects.get(pk=result.output["extra_id"])
    assert (deposit.vat_code, deposit.mandatory) == ("np", True)

    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)
    change = [invocation(EXTRA, _extra_fields(extra_id=str(deposit.id), amount_minor=60000))]
    assert shown(person, change)[0] == "apply"


def test_the_quote_answers_what_the_price_list_says_and_writes_nothing() -> None:
    person = owner("quote", "booking.quote.read@1")
    arguments = {
        "service_id": str(_stay(person).id),
        **_quote_fields(start_date="2027-07-01", end_date="2027-07-04", price_only=True),
    }
    with activate_tenant_context(assistant(person)):
        (quote, prices, setup) = execute_plan([
            invocation("booking.quote.read@1", arguments),
            invocation("booking.prices.read@1", {}),
            invocation("booking.setup.read@1", {}),
        ])

    assert quote.status == "done", quote
    # Three nights at 400.00, and the mandatory extras none: the optional one is not picked.
    assert (quote.output["gross_minor"], quote.output["currency"]) == (120000, "PLN")
    assert [line["price_rule_id"] for line in quote.output["lines"]] == [
        prices.output["prices"][0]["id"]
    ]
    assert (prices.output["amounts"], prices.output["currency"]) == ("gross", "PLN")
    assert [extra["name"] for extra in prices.output["extras"]] == ["Sprzątanie końcowe"]
    assert [category["name"] for category in prices.output["categories"]] == ["Dziecko"]
    # A price says whose it is with an id; the list names every such id itself,
    # so the whole setup is not read only to match a price to a service.
    pointed = {
        row[field]
        for row in (*prices.output["prices"], *prices.output["extras"])
        for field in ("service_id", "group_id", "resource_id")
        if row.get(field)
    }
    assert set(prices.output["names"]) == pointed
    assert prices.output["names"][arguments["service_id"]] == _stay(person).name
    # The pools are in the setup read, so a unit's `group_id` says something.
    assert [group["name"] for group in setup.output["groups"]] == ["Domki"]


# --- The undo of a draft --------------------------------------------------------------


def test_a_draft_is_removed_with_its_prices_on_a_click_of_its_own() -> None:
    person = owner("discard", DISCARD)
    plan = [invocation(DISCARD, {"service_id": str(_stay(person).id)})]

    risk, words = shown(person, plan)
    assert risk == "irreversible"
    assert "cenami (1), dopłatami i kaucjami (1)" in words
    assert "Jednostki i ich grupa zostają" in words

    assert run(person, plan).status == "done"
    organization_id = person.organization_id
    assert not Service.all_objects.filter(organization_id=organization_id, name="Domki").exists()
    assert not PriceRule.all_objects.filter(organization_id=organization_id).exists()
    assert names(person) == ["Domki 1"]


def test_an_offer_that_was_ever_switched_on_is_not_removed() -> None:
    person = owner("discard-live", DISCARD)
    Service.all_objects.filter(pk=_stay(person).pk).update(draft=False)

    assert refused(person, [invocation(DISCARD, {"service_id": str(_stay(person).id)})]) == (
        "service_id",
        "not_a_draft",
    )
