"""Wyłącznik tłumaczeń AI całego wdrożenia (ADR-069 pkt 30).

`none` — bez ograniczeń, `review` — każdy wynik czeka na osobę, `off` — model nie
jest wołany, a niezapisane wyniki przepadają bez opłaty. Działa od następnej
pozycji, także w zleceniach już w kolejce. Wymaga operatora z is_staff i
potwierdzonym MFA oraz powodu; zostawia wiersz historii.

    python manage.py translation_ceiling --operator <e-mail> --state off --reason "…"
    python manage.py translation_ceiling --show
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...engine_policy import ceiling_state
from ...models import TranslationCeiling
from ..operator import operator_user, reason_of

logger = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = "Ustawia wyłącznik tłumaczeń AI wdrożenia: none, review albo off."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--state", choices=["none", "review", "off"])
        parser.add_argument("--show", action="store_true", help="Stan i 10 ostatnich zmian.")
        parser.add_argument("--operator", help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--reason", help="Dlaczego. Trafia do historii, nie do logów.")

    def handle(self, *_args: Any, **options: Any) -> None:
        if options["show"]:
            self.stdout.write(f"Wyłącznik tłumaczeń: {ceiling_state()}.")
            for row in TranslationCeiling.objects.select_related("changed_by")[:10]:
                self.stdout.write(
                    f"{row.created_at:%Y-%m-%d %H:%M:%S%z}  {row.state:<6}  "
                    f"{row.changed_by.email}  {row.reason}"
                )
            return
        if not options["state"] or not options["operator"]:
            raise CommandError("Podaj --state i --operator albo --show.")
        reason = reason_of(options["reason"])
        operator = operator_user(options["operator"])
        TranslationCeiling.objects.create(
            state=options["state"], reason=reason, changed_by=operator
        )
        logger.warning(
            "translation_ceiling_set",
            extra={
                "security_event": "translation.ceiling_set",
                "user_id": str(operator.id),
                "state": options["state"],
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Wyłącznik tłumaczeń: {options['state']}."))
