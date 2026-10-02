"""The eval battery every registered command passes (ADR-076 §1).

Not a test of one command but of the contract each one keeps with a model and
a person: refused without the permission, before anything is read; wrong
arguments named field by field; stopped by a plan without the feature; a
preview that writes nothing and a read that writes nothing; the same digest
for the same state; no run without a click; a step that runs once however
often it is retried, recorded in the history as the assistant acting for the
person; a consent that goes stale when what it saw moved; and another company
left alone. The entries are in `tests/command_evals/`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from command_evals import CommandEval, all_evals
from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_consent import mint_consent
from saas_core.modules.core.organizations.command_executor import (
    Invocation,
    execute_plan,
    preview_plan,
)
from saas_core.modules.core.organizations.command_registry import command, registered_commands
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

pytestmark = pytest.mark.django_db

EVALS = all_evals()
COMMANDS = [spec.key for spec in registered_commands()]
READS = [key for key in COMMANDS if command(key).risk == "read"]
WRITES = [key for key in COMMANDS if command(key).risk != "read"]
_WRITE_SQL = ("INSERT", "UPDATE", "DELETE")


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The plan's own decision has its tests (`test_command_executor.py`)."""
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def owner(slug: str) -> TenantContext:
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name="Domki", slug=slug, status=OrganizationStatus.ACTIVE
    )
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    return context_from_membership(membership)


def assistant(person: TenantContext) -> TenantContext:
    return acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")


def invocation(key: str, arguments: dict[str, Any], step: str | None = None) -> Invocation:
    return Invocation(command=key, arguments=arguments, step_id=step or str(uuid7()))


def clicked(person: TenantContext, acting: TenantContext, plan: list[Invocation]) -> dict[str, str]:
    with activate_tenant_context(acting):
        groups = preview_plan(plan).groups
    return {
        group.id: mint_consent(person, digest=group.digest, acting_ref=acting.acting_ref)
        for group in groups
    }


def refusal_codes(context: TenantContext, plan: list[Invocation]) -> list[str]:
    with activate_tenant_context(context):
        return [refusal.code for refusal in preview_plan(plan).refusals]


def writes(queries: CaptureQueriesContext) -> list[str]:
    return [
        query["sql"]
        for query in queries.captured_queries
        if query["sql"].lstrip().upper().startswith(_WRITE_SQL)
    ]


def entry(key: str) -> CommandEval:
    return EVALS[key]


def test_every_registered_command_has_evals() -> None:
    assert COMMANDS, "Rejestr jest pusty — bateria niczego nie sprawdza."
    assert sorted(EVALS) == sorted(COMMANDS), (
        "Każde polecenie potrzebuje wpisu w tests/command_evals/ (i żaden wpis nie może "
        "zostać po poleceniu, którego już nie ma)."
    )


@pytest.mark.parametrize("key", COMMANDS)
def test_without_the_permission_it_is_refused_before_anything_is_read(key: str) -> None:
    person = owner(f"perm-{key.replace('.', '-').replace('@', '-')}")
    bare = assistant(replace(person, permissions=frozenset()))
    with CaptureQueriesContext(connection) as queries:
        codes = refusal_codes(bare, [invocation(key, entry(key).arguments(person))])
    assert codes == ["organization_permission_denied"]
    assert queries.captured_queries == []


@pytest.mark.parametrize("key", COMMANDS)
def test_wrong_arguments_name_the_field(key: str) -> None:
    person = owner(f"args-{key.replace('.', '-').replace('@', '-')}")
    with activate_tenant_context(assistant(person)):
        (refusal,) = preview_plan([invocation(key, entry(key).wrong_arguments)]).refusals
    assert refusal.status == 400
    assert entry(key).wrong_field in [error["field"] for error in refusal.errors]


