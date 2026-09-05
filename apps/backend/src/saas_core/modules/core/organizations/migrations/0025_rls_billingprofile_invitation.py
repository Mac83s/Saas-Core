from typing import Any

from django.conf import settings
from django.db import migrations

# ADR-041, krok 3: dwie tabele niosące dane osobowe idą pierwsze. Profil
# billingowy trzyma adres i numer VAT, zaproszenie — adres e-mail osoby, która
# nie jest jeszcze członkiem. Tam koszt wycieku jest największy, a odczyty
# sprzed poznania tenanta są pojedyncze i już przeniesione za drzwi.
TABLES = ("organizations_billingprofile", "organizations_invitation")


def _identity_role() -> str:
    alias = getattr(settings, "PRE_TENANT_DATABASE_ALIAS", "pre_tenant")
    return str(settings.DATABASES[alias]["USER"])


def _enable(apps: Any, schema_editor: Any) -> None:
    role = _identity_role()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone() is None:
            # Failing here is the point. A deployment without the door is a
            # deployment where the Stripe processor cannot find its tenant and
            # nobody can accept an invitation — better to stop now, with the
            # name of the missing role, than to find out at the first webhook.
            raise RuntimeError(
                f"Rola {role!r} nie istnieje; uruchom bootstrap ról PostgreSQL "
                "przed migracją (ADR-041)."
            )
        for table in TABLES:
            cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')::uuid) "
                "WITH CHECK (organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')::uuid)"
            )
            # The door: one named role, one table at a time, nothing implicit.
            cursor.execute(
                f"CREATE POLICY {table}_pre_tenant ON {table} "
                f"TO {schema_editor.quote_name(role)} "
                "USING (true) WITH CHECK (true)"
            )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DROP POLICY IF EXISTS {table}_pre_tenant ON {table}")
            cursor.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0024_alter_organizationauditentry_action"),
    ]

    operations = [migrations.RunPython(_enable, _disable)]
