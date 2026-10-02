"""What is particular to the assistant's service commands (A1b-12): a service it
creates is switched off, so nobody can book it until the person switches it
on; changing a service customers can book is a change of what they book, not
of a draft."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from command_evals.booking import _first, _service_fields
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.shared.booking.models import Service
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
