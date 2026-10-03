from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.observability import correlation_id

from .models import (
    AccountAuditEvent,
    AccountAuditEventType,
    MfaRecoveryCode,
    User,
    UserMfaMethod,
    UserSession,
)
from .tokens import digest_secret

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
logger = logging.getLogger("saas_core.security")


class InvalidMfaCode(APIException):
    status_code = 400
    default_detail = "Kod uwierzytelniający jest nieprawidłowy."
    default_code = "invalid_mfa_code"


class MfaEnrollmentMissing(APIException):
    status_code = 400
    default_detail = "Najpierw rozpocznij konfigurację MFA."
    default_code = "mfa_enrollment_missing"


class MfaAlreadyEnabled(APIException):
    status_code = 409
    default_detail = "MFA jest już włączone."
    default_code = "mfa_already_enabled"


class MfaLocked(APIException):
    status_code = 429
    default_detail = "Zbyt wiele błędnych kodów. Spróbuj ponownie za kwadrans."
    default_code = "mfa_locked"


class OperatorMfaByCommand(APIException):
    status_code = 403
    default_detail = "Pierwsze MFA konta operatora ustawia administrator serwera."
    default_code = "operator_mfa_by_command"


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    secret: str
    provisioning_uri: str


def begin_totp_enrollment(*, user: User, on_server: bool = False) -> TotpEnrollment:
    """Starts (or restarts) the person's own TOTP setup.

    An operator's first factor is set only on the server, by
    `enroll_operator_mfa` (`on_server`): set from a session, whoever had the
    password could bind their own app to a staff account (platform settings
    plan 0c).
    """
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    ciphertext = _fernet().encrypt(secret.encode("ascii")).decode("ascii")
    with transaction.atomic():
        method = UserMfaMethod.objects.select_for_update().filter(user=user).first()
        if method is not None and method.is_confirmed:
            raise MfaAlreadyEnabled
        if user.is_staff and not on_server:
            raise OperatorMfaByCommand
        if method is None:
            method = UserMfaMethod.objects.create(
                user=user,
                secret_ciphertext=ciphertext,
            )
        else:
            method.secret_ciphertext = ciphertext
            method.last_used_counter = -1
            method.save(update_fields=["secret_ciphertext", "last_used_counter", "updated_at"])
        method.recovery_codes.all().delete()
    label = f"{settings.MFA_ISSUER_NAME}:{user.email}"
    query = urlencode({
        "secret": secret,
        "issuer": settings.MFA_ISSUER_NAME,
        "algorithm": "SHA1",
        "digits": TOTP_DIGITS,
        "period": TOTP_PERIOD_SECONDS,
    })
    enrollment = TotpEnrollment(
        secret=secret,
        provisioning_uri=f"otpauth://totp/{quote(label)}?{query}",
    )
    logger.info(
        "identity_mfa_enrollment_started",
        extra={"security_event": "identity.mfa_enrollment_started", "user_id": str(user.id)},
    )
    return enrollment


def confirm_totp_enrollment(
    *, user: User, code: str, correlation_id: UUID | None = None, on_server: bool = False
) -> list[str]:
    if user.is_staff and not on_server:
        raise OperatorMfaByCommand
    now = timezone.now()
    with _counted_attempt(user), transaction.atomic():
        try:
            method = UserMfaMethod.objects.select_for_update().get(user=user)
        except UserMfaMethod.DoesNotExist as error:
            raise MfaEnrollmentMissing from error
        counter = _matching_totp_counter(method=method, code=code, at=now.timestamp())
        if counter is None:
            raise InvalidMfaCode
        method.confirmed_at = now
        method.last_used_counter = counter
        method.save(update_fields=["confirmed_at", "last_used_counter", "updated_at"])
        method.recovery_codes.all().delete()
        raw_codes = [_new_recovery_code() for _ in range(8)]
        MfaRecoveryCode.objects.bulk_create([
            MfaRecoveryCode(
                method=method,
                code_hash=_recovery_digest(raw_code),
            )
            for raw_code in raw_codes
        ])
        AccountAuditEvent.objects.create(
            event_type=AccountAuditEventType.MFA_ENABLED,
            subject_user=user,
            actor_user=user,
            correlation_id=correlation_id,
        )
    logger.info(
        "identity_mfa_enabled",
        extra={"security_event": "identity.mfa_enabled", "user_id": str(user.id)},
    )
    return raw_codes


def reset_operator_mfa(*, user: User, reason: str) -> None:
    """Takes an operator's second factor away, so the server administrator can
    set a new one after a lost phone (`enroll_operator_mfa --reset`, never the
    web): the method and its recovery codes go, every session of the account
    ends and the account is told by e-mail. The reason goes to the security
    log."""
    with transaction.atomic():
        deleted, _ = UserMfaMethod.objects.filter(user=user).delete()
        if not deleted:
            raise MfaEnrollmentMissing
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        _notify(user, "operator_reset")
    cache.delete_many([_failures_key(user), _lock_key(user)])
    logger.warning(
        "identity_operator_mfa_reset",
        extra={
            "security_event": "identity.operator_mfa_reset",
            "user_id": str(user.pk),
            "reason": reason,
        },
    )


