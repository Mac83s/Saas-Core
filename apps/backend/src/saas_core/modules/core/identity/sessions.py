from __future__ import annotations

import logging
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

from .middleware import MANAGED_SESSION_KEY
from .models import LoginAttempt, LoginOutcome, User, UserSession, UserStatus
from .tokens import digest_identifier, digest_secret

logger = logging.getLogger("saas_core.security")


class InvalidLogin(APIException):
    status_code = 400
    default_detail = "Nieprawidłowy e-mail lub hasło."
    default_code = "invalid_credentials"


class ManagedSessionNotFound(NotFound):
    default_detail = "Sesja nie istnieje."
    default_code = "session_not_found"


def login_user(*, request: HttpRequest, email: str, password: str) -> User:
    normalized_email = User.objects.normalize_email(email)
    user = User.objects.filter(email=normalized_email).first()
    valid_password = user.check_password(password) if user is not None else False
    if user is None:
        make_password(password)

    is_active = (
        user is not None
        and valid_password
        and user.status == UserStatus.ACTIVE
        and user.is_active
    )
    outcome = LoginOutcome.SUCCESS if is_active else LoginOutcome.INVALID
    if user is not None and valid_password and not is_active:
        outcome = LoginOutcome.INACTIVE
    LoginAttempt.objects.create(
        user=user,
        identifier_hash=digest_identifier(normalized_email),
        ip_hash=digest_secret(_client_ip(request)),
        outcome=outcome,
        correlation_id=getattr(request, "correlation_id", None),
    )

    if not is_active or user is None:
        logger.info(
            "identity_login_rejected",
            extra={"security_event": "identity.login_rejected"},
        )
        raise InvalidLogin

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
    return user


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