@pytest.mark.parametrize("key", COMMANDS)
def test_a_plan_without_the_feature_stops_it(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: "feature_disabled"})
    person = owner(f"feature-{key.replace('.', '-').replace('@', '-')}")
    assert refusal_codes(assistant(person), [invocation(key, entry(key).arguments(person))]) == [
        "feature_disabled"
    ]


@pytest.mark.parametrize("key", COMMANDS)
def test_the_preview_writes_nothing(key: str) -> None:
    person = owner(f"preview-{key.replace('.', '-').replace('@', '-')}")
    with activate_tenant_context(assistant(person)), CaptureQueriesContext(connection) as queries:
        plan = preview_plan([invocation(key, entry(key).arguments(person))])
    assert plan.refusals == ()
    assert writes(queries) == []


@pytest.mark.parametrize("key", READS)
def test_a_read_writes_nothing(key: str) -> None:
    person = owner(f"read-{key.replace('.', '-').replace('@', '-')}")
    with activate_tenant_context(assistant(person)), CaptureQueriesContext(connection) as queries:
        (result,) = execute_plan([invocation(key, entry(key).arguments(person))])
    assert result.status == "done", result
    assert writes(queries) == []


@pytest.mark.parametrize("key", WRITES)
def test_the_same_state_gives_the_same_digest(key: str) -> None:
    person = owner(f"digest-{key.replace('.', '-').replace('@', '-')}")
    acting = assistant(person)
    plan = [invocation(key, entry(key).arguments(person))]
    with activate_tenant_context(acting):
        first, second = preview_plan(plan), preview_plan(plan)
    assert [group.digest for group in first.groups] == [group.digest for group in second.groups]


@pytest.mark.parametrize("key", WRITES)
def test_nothing_runs_without_a_click(key: str) -> None:
    person = owner(f"click-{key.replace('.', '-').replace('@', '-')}")
    before = entry(key).state(person)
    with activate_tenant_context(assistant(person)):
        (result,) = execute_plan([invocation(key, entry(key).arguments(person))])
    assert (result.status, result.code) == ("refused", "consent_required")
    assert entry(key).state(person) == before


@pytest.mark.parametrize("key", WRITES)
def test_a_step_runs_once_and_the_history_says_who_acted_for_whom(key: str) -> None:
    person = owner(f"once-{key.replace('.', '-').replace('@', '-')}")
    acting = assistant(person)
    plan = [invocation(key, entry(key).arguments(person))]
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        first = execute_plan(plan, tokens)
        again = execute_plan(plan, tokens)

    assert [result.status for result in first] == ["done"], first
    assert again == first
    assert CommandReceipt.objects.filter(command=key).count() == 1
    latest = OrganizationAuditEntry.objects.filter(organization_id=person.organization_id).latest(
        "occurred_at"
    )
    assert (latest.channel, latest.acting_via, latest.acting_ref) == (
        "membership",
        "assistant",
        acting.acting_ref,
    )
    assert latest.actor_user_id == person.actor_id


@pytest.mark.parametrize("key", WRITES)
def test_a_consent_goes_stale_when_what_it_saw_moved(key: str) -> None:
    stale = entry(key).stale
    if isinstance(stale, str):
        pytest.skip(stale)
    person = owner(f"stale-{key.replace('.', '-').replace('@', '-')}")
    acting = assistant(person)
    plan = [invocation(key, entry(key).arguments(person))]
    tokens = clicked(person, acting, plan)
    stale(person)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)
    assert (result.status, result.code) == ("refused", "consent_digest_mismatch")


@pytest.mark.parametrize("key", WRITES)
def test_another_company_is_left_alone(key: str) -> None:
    here = owner(f"here-{key.replace('.', '-').replace('@', '-')}")
    there = owner(f"there-{key.replace('.', '-').replace('@', '-')}")
    before = entry(key).state(here)
    acting = assistant(there)
    plan = [invocation(key, entry(key).arguments(there))]
    tokens = clicked(there, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)
    assert result.status == "done", result
    assert entry(key).state(here) == before
