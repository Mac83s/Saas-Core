"""What is particular to the assistant's service commands (A1b-12): a service it
creates is switched off, so nobody can book it until the person switches it
on; changing a service customers can book is a change of what they book, not
of a draft. A place (A2) is added as the panel adds one, so adding it is never
a draft."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from command_evals.booking import (
    _first,
    _person_fields,
    _preset_fields,
    _service_fields,
    _week,
)
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.core.organizations.models import Invitation, Membership
from saas_core.modules.shared.booking.models import Location, Service, StaffMember
from test_command_evals import assistant, clicked, invocation, owner

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def test_a_service_the_assistant_creates_stays_switched_off() -> None:
    person = owner("create-off", "booking.offer.create@1")
    acting = assistant(person)
    plan = [
        invocation("booking.offer.create@1", _service_fields(name="Masaż", duration_minutes=60))
    ]
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)

    assert result.status == "done", result
    assert result.output["active"] is False
    created = Service.all_objects.get(organization_id=person.organization_id, name="Masaż")
    assert created.active is False


@pytest.mark.parametrize(("active", "risk"), [(True, "apply"), (False, "draft")])
def test_changing_a_bookable_service_is_more_than_a_draft(active: bool, risk: str) -> None:
    person = owner(f"update-{'on' if active else 'off'}", "booking.offer.update@1")
    service = _first(Service, person)
    Service.all_objects.filter(pk=service.id).update(active=active)
    plan = [
        invocation(
            "booking.offer.update@1",
            {"service_id": str(service.id), **_service_fields(name="Konsultacja online")},
        )
    ]
    with activate_tenant_context(assistant(person)):
        (group,) = preview_plan(plan).groups

    assert group.risk == risk


def test_a_place_is_added_as_the_panel_adds_one_and_changed_by_its_id() -> None:
    person = owner("place-save", "booking.location.save@1")
    acting = assistant(person)
    new = [
        invocation(
            "booking.location.save@1",
            {"location_id": None, "name": "Salon na Mazurskiej", "address": "ul. Mazurska 4"},
        )
    ]
    with activate_tenant_context(acting):
        (group,) = preview_plan(new).groups
    (effect,) = group.calls[0].preview.effects
    # Shown in online booking from the start: a click, and the address stays
    # out of the words the consent keeps.
    assert (group.risk, effect.kind) == ("apply", "created")
    assert "Mazurska 4" not in effect.summary["pl"]

    with activate_tenant_context(acting):
        (added,) = execute_plan(new, clicked(person, acting, new))
    assert added.status == "done", added
    assert (added.output["active"], added.output["online"]) == (True, True)

    change = [
        invocation(
            "booking.location.save@1",
            {"location_id": added.output["location_id"], "name": None, "address": ""},
        )
    ]
    with activate_tenant_context(acting):
        (changed,) = execute_plan(change, clicked(person, acting, change))
    assert changed.status == "done", changed
    place = Location.all_objects.get(pk=added.output["location_id"])
    assert (place.name, place.address, place.version) == ("Salon na Mazurskiej", "", 2)


def test_a_week_read_and_sent_back_changes_nothing() -> None:
    """The read gives a person's week in the shape the hours command takes, so
    a configurator can tell a week that is already set from one to set (A2)."""
    person = owner("week-read", "booking.staff.hours.set@1")
    acting = assistant(person)
    with activate_tenant_context(acting):
        (read,) = execute_plan([invocation("booking.setup.read@1", {})])
    (staff,) = read.output["staff"]
    place = str(_first(Location, person).id)
    assert staff["hours"] == [
        {"weekday": 0, "local_start": "08:00", "local_end": "12:00", "location_id": place}
    ]

    same = [
        invocation("booking.staff.hours.set@1", {"staff_id": staff["id"], "rules": staff["hours"]})
    ]
    with activate_tenant_context(acting):
        (group,) = preview_plan(same).groups
    assert "(bez zmian)" in group.calls[0].preview.effects[0].summary["pl"]

    other = [invocation("booking.staff.hours.set@1", _week(person, "09:00", "17:00"))]
    with activate_tenant_context(acting):
        (done,) = execute_plan(other, clicked(person, acting, other))
        (read,) = execute_plan([invocation("booking.setup.read@1", {})])
    assert done.status == "done", done
    assert read.output["staff"][0]["hours"] == _week(person, "09:00", "17:00")["rules"]
    assert StaffMember.all_objects.get(pk=staff["id"]).hours_version == done.output["hours_version"]


def test_a_preset_the_assistant_applies_is_a_draft_that_names_its_conversation() -> None:
    person = owner("preset-apply", "booking.preset.apply@1")
    acting = assistant(person)
    plan = [
        invocation(
            "booking.preset.apply@1", _preset_fields(name="Masaż klasyczny", duration_minutes=60)
        )
    ]
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)

    assert result.status == "done", result
    created = Service.all_objects.get(pk=result.output["service_id"])
    assert result.output == {
        "service_id": str(created.id),
        "name": "Masaż klasyczny",
        "active": False,
        "version": 1,
        "preset_id": "core.specialist_visit",
        "preset_version": 1,
    }
    assert (created.active, created.draft, created.origin_ref) == (False, True, acting.acting_ref)


def test_a_person_is_added_without_an_account_and_an_invitation_takes_its_own_click() -> None:
    person = owner("staff-add", "booking.staff.add@1")
    acting = assistant(person)
    plain = [invocation("booking.staff.add@1", _person_fields(name="Marta"))]
    invited = [
        invocation(
            "booking.staff.add@1",
            _person_fields(name="Ewa", invitation={"email": "ewa@example.test", "role": "staff"}),
        )
    ]
    with activate_tenant_context(acting):
        (quiet,) = preview_plan(plain).groups
        (loud,) = preview_plan(invited).groups
    # In the calendar at once: a change to working configuration. An e-mail
    # to somebody else and an account for them: a click of its own.
    assert (quiet.risk, loud.risk) == ("apply", "publish")
    (effect,) = loud.calls[0].preview.effects
    assert "ewa@example.test" in effect.summary["pl"] and "staff" in effect.summary["pl"]
    # A preview leaves nothing: no entry and no invitation to send.
    assert not StaffMember.all_objects.filter(display_name__in=["Marta", "Ewa"]).exists()
    assert not Invitation.objects.filter(organization_id=person.organization_id).exists()

    tokens = {**clicked(person, acting, plain), **clicked(person, acting, invited)}
    with activate_tenant_context(acting):
        (added,) = execute_plan(plain, tokens)
        (sent,) = execute_plan(invited, tokens)

    assert added.status == "done", added
    marta = StaffMember.all_objects.get(pk=added.output["staff_id"])
    assert added.output == {
        "staff_id": str(marta.id),
        "name": "Marta",
        "takes_visits": False,
        "invited": False,
    }
    assert sent.status == "done", sent
    assert (sent.output["name"], sent.output["invited"]) == ("Ewa", True)
    invitation = Invitation.objects.get(organization_id=person.organization_id)
    assert (invitation.email, invitation.role.key) == ("ewa@example.test", "staff")
    # The person the assistant acted for is who invited.
    assert invitation.invited_by_id == Membership.objects.get(pk=person.membership_id).user_id


def test_a_stay_from_a_preset_says_what_is_left_to_the_person_and_reads_back() -> None:
    person = owner("preset-stay", "booking.preset.apply@1")
    acting = assistant(person)
    plan = [
        invocation(
            "booking.preset.apply@1",
            _preset_fields(preset_id="core.lodging", name="Domek nad wodą"),
        )
    ]
    with activate_tenant_context(acting):
        (group,) = preview_plan(plan).groups
    # Said before the click: what the assistant does not make. A stay is
    # booked through the site (phase 5b), so nothing says the form comes later.
    (effect,) = group.calls[0].preview.effects
    assert "Jednostki i ceny dodasz w następnym kroku albo w panelu." in effect.summary["pl"]
    assert "wkrótce" not in effect.summary["pl"]
    assert "coming soon" not in effect.summary["en"]
    # What the preset writes about money: a start, the company's to change.
    assert effect.summary["pl"].endswith(
        " Warunki na start, do zmiany w „Cenniku”: przedpłata 30% przelewem (włączasz ją tam); "
        "reszta 14 dni przed początkiem; zwrot przedpłaty przy rezygnacji: 100% do 30 dni "
        "przed, 50% do 14 dni przed, później 0%."
    )
    assert "yours to change in the price list" in effect.summary["en"]
    # A preset that says nothing about paying ahead adds no such words.
    rental = [
        invocation(
            "booking.preset.apply@1", _preset_fields(preset_id="core.rental", name="Rowery")
        )
    ]
    with activate_tenant_context(acting):
        (plain,) = preview_plan(rental).groups
    assert "Warunki na start" not in plain.calls[0].preview.effects[0].summary["pl"]

    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)
        (read,) = execute_plan([invocation("booking.setup.read@1", {})])

    assert result.status == "done", result
    assert (result.output["preset_id"], result.output["preset_version"]) == ("core.lodging", 4)
    stay = next(item for item in read.output["services"] if item["name"] == "Domek nad wodą")
    # A stay's check-in and check-out are read as the week's hours are written.
    assert (stay["time_model"], stay["range_unit"]) == ("range", "night")
    assert (stay["range_start_local"], stay["range_end_local"]) == ("16:00", "11:00")
    assert (stay["online"], stay["active"], stay["draft"]) == (True, False, True)
