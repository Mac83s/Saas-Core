from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import make_password
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from .mfa import has_confirmed_mfa, verify_mfa_code
from .middleware import MANAGED_SESSION_KEY
from .models import (
    AccountAuditEvent,
    AccountAuditEventType,
    LoginAttempt,
    LoginOutcome,
    User,
    UserSession,
    UserStatus,
)
from .tokens import digest_identifier, digest_secret

logger = logging.getLogger("saas_core.security")

MFA_CHALLENGE_USER_KEY = "identity_mfa_user_id"
MFA_CHALLENGE_PURPOSE_KEY = "identity_mfa_purpose"
MFA_CHALLENGE_EXPIRES_KEY = "identity_mfa_expires_at"
MFA_CHALLENGE_VERIFY = "verify"
MFA_CHALLENGE_ENROLL = "enroll"


class InvalidLogin(APIException):
    status_code = 400
    default_detail = "Nieprawidłowy e-mail lub hasło."
    default_code = "invalid_credentials"


class ManagedSessionNotFound(NotFound):
    default_detail = "Sesja nie istnieje."
    default_code = "session_not_found"


class InvalidMfaChallenge(APIException):
    status_code = 400
    default_detail = "Wyzwanie MFA wygasło albo jest nieprawidłowe."
    default_code = "invalid_mfa_challenge"


class MfaSetupRequired(APIException):
    status_code = 403
    default_detail = "Operator musi skonfigurować MFA przed zalogowaniem."
    default_code = "mfa_setup_required"


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User | None
    mfa_required: bool = False


def login_user(*, request: HttpRequest, email: str, password: str) -> LoginResult:
    normalized_email = User.objects.normalize_email(email)
    user = User.objects.filter(email=normalized_email).first()
    valid_password = user.check_password(password) if user is not None else False
    if user is None:
        make_password(password)

    is_active = (
        user is not None and valid_password and user.status == UserStatus.ACTIVE and user.is_active
    )
    if not is_active or user is None:
        outcome = (
            LoginOutcome.INACTIVE if user is not None and valid_password else LoginOutcome.INVALID
        )
        _record_login_attempt(request=request, user=user, email=normalized_email, outcome=outcome)
        logger.info(
            "identity_login_rejected",
            extra={"security_event": "identity.login_rejected"},
        )
        raise InvalidLogin

    if has_confirmed_mfa(user):
        _record_login_attempt(
            request=request,
            user=user,
            email=normalized_email,
            outcome=LoginOutcome.MFA_REQUIRED,
        )
        _start_mfa_challenge(request=request, user=user, purpose=MFA_CHALLENGE_VERIFY)
        logger.info(
            "identity_mfa_challenge_started",
            extra={"security_event": "identity.mfa_challenge_started", "user_id": str(user.id)},
        )
        return LoginResult(user=None, mfa_required=True)

    if user.is_staff:
        _record_login_attempt(
            request=request,
            user=user,
            email=normalized_email,
            outcome=LoginOutcome.MFA_SETUP_REQUIRED,
        )
        _start_mfa_challenge(request=request, user=user, purpose=MFA_CHALLENGE_ENROLL)
        logger.info(
            "identity_mfa_setup_required",
            extra={"security_event": "identity.mfa_setup_required", "user_id": str(user.id)},
        )
        raise MfaSetupRequired

    _record_login_attempt(
        request=request,
        user=user,
        email=normalized_email,
        outcome=LoginOutcome.SUCCESS,
    )
    _establish_user_session(request=request, user=user)
    return LoginResult(user=user)


def complete_mfa_login(*, request: HttpRequest, code: str) -> User:
    user = _challenge_user(request=request, purpose=MFA_CHALLENGE_VERIFY)
    verify_mfa_code(user=user, code=code)
    _clear_mfa_challenge(request)
    _establish_user_session(request=request, user=user)
    logger.info(
        "identity_mfa_login_succeeded",
        extra={"security_event": "identity.mfa_login_succeeded", "user_id": str(user.id)},
    )
    return user


def mfa_enrollment_user(*, request: HttpRequest) -> tuple[User, bool]:
    if request.user.is_authenticated:
        return request.user, False
    return _challenge_user(request=request, purpose=MFA_CHALLENGE_ENROLL), True


def complete_mfa_enrollment_login(*, request: HttpRequest, user: User) -> None:
    challenge_user = _challenge_user(request=request, purpose=MFA_CHALLENGE_ENROLL)
    if challenge_user.pk != user.pk:
        raise InvalidMfaChallenge
    _clear_mfa_challenge(request)
    _establish_user_session(request=request, user=user)


