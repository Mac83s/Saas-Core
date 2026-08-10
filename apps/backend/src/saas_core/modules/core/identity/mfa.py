from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import struct
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from .models import MfaRecoveryCode, User, UserMfaMethod
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


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    secret: str
    provisioning_uri: str


def begin_totp_enrollment(*, user: User) -> TotpEnrollment:
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    ciphertext = _fernet().encrypt(secret.encode("ascii")).decode("ascii")
    with transaction.atomic():
        method = UserMfaMethod.objects.select_for_update().filter(user=user).first()
        if method is not None and method.is_confirmed:
            raise MfaAlreadyEnabled
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


def confirm_totp_enrollment(*, user: User, code: str) -> list[str]:
    now = timezone.now()
    with transaction.atomic():
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
    logger.info(
        "identity_mfa_enabled",
        extra={"security_event": "identity.mfa_enabled", "user_id": str(user.id)},
    )
    return raw_codes


def verify_mfa_code(*, user: User, code: str) -> None:
    now = timezone.now()
    with transaction.atomic():
        try:
            method = UserMfaMethod.objects.select_for_update().get(
                user=user,
                confirmed_at__isnull=False,
            )
        except UserMfaMethod.DoesNotExist as error:
            raise InvalidMfaCode from error

        counter = _matching_totp_counter(method=method, code=code, at=now.timestamp())
        if counter is not None and counter > method.last_used_counter:
            method.last_used_counter = counter
            method.save(update_fields=["last_used_counter", "updated_at"])
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
