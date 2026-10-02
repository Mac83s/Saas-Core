"""The consent a person's click gives a channel acting for them (ADR-076 §3).

A signed statement: this membership, in this conversation, agreed to the group
of calls whose digest is this, at most `COMMAND_CONSENT_TTL` seconds ago, with
or without a fresh step-up. Only the panel's consent endpoint mints it, for the
person acting directly (A1b-6); the executor reads it against a fresh preview.
A content preview token (ADR-044) proves an effect, not a person's agreement —
hence a salt of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core import signing
from rest_framework.exceptions import APIException, PermissionDenied

from .context import TenantContext

CONSENT_SALT = "core.commands.consent.v1"
CONSENT_VERSION = 1


class ConsentInvalid(PermissionDenied):
    default_detail = "Zgoda jest nieważna albo wygasła."
    default_code = "consent_invalid"


class ConsentDigestMismatch(APIException):
    status_code = 409
    default_detail = "Plan zmienił się od chwili zgody; trzeba go pokazać jeszcze raz."
    default_code = "consent_digest_mismatch"


@dataclass(frozen=True, slots=True)
class Consent:
    digest: str
    #: When the person last confirmed a second factor, as a Unix time; None
    #: when the click came without a step-up.
    step_up_at: int | None


def mint_consent(
    context: TenantContext,
    *,
    digest: str,
    acting_ref: str,
    step_up_at: int | None = None,
) -> str:
    """For the person themself, never for a context already acting for them:
    a channel cannot consent on its own behalf."""
    if context.acting_via or context.principal_kind != "membership":
        raise ConsentInvalid
    payload: dict[str, Any] = {
        "v": CONSENT_VERSION,
        "digest": digest,
        "organization": str(context.organization_id),
        "membership": str(context.membership_id),
        "acting_ref": acting_ref,
        "step_up_at": step_up_at,
    }
    return signing.dumps(payload, salt=CONSENT_SALT)


def read_consent(token: str, *, context: TenantContext) -> Consent:
    """The consent, if it is this membership's, for this conversation, and
    recent; the digest is the executor's to compare with a fresh preview."""
    try:
        payload = signing.loads(token, salt=CONSENT_SALT, max_age=settings.COMMAND_CONSENT_TTL)
    except signing.BadSignature:
        raise ConsentInvalid from None
    if (
        not isinstance(payload, dict)
        or payload.get("v") != CONSENT_VERSION
        or not context.acting_ref
        or payload.get("organization") != str(context.organization_id)
        or payload.get("membership") != str(context.membership_id)
        or payload.get("acting_ref") != context.acting_ref
        or not isinstance(payload.get("digest"), str)
    ):
        raise ConsentInvalid
    step_up_at = payload.get("step_up_at")
    return Consent(
        digest=payload["digest"],
        step_up_at=step_up_at if isinstance(step_up_at, int) else None,
    )
