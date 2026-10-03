"""Turns on an operator's first second factor, on the server (platform settings plan 0c).

An `is_staff` account cannot set its first TOTP in the panel: there, whoever
had the password could bind their own authenticator to it and cut the real
operator out. The server administrator runs this instead, in two steps and in
their own terminal — the secret and the recovery codes it prints must not end
up in a log or a chat:

    manage.py enroll_operator_mfa admin@example.com
    manage.py enroll_operator_mfa admin@example.com --confirm 123456

The first step starts over on every run until a code confirms it.

A lost phone with no recovery code left: `--reset --reason "…"` takes the old
factor and its recovery codes away, ends every session of the account, tells
the operator by e-mail and starts the first step again.

    manage.py enroll_operator_mfa admin@example.com --reset --reason "zgubiony telefon"
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.mfa import (
    begin_totp_enrollment,
    confirm_totp_enrollment,
    reset_operator_mfa,
)
from saas_core.modules.core.identity.models import User


class Command(BaseCommand):
    help = "Włącza pierwsze MFA (TOTP) konta operatora: najpierw sekret, potem --confirm KOD."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("email")
        parser.add_argument(
            "--confirm",
            metavar="KOD",
            help="Kod z aplikacji uwierzytelniającej; kończy włączanie i wypisuje kody zapasowe.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Usuwa dotychczasowe MFA i kody zapasowe, kończy sesje konta i zaczyna od nowa.",
        )
        parser.add_argument("--reason", help="Dlaczego reset; trafia do dziennika bezpieczeństwa.")

    def handle(
        self,
        *args: Any,
        email: str,
        confirm: str | None,
        reset: bool,
        reason: str | None,
        **options: Any,
    ) -> None:
        user = User.objects.filter(email=User.objects.normalize_email(email)).first()
        if user is None or not user.is_staff:
            raise CommandError("Nie ma konta operatora (is_staff) o tym adresie.")
        if reset and confirm is not None:
            raise CommandError("--reset zaczyna od nowa; --confirm podaj w następnym kroku.")
        if reset and not (reason or "").strip():
            raise CommandError("Podaj --reason: dlaczego reset. Trafia do dziennika.")
        try:
            if reset:
                reset_operator_mfa(user=user, reason=(reason or "").strip())
                self.stdout.write("Dotychczasowe MFA usunięte, sesje konta zakończone.")
            if confirm is None:
                self._begin(user)
            else:
                self._confirm(user, confirm.strip())
        except APIException as error:
            raise CommandError(str(error.detail)) from error

    def _begin(self, user: User) -> None:
        enrollment = begin_totp_enrollment(user=user, on_server=True)
        grouped = " ".join(
            enrollment.secret[index : index + 4] for index in range(0, len(enrollment.secret), 4)
        )
        self.stdout.write(
            "Dodaj konto w aplikacji uwierzytelniającej:\n"
            f"  sekret: {grouped}\n"
            f"  adres:  {enrollment.provisioning_uri}\n"
            f"Potem: manage.py enroll_operator_mfa {user.email} --confirm <kod z aplikacji>"
        )

    def _confirm(self, user: User, code: str) -> None:
        codes = confirm_totp_enrollment(user=user, code=code, on_server=True)
        self.stdout.write(
            "MFA włączone. Kody zapasowe — każdy działa raz; zapisz je poza serwerem:\n"
            + "\n".join(f"  {recovery}" for recovery in codes)
        )
