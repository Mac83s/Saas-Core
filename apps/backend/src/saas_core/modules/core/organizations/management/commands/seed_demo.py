"""Fill a staging stack with demo data (organizations/demo.py).

It refuses to run unless the environment says so for this run
(`DEMO_SEED_ENABLED=1`), and never on production or against live Stripe. The
accounts' password never passes through argv or the repository: it comes from
standard input (`--password-stdin`), a file named by `DEMO_SEED_PASSWORD_FILE`
or `DEMO_SEED_PASSWORD`.

`--scenario` names the companies to seed (all the profile can hold when it is
left out); `--list` prints what a run would make and writes nothing. A run ends
with the accounts and each company's click paths for a presentation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...demo import describe_demo, run_demo

MINIMUM_PASSWORD_LENGTH = 12
#: The stacks demo data may land on: a developer's machine, the staging VPS, tests.
DEMO_ENVIRONMENTS = frozenset({"local", "staging", "test"})


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
        parser.add_argument(
            "--scenario",
            action="append",
            default=[],
            metavar="KLUCZ",
            help="Która firma ma powstać (można podać kilka razy albo po przecinku); "
            "bez tej opcji wszystkie, które mieści profil. Klucze pokazuje --list.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="Wypisz, co powstałoby (firmy, konta, części modułów), niczego nie zapisując.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        only = [
            key.strip() for value in options["scenario"] for key in value.split(",") if key.strip()
        ]
        if options["list"]:
            # Reads the scenario only: no account, no row, no password asked for.
            try:
                for line in describe_demo(only or None):
                    self.stdout.write(line)
            except ValueError as error:
                raise CommandError(str(error)) from error
            return
        if os.environ.get("DEMO_SEED_ENABLED") != "1":
            raise CommandError("Dane demo są wyłączone: ustaw DEMO_SEED_ENABLED=1 na tym stosie.")
        # An allowlist, not a deny list: an environment added later (production)
        # is refused until somebody decides otherwise.
        if settings.APP_ENV not in DEMO_ENVIRONMENTS or getattr(settings, "STRIPE_LIVEMODE", False):
            raise CommandError("Dane demo nie trafiają na produkcję ani do Stripe w trybie live.")
        password = self._password(bool(options["password_stdin"]))
        try:
            run = run_demo(
                password=password,
                log=lambda line: self.stdout.write(f"  {line}"),
                only=only or None,
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Dane demo gotowe."))
        for line in run.guide():
            self.stdout.write(line)

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
