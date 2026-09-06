from typing import Any

from django.db import migrations

TABLES = ("seo_sourcesitebinding", "seo_auditorder", "seo_auditcallbackreceipt")
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION seo_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['site', 'binding', 'order', 'membership'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'site' THEN 'sites_site'
                WHEN 'binding' THEN 'seo_sourcesitebinding'
                WHEN 'order' THEN 'seo_auditorder'
                WHEN 'membership' THEN 'organizations_membership'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'seo relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS seo_validate_tenant_relations();"


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
            cursor.execute(
                f"CREATE TRIGGER {table}_tenant_relations "
                f"BEFORE INSERT OR UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION seo_validate_tenant_relations()"
            )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DROP TRIGGER IF EXISTS {table}_tenant_relations ON {table}")
            cursor.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("seo", "0001_initial")]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunPython(_enable, _disable),
    ]
