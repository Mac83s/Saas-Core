"""The person's click on a plan the assistant showed (ADR-076 §3).

The dialog reads the plan the server stored, never the model's description of
it; only the person signed in to the panel can consent, with the session and
CSRF; the conversation the token binds comes from the stored plan, not from the
request; and someone else's plan looks exactly like an expired one.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations import command_executor, command_registry
from saas_core.modules.core.organizations.command_consent import read_consent
from saas_core.modules.core.organizations.command_executor import (
    Invocation,
    execute_plan,
    offer_plan,
    pending_consent,
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
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.core.organizations.views import ConsentPersonOnly, _waiting_plan
from test_command_executor import INPUT, OUTPUT, allow_all
from test_sites_api import csrf_value, sites_client

pytestmark = pytest.mark.django_db

URL = "/api/v1/organizations/current/command-consents/{}/"


def _note(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return {"name": arguments["name"]}


def _preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    return Preview(
        effects=(
            Effect(
                kind="updated",
                resource="organization",
                resource_id=str(call.context.organization_id),
                summary={"pl": f"Nazwa: {arguments['name']}", "en": f"Name: {arguments['name']}"},
            ),
        ),
        observed_versions={},
    )


def spec(**changes: Any) -> CommandSpec:
    declaration: dict[str, Any] = {
        "name": "organization.note",
        "version": 1,
        "module": "core.organizations",
        "title": {"pl": "Notatka firmy", "en": "Company note"},
        "summary": {"pl": "Zapisuje notatkę.", "en": "Saves a note."},
        "model_description": "Saves a note.",
        "input_schema": INPUT,
        "output_schema": OUTPUT,
        "permission": SETTINGS_MANAGE,
        "risk": "apply",
        "run": _note,
        "undo": "none:a note stays",
        "preview": _preview,
        "no_version_reason": "A note has no version.",
    }
    declaration.update(changes)
    return CommandSpec(**declaration)


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_executor, "_gates", {"features": allow_all})
    cache.clear()
    register_command(spec())
    register_command(spec(name="organization.bill", modifiers=frozenset({"changes_billing"})))
    yield


def signed_in(slug: str, role_key: str = "owner") -> tuple[APIClient, TenantContext]:
    client, organization, user = sites_client(slug=slug, role_key=role_key)
    membership = Membership.objects.select_related("role").get(organization=organization, user=user)
    return client, context_from_membership(membership)


def shown(person: TenantContext, command: str = "organization.note@1") -> tuple[str, TenantContext]:
    """The assistant shows a one-call plan in a conversation of this person."""
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    invocation = Invocation(
        command=command,
        arguments={"name": "Domki nad jeziorem", "address": None, "items": []},
        step_id=str(uuid7()),
    )
    with activate_tenant_context(assistant):
        (group,) = offer_plan([invocation]).groups
    return group.digest, assistant


def test_the_dialog_shows_what_the_server_previewed() -> None:
    client, person = signed_in("consent-show")
    digest, _assistant = shown(person)

    response = client.get(URL.format(digest))

    assert response.status_code == 200, response.data
    (call,) = response.data["calls"]
    assert (response.data["digest"], response.data["risk"]) == (digest, "apply")
    assert response.data["step_up_required"] is False
    assert call["command"] == "organization.note@1"
    assert call["title"] == {"pl": "Notatka firmy", "en": "Company note"}
    assert call["effects"][0]["summary"]["pl"] == "Nazwa: Domki nad jeziorem"
    assert "acting_ref" not in response.data


def test_a_click_mints_a_token_for_the_conversation_the_plan_came_from() -> None:
    client, person = signed_in("consent-grant")
    digest, assistant = shown(person)
    other = f"conversation:{uuid7()}"

    response = client.post(
        URL.format(digest),
        {"acting_ref": other},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == 201, response.data
    token = response.data["consent_token"]
    assert read_consent(token, context=assistant).digest == digest
    entry = OrganizationAuditEntry.objects.filter(organization_id=person.organization_id).latest(
        "occurred_at"
    )
    assert entry.action == "commands.consent.granted"
    assert (entry.channel, entry.acting_via) == ("membership", "")
    assert entry.metadata["commands"] == ["organization.note@1"]
    assert entry.metadata["conversation"] == assistant.acting_ref


def test_the_token_runs_the_plan_it_was_given_for() -> None:
    client, person = signed_in("consent-run")
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    invocation = Invocation(
        command="organization.note@1",
        arguments={"name": "Domki nad jeziorem", "address": None, "items": []},
        step_id=str(uuid7()),
    )
    with activate_tenant_context(assistant):
        (group,) = offer_plan([invocation]).groups
    token = client.post(URL.format(group.digest), HTTP_X_CSRFTOKEN=csrf_value(client)).data[
        "consent_token"
    ]

    with activate_tenant_context(assistant):
        (result,) = execute_plan([invocation], {group.id: token})

    assert (result.status, result.output) == ("done", {"name": "Domki nad jeziorem"})


def test_without_csrf_or_a_session_there_is_no_click() -> None:
    client, person = signed_in("consent-csrf")
    digest, _assistant = shown(person)

    assert client.post(URL.format(digest)).status_code == 403
    assert APIClient().get(URL.format(digest)).status_code == 403


def test_someone_elses_plan_looks_like_an_expired_one() -> None:
    owner_client, owner = signed_in("consent-owner")
    digest, _assistant = shown(owner)
    other_company_client, _other = signed_in("consent-other")
    colleague = replace(owner, membership_id=uuid7(), actor_id=uuid7())

    elsewhere = other_company_client.get(URL.format(digest))
    malformed = owner_client.get(URL.format("not-a-digest"))
    assert pending_consent(colleague, digest) is None
    cache.clear()
    expired = owner_client.get(URL.format(digest))

    for response in (elsewhere, malformed, expired):
        assert response.status_code == 404
        assert response.data["code"] == "consent_preview_not_found"


def test_neither_an_integration_nor_the_assistant_consents() -> None:
    _client, person = signed_in("consent-channels")
    digest, assistant = shown(person)
    for context in (assistant, replace(person, principal_kind="api_key")):
        with activate_tenant_context(context), pytest.raises(ConsentPersonOnly):
            _waiting_plan(digest)


def test_a_plan_that_needs_a_step_up_waits_for_one() -> None:
    """Without two-factor sign-in the person is told to turn it on (answer 31b);
    with it, the click waits for a code (tests/test_identity_step_up.py)."""
    client, person = signed_in("consent-step-up")
    digest, _assistant = shown(person, "organization.bill@1")

    response = client.post(URL.format(digest), HTTP_X_CSRFTOKEN=csrf_value(client))

    assert response.status_code == 403
    assert response.data["code"] == "step_up_mfa_setup_required"
    assert client.get(URL.format(digest)).data["step_up_required"] is True
