from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.observability import correlation_id

from .models import PasswordReset, User, UserSession, UserStatus
from .tokens import digest_identifier, digest_secret, issue_bound_token

logger = logging.getLogger("saas_core.security")
GENERIC_PASSWORD_RESET_MESSAGE = (
    "Jeżeli konto może zresetować hasło, wysłaliśmy dalsze instrukcje."
)


class InvalidPasswordResetToken(APIException):
    status_code = 400
    default_detail = "Token resetu hasła jest nieprawidłowy albo wygasł."
    default_code = "invalid_password_reset_token"


def request_password_reset(*, email: str) -> None:
    normalized_email = User.objects.normalize_email(email)
    user = User.objects.filter(email=normalized_email, status=UserStatus.ACTIVE).first()
    if user is not None:
        schedule_password_reset(user=user)
    else:
        digest_identifier(normalized_email)
    logger.info(
        "identity_password_reset_requested",
        extra={"security_event": "identity.password_reset_requested"},
    )


def schedule_password_reset(*, user: User) -> PasswordReset | None:
    cache_key = f"identity:password-reset-cooldown:{digest_identifier(user.email)}"
    try:
        acquired = cache.add(
            cache_key,
            "1",
            timeout=settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS,
        )
    except Exception:
        logger.warning(
            "identity_password_reset_cooldown_unavailable",
            extra={"security_event": "identity.password_reset_cooldown_unavailable"},
        )
        acquired = True
    if not acquired:
        return None

    try:
        with transaction.atomic():
            locked_user = User.objects.select_for_update().get(pk=user.pk)
            if locked_user.status != UserStatus.ACTIVE:
                return None
            now = timezone.now()
            PasswordReset.objects.filter(user=locked_user, used_at__isnull=True).update(
                used_at=now
            )
            reset_id = uuid.uuid7()
            issued = issue_bound_token(
                purpose="password-reset",
                identifier=str(reset_id),
            )
            reset = PasswordReset.objects.create(
                id=reset_id,
                user=locked_user,
                token_hash=issued.digest,
                expires_at=now + timedelta(seconds=settings.PASSWORD_RESET_TTL_SECONDS),
            )
            from .tasks import send_password_reset

            task_reset_id = str(reset.id)
            request_correlation_id = correlation_id.get()

            def enqueue_password_reset_email() -> None:
                send_password_reset.delay(task_reset_id, request_correlation_id)

            transaction.on_commit(enqueue_password_reset_email, robust=True)
            return reset
    except Exception:
        try:
            cache.delete(cache_key)
        except Exception:
            logger.warning(
                "identity_password_reset_cooldown_release_failed",
                extra={
                    "security_event": "identity.password_reset_cooldown_release_failed"
                },
            )
        raise


def confirm_password_reset(*, token: str, password: str) -> User:
    now = timezone.now()
    with transaction.atomic():
        try:
            reset = (
                PasswordReset.objects.select_for_update()
                .select_related("user")
                .get(token_hash=digest_secret(token))
            )
        except PasswordReset.DoesNotExist as error:
            raise InvalidPasswordResetToken from error
        if not reset.is_usable(at=now):
            raise InvalidPasswordResetToken

        user = reset.user
        user.set_password(password)
        user.updated_at = now
        user.save(update_fields=["password", "updated_at"])
        PasswordReset.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)

    logger.info(
        "identity_password_reset_completed",
        extra={
            "security_event": "identity.password_reset_completed",
            "user_id": str(user.id),
        },
    )
    return user
