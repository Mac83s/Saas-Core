from typing import Any

from django.db import migrations

TABLE = "image_generation_imagegenerationjob"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION image_generation_validate_tenant_relations()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM organizations_membership
        WHERE id = NEW.membership_id AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'image generation membership belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS image_generation_validate_tenant_relations();"


def _enable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"CREATE POLICY {TABLE}_tenant_isolation ON {TABLE} "
            f"USING (organization_id = {TENANT}) "
            f"WITH CHECK (organization_id = {TENANT})"
        )
        cursor.execute(
            f"CREATE TRIGGER {TABLE}_tenant_relations "
            f"BEFORE INSERT OR UPDATE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION image_generation_validate_tenant_relations()"
        )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_tenant_relations ON {TABLE}")
        cursor.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
        cursor.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("image_generation", "0001_initial")]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunPython(_enable, _disable),
    ]
