"""What is particular to the assistant's commands for an offer's seasons
(`shared/booking/season_commands.py`): the words the person agrees to carry
the dates and every rule in the panel's own words; a season of an offer nobody
can book yet is a draft and the same save on a switched-on offer is not; a
change names the version the person saw; and the read answers what the panel's
„Sezony” lists."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from command_evals.booking import _season_fields, _stay
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.shared.booking.models import BookingRule, ResourceGroup, Service
from test_booking_pricing_commands import refused, run, shown
from test_command_evals import assistant, invocation, owner

pytestmark = pytest.mark.django_db

SEASON = "booking.season.save@1"
SEASONS = "booking.seasons.read@1"


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def new_season(person: TenantContext, **more: Any) -> list[Any]:
    arguments = {
        "service_id": str(_stay(person).id),
        "starts_on": "2028-07-01",
        "ends_on": "2028-08-31",
        "min_length": 7,
        "start_weekdays": [5],
        **more,
    }
    return [invocation(SEASON, _season_fields(**arguments))]


def test_the_words_of_a_season_carry_its_dates_and_every_rule() -> None:
    person = owner("season-words", SEASON)

    risk, words = shown(person, new_season(person, name="Wakacje"))

    # A draft: the offer is switched off, so no customer meets this rule yet.
    assert risk == "draft"
    assert words == (
        "Nowy sezon usługi „Domki” — „Wakacje” 2028-07-01 – 2028-08-31: od 7 nocy, przyjazd: sob."
    )

    result = run(person, new_season(person, name="Wakacje"))

    assert result.status == "done", result
    saved = BookingRule.all_objects.get(pk=result.output["season_id"])
    assert (saved.service_id, saved.min_length, saved.start_weekdays, saved.active) == (
        _stay(person).id,
        7,
        [5],
        True,
    )
    # What was not said is not set: the offer's own settings stay in force.
    assert (saved.max_length, saved.end_weekdays, saved.notice_hours, saved.closed) == (
        None,
        [],
        None,
        False,
    )


def test_a_season_a_customer_will_meet_is_not_a_draft() -> None:
    person = owner("season-live", SEASON)
    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)

    risk, words = shown(person, new_season(person))

    assert risk == "apply"
    assert words.endswith("— obowiązuje od razu, dla nowych rezerwacji")


def test_a_season_of_a_group_follows_the_offers_that_book_it() -> None:
    person = owner("season-group", SEASON)
    group = ResourceGroup.all_objects.get(organization_id=person.organization_id)
    plan = new_season(person, service_id=None, group_id=str(group.id), closed=True)

    risk, words = shown(person, plan)
    assert risk == "draft"
    # A group has no time unit of its own: the length is said without one.
    assert words == (
        "Nowy sezon grupy jednostek „Domki” — 2028-07-01 – 2028-08-31: zamknięte — bez "
        "rezerwacji, od 7 jednostek czasu, przyjazd: sob."
    )

    Service.all_objects.filter(pk=_stay(person).pk).update(active=True, draft=False)
    assert shown(person, plan)[0] == "apply"


def test_a_season_is_changed_at_the_version_the_person_saw() -> None:
    person = owner("season-change", SEASON)
    season = BookingRule.all_objects.get(organization_id=person.organization_id)
    plan = [invocation(SEASON, _season_fields(season_id=str(season.id), min_length=5))]

    risk, words = shown(person, plan)
    assert words == (
        "Sezon usługi „Domki” po zmianie — „Sezon wysoki” 2027-07-01 – 2027-08-31: od 5 nocy"
    )
    result = run(person, plan)

    assert (result.status, result.output["version"]) == ("done", 2)
    season.refresh_from_db()
    # Only what was named moved: the dates and the name stay.
    assert (season.min_length, season.name, season.starts_on.isoformat()) == (
        5,
        "Sezon wysoki",
        "2027-07-01",
    )


def test_a_season_is_switched_off_never_removed() -> None:
    person = owner("season-off", SEASON)
    season = BookingRule.all_objects.get(organization_id=person.organization_id)
    plan = [invocation(SEASON, _season_fields(season_id=str(season.id), active=False))]

    assert shown(person, plan)[1].endswith("od 7 nocy, wyłączony")
    assert run(person, plan).status == "done"

    season.refresh_from_db()
    assert season.active is False


def test_a_season_the_service_refuses_names_its_field() -> None:
    person = owner("season-refused", SEASON)

    # The panel's own rules: the last day not before the first, one scope.
    assert refused(person, new_season(person, ends_on="2028-06-01")) == (
        "ends_on",
        "end_before_start",
    )
    assert refused(person, new_season(person, service_id=None)) == ("service_id", "one_scope")
    assert refused(person, new_season(person, max_length=3)) == ("max_length", "max_below_min")
    assert BookingRule.all_objects.filter(organization_id=person.organization_id).count() == 1


def test_the_read_answers_what_the_panel_lists() -> None:
    person = owner("season-read", SEASONS)

    with activate_tenant_context(assistant(person)):
        (result,) = execute_plan([invocation(SEASONS, {})])

    assert result.status == "done", result
    (season,) = result.output["seasons"]
    assert (season["name"], season["starts_on"], season["ends_on"], season["min_length"]) == (
        "Sezon wysoki",
        "2027-07-01",
        "2027-08-31",
        7,
    )
    assert (season["service_id"], season["version"]) == (str(_stay(person).id), 1)
    # Whose the season is, in words — and that nobody can book that offer yet.
    stay = _stay(person)
    assert result.output["names"] == {str(stay.id): stay.name}
    assert result.output["switched_off"] == ([] if stay.active else [str(stay.id)])
