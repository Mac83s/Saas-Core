"""Kto czeka na który rodzaj rezerwacji i czego mu brakuje (ADR-072 §10,
„wkrótce”; plaster 5g) — lista dla operatora platformy, dopóki nie ma jej w
panelu „Platforma”.

Firma sama zapisuje się na tę listę („Daj znać, gdy będzie gotowe”) i sama
pisze, czego jej brakuje: zapis jest skierowany do platformy, więc jego odczyt
nie jest wglądem wsparcia w dane firmy i nie zostawia wpisu w jej historii.
Tabela jest tenantowa (wymuszony RLS), więc lista powstaje firma po firmie.

    python manage.py booking_preset_interest
    python manage.py booking_preset_interest --preset core.hourly_space
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import billing_organization_ids

from ...models import PresetInterest


class Command(BaseCommand):
    help = "Wypisuje firmy zapisane na wzorce „wkrótce” i to, czego im brakuje."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--preset", help="Tylko ten wzorzec, np. core.hourly_space.")

    def handle(self, *_args: Any, **options: Any) -> None:
        waiting: dict[str, list[str]] = {}
        for organization_id in billing_organization_ids():
            # One company at a time: a read across companies returns nothing
            # under row-level security.
            with transaction.atomic():
                set_local_organization_id(organization_id)
                rows = PresetInterest.all_objects.filter(organization_id=organization_id)
                if options.get("preset"):
                    rows = rows.filter(preset_id=options["preset"])
                found = list(rows.order_by("preset_id"))
                if not found:
                    continue
                name = (
                    Organization.objects.filter(pk=organization_id)
                    .values_list("name", flat=True)
                    .first()
                )
                for row in found:
                    note = " ".join(row.note.split()) or "—"
                    waiting.setdefault(row.preset_id, []).append(
                        f"  {row.updated_at:%Y-%m-%d} {name} ({organization_id}): {note}"
                    )
        if not waiting:
            self.stdout.write("Nikt nie czeka.")
            return
        for preset_id in sorted(waiting, key=lambda key: (-len(waiting[key]), key)):
            self.stdout.write(f"{preset_id}: {len(waiting[preset_id])}")
            for line in waiting[preset_id]:
                self.stdout.write(line)
