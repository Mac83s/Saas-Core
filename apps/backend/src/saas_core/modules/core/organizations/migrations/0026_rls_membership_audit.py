from typing import Any

from django.conf import settings
from django.db import migrations

# ADR-041, krok 3: kto należy do której firmy i co się w niej wydarzyło.
# Członkostwo dostaje drzwi, bo logowanie, przełącznik organizacji i operatorskie
# przemiatanie pytają o nie, zanim tenant istnieje. Wpisy audytowe drzwi nie
# dostają: każda ścieżka, która je pisze, ustawia tenanta wcześniej (tworzenie
# organizacji, workspace platformy, przyjęcie zaproszenia), więc drugie wejście
# byłoby dziurą bez powodu.
TENANT_TABLES = ("organizations_membership", "organizations_organizationauditentry")
DOOR_TABLES = ("organizations_membership",)


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
        for table in TENANT_TABLES:
            cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')::uuid)"
            )
        for table in DOOR_TABLES:
            cursor.execute(
                f"CREATE POLICY {table}_pre_tenant ON {table} "
                f"TO {schema_editor.quote_name(role)} "
                "USING (true) WITH CHECK (true)"
            )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(f"DROP POLICY IF EXISTS {table}_pre_tenant ON {table}")
            cursor.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0025_rls_billingprofile_invitation"),
    ]

    operations = [migrations.RunPython(_enable, _disable)]
