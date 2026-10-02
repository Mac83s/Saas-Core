"""Running a plan a person consented to (ADR-076 §3): the token binds this
membership, this conversation and the exact previewed plan; a step runs once,
its receipt answering every retry; a group that fails is undone whole and stops
the groups after it."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
from django.core import signing
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import command_executor, command_registry
from saas_core.modules.core.organizations.command_consent import (
    CONSENT_SALT,
    ConsentInvalid,
    mint_consent,
    read_consent,
)
from saas_core.modules.core.organizations.command_executor import (
    Invocation,
    execute_plan,
    preview_plan,
)
from saas_core.modules.core.organizations.command_registry import (
    CommandSpec,
    Preview,
    register_command,
)
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    CommandReceipt,
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.services import update_current_organization
from test_command_executor import INPUT, OUTPUT, allow_all

pytestmark = pytest.mark.django_db

RUNS: list[str] = []


def _observed(call: Any) -> int:
    organization = Organization.objects.get(pk=call.context.organization_id)
    return organization.version


def _rename_preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(
        effects=(),
        observed_versions={f"organization:{call.context.organization_id}": _observed(call)},
    )


def _rename(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    RUNS.append(arguments["name"])
    if arguments["name"] == "Odmowa":
        raise ValidationError({"name": ["Ta nazwa jest zajęta."]})
    if arguments["name"] == "Błąd":
        raise RuntimeError("bug")
    (version,) = call.preview.observed_versions.values()
    access = update_current_organization(changes={"name": arguments["name"], "version": version})
    return {"name": access.organization.name}


def _note(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    RUNS.append(f"note:{arguments['name']}")
    return {"name": arguments["name"]}


def spec(**changes: Any) -> CommandSpec:
    declaration: dict[str, Any] = {
        "name": "organization.rename",
        "version": 1,
        "module": "core.organizations",
        "title": {"pl": "Zmień nazwę", "en": "Rename"},
        "summary": {"pl": "Nazwa firmy.", "en": "Company name."},
        "model_description": "Renames the company.",
        "input_schema": INPUT,
        "output_schema": OUTPUT,
        "permission": "organization.settings.manage",
        "risk": "apply",
        "run": _rename,
        "undo": "restore_version",
        "preview": _rename_preview,
        "version_field": "version",
    }
    declaration.update(changes)
    return CommandSpec(**declaration)


def _unobserved(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(effects=(), observed_versions={})


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_executor, "_gates", {"features": allow_all})
    RUNS.clear()
    register_command(spec())
    register_command(spec(name="organization.note", risk="publish", run=_note, preview=_unobserved))
    register_command(
        spec(
            name="organization.bill",
            run=_note,
            preview=_unobserved,
            modifiers=frozenset({"changes_billing"}),
        )
    )
    yield


@pytest.fixture
def owner() -> TenantContext:
    user = User.objects.create_user(email="owner@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name="Domki", slug="domki", status=OrganizationStatus.ACTIVE
    )
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    return context_from_membership(membership)


def call(command: str, name: str = "Domki nad jeziorem", step: str | None = None) -> Invocation:
    return Invocation(
        command=command,
        arguments={"name": name, "address": None, "items": []},
        step_id=step or str(uuid7()),
    )


def consents(
    person: TenantContext, assistant: TenantContext, plan_calls: list[Invocation]
) -> dict[str, str]:
    """What the panel's consent endpoint gives for each group shown (A1b-6)."""
    with activate_tenant_context(assistant):
        plan = preview_plan(plan_calls)
    return {
        group.id: mint_consent(person, digest=group.digest, acting_ref=assistant.acting_ref)
        for group in plan.groups
    }


def assistant_of(person: TenantContext) -> TenantContext:
    return acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")


def name_of(context: TenantContext) -> str:
    return Organization.objects.get(pk=context.organization_id).name


def test_a_token_is_this_memberships_in_this_conversation_and_recent(
    owner: TenantContext, settings: Any
) -> None:
    assistant = assistant_of(owner)
    token = mint_consent(owner, digest="d" * 64, acting_ref=assistant.acting_ref)

    assert read_consent(token, context=assistant).digest == "d" * 64
    for other in (
        assistant_of(owner),
        replace(assistant, membership_id=uuid7()),
        replace(assistant, organization_id=uuid7()),
    ):
        with pytest.raises(ConsentInvalid):
            read_consent(token, context=other)
    preview_token = signing.dumps({"digest": "d" * 64}, salt="sites.content-change-set.approval.v1")
    forged = signing.dumps({"v": 1, "digest": "d" * 64}, salt=CONSENT_SALT)
    for wrong in (preview_token, forged, token + "x"):
        with pytest.raises(ConsentInvalid):
            read_consent(wrong, context=assistant)
    settings.COMMAND_CONSENT_TTL = -1
    with pytest.raises(ConsentInvalid):
        read_consent(token, context=assistant)


def test_only_the_person_acting_directly_consents(owner: TenantContext) -> None:
    assistant = assistant_of(owner)
    with pytest.raises(ConsentInvalid):
        mint_consent(assistant, digest="d" * 64, acting_ref=assistant.acting_ref)
    with pytest.raises(ConsentInvalid):
        mint_consent(
            replace(owner, principal_kind="api_key"),
            digest="d" * 64,
            acting_ref=assistant.acting_ref,
        )


