from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError

from .metrics import SIGNATURE_FAILURES

Resolver = Callable[[str, int, int, int], list[tuple[Any, ...]]]


def recipient_digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def validate_webhook_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("Webhook wymaga URL HTTPS bez danych logowania.")
    if parsed.fragment:
        raise ValidationError("Webhook URL nie może zawierać fragmentu.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValidationError("Webhook host nie może być adresem lokalnym.")
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            records = resolver(hostname, parsed.port or 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(record[4][0]) for record in records]
        except (OSError, ValueError) as error:
            raise ValidationError("Nie można bezpiecznie rozwiązać hosta webhooka.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValidationError("Webhook host musi wskazywać wyłącznie publiczne adresy IP.")
    return parsed.geturl()


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise RuntimeError("Nie można odszyfrować sekretu integracji.") from error


def sign_webhook(*, secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "v1=" + digest.hexdigest()


def verify_provider_webhook(*, body: bytes, timestamp: str, signature: str) -> None:
    try:
        parsed_timestamp = int(timestamp)
    except (TypeError, ValueError) as error:
        SIGNATURE_FAILURES.labels(kind="provider_email").inc()
        raise ValidationError("Nieprawidłowy timestamp webhooka.") from error
    if abs(int(time.time()) - parsed_timestamp) > settings.NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS:
        SIGNATURE_FAILURES.labels(kind="provider_email").inc()
        raise ValidationError("Webhook wygasł.")
    expected = sign_webhook(
        secret=settings.NOTIFICATIONS_PROVIDER_WEBHOOK_SECRET,
        timestamp=parsed_timestamp,
        body=body,
    )
    if not settings.NOTIFICATIONS_PROVIDER_WEBHOOK_SECRET or not hmac.compare_digest(
        expected, signature
    ):
        SIGNATURE_FAILURES.labels(kind="provider_email").inc()
        raise ValidationError("Nieprawidłowy podpis webhooka.")


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _fernet() -> Fernet:
    material = settings.INTEGRATIONS_ENCRYPTION_KEY or settings.SECRET_KEY
    if not material:
        raise RuntimeError("Brak klucza szyfrowania integracji.")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)
