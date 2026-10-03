"""Who operates the platform, and at which level (platform settings plan,
S-T7; owner decision U2).

One gate for every door — the API, the panel and the server commands: a
staff account with confirmed two-factor sign-in, and on the web a managed
session that passed it. Level 1 sees, previews and supports without a
financial effect; level 2 also changes what a company pays or gets for free
and whatever has a legal effect. Level 2 is an explicit grant
(`OperatorGrant`), given and taken back only on the server, with a reason;
either ends the person's sessions, so the new level holds from their next
sign-in.
"""

from __future__ import annotations

from typing import cast

from django.core.management.base import CommandError
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .admin_site import is_mfa_operator
from .mfa import has_confirmed_mfa
from .models import OperatorGrant, User, UserSession

OPERATOR = 1
PLATFORM_ADMIN = 2


class OperatorLevelRequired(PermissionDenied):
    default_detail = "Ta zmiana wymaga wyższego poziomu operatora platformy."
    default_code = "operator_level_required"


def operator_level(user: User | None) -> int:
    """0: not an operator; 1: staff with confirmed MFA; 2: and a grant."""
    if user is None or not user.is_active or not user.is_staff or not has_confirmed_mfa(user):
        return 0
    if OperatorGrant.objects.filter(user=user, revoked_at__isnull=True).exists():
        return PLATFORM_ADMIN
    return OPERATOR


def require_operator(request: HttpRequest, *, level: int = OPERATOR) -> User:
    """The web's gate: an operator on a session signed in through MFA, at
    least at `level`."""
    user = cast(User, request.user)
    if not is_mfa_operator(request) or operator_level(user) < level:
        raise OperatorLevelRequired
    return user


def operator_for_command(email: str | None, *, level: int = OPERATOR) -> User:
    """The `--operator` of a server command: who runs it and answers for it."""
    if not email:
        raise CommandError("Podaj --operator: adres konta operatora (is_staff i MFA).")
    normalized = User.objects.normalize_email(email)
    operator = User.objects.filter(email=normalized).first()
    found = operator_level(operator)
    if found == 0:
        raise CommandError(
            f"{normalized} nie jest operatorem platformy: potrzebne is_staff i potwierdzone MFA."
        )
    if found < level:
        raise CommandError(f"{normalized} nie ma poziomu {level} operatora platformy.")
    return cast(User, operator)


def reason_of(value: str | None) -> str:
    reason = (value or "").strip()
    if not reason:
        raise CommandError("Podaj --reason: dlaczego. Trafia do historii.")
    return reason


def grant_platform_admin(user: User, *, by: User | None, reason: str) -> OperatorGrant:
    """Level 2 for `user`; their sessions end, so it applies from the next sign-in."""
    grant = OperatorGrant.objects.create(user=user, granted_by=by, reason=reason)
    _end_sessions(user)
    return grant


def revoke_platform_admin(user: User, *, by: User, reason: str) -> int:
    """Back to level 1 (or none); their sessions end at once."""
    revoked = OperatorGrant.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_by=by, revoke_reason=reason
    )
    _end_sessions(user)
    return revoked


def _end_sessions(user: User) -> None:
    UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
