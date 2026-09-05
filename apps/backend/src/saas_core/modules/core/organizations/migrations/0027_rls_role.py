from typing import Any

from django.conf import settings
from django.db import migrations

# ADR-041, krok 3: role. Wiersz z pustą organizacją jest katalogiem globalnym —
# `owner`, `admin` i reszta szablonów, które każdy tenant czyta i żaden nie
# posiada. Rola własna firmy jest już danymi tenanta i widzi ją tylko ona.
#
# Zapis jest węższy niż odczyt celowo: WITH CHECK nie dopuszcza pustej
# organizacji, więc żaden tenant nie dopisze sobie roli globalnej. Katalog
# zakłada migracja, która biegnie właścicielem tabeli i politykom nie podlega.
TABLE = "organizations_role"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"


def _identity_role() -> str:
    alias = getattr(settings, "PRE_TENANT_DATABASE_ALIAS", "pre_tenant")
    return str(settings.DATABASES[alias]["USER"])


def _enable(apps: Any, schema_editor: Any) -> None:
    role = _identity_role()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone() is None:
            raise RuntimeError(
                f"Rola {role!r} nie istnieje; uruchom bootstrap ról PostgreSQL "
                "przed migracją (ADR-041)."
            )
        cursor.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"CREATE POLICY {TABLE}_tenant_isolation ON {TABLE} "
            f"USING (organization_id IS NULL OR organization_id = {TENANT}) "
            f"WITH CHECK (organization_id = {TENANT})"
        )
        # Logowanie i przełącznik organizacji dołączają rolę do członkostwa,
        # więc drzwi muszą widzieć jedno i drugie.
        cursor.execute(
            f"CREATE POLICY {TABLE}_pre_tenant ON {TABLE} "
            f"TO {schema_editor.quote_name(role)} "
            "USING (true) WITH CHECK (true)"
        )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS {TABLE}_pre_tenant ON {TABLE}")
        cursor.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
        cursor.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0026_rls_membership_audit"),
    ]

    operations = [migrations.RunPython(_enable, _disable)]
