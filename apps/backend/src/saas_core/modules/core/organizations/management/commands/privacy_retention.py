"""Removal of personal data after a time, as the companies' own settings ask
(settings plan D1–D2, answer 37a).

    manage.py privacy_retention --dry-run     what a run would remove now; changes nothing
    manage.py privacy_retention --run         removes it

A company appears only when it turned a removal on. `--run` takes each
company in its own transaction: one that fails is reported, the others run,
and the command exits non-zero. Counts only — never a name or an address.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.organizations.retention import dry_run, registered_sweeps, run


class Command(BaseCommand):
    help = "Usuwanie danych osobowych po czasie: --dry-run liczy, --run usuwa."

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--dry-run", action="store_true", help="Policz i wypisz; niczego nie usuwaj."
        )
        mode.add_argument("--run", action="store_true", help="Usuń to, co jest po terminie.")

    def handle(self, *args: Any, **options: Any) -> None:
        sweeps = ", ".join(sweep.key for sweep in registered_sweeps()) or "brak"
        if options["dry_run"]:
            found = dry_run()
            for item in found:
                waits = (
                    f"\tczeka do {item.waits_until:%Y-%m-%d %H:%M} UTC" if item.waits_until else ""
                )
                self.stdout.write(
                    f"{item.organization_id}\t{item.sweep}\t{item.period}\t"
                    f"przed {item.cutoff:%Y-%m-%d}\t{item.count}{waits}"
                )
            companies = len({item.organization_id for item in found})
            self.stdout.write(
                f"Firmy z włączonym usuwaniem: {companies}; rodzaje danych: {sweeps}. "
                "Niczego nie usunięto."
            )
            return
        result = run()
        for done in result.removed:
            self.stdout.write(
                f"{done.organization_id}\t{done.sweep}\t{done.period}\tusunięto {done.count}"
            )
        self.stdout.write(
            f"Usunięto w {len({done.organization_id for done in result.removed})} firmach; "
            f"rodzaje danych: {sweeps}."
        )
        if result.failed:
            raise CommandError(
                "Nie udało się w firmach: "
                + ", ".join(str(organization_id) for organization_id in result.failed)
                + ". Pozostałe firmy przeszły; szczegóły w logu."
            )
