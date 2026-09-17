from django.db import migrations

TABLE = "hoofcare_herdvisit"

#: The guard now has two relations to check. `appointment` points at a table
#: owned by `shared.booking`: a vertical may hang its detail row off a booking
#: appointment, and the row must belong to the same organization as the
#: appointment it describes — a foreign key alone would happily let a tenant
#: attach its visit to somebody else's calendar entry.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION hoofcare_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['farm', 'appointment'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'farm' THEN 'hoofcare_farm'
                WHEN 'appointment' THEN 'booking_appointment'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'hoofcare relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

PREVIOUS_FUNCTION = """
CREATE OR REPLACE FUNCTION hoofcare_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['farm'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'farm' THEN 'hoofcare_farm'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'hoofcare relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

ENABLE_RLS = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
    USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
CREATE TRIGGER {TABLE}_tenant_guard BEFORE INSERT OR UPDATE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION hoofcare_validate_tenant_relations();
"""

DISABLE_RLS = f"""
DROP TRIGGER IF EXISTS {TABLE}_tenant_guard ON {TABLE};
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("hoofcare", "0003_herdvisit"), ("booking", "0004_service_appointment_kind")]

    operations = [
        migrations.RunSQL(sql=CREATE_FUNCTION, reverse_sql=PREVIOUS_FUNCTION),
        migrations.RunSQL(sql=ENABLE_RLS, reverse_sql=DISABLE_RLS),
    ]
