"""What is particular to the assistant's service commands (A1b-12): a service it
creates is switched off, so nobody can book it until the person switches it
on; changing a service customers can book is a change of what they book, not
of a draft. A place (A2) is added as the panel adds one, so adding it is never
a draft."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from command_evals.booking import _first, _service_fields
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.shared.booking.models import Location, Service
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
