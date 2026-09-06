from typing import Any

from django.db import migrations

TABLES = ("seo_gscworkspacestate", "seo_gscoauthattempt", "seo_gscgrantintent", "seo_gscsyncintent")
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

CREATE = """
CREATE FUNCTION seo_gsc_guard() RETURNS trigger AS $$
DECLARE
    mutable_fields text[];
    payload jsonb := to_jsonb(NEW);
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.organization_id = NULLIF(current_setting('app.erasing_organization_id', true), '')::uuid THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'GSC receipt requires tenant erasure' USING ERRCODE = '55000';
    END IF;
    IF payload ? 'binding_id' AND NOT EXISTS (
        SELECT 1 FROM seo_sourcesitebinding WHERE id=(payload->>'binding_id')::uuid
        AND organization_id=NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'GSC binding tenant mismatch' USING ERRCODE = '23514';
    END IF;
    IF payload ? 'grant_id' AND NOT EXISTS (
        SELECT 1 FROM seo_gscgrantintent WHERE id=(payload->>'grant_id')::uuid
        AND organization_id=NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'GSC grant tenant mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        mutable_fields := CASE TG_TABLE_NAME
            WHEN 'seo_gscworkspacestate' THEN ARRAY['cleanup_required','updated_at']
            WHEN 'seo_gscoauthattempt' THEN ARRAY['consumed_at']
            ELSE ARRAY['remote_id'] END;
        IF (to_jsonb(OLD) - mutable_fields) IS DISTINCT FROM (to_jsonb(NEW) - mutable_fields) THEN
            RAISE EXCEPTION 'GSC intent immutable' USING ERRCODE = '55000';
        END IF;
        IF to_jsonb(OLD)->>'remote_id' IS NOT NULL AND
           to_jsonb(OLD)->'remote_id' IS DISTINCT FROM to_jsonb(NEW)->'remote_id' THEN
            RAISE EXCEPTION 'GSC remote identity immutable' USING ERRCODE = '55000';
        END IF;
        IF to_jsonb(OLD)->>'consumed_at' IS NOT NULL AND
           to_jsonb(OLD)->'consumed_at' IS DISTINCT FROM to_jsonb(NEW)->'consumed_at' THEN
            RAISE EXCEPTION 'GSC state already consumed' USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def enable(apps: Any, schema_editor: Any) -> None:
    for table in TABLES:
        schema_editor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        schema_editor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        schema_editor.execute(
            f"CREATE POLICY {table}_tenant ON {table} USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})"
        )
        schema_editor.execute(
            f"CREATE TRIGGER {table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION seo_gsc_guard()"
        )


def disable(apps: Any, schema_editor: Any) -> None:
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER {table}_guard ON {table}")
        schema_editor.execute(f"DROP POLICY {table}_tenant ON {table}")
        schema_editor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        schema_editor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def seed(apps: Any, schema_editor: Any) -> None:
    apps.get_model("billing", "Feature").objects.get_or_create(
        key="seo.gsc.enabled",
        defaults={"name": "Google Search Console", "module": "shared.seo", "is_active": True},
    )


def unseed(apps: Any, schema_editor: Any) -> None:
    apps.get_model("billing", "Feature").objects.filter(key="seo.gsc.enabled").delete()


class Migration(migrations.Migration):
    dependencies = [("seo", "0005_delegated_gsc")]
    operations = [
        migrations.RunSQL(CREATE, "DROP FUNCTION seo_gsc_guard();"),
        migrations.RunPython(enable, disable),
        migrations.RunPython(seed, unseed),
    ]
