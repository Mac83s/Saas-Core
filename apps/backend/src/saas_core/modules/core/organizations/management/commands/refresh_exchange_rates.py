"""The daily reference rates of exchange, read now (`exchange_rates.py`).

    manage.py refresh_exchange_rates

The scheduler does the same every three hours; this is for the first table of
a new deployment and for a look at what is kept. One request to the chosen
bank, none when today's table is already here.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from saas_core.modules.core.organizations.exchange_rates import RatesUnavailable, refresh


class Command(BaseCommand):
    help = "Pobiera dzienną tabelę kursów walut z wybranego źródła (NBP albo EBC)."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            table = refresh()
        except RatesUnavailable as error:
            raise CommandError(f"Źródło kursów nie odpowiedziało tabelą: {error}") from error
        rates = ", ".join(f"{code} {value}" for code, value in sorted(table.rates.items()))
        self.stdout.write(
            f"{table.source}\t{table.published_on.isoformat()}\t"
            f"1 jednostka w {table.base_currency}: {rates}"
        )
