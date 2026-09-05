"""One row of the deployment matrix, taken from the running image.

Several products are built from one repository and update on their own
schedules, so "which version is this and can it go back" has to be answerable
per deployment rather than per commit. Typing that into a table by hand is how
it stops being true after the second release; this reads it from the image and
the database it is pointed at.

Lives in `core.health` because that module is in every profile — a record you
can only produce from the products that happen to include Billing would be a
record you cannot produce when you most need it.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


def _shipped() -> dict[str, str]:
    """The last migration of each app this image carries."""
    loader = MigrationLoader(None, ignore_no_migrations=True)
    heads: dict[str, str] = {}
    for app_label, name in sorted(loader.disk_migrations):
        heads[app_label] = name
    return heads


def _irreversible() -> list[str]:
    """Migrations that cannot be undone, which is where rollback stops.

    Reversible does not mean harmless — undoing a data migration restores the
    shape of the rows, not the rows that were dropped. It means the schema can
    be walked back at all, which is the part a deploy decision can rely on.
    """
    loader = MigrationLoader(None, ignore_no_migrations=True)
    blocked: list[str] = []
    for (app_label, name), migration in sorted(loader.disk_migrations.items()):
        for index, operation in enumerate(migration.operations):
            if not operation.reversible:
                blocked.append(f"{app_label}.{name}[{index}]:{type(operation).__name__}")
    return blocked


def _applied() -> dict[str, str] | None:
    try:
        recorder = MigrationRecorder(connection)
        if not recorder.has_table():
            return None
        heads: dict[str, str] = {}
        for app_label, name in sorted(
            recorder.migration_qs.values_list("app", "name").order_by("app", "id")
        ):
            heads[app_label] = name
        return heads
    except DatabaseError:
        return None


class Command(BaseCommand):
    help = "Wypisuje wiersz macierzy deploymentu: wersja, obrazy, migracje, rollback."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--image",
            action="append",
            default=[],
            metavar="NAZWA=DIGEST",
            help=(
                "Digest obrazu, np. --image backend=sha256:… . Powtarzalny; "
                "podaje go ten, kto wie, co wdraża — proces nie zna swojego digestu."
            ),
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        images: dict[str, str] = {}
        for raw in options["image"]:
            name, separator, digest = str(raw).partition("=")
            if not separator or not name.strip() or not digest.strip():
                raise CommandError(f"Nieprawidłowy --image {raw!r}; oczekuję NAZWA=DIGEST.")
            images[name.strip()] = digest.strip()

        applied = _applied()
        shipped = _shipped()
        irreversible = _irreversible()
        record = {
            "deployment": settings.DEPLOYMENT,
            "profileHash": settings.PROFILE_HASH,
            "version": settings.APPLICATION_VERSION,
            "modules": list(settings.ACTIVE_MODULES),
            "images": images,
            "migrations": {
                "shipped": shipped,
                # None when the process cannot reach a database — a record from
                # a build agent is still worth having, and pretending it saw a
                # schema would be worse than saying it did not.
                "applied": applied,
                "pending": (
                    None
                    if applied is None
                    else sorted(app for app, head in shipped.items() if applied.get(app) != head)
                ),
            },
            "rollback": {
                "reversible": not irreversible,
                "irreversible": irreversible,
            },
        }
        self.stdout.write(json.dumps(record, indent=2, ensure_ascii=False))
