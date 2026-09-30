"""Fill a staging stack with demo data (organizations/demo.py).

It refuses to run unless the environment says so for this run
(`DEMO_SEED_ENABLED=1`), and never on production or against live Stripe. The
accounts' password never passes through argv or the repository: it comes from
standard input (`--password-stdin`), a file named by `DEMO_SEED_PASSWORD_FILE`
or `DEMO_SEED_PASSWORD`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...demo import run_demo

MINIMUM_PASSWORD_LENGTH = 12


class Command(BaseCommand):
    help = (
        "Zakłada dane demo (firmy, zespół, wizyty, magazyn) na stosie testowym. "
        "Wymaga DEMO_SEED_ENABLED=1; hasło kont ze stdin, pliku albo zmiennej."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help="Przeczytaj hasło kont demo ze standardowego wejścia.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        if os.environ.get("DEMO_SEED_ENABLED") != "1":
            raise CommandError("Dane demo są wyłączone: ustaw DEMO_SEED_ENABLED=1 na tym stosie.")
        if settings.APP_ENV == "production" or getattr(settings, "STRIPE_LIVEMODE", False):
            raise CommandError("Dane demo nie trafiają na produkcję ani do Stripe w trybie live.")
        password = self._password(bool(options["password_stdin"]))
        try:
            run_demo(password=password, log=lambda line: self.stdout.write(f"  {line}"))
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Dane demo gotowe."))

    def _password(self, from_stdin: bool) -> str:
        if from_stdin:
            password = sys.stdin.readline().rstrip("\n")
        elif path := os.environ.get("DEMO_SEED_PASSWORD_FILE"):
            password = Path(path).read_text(encoding="utf-8").strip()
        else:
            password = os.environ.get("DEMO_SEED_PASSWORD", "")
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise CommandError(
                f"Hasło kont demo: co najmniej {MINIMUM_PASSWORD_LENGTH} znaków "
                "(--password-stdin, DEMO_SEED_PASSWORD_FILE albo DEMO_SEED_PASSWORD)."
            )
        return password
