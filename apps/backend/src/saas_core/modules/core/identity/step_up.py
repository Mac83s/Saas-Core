"""Confirming once more, with a second factor, what must not ride on a session
alone (ADR-076 §2; owner answers 30a and 31b, 2026-10-02).

Only accepting legal documents and changing billing ask for it — in the panel
and for the assistant alike, and for the operator's level-2 settings. It is a
code from the authenticator app: a password proves nothing a hijacked session
could not have watched being typed, and a recovery code is for getting back
into the account, not for confirming one operation. An account without
two-factor sign-in cannot step up at all; it is told to turn it on first.

A step-up lives in the session for `STEP_UP_MAX_AGE` seconds. A request runs
with the session's step-up active; the command executor replaces it with the
one its consent token carries, so a step-up made in the panel never reaches
what the assistant does without it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .mfa import InvalidMfaCode, has_confirmed_mfa, verify_totp_code
from .models import User, UserMfaMethod

logger = logging.getLogger(__name__)

STEP_UP_SESSION_KEY = "identity_step_up_at"
#: Wrong codes a person may give before the session ends, per window.
STEP_UP_FAILURE_LIMIT = 5
STEP_UP_FAILURE_WINDOW = 15 * 60

_step_up_at: ContextVar[int | None] = ContextVar("identity_step_up_at", default=None)


class StepUpRequired(PermissionDenied):
    default_detail = "Potwierdź tę operację kodem z aplikacji uwierzytelniającej."
    default_code = "step_up_required"


class StepUpMfaSetupRequired(PermissionDenied):
    default_detail = (
        "Włącz weryfikację dwuetapową, aby akceptować dokumenty prawne i zmieniać rozliczenia."
    )
    default_code = "step_up_mfa_setup_required"


class StepUpLocked(PermissionDenied):
    default_detail = "Zbyt wiele błędnych kodów. Zaloguj się ponownie."
    default_code = "step_up_locked"


def confirm_step_up(*, request: HttpRequest, code: str) -> int:
    """Checks the code and marks the session as stepped up now; returns when."""
    user = cast(User, request.user)
    if not has_confirmed_mfa(user):
        raise StepUpMfaSetupRequired
    failures_key = f"identity.step_up.failures:{user.pk}"
    try:
        verify_totp_code(user=user, code=code)
    except InvalidMfaCode:
        cache.add(failures_key, 0, timeout=STEP_UP_FAILURE_WINDOW)
        if cache.incr(failures_key) >= STEP_UP_FAILURE_LIMIT:
            cache.delete(failures_key)
            logger.warning(
                "identity_step_up_locked",
                extra={"security_event": "identity.step_up_locked", "user_id": str(user.pk)},
            )
            # Imported here: the session middleware imports this module.
            from .sessions import logout_user  # noqa: PLC0415

            logout_user(request=request)
            raise StepUpLocked from None
        raise
    cache.delete(failures_key)
    at = int(timezone.now().timestamp())
    request.session[STEP_UP_SESSION_KEY] = at
    logger.info(
        "identity_step_up_confirmed",
        extra={"security_event": "identity.step_up_confirmed", "user_id": str(user.pk)},
    )
    return at


def session_step_up_at(request: HttpRequest) -> int | None:
    """The session's step-up while it is still fresh, else None."""
    at = request.session.get(STEP_UP_SESSION_KEY)
    return at if isinstance(at, int) and _fresh(at) else None


@contextmanager
def activate_step_up(at: int | None) -> Iterator[None]:
    token = _step_up_at.set(at)
    try:
        yield
    finally:
        _step_up_at.reset(token)


def require_step_up(*, user_id: UUID, reason: str) -> None:
    """Refuses unless a fresh step-up is active for this run.

    A service calls it before accepting a legal document or changing billing;
    `reason` names the operation in the security log. Without two-factor
    sign-in the answer says to turn it on, not to enter a code.
    """
    at = _step_up_at.get()
    if at is not None and _fresh(at):
        return
    logger.info(
        "identity_step_up_required",
        extra={
            "security_event": "identity.step_up_required",
            "user_id": str(user_id),
            "reason": reason,
        },
    )
    if not UserMfaMethod.objects.filter(user_id=user_id, confirmed_at__isnull=False).exists():
        raise StepUpMfaSetupRequired
    raise StepUpRequired


def _fresh(at: int) -> bool:
    return 0 <= timezone.now().timestamp() - at <= settings.STEP_UP_MAX_AGE
