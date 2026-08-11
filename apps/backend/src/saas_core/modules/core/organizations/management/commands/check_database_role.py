from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


@dataclass(frozen=True, slots=True)
class DatabaseRoleAttributes:
    name: str
    superuser: bool
    create_database: bool
    create_role: bool
    replication: bool
    bypass_rls: bool

    @property
    def unsafe_attributes(self) -> tuple[str, ...]:
        attributes = (
            ("SUPERUSER", self.superuser),
            ("CREATEDB", self.create_database),
            ("CREATEROLE", self.create_role),
            ("REPLICATION", self.replication),
            ("BYPASSRLS", self.bypass_rls),
        )
        return tuple(name for name, enabled in attributes if enabled)


def current_database_role() -> DatabaseRoleAttributes:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise CommandError("Nie można odczytać bieżącej roli PostgreSQL.")
    return DatabaseRoleAttributes(
        name=row[0],
        superuser=row[1],
        create_database=row[2],
        create_role=row[3],
        replication=row[4],
        bypass_rls=row[5],
    )


class Command(BaseCommand):
    help = "Kończy start, jeżeli rola aplikacyjna PostgreSQL może ominąć RLS."

    def handle(self, *args: object, **options: object) -> None:
        role = current_database_role()
        if role.unsafe_attributes:
            unsafe = ", ".join(role.unsafe_attributes)
            raise CommandError(
                f"Rola aplikacyjna PostgreSQL {role.name!r} ma niedozwolone atrybuty: "
                f"{unsafe}."
            )
        self.stdout.write(
            self.style.SUCCESS(f"Rola PostgreSQL {role.name!r} egzekwuje kontrakt RLS.")
        )
