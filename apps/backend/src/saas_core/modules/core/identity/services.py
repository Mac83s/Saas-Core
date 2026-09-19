from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.observability import correlation_id

from .models import AccountAuditEvent, AccountAuditEventType, EmailVerification, User, UserStatus
from .tokens import digest_identifier, digest_secret, issue_bound_token

logger = logging.getLogger("saas_core.security")
GENERIC_VERIFICATION_MESSAGE = (
    "Jeżeli konto może zostać utworzone lub wymaga weryfikacji, wysłaliśmy instrukcję."
)


class InvalidVerificationToken(APIException):
    status_code = 400
    default_detail = "Token weryfikacyjny jest nieprawidłowy albo wygasł."
    default_code = "invalid_verification_token"


@transaction.atomic
def update_profile(
    *, user: User, changes: dict[str, str], correlation_id: uuid.UUID | None = None
) -> User:
    """The person's own name; audited like the other account changes."""
    cleaned = {field: value.strip() for field, value in changes.items()}
    changed = [field for field, value in cleaned.items() if getattr(user, field) != value]
    if changed:
        for field in changed:
            setattr(user, field, cleaned[field])
        user.save(update_fields=[*changed, "updated_at"])
        AccountAuditEvent.objects.create(
            event_type=AccountAuditEventType.PROFILE_UPDATED,
            subject_user=user,
            actor_user=user,
            correlation_id=correlation_id,
        )
    return user


def register_user(*, email: str, password: str, locale: str) -> None:
    normalized_email = User.objects.normalize_email(email)
    created = False
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=normalized_email,
                password=password,
                locale=locale,
            )
            created = True
    except (IntegrityError, ValidationError):
        existing_user = User.objects.filter(email=normalized_email).first()
        if existing_user is None:
            raise
        user = existing_user

    if not created:
        # Equalize the expensive part of the path without modifying an existing account.
        make_password(password)

    if user.status == UserStatus.PENDING:
        schedule_email_verification(user=user)
    logger.info(
        "identity_registration_requested",
        extra={"security_event": "identity.registration_requested"},
    )


def request_email_verification(*, email: str) -> None:
    normalized_email = User.objects.normalize_email(email)
    user = User.objects.filter(email=normalized_email, status=UserStatus.PENDING).first()
    if user is not None:
        schedule_email_verification(user=user)
    else:
        digest_identifier(normalized_email)
    logger.info(
        "identity_verification_requested",
        extra={"security_event": "identity.verification_requested"},
    )


def schedule_email_verification(*, user: User) -> EmailVerification | None:
    cache_key = f"identity:verification-cooldown:{digest_identifier(user.email)}"
    try:
        acquired = cache.add(
            cache_key,
            "1",
            timeout=settings.EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS,
        )
    except Exception:
        logger.warning(
            "identity_verification_cooldown_unavailable",
            extra={"security_event": "identity.verification_cooldown_unavailable"},
        )
        acquired = True
    if not acquired:
        return None

    try:
        with transaction.atomic():
            locked_user = User.objects.select_for_update().get(pk=user.pk)
            if locked_user.status != UserStatus.PENDING:
                return None
            now = timezone.now()
            EmailVerification.objects.filter(user=locked_user, used_at__isnull=True).update(
                used_at=now
            )
            verification_id = uuid.uuid7()
            issued = issue_bound_token(
                purpose="email-verification",
                identifier=str(verification_id),
            )
            verification = EmailVerification.objects.create(
                id=verification_id,
                user=locked_user,
                email=locked_user.email,
                token_hash=issued.digest,
                expires_at=now + timedelta(seconds=settings.EMAIL_VERIFICATION_TTL_SECONDS),
            )
            from .tasks import send_email_verification

            task_verification_id = str(verification.id)
            request_correlation_id = correlation_id.get()

            def enqueue_verification_email() -> None:
                send_email_verification.delay(
                    task_verification_id,
                    request_correlation_id,
                )

            transaction.on_commit(enqueue_verification_email, robust=True)
            return verification
    except Exception:
        try:
            cache.delete(cache_key)
        except Exception:
            logger.warning(
                "identity_verification_cooldown_release_failed",
                extra={"security_event": "identity.verification_cooldown_release_failed"},
            )
        raise


def confirm_email_verification(*, token: str, correlation_id: uuid.UUID | None = None) -> User:
    now = timezone.now()
    with transaction.atomic():
        try:
            verification = (
                EmailVerification.objects.select_for_update()
                .select_related("user")
                .get(token_hash=digest_secret(token))
            )
        except EmailVerification.DoesNotExist as error:
            raise InvalidVerificationToken from error

        user = verification.user
        if not verification.is_usable(at=now) or verification.email != user.email:
            raise InvalidVerificationToken

        verification.used_at = now
        verification.save(update_fields=["used_at"])
        EmailVerification.objects.filter(user=user, used_at__isnull=True).exclude(
            pk=verification.pk
        ).update(used_at=now)
        user.status = UserStatus.ACTIVE
        user.save(update_fields=["status", "is_active", "updated_at"])
        AccountAuditEvent.objects.create(
            event_type=AccountAuditEventType.EMAIL_VERIFIED,
            subject_user=user,
            correlation_id=correlation_id,
        )

    logger.info(
        "identity_email_verified",
        extra={
            "security_event": "identity.email_verified",
            "user_id": str(user.id),
        },
    )
    return user
