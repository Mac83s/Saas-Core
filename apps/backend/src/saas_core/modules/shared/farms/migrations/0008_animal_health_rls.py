from django.db import migrations

#: The history of an animal is tenant data like the animal itself (ADR-039), and
#: a company publishes into it through a share — which is exactly why the table
#: needs the policy rather than trusting the caller's context.
TABLE = "farms_animalhealthentry"

#: Its animal must belong to the same organization: the foreign key says the row
#: exists, not whose it is. The guard function from 0002 walks a fixed list of
#: relation names, so this table gets one of its own.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION farms_validate_health_relations()
RETURNS trigger AS $$
DECLARE
    relation_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM farms_animal
        WHERE id = NEW.animal_id AND organization_id = NEW.organization_id
    ) INTO relation_ok;
    IF NOT relation_ok THEN
        RAISE EXCEPTION 'farms relation belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

ENABLE = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""

DISABLE = f"""
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""

CREATE_GUARD = f"""
{CREATE_FUNCTION}
CREATE TRIGGER {TABLE}_tenant_guard BEFORE INSERT OR UPDATE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION farms_validate_health_relations();
"""

DROP_GUARD = f"""
DROP TRIGGER IF EXISTS {TABLE}_tenant_guard ON {TABLE};
DROP FUNCTION IF EXISTS farms_validate_health_relations();
"""


class Migration(migrations.Migration):
    dependencies = [("farms", "0007_animal_health")]

    operations = [
        migrations.RunSQL(sql=ENABLE, reverse_sql=DISABLE),
        migrations.RunSQL(sql=CREATE_GUARD, reverse_sql=DROP_GUARD),
    ]