def verify_mfa_code(*, user: User, code: str) -> None:
    now = timezone.now()
    with _counted_attempt(user), transaction.atomic():
        method = _locked_method(user)
        if _consume_totp(method, code, now):
            return

        normalized = _normalize_recovery_code(code)
        recovery = (
            MfaRecoveryCode.objects.select_for_update()
            .filter(
                method=method,
                code_hash=_recovery_digest(normalized),
                used_at__isnull=True,
            )
            .first()
        )
        if recovery is None:
            raise InvalidMfaCode
        recovery.used_at = now
        recovery.save(update_fields=["used_at"])


def verify_totp_code(*, user: User, code: str) -> None:
    """A code from the authenticator app only. A recovery code gets a person
    back into the account; it is not spent on confirming one operation."""
    with _counted_attempt(user), transaction.atomic():
        if not _consume_totp(_locked_method(user), code, timezone.now()):
            raise InvalidMfaCode


def mfa_locked(user: User) -> bool:
    return cache.get(_lock_key(user)) is not None


@contextmanager
def _counted_attempt(user: User) -> Iterator[None]:
    """Wrong codes count per account, wherever they are given (ADR-023): at the
    limit the account takes no code at all for `MFA_LOCK_SECONDS`, a right one
    included. A right code clears the count."""
    if mfa_locked(user):
        raise MfaLocked
    failures_key = _failures_key(user)
    try:
        yield
    except InvalidMfaCode:
        cache.add(failures_key, 0, timeout=settings.MFA_LOCK_SECONDS)
        if cache.incr(failures_key) >= settings.MFA_FAILURE_LIMIT:
            cache.delete(failures_key)
            cache.set(_lock_key(user), 1, timeout=settings.MFA_LOCK_SECONDS)
            logger.warning(
                "identity_mfa_locked",
                extra={"security_event": "identity.mfa_locked", "user_id": str(user.pk)},
            )
            _notify(user, "locked")
            raise MfaLocked from None
        raise
    cache.delete(failures_key)


def _notify(user: User, notice: str) -> None:
    """Queues one of the account's security e-mails after commit."""
    from . import tasks  # noqa: PLC0415

    send = {
        "locked": tasks.send_mfa_locked_notice,
        "operator_reset": tasks.send_operator_mfa_reset_notice,
    }[notice]
    user_id, request_correlation_id = str(user.pk), correlation_id.get()

    def enqueue_notice() -> None:
        send.delay(user_id, request_correlation_id)

    transaction.on_commit(enqueue_notice, robust=True)


def _failures_key(user: User) -> str:
    return f"identity.mfa.failures:{user.pk}"


def _lock_key(user: User) -> str:
    return f"identity.mfa.lock:{user.pk}"


def _locked_method(user: User) -> UserMfaMethod:
    try:
        return UserMfaMethod.objects.select_for_update().get(user=user, confirmed_at__isnull=False)
    except UserMfaMethod.DoesNotExist as error:
        raise InvalidMfaCode from error


def _consume_totp(method: UserMfaMethod, code: str, now: datetime) -> bool:
    """A code counts once: one already used, or older than the last used, fails."""
    counter = _matching_totp_counter(method=method, code=code, at=now.timestamp())
    if counter is None or counter <= method.last_used_counter:
        return False
    method.last_used_counter = counter
    method.save(update_fields=["last_used_counter", "updated_at"])
    return True


def has_confirmed_mfa(user: User) -> bool:
    return UserMfaMethod.objects.filter(user=user, confirmed_at__isnull=False).exists()


def current_totp_code(secret: str, *, at: float | None = None) -> str:
    timestamp = timezone.now().timestamp() if at is None else at
    return _totp(secret=secret, counter=int(timestamp // TOTP_PERIOD_SECONDS))


def _matching_totp_counter(
    *,
    method: UserMfaMethod,
    code: str,
    at: float,
) -> int | None:
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    secret = _decrypt_secret(method.secret_ciphertext)
    current = int(at // TOTP_PERIOD_SECONDS)
    for counter in range(current - 1, current + 2):
        if hmac.compare_digest(_totp(secret=secret, counter=counter), code):
            return counter
    return None


def _totp(*, secret: str, counter: int) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _fernet() -> Fernet:
    material = hashlib.sha256(f"saas-core:mfa:{settings.MFA_ENCRYPTION_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("ascii")
    except InvalidToken as error:
        raise RuntimeError("Nie można odszyfrować sekretu MFA") from error


def _new_recovery_code() -> str:
    compact = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16))
    return "-".join(compact[index : index + 4] for index in range(0, 16, 4))


def _normalize_recovery_code(code: str) -> str:
    compact = "".join(character for character in code.upper() if character.isalnum())
    return "-".join(compact[index : index + 4] for index in range(0, len(compact), 4))


def _recovery_digest(code: str) -> str:
    return digest_secret(f"mfa-recovery:{_normalize_recovery_code(code)}")