def test_a_consented_group_runs_as_the_assistant_acting_for_the_person(
    owner: TenantContext,
) -> None:
    assistant = assistant_of(owner)
    plan = [call("organization.rename@1")]
    with activate_tenant_context(assistant):
        waiting = execute_plan(plan)
    tokens = consents(owner, assistant, plan)
    with activate_tenant_context(assistant):
        (result,) = execute_plan(plan, tokens)

    assert [(r.status, r.code) for r in waiting] == [("refused", "consent_required")]
    assert (result.status, result.output) == ("done", {"name": "Domki nad jeziorem"})
    assert name_of(owner) == "Domki nad jeziorem"
    entry = OrganizationAuditEntry.objects.filter(organization_id=owner.organization_id).latest(
        "occurred_at"
    )
    assert (entry.channel, entry.acting_via, entry.acting_ref, entry.actor_user_id) == (
        "membership",
        "assistant",
        assistant.acting_ref,
        owner.actor_id,
    )


def test_a_retried_step_answers_from_its_receipt_even_after_its_own_write(
    owner: TenantContext,
) -> None:
    assistant = assistant_of(owner)
    step = str(uuid7())
    plan = [call("organization.rename@1", step=step)]
    tokens = consents(owner, assistant, plan)
    with activate_tenant_context(assistant):
        first = execute_plan(plan, tokens)
        # The rename moved the version the preview read, so a new preview
        # would no longer match the consent; the receipt answers first.
        again = execute_plan(plan, tokens)
        changed = execute_plan([call("organization.rename@1", "Inna nazwa", step=step)], tokens)

    assert first == again
    assert RUNS == ["Domki nad jeziorem"]
    assert CommandReceipt.objects.count() == 1
    assert [(r.status, r.code) for r in changed] == [("refused", "command_idempotency_conflict")]


def test_a_plan_whose_state_moved_since_the_click_is_shown_again(owner: TenantContext) -> None:
    assistant = assistant_of(owner)
    plan = [call("organization.rename@1")]
    tokens = consents(owner, assistant, plan)
    Organization.objects.filter(pk=owner.organization_id).update(version=9)
    with activate_tenant_context(assistant):
        (result,) = execute_plan(plan, tokens)
    assert (result.status, result.code) == ("refused", "consent_digest_mismatch")
    assert RUNS == []


def test_each_group_needs_its_own_click(owner: TenantContext) -> None:
    assistant = assistant_of(owner)
    plan = [call("organization.rename@1"), call("organization.note@1", "Ogłoszenie")]
    tokens = consents(owner, assistant, plan)
    first_group = next(iter(tokens))
    with activate_tenant_context(assistant):
        only_first = execute_plan(plan, {first_group: tokens[first_group]})
    assert [(r.status, r.code) for r in only_first] == [
        ("done", None),
        ("refused", "consent_required"),
    ]
    # The rest of a half-run plan is a new plan, not a retry of this one.
    with activate_tenant_context(assistant):
        retried = execute_plan(plan, tokens)
    assert [(r.status, r.code) for r in retried] == [
        ("done", None),
        ("refused", "command_partially_applied"),
    ]
    assert RUNS == ["Domki nad jeziorem"]


def test_a_failing_group_is_undone_and_stops_the_groups_after_it(owner: TenantContext) -> None:
    assistant = assistant_of(owner)
    for failing, code, status in (
        ("Odmowa", "invalid", "refused"),
        ("Błąd", "command_internal_error", "failed"),
    ):
        plan = [call("organization.note@1", "Przed"), call("organization.rename@1", failing)]
        plan.append(call("organization.note@1", "Po"))
        tokens = consents(owner, assistant, plan)
        with activate_tenant_context(assistant):
            results = execute_plan(plan, tokens)
        assert [(r.status, r.code) for r in results] == [
            ("done", None),
            (status, code),
            ("skipped", None),
        ]
        assert name_of(owner) == "Domki"
    refused = [r for r in results if r.status == "failed"]
    assert refused[0].errors == ()
    # A retry after a failure runs afresh: the failed step left no receipt.
    assert not CommandReceipt.objects.filter(command="organization.rename@1").exists()


def test_a_field_refusal_names_the_field(owner: TenantContext) -> None:
    assistant = assistant_of(owner)
    plan = [call("organization.rename@1", "Odmowa")]
    tokens = consents(owner, assistant, plan)
    with activate_tenant_context(assistant):
        (result,) = execute_plan(plan, tokens)
    assert [(error["field"], error["code"]) for error in result.errors] == [("name", "invalid")]


def test_a_group_that_needs_a_step_up_stays_closed_until_there_is_one(
    owner: TenantContext,
) -> None:
    assistant = assistant_of(owner)
    plan = [call("organization.bill@1")]
    tokens = consents(owner, assistant, plan)
    with activate_tenant_context(assistant):
        (result,) = execute_plan(plan, tokens)
    assert (result.status, result.code) == ("refused", "step_up_required")
    assert RUNS == []