def _establish_user_session(*, request: HttpRequest, user: User) -> None:
    previous_tracking_id = request.session.get(MANAGED_SESSION_KEY)
    if previous_tracking_id:
        UserSession.objects.filter(pk=previous_tracking_id).update(revoked_at=timezone.now())

    django_login(request, user)
    request.session.cycle_key()
    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key
    if session_key is None:
        raise RuntimeError("Django nie utworzyło klucza sesji")

    now = timezone.now()
    tracking = UserSession.objects.create(
        user=user,
        session_key_hash=digest_secret(session_key),
        device_label=_device_label(request),
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.SESSION_MAX_LIFETIME_SECONDS),
    )
    request.session[MANAGED_SESSION_KEY] = str(tracking.id)
    request.session.set_expiry(
        min(settings.SESSION_IDLE_TIMEOUT_SECONDS, settings.SESSION_MAX_LIFETIME_SECONDS)
    )
    logger.info(
        "identity_login_succeeded",
        extra={
            "security_event": "identity.login_succeeded",
            "user_id": str(user.id),
        },
    )


def _start_mfa_challenge(*, request: HttpRequest, user: User, purpose: str) -> None:
    previous_tracking_id = request.session.get(MANAGED_SESSION_KEY)
    if previous_tracking_id:
        UserSession.objects.filter(pk=previous_tracking_id).update(revoked_at=timezone.now())
    request.session.flush()
    request.session[MFA_CHALLENGE_USER_KEY] = str(user.pk)
    request.session[MFA_CHALLENGE_PURPOSE_KEY] = purpose
    request.session[MFA_CHALLENGE_EXPIRES_KEY] = int(
        timezone.now().timestamp() + settings.MFA_CHALLENGE_TTL_SECONDS
    )
    request.session.set_expiry(settings.MFA_CHALLENGE_TTL_SECONDS)


def _challenge_user(*, request: HttpRequest, purpose: str) -> User:
    user_id = request.session.get(MFA_CHALLENGE_USER_KEY)
    challenge_purpose = request.session.get(MFA_CHALLENGE_PURPOSE_KEY)
    expires_at = request.session.get(MFA_CHALLENGE_EXPIRES_KEY, 0)
    if (
        not isinstance(user_id, str)
        or challenge_purpose != purpose
        or not isinstance(expires_at, int | float)
        or expires_at <= timezone.now().timestamp()
    ):
        _clear_mfa_challenge(request)
        raise InvalidMfaChallenge
    user = User.objects.filter(pk=user_id, status=UserStatus.ACTIVE, is_active=True).first()
    if user is None:
        _clear_mfa_challenge(request)
        raise InvalidMfaChallenge
    return user


def _clear_mfa_challenge(request: HttpRequest) -> None:
    for key in (
        MFA_CHALLENGE_USER_KEY,
        MFA_CHALLENGE_PURPOSE_KEY,
        MFA_CHALLENGE_EXPIRES_KEY,
    ):
        request.session.pop(key, None)


def _record_login_attempt(
    *,
    request: HttpRequest,
    user: User | None,
    email: str,
    outcome: str,
) -> None:
    LoginAttempt.objects.create(
        user=user,
        identifier_hash=digest_identifier(email),
        ip_hash=digest_secret(_client_ip(request)),
        outcome=outcome,
        correlation_id=getattr(request, "correlation_id", None),
    )


def logout_user(*, request: HttpRequest) -> None:
    tracking_id = request.session.get(MANAGED_SESSION_KEY)
    user = cast(User, request.user)
    assert user.pk is not None
    if tracking_id:
        UserSession.objects.filter(pk=tracking_id, user_id=user.pk).update(
            revoked_at=timezone.now()
        )
    user_id = str(user.pk)
    django_logout(request)
    logger.info(
        "identity_logout",
        extra={"security_event": "identity.logout", "user_id": user_id},
    )


def revoke_user_session(
    *,
    request: HttpRequest,
    session_id: UUID,
) -> bool:
    user = cast(User, request.user)
    assert user.pk is not None
    tracking = UserSession.objects.filter(pk=session_id, user_id=user.pk).first()
    if tracking is None:
        raise ManagedSessionNotFound
    tracking.revoke()
    is_current = str(session_id) == request.session.get(MANAGED_SESSION_KEY)
    if is_current:
        django_logout(request)
    AccountAuditEvent.objects.create(
        event_type=AccountAuditEventType.SESSION_REVOKED,
        subject_user=tracking.user,
        actor_user=user,
        correlation_id=getattr(request, "correlation_id", None),
    )
    logger.info(
        "identity_session_revoked",
        extra={
            "security_event": "identity.session_revoked",
            "user_id": str(tracking.user_id),
        },
    )
    return is_current


def _client_ip(request: HttpRequest) -> str:
    remote_address = cast(str, request.META.get("REMOTE_ADDR", ""))
    proxy_count = cast(int, settings.REST_FRAMEWORK.get("NUM_PROXIES", 0))
    forwarded = [
        item.strip()
        for item in cast(str, request.META.get("HTTP_X_FORWARDED_FOR", "")).split(",")
        if item.strip()
    ]
    if proxy_count and len(forwarded) >= proxy_count:
        return forwarded[-proxy_count]
    return remote_address


def _device_label(request: HttpRequest) -> str:
    user_agent = cast(str, request.META.get("HTTP_USER_AGENT", "Nieznane urządzenie"))
    cleaned = "".join(character if character.isprintable() else " " for character in user_agent)
    return cleaned[:160] or "Nieznane urządzenie"
