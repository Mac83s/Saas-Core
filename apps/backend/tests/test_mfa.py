from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import (
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


def test_staff_bootstrap_only_creates_session_after_totp_confirmation() -> None:
    user = active_user("operator@example.com", staff=True)
    client = APIClient(enforce_csrf_checks=True)

    first_factor = login(client, user)

    assert first_factor.status_code == 403
    assert first_factor.data["code"] == "mfa_setup_required"
    assert client.get(ME_URL).status_code == 403
    assert not UserSession.objects.exists()
    setup = client.post(
        MFA_SETUP_URL,
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    confirmed = client.post(
        MFA_CONFIRM_URL,
        {"code": current_totp_code(setup.data["secret"])},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert setup.status_code == 200
    assert confirmed.status_code == 200
    assert client.get(ME_URL).status_code == 200
    assert UserSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1


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
        MFA_SETUP_URL,
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
