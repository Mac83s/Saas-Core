from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import (
    AccountAuditEvent,
    AccountAuditEventType,
    LoginAttempt,
    LoginOutcome,
    MfaRecoveryCode,
    User,
    UserMfaMethod,
    UserSession,
    UserStatus,
)
from saas_core.modules.core.identity.sessions import MFA_CHALLENGE_EXPIRES_KEY

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
MFA_LOGIN_URL = "/api/v1/auth/login/mfa/"
MFA_SETUP_URL = "/api/v1/auth/mfa/totp/setup/"
MFA_CONFIRM_URL = "/api/v1/auth/mfa/totp/confirm/"
LOGOUT_URL = "/api/v1/auth/logout/"
STEP_UP_URL = "/api/v1/auth/step-up/"
ME_URL = "/api/v1/auth/me/"
PASSWORD = "Bezpieczne-Haslo-MFA-2026!"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def active_user(email: str = "mfa@example.com", *, staff: bool = False) -> User:
    user = User.objects.create_user(email=email, password=PASSWORD, is_staff=staff)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def csrf_token(client: APIClient) -> str:
    return client.get(CSRF_URL).data["csrf_token"]


def login(client: APIClient, user: User):
    return client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token(client),
    )


def enable_mfa(client: APIClient, user: User) -> tuple[str, list[str]]:
    assert login(client, user).status_code == 200
    setup = client.post(
        MFA_SETUP_URL,
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert setup.status_code == 200, setup.data
    secret = setup.data["secret"]
    confirmed = client.post(
        MFA_CONFIRM_URL,
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert confirmed.status_code == 200
    return secret, confirmed.data["recovery_codes"]


def test_totp_enrollment_encrypts_secret_and_hashes_recovery_codes(caplog) -> None:
    user = active_user()
    client = APIClient(enforce_csrf_checks=True)

    with caplog.at_level("INFO", logger="saas_core.security"):
        secret, recovery_codes = enable_mfa(client, user)

    method = UserMfaMethod.objects.get(user=user)
    stored_codes = list(
        MfaRecoveryCode.objects.filter(method=method).values_list("code_hash", flat=True)
    )
    assert method.confirmed_at is not None
    assert secret not in method.secret_ciphertext
    assert method.secret_ciphertext != secret
    assert len(recovery_codes) == len(stored_codes) == 8
    assert all(raw_code not in stored_codes for raw_code in recovery_codes)
    assert secret not in caplog.text
    assert all(raw_code not in caplog.text for raw_code in recovery_codes)
    audit = AccountAuditEvent.objects.get(
        subject_user=user,
        event_type=AccountAuditEventType.MFA_ENABLED,
    )
    assert audit.actor_user == user
    assert audit.correlation_id is not None

    replacement = client.post(
        MFA_SETUP_URL,
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert replacement.status_code == 409
    assert replacement.data["code"] == "mfa_already_enabled"


def test_confirmed_mfa_requires_challenge_before_creating_session() -> None:
    user = active_user("challenge@example.com")
    enrollment_client = APIClient(enforce_csrf_checks=True)
    secret, _ = enable_mfa(enrollment_client, user)
    enrollment_client.post(
        LOGOUT_URL,
        HTTP_X_CSRFTOKEN=enrollment_client.cookies["csrftoken"].value,
    )
    UserSession.objects.all().delete()

    client = APIClient(enforce_csrf_checks=True)
    first_factor = login(client, user)

    assert first_factor.status_code == 202
    assert first_factor.data == {"status": "mfa_required"}
    assert client.get(ME_URL).status_code == 403
    assert not UserSession.objects.exists()
    assert LoginAttempt.objects.latest("created_at").outcome == LoginOutcome.MFA_REQUIRED

    second_factor = client.post(
        MFA_LOGIN_URL,
        {"code": current_totp_code(secret, at=timezone.now().timestamp() + 30)},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert second_factor.status_code == 200
    assert second_factor.data["email"] == user.email
    assert client.get(ME_URL).status_code == 200
    assert UserSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1


def test_totp_cannot_be_replayed() -> None:
    user = active_user("replay@example.com")
    enrollment_client = APIClient(enforce_csrf_checks=True)
    secret, _ = enable_mfa(enrollment_client, user)
    code = current_totp_code(secret, at=timezone.now().timestamp() + 30)

    first = APIClient(enforce_csrf_checks=True)
    assert login(first, user).status_code == 202
    assert (
        first.post(
            MFA_LOGIN_URL,
            {"code": code},
            format="json",
            HTTP_X_CSRFTOKEN=first.cookies["csrftoken"].value,
        ).status_code
        == 200
    )

    second = APIClient(enforce_csrf_checks=True)
    assert login(second, user).status_code == 202
    replay = second.post(
        MFA_LOGIN_URL,
        {"code": code},
        format="json",
        HTTP_X_CSRFTOKEN=second.cookies["csrftoken"].value,
    )

    assert replay.status_code == 400
    assert replay.data["code"] == "invalid_mfa_code"
    assert second.get(ME_URL).status_code == 403


def test_recovery_code_is_consumed_once() -> None:
    user = active_user("recovery@example.com")
    enrollment_client = APIClient(enforce_csrf_checks=True)
    _, recovery_codes = enable_mfa(enrollment_client, user)
    recovery_code = recovery_codes[0]

    first = APIClient(enforce_csrf_checks=True)
    assert login(first, user).status_code == 202
    recovered = first.post(
        MFA_LOGIN_URL,
        {"code": recovery_code.lower().replace("-", " ")},
        format="json",
        HTTP_X_CSRFTOKEN=first.cookies["csrftoken"].value,
    )
    assert recovered.status_code == 200
    assert MfaRecoveryCode.objects.get(code_hash__isnull=False, used_at__isnull=False)

    second = APIClient(enforce_csrf_checks=True)
    assert login(second, user).status_code == 202
    reused = second.post(
        MFA_LOGIN_URL,
        {"code": recovery_code},
        format="json",
        HTTP_X_CSRFTOKEN=second.cookies["csrftoken"].value,
    )

    assert reused.status_code == 400
    assert reused.data["code"] == "invalid_mfa_code"


def enroll_on_server(user: User) -> str:
    """The server administrator's two steps; hands back the secret."""
    started = StringIO()
    call_command("enroll_operator_mfa", user.email, stdout=started)
    secret = started.getvalue().split("sekret:")[1].split("\n")[0].replace(" ", "")
    confirmed = StringIO()
    code = current_totp_code(secret, at=timezone.now().timestamp() - 30)
    call_command("enroll_operator_mfa", user.email, confirm=code, stdout=confirmed)
    assert confirmed.getvalue().count("\n  ") == 8  # the recovery codes
    return secret


def test_an_operator_without_mfa_gets_it_on_the_server_not_with_the_password() -> None:
    """Platform settings 0c: before, the password alone opened a challenge in
    which anyone holding it set their own TOTP on a staff account."""
    user = active_user("operator@example.com", staff=True)
    client = APIClient(enforce_csrf_checks=True)

    first_factor = login(client, user)
    setup = client.post(MFA_SETUP_URL, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)

    assert first_factor.status_code == 403
    assert first_factor.data["code"] == "mfa_setup_required"
    assert LoginAttempt.objects.latest("created_at").outcome == LoginOutcome.MFA_SETUP_REQUIRED
    assert setup.status_code == 403
    assert client.get(ME_URL).status_code == 403
    assert not UserSession.objects.exists()
    assert not UserMfaMethod.objects.exists()

    secret = enroll_on_server(user)
    assert login(client, user).status_code == 202
    second_factor = client.post(
        MFA_LOGIN_URL,
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert second_factor.status_code == 200, second_factor.data
    assert UserSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1


def test_a_session_never_sets_an_operators_first_factor() -> None:
    """A member promoted mid-session still cannot bind an app to the staff
    account, nor replace the one the server administrator started."""
    user = active_user("promoted@example.com")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    User.objects.filter(pk=user.pk).update(is_staff=True)
    call_command("enroll_operator_mfa", user.email, stdout=StringIO())
    started = UserMfaMethod.objects.get(user=user).secret_ciphertext

    setup = client.post(MFA_SETUP_URL, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
    confirm = client.post(
        MFA_CONFIRM_URL,
        {"code": "123456"},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert setup.status_code == confirm.status_code == 403
    assert setup.data["code"] == confirm.data["code"] == "operator_mfa_by_command"
    method = UserMfaMethod.objects.get(user=user)
    assert (method.secret_ciphertext, method.confirmed_at) == (started, None)


def test_the_command_takes_only_operator_accounts() -> None:
    member = active_user("member@example.com")

    with pytest.raises(CommandError):
        call_command("enroll_operator_mfa", member.email, stdout=StringIO())
    with pytest.raises(CommandError):
        call_command("enroll_operator_mfa", "nobody@example.com", stdout=StringIO())
    assert not UserMfaMethod.objects.exists()


def test_wrong_codes_lock_the_account_wherever_they_are_given(caplog) -> None:
    """Per account, not per address (ADR-023): sign-in and step-up share one
    count, and while locked even the right code is refused."""
    user = active_user("locked@example.com")
    signed_in = APIClient(enforce_csrf_checks=True)
    secret, _ = enable_mfa(signed_in, user)
    challenged = APIClient(enforce_csrf_checks=True)
    assert login(challenged, user).status_code == 202

    def mfa_login(code: str):
        return challenged.post(
            MFA_LOGIN_URL,
            {"code": code},
            format="json",
            HTTP_X_CSRFTOKEN=challenged.cookies["csrftoken"].value,
        )

    def step_up(code: str):
        return signed_in.post(
            STEP_UP_URL,
            {"code": code},
            format="json",
            HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value,
        )

    assert [mfa_login("000000").status_code for _ in range(4)] == [400] * 4
    with caplog.at_level("WARNING", logger="saas_core.security"):
        locked = mfa_login("000000")
    assert locked.status_code == 429
    assert locked.data["code"] == "mfa_locked"
    assert "identity.mfa_locked" in [getattr(r, "security_event", None) for r in caplog.records]

    right = current_totp_code(secret, at=timezone.now().timestamp() + 30)
    assert mfa_login(right).data["code"] == "mfa_locked"
    # Locked by someone else's guesses: refused, but this session goes on —
    # the password alone must not be a way to sign the owner out.
    refused = step_up(right)
    assert (refused.status_code, refused.data["code"]) == (429, "mfa_locked")
    assert signed_in.get(ME_URL).status_code == 200

    cache.delete(f"identity.mfa.lock:{user.pk}")
    assert mfa_login(right).status_code == 200


def test_the_wrong_code_that_reaches_the_limit_on_a_step_up_ends_that_session() -> None:
    user = active_user("step-up-shared@example.com")
    signed_in = APIClient(enforce_csrf_checks=True)
    enable_mfa(signed_in, user)
    challenged = APIClient(enforce_csrf_checks=True)
    assert login(challenged, user).status_code == 202
    for _ in range(3):
        challenged.post(
            MFA_LOGIN_URL,
            {"code": "000000"},
            format="json",
            HTTP_X_CSRFTOKEN=challenged.cookies["csrftoken"].value,
        )

    answers = [
        signed_in.post(
            STEP_UP_URL,
            {"code": "000000"},
            format="json",
            HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value,
        )
        for _ in range(2)
    ]

    assert [answer.status_code for answer in answers] == [400, 403]
    assert answers[-1].data["code"] == "step_up_locked"
    assert signed_in.get(ME_URL).status_code == 403


def test_expired_or_missing_mfa_challenge_is_rejected() -> None:
    user = active_user("expired@example.com")
    enrollment_client = APIClient(enforce_csrf_checks=True)
    secret, _ = enable_mfa(enrollment_client, user)
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 202
    session = client.session
    session[MFA_CHALLENGE_EXPIRES_KEY] = int((timezone.now() - timedelta(seconds=1)).timestamp())
    session.save()

    expired = client.post(
        MFA_LOGIN_URL,
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    missing = APIClient(enforce_csrf_checks=True)
    missing_csrf = csrf_token(missing)
    missing_response = missing.post(
        MFA_LOGIN_URL,
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=missing_csrf,
    )

    assert expired.status_code == missing_response.status_code == 400
    assert expired.data["code"] == missing_response.data["code"] == "invalid_mfa_challenge"


def test_mfa_endpoints_require_csrf() -> None:
    user = active_user("csrf-mfa@example.com")
    enrollment_client = APIClient(enforce_csrf_checks=True)
    _, _ = enable_mfa(enrollment_client, user)
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 202

    response = client.post(MFA_LOGIN_URL, {"code": "123456"}, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert settings.MFA_CHALLENGE_TTL_SECONDS > 0
