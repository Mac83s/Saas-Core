from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from django.conf import settings


@dataclass(frozen=True, slots=True)
class IssuedToken:
    value: str = field(repr=False)
    digest: str


def digest_secret(value: str) -> str:
    """Return a stable keyed digest suitable for database lookup."""
    return hmac.new(
        key=settings.SECRET_KEY.encode("utf-8"),
        msg=value.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def issue_token() -> IssuedToken:
    value = secrets.token_urlsafe(32)
    return IssuedToken(value=value, digest=digest_secret(value))


def issue_bound_token(*, purpose: str, identifier: str) -> IssuedToken:
    signature = digest_secret(f"{purpose}:{identifier}")
    value = f"{identifier}.{signature}"
    return IssuedToken(value=value, digest=digest_secret(value))


def digest_identifier(value: str) -> str:
    return digest_secret(value.strip().casefold())
