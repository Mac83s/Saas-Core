from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import EmailVerification, User, UserStatus
from saas_core.modules.core.identity.services import (
    GENERIC_VERIFICATION_MESSAGE,
    schedule_email_verification,
)
from saas_core.modules.core.identity.tasks import send_email_verification
from saas_core.modules.core.identity.tokens import issue_bound_token

pytestmark = pytest.mark.django_db

REGISTER_URL = "/api/v1/auth/register/"
RESEND_URL = "/api/v1/auth/email-verifications/resend/"
CONFIRM_URL = "/api/v1/auth/email-verifications/confirm/"
CSRF_URL = "/api/v1/auth/csrf/"
VALID_PASSWORD = "Unikalne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_identity_cache() -> None:
    cache.clear()


def registration_payload(email: str) -> dict[str, str]:
    return {"email": email, "password": VALID_PASSWORD, "locale": "pl"}


def create_verification(email: str = "verify@example.com") -> tuple[User, EmailVerification, str]:
    user = User.objects.create_user(email=email, password=VALID_PASSWORD)
    verification = schedule_email_verification(user=user)
    assert verification is not None
    token = issue_bound_token(
        purpose="email-verification",
        identifier=str(verification.id),
    ).value
    return user, verification, token


def test_registration_creates_pending_user_and_enqueues_only_record_id(
    django_capture_on_commit_callbacks,
) -> None:
    client = APIClient()

    with (
        patch(
            "saas_core.modules.core.identity.tasks.send_email_verification.delay"
        ) as enqueue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post(
            REGISTER_URL,
            registration_payload("New.User@Example.com"),
            format="json",
        )

    assert response.status_code == 202
    assert response.data == {"detail": GENERIC_VERIFICATION_MESSAGE}
    user = User.objects.get(email="new.user@example.com")
    assert user.status == UserStatus.PENDING
    verification = EmailVerification.objects.get(user=user)
    assert verification.token_hash
    assert verification.email not in enqueue.call_args.args
    assert verification.token_hash not in enqueue.call_args.args
    assert enqueue.call_args.args[0] == str(verification.id)


def test_broker_failure_does_not_change_generic_registration_response(
    django_capture_on_commit_callbacks,
) -> None:
    client = APIClient()

    with (
        patch(
            "saas_core.modules.core.identity.tasks.send_email_verification.delay",
            side_effect=RuntimeError("broker unavailable"),
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = client.post(
            REGISTER_URL,
            registration_payload("broker-failure@example.com"),
            format="json",
        )

    assert response.status_code == 202
    assert response.data == {"detail": GENERIC_VERIFICATION_MESSAGE}
    assert EmailVerification.objects.filter(user__email="broker-failure@example.com").exists()


def test_registration_does_not_disclose_an_existing_account() -> None:
    client = APIClient()
    user = User.objects.create_user(email="existing@example.com", password=VALID_PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()

    response = client.post(
        REGISTER_URL,
        registration_payload("EXISTING@example.com"),
        format="json",
    )

    assert response.status_code == 202
    assert response.data == {"detail": GENERIC_VERIFICATION_MESSAGE}
    assert User.objects.filter(email="existing@example.com").count() == 1
    assert not EmailVerification.objects.filter(user=user).exists()


def test_registration_validation_uses_problem_details_without_losing_field_errors() -> None:
    response = APIClient().post(
        REGISTER_URL,
        {"email": "invalid@example.com", "password": "short", "locale": "pl"},
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/problem+json"
    assert response.data["code"] == "invalid"
    assert "password" in response.data["detail"]


def test_resend_has_the_same_response_for_present_and_missing_accounts() -> None:
    client = APIClient()
    User.objects.create_user(email="pending@example.com", password=VALID_PASSWORD)

    present = client.post(RESEND_URL, {"email": "pending@example.com"}, format="json")
    missing = client.post(RESEND_URL, {"email": "missing@example.com"}, format="json")

    assert present.status_code == missing.status_code == 202
    assert present.data == missing.data == {"detail": GENERIC_VERIFICATION_MESSAGE}


def test_verification_activates_account_exactly_once() -> None:
    client = APIClient()
    user, verification, token = create_verification()

    response = client.post(CONFIRM_URL, {"token": token}, format="json")

    assert response.status_code == 200
    assert response.data == {"status": "verified"}
    user.refresh_from_db()
    verification.refresh_from_db()
    assert user.status == UserStatus.ACTIVE
    assert user.is_active
    assert verification.used_at is not None

    reused = client.post(CONFIRM_URL, {"token": token}, format="json")
    assert reused.status_code == 400
    assert reused.data["code"] == "invalid_verification_token"


def test_expired_or_modified_verification_token_is_rejected() -> None:
    client = APIClient()
    _, verification, token = create_verification("expired@example.com")
    verification.expires_at = timezone.now() - timedelta(seconds=1)
    verification.save(update_fields=["expires_at"])

    expired = client.post(CONFIRM_URL, {"token": token}, format="json")
    modified = client.post(CONFIRM_URL, {"token": f"{token}x"}, format="json")

    assert expired.status_code == modified.status_code == 400
    assert expired.data["code"] == modified.data["code"] == "invalid_verification_token"


def test_identity_writes_require_csrf_when_checks_are_enforced() -> None:
    client = APIClient(enforce_csrf_checks=True)
    payload = registration_payload("csrf@example.com")

    rejected = client.post(REGISTER_URL, payload, format="json")
    csrf_response = client.get(CSRF_URL)
    accepted = client.post(
        REGISTER_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_response.data["csrf_token"],
    )

    assert rejected.status_code == 403
    assert rejected["Content-Type"] == "application/problem+json"
    assert rejected.json()["code"] == "csrf_failed"
    assert csrf_response.status_code == 200
    assert "csrftoken" in csrf_response.cookies
    assert accepted.status_code == 202


def test_registration_is_rate_limited() -> None:
    client = APIClient()

    accepted = [
        client.post(
            REGISTER_URL,
            registration_payload(f"rate-{index}@example.com"),
            format="json",
        )
        for index in range(5)
    ]
    limited = client.post(
        REGISTER_URL,
        registration_payload("rate-limited@example.com"),
        format="json",
    )

    assert all(response.status_code == 202 for response in accepted)
    assert limited.status_code == 429


def test_resend_cooldown_keeps_one_current_verification() -> None:
    user = User.objects.create_user(email="cooldown@example.com", password=VALID_PASSWORD)

    first = schedule_email_verification(user=user)
    second = schedule_email_verification(user=user)

    assert first is not None
    assert second is None
    assert EmailVerification.objects.filter(user=user, used_at__isnull=True).count() == 1


def test_resend_replaces_the_prior_token_after_cooldown() -> None:
    user = User.objects.create_user(email="replacement@example.com", password=VALID_PASSWORD)
    first = schedule_email_verification(user=user)
    assert first is not None
    cache.clear()

    replacement = schedule_email_verification(user=user)

    assert replacement is not None
    first.refresh_from_db()
    assert first.used_at is not None
    assert replacement.token_hash != first.token_hash
    assert EmailVerification.objects.filter(user=user, used_at__isnull=True).count() == 1


def test_email_task_reconstructs_token_without_logging_it(caplog) -> None:
    _, verification, token = create_verification("delivery@example.com")

    with caplog.at_level("INFO", logger="saas_core.security"):
        send_email_verification(str(verification.id), "test-correlation-id")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["delivery@example.com"]
    assert token in mail.outbox[0].body
    assert token not in caplog.text
    assert verification.token_hash not in caplog.text
