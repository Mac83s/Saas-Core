from typing import Any

from django.db import migrations

TABLES = (
    "translation_translationjob",
    "translation_translationjobpart",
    "translation_translationjobitem",
)
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# A foreign key does not see row-level security: a row could point at another
# tenant's job or membership. These refuse it (ADR-039).
FUNCTIONS = """
CREATE OR REPLACE FUNCTION translation_job_validate_tenant_relations()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM organizations_membership
        WHERE id = NEW.membership_id AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'translation job membership belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION translation_job_child_validate_tenant_relations()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM translation_translationjob
        WHERE id = NEW.job_id AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'translation job belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS translation_job_validate_tenant_relations();
DROP FUNCTION IF EXISTS translation_job_child_validate_tenant_relations();
"""
TRIGGERS = (
    ("translation_translationjob", "translation_job_validate_tenant_relations"),
    ("translation_translationjobpart", "translation_job_child_validate_tenant_relations"),
    ("translation_translationjobitem", "translation_job_child_validate_tenant_relations"),
)


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
    dependencies = [("translation", "0007_jobs")]

    operations = [
        migrations.RunSQL(FUNCTIONS, reverse_sql=DROP_FUNCTIONS),
        migrations.RunPython(_enable, _disable),
    ]
