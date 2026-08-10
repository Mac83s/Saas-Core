from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import PasswordReset, User, UserSession, UserStatus
from saas_core.modules.core.identity.password_reset import (
    GENERIC_PASSWORD_RESET_MESSAGE,
    schedule_password_reset,
)
from saas_core.modules.core.identity.tasks import send_password_reset
from saas_core.modules.core.identity.tokens import issue_bound_token

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
ME_URL = "/api/v1/auth/me/"
RESET_URL = "/api/v1/auth/password-resets/"
CONFIRM_URL = "/api/v1/auth/password-resets/confirm/"
OLD_PASSWORD = "Stare-Bezpieczne-Haslo-2026!"
NEW_PASSWORD = "Nowe-Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_reset_cache() -> None:
    cache.clear()


def active_user(email: str = "reset@example.com") -> User:
    user = User.objects.create_user(email=email, password=OLD_PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def reset_token(reset: PasswordReset) -> str:
    return issue_bound_token(
        purpose="password-reset",
        identifier=str(reset.id),
    ).value


def test_reset_request_is_generic_and_enqueues_only_record_id(
    django_capture_on_commit_callbacks,
) -> None:
    user = active_user()
    client = APIClient()

    with (
        patch("saas_core.modules.core.identity.tasks.send_password_reset.delay") as enqueue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        present = client.post(RESET_URL, {"email": user.email}, format="json")
    missing = client.post(RESET_URL, {"email": "missing@example.com"}, format="json")

    assert present.status_code == missing.status_code == 202
    assert present.data == missing.data == {"detail": GENERIC_PASSWORD_RESET_MESSAGE}
    reset = PasswordReset.objects.get(user=user)
    assert enqueue.call_args.args[0] == str(reset.id)
    assert user.email not in enqueue.call_args.args
    assert reset.token_hash not in enqueue.call_args.args


def test_reset_email_task_reconstructs_token_without_logging_it(caplog) -> None:
    user = active_user("reset-mail@example.com")
    reset = schedule_password_reset(user=user)
    assert reset is not None
    token = reset_token(reset)

    with caplog.at_level("INFO", logger="saas_core.security"):
        send_password_reset(str(reset.id), "reset-correlation")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert token in mail.outbox[0].body
    assert token not in caplog.text
    assert reset.token_hash not in caplog.text


def test_confirm_reset_changes_password_and_revokes_existing_sessions() -> None:
    user = active_user("reset-session@example.com")
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get(CSRF_URL).data["csrf_token"]
    logged_in = client.post(
        LOGIN_URL,
        {"email": user.email, "password": OLD_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert logged_in.status_code == 200
    reset = schedule_password_reset(user=user)
    assert reset is not None

    response = client.post(
        CONFIRM_URL,
        {"token": reset_token(reset), "password": NEW_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert response.status_code == 200
    assert response.data == {"status": "password_updated"}
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert not user.check_password(OLD_PASSWORD)
    assert UserSession.objects.get(user=user).revoked_at is not None
    assert client.get(ME_URL).status_code == 403


def test_reset_token_is_expiring_and_single_use() -> None:
    user = active_user("single-reset@example.com")
    reset = schedule_password_reset(user=user)
    assert reset is not None
    token = reset_token(reset)
    client = APIClient()

    accepted = client.post(
        CONFIRM_URL,
        {"token": token, "password": NEW_PASSWORD},
        format="json",
    )
    reused = client.post(
        CONFIRM_URL,
        {"token": token, "password": OLD_PASSWORD},
        format="json",
    )

    assert accepted.status_code == 200
    assert reused.status_code == 400
    assert reused.data["code"] == "invalid_password_reset_token"


def test_expired_or_modified_reset_token_is_rejected() -> None:
    user = active_user("expired-reset@example.com")
    reset = schedule_password_reset(user=user)
    assert reset is not None
    token = reset_token(reset)
    reset.expires_at = timezone.now() - timedelta(seconds=1)
    reset.save(update_fields=["expires_at"])

    expired = APIClient().post(
        CONFIRM_URL,
        {"token": token, "password": NEW_PASSWORD},
        format="json",
    )
    modified = APIClient().post(
        CONFIRM_URL,
        {"token": f"{token}x", "password": NEW_PASSWORD},
        format="json",
    )

    assert expired.status_code == modified.status_code == 400
    assert expired.data["code"] == modified.data["code"] == "invalid_password_reset_token"


def test_reset_request_requires_csrf_and_is_rate_limited() -> None:
    client = APIClient(enforce_csrf_checks=True)
    rejected = client.post(RESET_URL, {"email": "csrf-reset@example.com"}, format="json")
    csrf = client.get(CSRF_URL).data["csrf_token"]
    accepted = [
        client.post(
            RESET_URL,
            {"email": f"rate-reset-{index}@example.com"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        for index in range(5)
    ]
    limited = client.post(
        RESET_URL,
        {"email": "rate-reset-limited@example.com"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert rejected.status_code == 403
    assert all(response.status_code == 202 for response in accepted)
    assert limited.status_code == 429
