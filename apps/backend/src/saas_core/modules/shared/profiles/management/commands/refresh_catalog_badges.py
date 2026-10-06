"""Ask every catalogue row's badges again (ADR-072 §11, slice 5h).

A row copies what other modules say of its company — „rezerwacja online” —
when it is written and when a module reports a change. This is for the rest:
the deploy that brings a badge (rows written before it have none) and what no
module reports, like a plan that stopped covering bookings. Safe to repeat.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from saas_core.modules.shared.profiles.search_index import refresh_catalog_badges


class Command(BaseCommand):
    help = "Odświeża odznaki wpisów katalogu (np. „rezerwacja online”), firma po firmie."

    def handle(self, *args: Any, **options: Any) -> None:
        result = refresh_catalog_badges()
        self.stdout.write(f"Wpisy katalogu: {result['entries']}, zmienione: {result['changed']}.")
