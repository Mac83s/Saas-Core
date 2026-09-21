from django.db import migrations

#: A company's visits land in the farmer's tenant through the registry door, so
#: this table is written by somebody who is not its owner. That is exactly the
#: case the policy exists for: the door sets the tenant, the policy checks it
#: (ADR-039, ADR-052).
TABLE = "farms_farmvisitentry"

#: Its farm must belong to the same organization. The foreign key says the row
#: exists, not whose it is, and here the writer is a guest.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION farms_validate_visit_relations()
RETURNS trigger AS $$
DECLARE
    relation_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM farms_farm
        WHERE id = NEW.farm_id AND organization_id = NEW.organization_id
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
FOR EACH ROW EXECUTE FUNCTION farms_validate_visit_relations();
"""

DROP_GUARD = f"""
DROP TRIGGER IF EXISTS {TABLE}_tenant_guard ON {TABLE};
DROP FUNCTION IF EXISTS farms_validate_visit_relations();
"""


class Migration(migrations.Migration):
    dependencies = [("farms", "0011_farm_visits")]

    operations = [
        migrations.RunSQL(sql=ENABLE, reverse_sql=DISABLE),
        migrations.RunSQL(sql=CREATE_GUARD, reverse_sql=DROP_GUARD),
    ]
