"""What the companies' own retention settings would remove now (settings plan
D1–D2, answer 37a) — counted company by company, nothing removed.

    manage.py privacy_retention --dry-run

A company appears only when it turned a removal on. This version only
counts: without `--dry-run` it refuses, because there is no removal to run.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.organizations.retention import dry_run, registered_sweeps


class Command(BaseCommand):
    help = "Usuwanie danych osobowych po czasie: co zostałoby usunięte teraz (tylko podgląd)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true", help="Policz i wypisz; niczego nie usuwaj."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["dry_run"]:
            raise CommandError(
                "Ta wersja tylko liczy: uruchom z --dry-run. Usuwanie nie jest jeszcze wdrożone."
            )
        found = dry_run()
        for item in found:
            self.stdout.write(
                f"{item.organization_id}\t{item.sweep}\t{item.months} mies.\t"
                f"przed {item.cutoff:%Y-%m-%d}\t{item.count}"
            )
        companies = len({item.organization_id for item in found})
        self.stdout.write(
            f"Firmy z włączonym usuwaniem: {companies}; rodzaje danych: "
            f"{', '.join(sweep.key for sweep in registered_sweeps()) or 'brak'}. "
            "Niczego nie usunięto."
        )
