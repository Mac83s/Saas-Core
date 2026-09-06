from typing import Any

from django.db import migrations

# ADR-039: private by default. Nothing reads a profile before the tenant is
# known — the panel reads it inside a session, and the public renderer will read
# a publication snapshot rather than this table — so there is no door policy
# here, and there should not be one.
TABLES = ("profiles_publicprofile", "profiles_publicprofiletranslation")
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# A photo, a membership and a parent profile all have to belong to the same
# organization as the row pointing at them. The application checks it for a good
# error message; this is what makes it true.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION profiles_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['photo', 'membership', 'profile'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'photo' THEN 'media_mediaasset'
                WHEN 'membership' THEN 'organizations_membership'
                WHEN 'profile' THEN 'profiles_publicprofile'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'profile relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS profiles_validate_tenant_relations();"


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
    dependencies = [("profiles", "0001_initial"), ("media", "0001_initial")]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunPython(_enable, _disable),
    ]
