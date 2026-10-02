from typing import Any

from django.db import migrations

TABLES = ("translation_translationreviewitem",)
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# A foreign key does not see row-level security: a row could point at another
# tenant's job. The trigger refuses it (ADR-039).
TRIGGERS = (
    # The job a review item names belongs to the same organization.
    ("translation_translationreviewitem", "translation_review_validate_tenant_relations"),
)
FUNCTIONS = """
CREATE OR REPLACE FUNCTION translation_review_validate_tenant_relations()
RETURNS trigger AS $$
BEGIN
    IF NEW.job_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM translation_translationjob
        WHERE id = NEW.job_id AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'translation review job belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
DROP_FUNCTIONS = "DROP FUNCTION IF EXISTS translation_review_validate_tenant_relations();"


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
        for table, function in TRIGGERS:
            cursor.execute(
                f"CREATE TRIGGER {table}_tenant_relations BEFORE INSERT OR UPDATE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {function}()"
            )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table, _function in TRIGGERS:
            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_tenant_relations ON {table}")
        for table in TABLES:
            cursor.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("translation", "0009_review")]

    operations = [
        migrations.RunSQL(FUNCTIONS, reverse_sql=DROP_FUNCTIONS),
        migrations.RunPython(_enable, _disable),
    ]
