"""Połącz kartę firmy z gospodarstwem rolnika bez kodu (ADR-051 pkt 5).

Kod aktywacji jest zgodą hodowcy na wydanie stada. Ta komenda tę zgodę omija,
bo czasem trzeba: kod nie dotarł, wydruk zginął, hodowca dzwoni do wsparcia.
Dlatego nie ma tu przycisku — jest komenda z nazwiskiem operatora, powodem i
śladem w audycie obu organizacji. Wersja, którą łatwo kliknąć przez pomyłkę,
prędzej czy później zostanie kliknięta przez pomyłkę.

Stada nie kopiuje. Firma robi to osobno akcją „wyślij stado do rejestru",
świadomie decydując, co przekazuje.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User

from ...sharing import link_without_code


class Command(BaseCommand):
    help = "Łączy kartę gospodarstwa firmy z rejestrem rolnika bez kodu aktywacji."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--operator", required=True, help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--company-organization", required=True, help="Organizacja firmy.")
        parser.add_argument("--company-farm", required=True, help="Karta gospodarstwa u firmy.")
        parser.add_argument("--registry-organization", required=True, help="Organizacja rolnika.")
        parser.add_argument("--registry-farm", required=True, help="Gospodarstwo w rejestrze.")
        parser.add_argument(
            "--reason",
            required=True,
            help="Dlaczego łączymy bez kodu. Trafia do wyniku komendy i audytu.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        operator = self._operator(options["operator"])
        if len(options["reason"].strip()) < 10:
            raise CommandError("Powód musi być zdaniem, nie znakiem.")
        try:
            with transaction.atomic():
                share = link_without_code(
                    operator_id=operator.id,
                    company_organization_id=UUID(options["company_organization"]),
                    company_farm_id=UUID(options["company_farm"]),
                    registry_organization_id=UUID(options["registry_organization"]),
                    registry_farm_id=UUID(options["registry_farm"]),
                )
        except ValueError as error:
            raise CommandError(f"Nieprawidłowy identyfikator: {error}") from error
        except (APIException, NotFound, ValidationError) as error:
            raise CommandError(str(error.detail)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Połączono: udział {share.id}, firma {share.company_name}, "
                f"rejestr {share.registry_name}. Powód: {options['reason'].strip()}"
            )
        )
        self.stdout.write(
            "Stado nie zostało skopiowane — firma wysyła je akcją „wyślij stado do rejestru”."
        )

    def _operator(self, email: str) -> User:
        normalized = User.objects.normalize_email(email)
        operator = User.objects.filter(email=normalized).first()
        if operator is None or not operator.is_active:
            raise CommandError(f"Operator {normalized} nie istnieje albo jest nieaktywny.")
        if not operator.is_staff:
            raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            # Akcja omija zgodę hodowcy na wydanie stada; samo hasło nie
            # wystarczy, żeby ją ominąć.
            raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
        return operator
