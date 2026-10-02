"""Step-up: a fresh second factor for legal documents and billing (ADR-076 §2;
owner answers 30a and 31b). A code from the authenticator app and nothing
else; an account without two-factor sign-in is told to turn it on; wrong codes
end the session; and a step-up made in the panel never reaches what the
assistant runs without one."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import MfaRecoveryCode, User, UserMfaMethod
from saas_core.modules.core.identity.step_up import (
    STEP_UP_SESSION_KEY,
    StepUpMfaSetupRequired,
    StepUpRequired,
    activate_step_up,
    require_step_up,
)
from saas_core.modules.core.organizations import command_executor, command_registry
from saas_core.modules.core.organizations.command_executor import Invocation, execute_plan
from saas_core.modules.core.organizations.command_registry import register_command
from saas_core.modules.core.organizations.context import acting_context, activate_tenant_context
from test_command_consent import consents
from test_command_consent_api import URL, shown, signed_in, spec
from test_command_executor import allow_all
from test_mfa import active_user, enable_mfa
from test_sites_api import csrf_value

pytestmark = pytest.mark.django_db

STEP_UP_URL = "/api/v1/auth/step-up/"


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_registry, "_commands", {})
    monkeypatch.setattr(command_registry, "_tools", {})
    monkeypatch.setattr(command_executor, "_gates", {"features": allow_all})
    cache.clear()
    yield


def step_up(client: APIClient, code: str) -> Any:
    return client.post(
        STEP_UP_URL, {"code": code}, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )


def next_code(secret: str) -> str:
    """The next period's code: the one used to enable MFA counts only once."""
    return current_totp_code(secret, at=timezone.now().timestamp() + 30)


def test_a_code_from_the_app_steps_up_and_a_recovery_code_does_not() -> None:
    client = APIClient(enforce_csrf_checks=True)
    user = active_user("step-up@example.com")
    secret, recovery_codes = enable_mfa(client, user)

    recovery = step_up(client, recovery_codes[0])
    assert recovery.status_code == 400
    assert recovery.data["code"] == "invalid_mfa_code"
    assert not MfaRecoveryCode.objects.filter(used_at__isnull=False).exists()

    confirmed = step_up(client, next_code(secret))
    assert confirmed.status_code == 200, confirmed.data
    assert STEP_UP_SESSION_KEY in client.session
    assert step_up(client, next_code(secret)).status_code == 400  # a code counts once


def test_an_account_without_two_factor_is_told_to_turn_it_on() -> None:
    client, _person = signed_in("step-up-no-mfa")

    response = step_up(client, "123456")

    assert response.status_code == 403
    assert response.data["code"] == "step_up_mfa_setup_required"
    assert "weryfikację dwuetapową" in response.data["detail"]


def test_five_wrong_codes_end_the_session() -> None:
    client = APIClient(enforce_csrf_checks=True)
    user = active_user("step-up-locked@example.com")
    enable_mfa(client, user)

    answers = [step_up(client, "000000") for _ in range(5)]

    assert [answer.status_code for answer in answers] == [400, 400, 400, 400, 403]
    assert answers[-1].data["code"] == "step_up_locked"
    assert client.get("/api/v1/auth/me/").status_code in {401, 403}


def test_a_step_up_is_fresh_for_a_while_and_then_asked_again(settings: Any) -> None:
    user = active_user("step-up-window@example.com")
    enable_mfa(APIClient(enforce_csrf_checks=True), user)
    plain = active_user("step-up-plain@example.com")

    with activate_step_up(int(timezone.now().timestamp())):
        require_step_up(user_id=user.id, reason="legal document")
        settings.STEP_UP_MAX_AGE = -1
        with pytest.raises(StepUpRequired):
            require_step_up(user_id=user.id, reason="legal document")
    with pytest.raises(StepUpMfaSetupRequired):
        require_step_up(user_id=plain.id, reason="billing")


def _billing(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    require_step_up(user_id=call.context.actor_id, reason="billing")
    return {"name": arguments["name"]}


def test_a_billing_command_runs_with_the_step_up_its_click_carried() -> None:
    register_command(
        spec(name="organization.bill", modifiers=frozenset({"changes_billing"}), run=_billing)
    )
    client, person = signed_in("step-up-billing")
    user = User.objects.get(pk=person.actor_id)
    setup = client.post("/api/v1/auth/mfa/totp/setup/", HTTP_X_CSRFTOKEN=csrf_value(client))
    secret = setup.data["secret"]
    client.post(
        "/api/v1/auth/mfa/totp/confirm/",
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert UserMfaMethod.objects.filter(user=user, confirmed_at__isnull=False).exists()
    digest, assistant = shown(person, "organization.bill@1")

    before = client.post(URL.format(digest), HTTP_X_CSRFTOKEN=csrf_value(client))
    assert before.data["code"] == "step_up_required"
    assert step_up(client, next_code(secret)).status_code == 200
    granted = client.post(URL.format(digest), HTTP_X_CSRFTOKEN=csrf_value(client))
    assert granted.status_code == 201, granted.data

    invocation = Invocation(
        command="organization.bill@1",
        arguments={"name": "Domki nad jeziorem", "address": None, "items": []},
        step_id=_step_of(digest),
    )
    with activate_tenant_context(assistant):
        (result,) = execute_plan([invocation], {invocation.step_id: granted.data["consent_token"]})
    assert (result.status, result.code) == ("done", None)


def test_a_step_up_from_the_panel_session_never_reaches_a_command() -> None:
    """The command did not declare billing, its service still asks: the
    person's fresh panel step-up must not answer for the assistant."""
    register_command(spec(name="organization.note", run=_billing))
    _client, person = signed_in("step-up-leak")
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    invocation = Invocation(
        command="organization.note@1",
        arguments={"name": "Notatka", "address": None, "items": []},
        step_id=str(uuid7()),
    )
    tokens = consents(person, assistant, [invocation])
    with activate_step_up(int(timezone.now().timestamp())), activate_tenant_context(assistant):
        (result,) = execute_plan([invocation], tokens)

    assert result.code in {"step_up_required", "step_up_mfa_setup_required"}


def _step_of(digest: str) -> str:
    return cache.get(f"core.commands.pending:{digest}")["group"]
