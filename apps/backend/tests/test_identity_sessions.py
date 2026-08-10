from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import LoginAttempt, User, UserSession, UserStatus
from saas_core.modules.core.identity.tokens import digest_identifier, digest_secret

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
SESSIONS_URL = "/api/v1/auth/sessions/"
PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def active_user(email: str = "active@example.com") -> User:
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def login(client: APIClient, email: str, *, user_agent: str = "Test Browser"):
    csrf = client.get(CSRF_URL).data["csrf_token"]
    return client.post(
        LOGIN_URL,
        {"email": email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_USER_AGENT=user_agent,
    )


def csrf_value(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def test_login_rotates_session_key_and_exposes_current_user() -> None:
    user = active_user()
    client = APIClient(enforce_csrf_checks=True)
    anonymous_session = client.session
    anonymous_session["before_login"] = True
    anonymous_session.save()
    old_key = anonymous_session.session_key

    response = login(client, user.email, user_agent="Firefox test")

    assert response.status_code == 200
    assert response.data["email"] == user.email
    new_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert new_key != old_key
    assert not Session.objects.filter(session_key=old_key).exists()
    tracking = UserSession.objects.get(user=user)
    assert tracking.session_key_hash == digest_secret(new_key)
    assert new_key not in tracking.session_key_hash
    assert tracking.device_label == "Firefox test"
    assert client.get(ME_URL).status_code == 200


def test_login_rejects_missing_csrf_and_uses_generic_invalid_credentials() -> None:
    pending = User.objects.create_user(email="pending@example.com", password=PASSWORD)
    csrf_client = APIClient(enforce_csrf_checks=True)

    missing_csrf = csrf_client.post(
        LOGIN_URL,
        {"email": pending.email, "password": PASSWORD},
        format="json",
    )
    csrf_client.get(CSRF_URL)
    pending_response = csrf_client.post(
        LOGIN_URL,
        {"email": pending.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(csrf_client),
    )
    missing_response = csrf_client.post(
        LOGIN_URL,
        {"email": "missing@example.com", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(csrf_client),
    )

    assert missing_csrf.status_code == 403
    assert pending_response.status_code == missing_response.status_code == 400
    assert pending_response.data["code"] == missing_response.data["code"]
    assert pending_response.data["detail"] == missing_response.data["detail"]
    assert not UserSession.objects.exists()


def test_login_attempt_contains_only_hashed_identifier_and_ip() -> None:
    user = active_user("attempt@example.com")
    client = APIClient(enforce_csrf_checks=True)

    response = login(client, user.email)

    assert response.status_code == 200
    attempt = LoginAttempt.objects.get()
    assert attempt.identifier_hash == digest_identifier(user.email)
    assert attempt.ip_hash == digest_secret("127.0.0.1")
    assert user.email not in attempt.identifier_hash
    assert "127.0.0.1" not in attempt.ip_hash


def test_user_can_list_and_revoke_another_device() -> None:
    user = active_user("devices@example.com")
    first = APIClient(enforce_csrf_checks=True)
    second = APIClient(enforce_csrf_checks=True)
    assert login(first, user.email, user_agent="Laptop").status_code == 200
    assert login(second, user.email, user_agent="Telefon").status_code == 200

    listed = first.get(SESSIONS_URL)
    phone = next(item for item in listed.data if item["device_label"] == "Telefon")
    revoked = first.delete(
        f"{SESSIONS_URL}{phone['id']}/",
        HTTP_X_CSRFTOKEN=csrf_value(first),
    )

    assert listed.status_code == 200
    assert len(listed.data) == 2
    assert sum(item["current"] for item in listed.data) == 1
    assert revoked.status_code == 204
    assert first.get(ME_URL).status_code == 200
    assert second.get(ME_URL).status_code == 403
    assert UserSession.objects.get(pk=phone["id"]).revoked_at is not None


def test_logout_revokes_current_session_and_removes_authentication() -> None:
    user = active_user("logout@example.com")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user.email).status_code == 200

    response = client.post(LOGOUT_URL, HTTP_X_CSRFTOKEN=csrf_value(client))

    assert response.status_code == 204
    assert UserSession.objects.get(user=user).revoked_at is not None
    assert client.get(ME_URL).status_code == 403


@pytest.mark.parametrize("expiry_kind", ["idle", "maximum"])
def test_expired_managed_session_is_rejected(expiry_kind: str) -> None:
    user = active_user(f"{expiry_kind}@example.com")
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user.email).status_code == 200
    tracking = UserSession.objects.get(user=user)
    if expiry_kind == "idle":
        tracking.last_seen_at = timezone.now() - timedelta(
            seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS + 1
        )
        tracking.save(update_fields=["last_seen_at"])
    else:
        tracking.expires_at = timezone.now() - timedelta(seconds=1)
        tracking.save(update_fields=["expires_at"])

    response = client.get(ME_URL)

    assert response.status_code == 403
    tracking.refresh_from_db()
    assert tracking.revoked_at is not None
