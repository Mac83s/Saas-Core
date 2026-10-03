from typing import Any

from django.db import migrations

TABLES = ("profiles_profiletranslationwrite",)
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"


def _enable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                f"USING (organization_id = {TENANT}) "
                f"WITH CHECK (organization_id = {TENANT})"
            )
            # The card a receipt names belongs to the same organization (0002).
            cursor.execute(
                f"CREATE TRIGGER {table}_tenant_relations "
                f"BEFORE INSERT OR UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION profiles_validate_tenant_relations()"
            )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_tenant_relations ON {table}")
            cursor.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("profiles", "0007_translation_source")]

    operations = [migrations.RunPython(_enable, _disable)]
