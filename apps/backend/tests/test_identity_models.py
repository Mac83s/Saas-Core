from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import (
    EmailVerification,
    LoginAttempt,
    LoginOutcome,
    User,
    UserSession,
    UserStatus,
)
from saas_core.modules.core.identity.tokens import (
    digest_identifier,
    digest_secret,
    issue_token,
)

pytestmark = pytest.mark.django_db


def test_user_email_is_normalized_and_uuid_is_version_seven() -> None:
    user = User.objects.create_user(email="  Jan.Kowalski@Example.COM ", password="secret")

    assert user.email == "jan.kowalski@example.com"
    assert user.id.version == 7
    assert user.status == UserStatus.PENDING
    assert not user.is_active
    assert user.check_password("secret")


def test_database_rejects_case_insensitive_duplicate_email() -> None:
    User.objects.create_user(email="owner@example.com")
    other = User.objects.create_user(email="other@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=other.pk).update(email="OWNER@EXAMPLE.COM")


def test_user_status_and_django_active_flag_cannot_drift() -> None:
    user = User.objects.create_user(email="status@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status=UserStatus.ACTIVE)

    user.status = UserStatus.ACTIVE
    user.save()
    user.refresh_from_db()
    assert user.is_active


def test_one_time_token_stores_only_keyed_digest() -> None:
    user = User.objects.create_user(email="verify@example.com")
    issued = issue_token()
    verification = EmailVerification.objects.create(
        user=user,
        email="VERIFY@EXAMPLE.COM",
        token_hash=issued.digest,
        expires_at=timezone.now() + timedelta(hours=1),
    )

    verification.refresh_from_db()
    assert verification.email == "verify@example.com"
    assert verification.token_hash == digest_secret(issued.value)
    assert issued.value not in repr(issued)
    assert issued.value not in verification.token_hash
    assert verification.is_usable()


def test_expired_or_used_token_is_not_usable() -> None:
    user = User.objects.create_user(email="expired@example.com")
    now = timezone.now()
    verification = EmailVerification.objects.create(
        user=user,
        email=user.email,
        token_hash=issue_token().digest,
        expires_at=now - timedelta(seconds=1),
    )
    assert not verification.is_usable(at=now)

    verification.expires_at = now + timedelta(hours=1)
    verification.used_at = now
    assert not verification.is_usable(at=now)


def test_revoked_session_is_invalid_without_storing_raw_key() -> None:
    user = User.objects.create_user(email="session@example.com")
    raw_session_key = "browser-session-key"
    session = UserSession.objects.create(
        user=user,
        session_key_hash=digest_secret(raw_session_key),
        expires_at=timezone.now() + timedelta(hours=1),
    )

    assert session.is_valid()
    assert raw_session_key not in session.session_key_hash
    session.revoke()
    assert not session.is_valid()


def test_login_attempt_hashes_identifier_and_ip() -> None:
    identifier = "Person@Example.com"
    ip_address = "192.0.2.15"
    attempt = LoginAttempt.objects.create(
        identifier_hash=digest_identifier(identifier),
        ip_hash=digest_secret(ip_address),
        outcome=LoginOutcome.INVALID,
    )

    assert identifier.casefold() not in attempt.identifier_hash
    assert ip_address not in attempt.ip_hash
    assert attempt.identifier_hash == digest_identifier(" person@example.COM ")
