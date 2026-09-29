"""Rebuild the catalogue's search index from the database (ADR-064).

For the first deploy of the engine and after a change of the index settings;
day-to-day drift is the reconcile sweep's job. The new index is filled beside
the old one and swapped in, so searches never see a half-built index.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from saas_core.modules.shared.profiles.search_engine import SearchEngineUnavailable
from saas_core.modules.shared.profiles.search_index import index_name, rebuild


class Command(BaseCommand):
    help = "Przebudowuje indeks wyszukiwarki katalogu z bazy i podmienia go atomowo."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            count = rebuild()
        except SearchEngineUnavailable as error:
            raise CommandError(f"Silnik wyszukiwania nie odpowiada: {error}") from error
        self.stdout.write(f"Indeks {index_name()}: {count} wpisów.")
