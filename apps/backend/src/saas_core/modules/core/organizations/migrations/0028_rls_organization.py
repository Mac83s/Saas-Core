from typing import Any

from django.conf import settings
from django.db import migrations

# ADR-041, krok 3: sam rejestr. Tutaj tenantem jest klucz główny, nie kolumna
# obca — wiersz organizacji widzi ta organizacja i nikt poza nią. Renderer
# publiczny nie idzie drzwiami: host nazywa tenanta, więc `tenant_is_servable`
# ustawia go i czyta status od środka. Drzwi zostają dla pytań o cały rejestr,
# których nie da się zadać z wnętrza jednej firmy: workspace platformy,
# przełącznik organizacji, przemiatania w tle, purge kont testowych.
TABLE = "organizations_organization"
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
            f"USING (id = {TENANT}) WITH CHECK (id = {TENANT})"
        )
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
        ("organizations", "0027_rls_role"),
    ]

    operations = [migrations.RunPython(_enable, _disable)]
