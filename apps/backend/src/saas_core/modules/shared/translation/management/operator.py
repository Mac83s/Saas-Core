"""Who may run the translation operator commands: `is_staff` with confirmed MFA."""

from __future__ import annotations

from django.core.management.base import CommandError

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User


def operator_user(email: str) -> User:
    normalized = User.objects.normalize_email(email)
    operator = User.objects.filter(email=normalized).first()
    if operator is None or not operator.is_active:
        raise CommandError(f"Operator {normalized} nie istnieje albo jest nieaktywny.")
    if not operator.is_staff:
        raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
    if not has_confirmed_mfa(operator):
        raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
    return operator


def reason_of(value: str | None) -> str:
    reason = (value or "").strip()
    if not reason:
        raise CommandError("Podaj --reason: dlaczego. Trafia do historii.")
    return reason
