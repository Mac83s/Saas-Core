"""Gives or takes back level 2 of a platform operator (S-T7), on the server
only and with a reason; lists who holds it.

    manage.py operator_level --list
    manage.py operator_level --grant anna@firma.pl --operator maciej@… --reason "…"
    manage.py operator_level --revoke anna@firma.pl --operator maciej@… --reason "…"

The person must already be an operator (staff with confirmed MFA). Giving it
needs a level-2 operator — except the first grant on a deployment, which
whoever has server access gives. Either ends the person's sessions.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.identity.models import OperatorGrant, User
from saas_core.modules.core.identity.operators import (
    OPERATOR,
    PLATFORM_ADMIN,
    grant_platform_admin,
    operator_for_command,
    operator_level,
    reason_of,
    revoke_platform_admin,
)


class Command(BaseCommand):
    help = "Poziom 2 operatora platformy: nadaj, odbierz albo pokaż."

    def add_arguments(self, parser: CommandParser) -> None:
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--grant", help="E-mail osoby, która dostaje poziom 2.")
        action.add_argument("--revoke", help="E-mail osoby, której poziom 2 się odbiera.")
        action.add_argument("--list", action="store_true", help="Kto ma poziom 2.")
        parser.add_argument("--operator", help="Kto to robi (is_staff i MFA).")
        parser.add_argument("--reason", help="Dlaczego; trafia do historii.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["list"]:
            for grant in OperatorGrant.objects.filter(revoked_at__isnull=True).select_related(
                "user", "granted_by"
            ):
                by = grant.granted_by.email if grant.granted_by else "—"
                self.stdout.write(f"{grant.user.email}\tod {grant.granted_at:%Y-%m-%d}\t{by}")
            return
        reason = reason_of(options["reason"])
        first = not OperatorGrant.objects.filter(revoked_at__isnull=True).exists()
        actor = operator_for_command(
            options["operator"], level=OPERATOR if first and options["grant"] else PLATFORM_ADMIN
        )
        email = options["grant"] or options["revoke"]
        person = User.objects.filter(email=User.objects.normalize_email(email)).first()
        if person is None:
            raise CommandError(f"Nie ma konta {email}.")
        if options["grant"]:
            if operator_level(person) == 0:
                raise CommandError(
                    f"{person.email} najpierw musi być operatorem: is_staff i potwierdzone MFA."
                )
            if operator_level(person) == PLATFORM_ADMIN:
                raise CommandError(f"{person.email} ma już poziom 2.")
            grant_platform_admin(person, by=actor, reason=reason)
            self.stdout.write(f"{person.email}: poziom 2; sesje zakończone.")
            return
        if not revoke_platform_admin(person, by=actor, reason=reason):
            raise CommandError(f"{person.email} nie ma poziomu 2.")
        self.stdout.write(f"{person.email}: poziom 2 odebrany; sesje zakończone.")
