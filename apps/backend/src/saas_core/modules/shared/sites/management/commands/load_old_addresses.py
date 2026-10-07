"""Wczytuje mapę starych adresów strony (ADR-077).

Strona, która zastępuje inną, dziedziczy jej linki: każdy stary adres prowadzi
jednym 308 tam, gdzie ta treść odpowiada dziś, albo odpowiada 410 — „usunięte
na stałe”. Plik CSV ma dwie kolumny: stary adres i nowy adres na tej stronie
albo słowo `gone`:

    old_path,new_path
    /pl/rasy-psow/owczarek-niemiecki,/rasy-psow/owczarek-niemiecki/
    /ru/%D0%BF%D0%BE%D1%80%D0%BE%D0%B4%D1%8B,/ru/porody/
    /ogloszenia,gone

Jak adres jest porównywany (bez końcowego ukośnika, bez wielkości liter, po
rozkodowaniu `%XX`, bez query stringu) — `old_addresses.address_key`. Reguła
odpowiada tylko tam, gdzie nie odpowiada nic ze strony.

    python manage.py load_old_addresses --host <host strony> --csv mapa.csv \\
        --operator <e-mail> --dry-run
    python manage.py load_old_addresses --host <host strony> --csv mapa.csv \\
        --operator <e-mail> [--replace]

`--dry-run` niczego nie zapisuje i pokazuje to samo podsumowanie. Bez
`--replace` plik dopisuje i poprawia reguły; z `--replace` jest całą mapą —
reguły, których w nim nie ma, znikają. Odrzucony wiersz zatrzymuje zapis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User

from ...domains import InvalidHostname, normalize_hostname
from ...models import Domain, DomainStatus
from ...old_addresses import (
    MAX_RULES,
    OldAddressReport,
    apply_rows,
    check_against_site,
    file_hash,
    read_rows,
)

NOTES = {
    "answers_today": "stary adres odpowiada dziś na stronie — reguła czeka za żywym adresem",
    "target_missing": "nowy adres dziś nie odpowiada — stary da 404, dopóki nie zacznie",
    "target_moves": "nowy adres sam przekierowuje — reguła poprowadzi od razu do celu",
    "unserved": "adres z kropką nie dociera do strony (pliki statyczne) — reguła nie zadziała",
    "same": "stary i nowy adres to ten sam adres — reguła zbędna, pominięta",
    "repeated": "powtórzony wiersz — pominięty",
}


class Command(BaseCommand):
    help = "Wczytuje mapę starych adresów strony: 308 do dzisiejszego adresu albo 410."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", required=True, help="Zweryfikowany host strony.")
        parser.add_argument("--csv", required=True, help="Plik: stary adres, nowy adres | gone.")
        parser.add_argument("--operator", required=True, help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--delimiter", default=",", help="Separator kolumn (domyślnie ,).")
        parser.add_argument("--dry-run", action="store_true", help="Tylko podsumowanie.")
        parser.add_argument(
            "--replace", action="store_true", help="Plik jest całą mapą: reszta reguł znika."
        )
        parser.add_argument(
            "--examples", type=int, default=10, help="Ile przykładów każdej uwagi wypisać."
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        operator = self._operator(options["operator"])
        try:
            hostname = normalize_hostname(options["host"], allow_port=True)
        except InvalidHostname as error:
            raise CommandError(f"Niepoprawny host: {error}") from error
        domain = (
            Domain.all_objects.select_related("site__organization")
            .filter(hostname=hostname, status=DomainStatus.VERIFIED)
            .first()
        )
        if domain is None:
            raise CommandError(f"Żadna strona nie odpowiada pod zweryfikowanym hostem {hostname}.")
        try:
            text = Path(options["csv"]).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            raise CommandError(f"Nie da się odczytać pliku: {error}") from error

        report = read_rows(text, delimiter=options["delimiter"])
        if len(report.rows) > MAX_RULES:
            raise CommandError(
                f"Plik ma {len(report.rows)} reguł; jedna mapa to najwyżej {MAX_RULES}."
            )
        dry_run = bool(options["dry_run"])
        blocked = bool(report.rejected)
        check_against_site(report, host=hostname)
        apply_rows(
            report,
            site=domain.site,
            actor=operator,
            replace=bool(options["replace"]),
            # A file with a refused row is not half-loaded: fix it and run again.
            dry_run=dry_run or blocked,
            source_hash=file_hash(text),
        )
        self._print(report, examples=int(options["examples"]))
        if blocked:
            raise CommandError(
                f"Odrzucone wiersze: {len(report.rejected)}. Nic nie zapisano — popraw plik."
            )
        verb = "Zmieniłoby się" if dry_run else "Zapisano"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {report.added} nowych, {report.changed} zmienionych, "
                f"{report.removed} usuniętych; bez zmian {report.unchanged}."
            )
        )

    def _print(self, report: OldAddressReport, *, examples: int) -> None:
        moved = sum(1 for row in report.rows if row.to_path)
        self.stdout.write(
            f"Reguły w pliku: {len(report.rows)} (308: {moved}, 410: {len(report.rows) - moved})."
        )
        for line, old, reason in report.rejected[:examples]:
            self.stdout.write(self.style.ERROR(f"  odrzucony wiersz {line}: {old} — {reason}"))
        if len(report.rejected) > examples:
            self.stdout.write(f"  … i {len(report.rejected) - examples} kolejnych odrzuconych")
        for kind, label in NOTES.items():
            found = report.notes.get(kind, [])
            if not found:
                continue
            self.stdout.write(self.style.WARNING(f"Uwaga ({len(found)}): {label}"))
            for line, text in found[:examples]:
                self.stdout.write(f"  wiersz {line}: {text}")

    def _operator(self, email: str) -> User:
        normalized = User.objects.normalize_email(email)
        operator = User.objects.filter(email=normalized).first()
        if operator is None or not operator.is_active:
            raise CommandError(f"Operator {normalized} nie istnieje albo jest nieaktywny.")
        if not operator.is_staff:
            raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
        return operator
