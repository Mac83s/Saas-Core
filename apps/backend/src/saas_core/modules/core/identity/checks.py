from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def operator_mfa_setup_at_login(app_configs: Any, **kwargs: Any) -> list[Any]:
    """Says at every start that the first factor of a staff account can be set
    with the password alone (ADR-023, uzupełnienie 2026-10-06). A warning, not
    an error: the owner keeps it on for the test stacks, and it must not be
    forgotten there when the first customer comes. Under `APP_ENV=staging` it
    is an error instead: staging holds the real stack, and the backend does not
    start with the switch on (decision 2026-10-06, variant b)."""
    if not settings.OPERATOR_MFA_SETUP_AT_LOGIN:
        return []
    if settings.APP_ENV == "staging":
        return [
            Error(
                "OPERATOR_MFA_SETUP_AT_LOGIN jest włączone przy APP_ENV=staging: "
                "hasło konta operatora wystarczyłoby do przejęcia go.",
                hint=(
                    "Usuń OPERATOR_MFA_SETUP_AT_LOGIN z .env albo ustaw false i utwórz "
                    "kontenery ponownie; pierwsze MFA ustawia `manage.py enroll_operator_mfa`."
                ),
                id="identity.E001",
            )
        ]
    return [
        Warning(
            "OPERATOR_MFA_SETUP_AT_LOGIN jest włączone: pierwsze MFA konta operatora "
            "ustawi przy logowaniu każdy, kto zna jego hasło.",
            hint=(
                "Zostaw tylko na stacku testowym. Przed pierwszym klientem usuń zmienną "
                "albo ustaw false i utwórz kontenery ponownie; pierwsze MFA ustawia wtedy "
                "`manage.py enroll_operator_mfa`."
            ),
            id="identity.W001",
        )
    ]
