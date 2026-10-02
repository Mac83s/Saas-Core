"""What the assistant's translation commands ask of the person (ADR-069 pkt 28,
ADR-076 §2): ordering binds the quote, turning the automation on is the
person's consent with a second factor, decisions open only their own gate."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid7

import pytest

from command_evals.translation import _company, _quote_arguments, translation_ready
from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import Invocation, preview_plan
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.translation.services import AUTOMATION_CONSENT

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def ready(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    with translation_ready():
        yield


def company(slug: str) -> TenantContext:
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE
    )
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    context = context_from_membership(membership)
    _company(context)
    return context


def preview(person: TenantContext, command: str, arguments: dict[str, object]) -> object:
    acting = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    with activate_tenant_context(acting):
        plan = preview_plan([
            Invocation(command=command, arguments=arguments, step_id=str(uuid7()))
        ])
    assert plan.refusals == (), plan.refusals
    return plan.groups[0]


SETTINGS = {"mode": None, "auto_changes": None, "auto_monthly_limit": None, "reset": None}


def test_turning_the_automation_on_is_consent_with_a_second_factor() -> None:
    person = company("tl6c-cmd-auto")
    group = preview(person, "translation.settings.update@1", {**SETTINGS, "auto_changes": True})
    assert group.risk == "irreversible" and group.step_up_required
    (call,) = group.calls
    assert call.preview.person_gates == {AUTOMATION_CONSENT}
    plain = preview(person, "translation.settings.update@1", {**SETTINGS, "mode": "review"})
    assert plain.risk == "apply" and not plain.step_up_required
    raised = preview(
        person, "translation.settings.update@1", {**SETTINGS, "auto_monthly_limit": 500}
    )
    assert raised.step_up_required


def test_an_order_binds_the_quote_it_showed() -> None:
    person = company("tl6c-cmd-order")
    group = preview(person, "translation.job.create@1", _quote_arguments(person))
    (call,) = group.calls
    assert group.risk == "irreversible"
    quote = call.preview.quote
    assert quote is not None and quote["credits"] == quote["units"] >= 1
    assert call.preview.observed_versions == {"translation.quote": quote["digest"]}
