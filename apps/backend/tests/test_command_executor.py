"""The command executor admits every call as if the model had made it up
(ADR-076 §1–§3): exposure, permission, module, arguments, a preview that cannot
write, every gate — and groups what one click may cover under a digest that
changes whenever the plan, an argument or the previewed state does."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import command_executor, command_registry
from saas_core.modules.core.organizations.command_executor import (
    CommandUnavailable,
    Invocation,
    execute_plan,
    idempotency_key,
    preview_plan,
    register_command_gate,
)
from saas_core.modules.core.organizations.command_registry import (
    CommandSpec,
    Effect,
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
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.permissions import ORGANIZATION_READ, SETTINGS_MANAGE
from saas_core.modules.shared.billing import command_gate
from saas_core.modules.shared.billing.overrides import create_entitlement_override
from test_billing_decisions import snapshot

pytestmark = pytest.mark.django_db

PREVIEWED: list[str] = []


def _rename(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    organization = Organization.objects.get(pk=call.context.organization_id)
    organization.name = arguments["name"]
    organization.save(update_fields=["name"])
    return {"name": organization.name}


def _read(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    # A read that writes anyway: the executor must roll it back.
    Organization.objects.filter(pk=call.context.organization_id).update(name="Zmienione")
    return {"name": Organization.objects.get(pk=call.context.organization_id).name}


def _preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    PREVIEWED.append(arguments["name"])
    organization = Organization.objects.get(pk=call.context.organization_id)
    # A preview that writes anyway: rolled back with the preview.
    Organization.objects.filter(pk=organization.pk).update(name="Podgląd")
    return Preview(
        effects=(
            Effect(
                kind="updated",
                resource="organization",
                resource_id=str(organization.pk),
                summary={"pl": f"Nazwa: {arguments['name']}", "en": f"Name: {arguments['name']}"},
            ),
        ),
        observed_versions={f"organization:{organization.pk}": organization.version},
        escalate_to="publish" if arguments["name"] == "Na żywo" else None,
    )


INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "address", "items"],
    "properties": {
        "name": {"type": "string", "description": "Name.", "maxLength": 40},
        "address": {
            "type": ["object", "null"],
            "description": "Address.",
            "additionalProperties": False,
            "required": ["city"],
            "properties": {"city": {"type": "string", "description": "City."}},
        },
        "items": {
            "type": "array",
            "description": "Items.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": {"type": "string", "description": "Item."}},
            },
        },
    },
}
OUTPUT = {"type": "object", "properties": {"name": {"type": "string", "x-data-class": "public"}}}


def _unobserved(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(effects=(), observed_versions={})


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
        "permission": SETTINGS_MANAGE,
        "risk": "apply",
        "run": _rename,
        "undo": "restore_version",
        "preview": _preview,
        "version_field": "version",
    }
    declaration.update(changes)
    return CommandSpec(**declaration)


def allow_all(*_: Any) -> None:
    return None


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_executor, "_gates", {"features": allow_all})
    PREVIEWED.clear()
    register_command(spec())
    register_command(
        spec(
            name="organization.overview",
            risk="read",
            run=_read,
            preview=None,
            no_preview_reason="A read changes nothing to preview.",
            version_field=None,
            no_version_reason="A read has no version to check.",
            permission=ORGANIZATION_READ,
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


def assistant(context: TenantContext, conversation: str | None = None) -> TenantContext:
    return acting_context(context, via="assistant", ref=f"conversation:{conversation or uuid7()}")


def call(command: str, step_id: str | None = None, **arguments: Any) -> Invocation:
    return Invocation(
        command=command,
        arguments={"name": "Domki nad jeziorem", "address": None, "items": [], **arguments},
        step_id=step_id or str(uuid7()),
    )


def test_the_person_in_the_panel_does_not_run_commands(owner: TenantContext) -> None:
    with activate_tenant_context(owner), pytest.raises(CommandUnavailable):
        preview_plan([call("organization.rename@1")])


def test_unknown_unexposed_and_unreachable_commands_are_one_refusal(
    owner: TenantContext, settings: Any
) -> None:
    register_command(spec(name="organization.export", exposure=frozenset({"mcp"})))
    register_command(
        spec(name="sites.page.rename", module="shared.sites", permission="site.content.edit")
    )
    # Every type without modules — a product's types are not core's.
    settings.ORGANIZATION_TYPES = {
        key: replace(kind, modules=frozenset())
        for key, kind in settings.ORGANIZATION_TYPES.items()
    }
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([
            call("organization.rename@9"),
            call("organization_export_v1"),
            call("sites.page.rename@1"),
        ])
    assert [refusal.code for refusal in plan.refusals] == [
        "command_unavailable",
        "command_unavailable",
        "module_not_available",
    ]
    assert (plan.groups, plan.reads) == ((), ())


def test_the_permission_is_checked_before_anything_is_read(owner: TenantContext) -> None:
    reader = replace(owner, permissions=frozenset({ORGANIZATION_READ}))
    with activate_tenant_context(assistant(reader)):
        plan = preview_plan([call("organization_rename_v1")])
    assert [refusal.code for refusal in plan.refusals] == ["organization_permission_denied"]
    assert PREVIEWED == []


def test_arguments_are_refused_field_by_field(owner: TenantContext) -> None:
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([
            Invocation(
                command="organization.rename@1",
                arguments={"name": 7, "address": {"town": "Mrągowo"}, "items": [{}, {"name": 1}]},
                step_id=str(uuid7()),
            )
        ])
    (refusal,) = plan.refusals
    assert (refusal.status, refusal.code) == (400, "command_args_invalid")
    assert sorted((error["field"], error["code"]) for error in refusal.errors) == [
        ("address.city", "required"),
        ("address.town", "additionalProperties"),
        ("items.0.name", "required"),
        ("items.1.name", "type"),
        ("name", "type"),
    ]
    assert PREVIEWED == []


def test_without_the_features_gate_nothing_runs(
    owner: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command_executor, "_gates", {})
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([call("organization.overview@1")])
    assert [refusal.code for refusal in plan.refusals] == ["command_features_unavailable"]


def test_every_gate_must_pass_and_a_failing_gate_refuses(owner: TenantContext) -> None:
    register_command_gate("company", lambda spec, *_: "offer_switched_off")
    with activate_tenant_context(assistant(owner)):
        assert [r.code for r in preview_plan([call("organization.rename@1")]).refusals] == [
            "offer_switched_off"
        ]

    def broken(*_: Any) -> str | None:
        raise RuntimeError("settings unavailable")

    command_executor._gates["company"] = broken
    with activate_tenant_context(assistant(owner)):
        assert [r.code for r in preview_plan([call("organization.rename@1")]).refusals] == [
            "command_company_unavailable"
        ]


def test_a_preview_and_a_read_cannot_write(owner: TenantContext) -> None:
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([call("organization.rename@1")])
        results = execute_plan([call("organization.overview@1")])
    assert PREVIEWED == ["Domki nad jeziorem"]
    assert plan.groups[0].calls[0].preview is not None
    (result,) = results
    assert (result.status, result.output) == ("done", {"name": "Zmienione"})
    assert Organization.objects.get(pk=owner.organization_id).name == "Domki"


def test_draft_and_apply_share_a_click_and_the_rest_get_their_own(
    owner: TenantContext,
) -> None:
    for name, changes in (
        ("organization.describe", {"risk": "draft"}),
        ("organization.bill", {"modifiers": frozenset({"changes_billing"})}),
        ("organization.bulk", {"modifiers": frozenset({"bulk"})}),
    ):
        register_command(spec(name=name, preview=_unobserved, **changes))
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([
            call("organization.overview@1"),
            call("organization.rename@1"),
            call("organization.describe@1"),
            call("organization.bill@1"),
            call("organization.bulk@1"),
        ])
    assert [call.spec.name for call in plan.reads] == ["organization.overview"]
    assert [[call.spec.name for call in group.calls] for group in plan.groups] == [
        ["organization.rename", "organization.describe"],
        ["organization.bill"],
        ["organization.bulk"],
    ]
    assert [group.step_up_required for group in plan.groups] == [False, True, False]


def test_one_resource_is_changed_by_one_call_of_a_plan(owner: TenantContext) -> None:
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([call("organization.rename@1"), call("organization.rename@1")])
    assert [refusal.code for refusal in plan.refusals] == ["command_plan_conflict"]


def test_an_escalation_only_raises_the_class(owner: TenantContext) -> None:
    with activate_tenant_context(assistant(owner)):
        plan = preview_plan([call("organization.rename@1", name="Na żywo")])
    (group,) = plan.groups
    assert group.risk == "publish"


def test_the_digest_binds_the_plan_the_state_and_the_conversation(owner: TenantContext) -> None:
    conversation = str(uuid7())
    step = str(uuid7())

    def digest(context: TenantContext, **arguments: Any) -> str:
        with activate_tenant_context(context):
            (group,) = preview_plan([call("organization.rename@1", step, **arguments)]).groups
        return group.digest

    first = digest(assistant(owner, conversation))
    assert digest(assistant(owner, conversation)) == first
    assert digest(assistant(owner, conversation), name="Inna nazwa") != first
    assert digest(assistant(owner)) != first
    Organization.objects.filter(pk=owner.organization_id).update(version=7)
    assert digest(assistant(owner, conversation)) != first


def test_the_idempotency_key_follows_the_servers_step(owner: TenantContext) -> None:
    context = assistant(owner)
    step = str(uuid7())
    rename = command_registry.command("organization.rename@1")
    assert idempotency_key(context, rename, step) == idempotency_key(context, rename, step)
    assert idempotency_key(context, rename, step) != idempotency_key(context, rename, str(uuid7()))


def test_writes_wait_for_consent_and_a_refused_plan_runs_nothing(owner: TenantContext) -> None:
    with activate_tenant_context(assistant(owner)):
        waiting = execute_plan([call("organization.overview@1"), call("organization.rename@1")])
        refused = execute_plan([call("organization.overview@1"), call("organization.rename@9")])
    assert [(result.status, result.code) for result in waiting] == [
        ("done", None),
        ("refused", "consent_required"),
    ]
    assert [(result.status, result.code) for result in refused] == [
        ("skipped", None),
        ("refused", "command_unavailable"),
    ]
    assert Organization.objects.get(pk=owner.organization_id).name == "Domki"


def test_a_command_that_breaks_fails_without_taking_the_plan_down(owner: TenantContext) -> None:
    def broken(*_: Any) -> dict[str, Any]:
        raise RuntimeError("bug")

    register_command(
        spec(
            name="organization.broken",
            risk="read",
            run=broken,
            preview=None,
            no_preview_reason="Read.",
            version_field=None,
            no_version_reason="Read.",
        )
    )
    with activate_tenant_context(assistant(owner)):
        results = execute_plan([call("organization.broken@1"), call("organization.overview@1")])
    assert [(result.status, result.code) for result in results] == [
        ("failed", "command_internal_error"),
        ("done", None),
    ]


def test_the_plan_decides_whether_the_assistant_may_act(owner: TenantContext) -> None:
    """In no plan yet (billing 0026): refused until an operator's audited
    override gives one pilot organization the assistant."""
    rename = command_registry.command("organization.rename@1")
    organization = Organization.objects.get(pk=owner.organization_id)
    snapshot(organization)
    with activate_tenant_context(assistant(owner)):
        assert command_gate.plan_features(rename, assistant(owner), {}, None) == (
            "feature_disabled"
        )
    assert command_gate.plan_features(rename, owner, {}, None) == "channel_unavailable"

    operator = User.objects.create_user(
        email="pilot-operator@example.test", status=UserStatus.ACTIVE, is_staff=True
    )
    with activate_tenant_context(replace(owner, actor_id=operator.id, permissions=frozenset())):
        create_entitlement_override(
            actor=operator,
            feature_key="assistant.text.enabled",
            enabled=True,
            reason="Pilot asystenta",
            idempotency_key="pilot:assistant-text",
        )
    with activate_tenant_context(assistant(owner)):
        assert command_gate.plan_features(rename, assistant(owner), {}, None) is None


def test_the_plan_gate_asks_for_channel_extra_features_and_entitlement(
    owner: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, str]] = []

    class Allowed:
        allowed = True

    def decide(key: str, *, operation: Any) -> Allowed:
        asked.append((key, str(operation)))
        return Allowed()

    monkeypatch.setattr(command_gate, "decide_feature", decide)
    site_command = spec(
        name="sites.page.draft",
        module="shared.sites",
        permission="site.content.edit",
        entitlement="sites.enabled",
        extra_features=frozenset({"assistant.site_generation.enabled"}),
        risk="read",
    )
    assert command_gate.plan_features(site_command, assistant(owner), {}, None) is None
    assert asked == [
        ("assistant.text.enabled", "read"),
        ("assistant.site_generation.enabled", "read"),
        ("sites.enabled", "read"),
    ]
