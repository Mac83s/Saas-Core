from django.db import migrations

TABLE = "commerce_refund"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# A refund is the company's own and points at its own order: the policy of
# every commerce table and the guard of 0002, which already checks `order`.
ENABLE = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
CREATE TRIGGER {TABLE}_tenant_guard BEFORE INSERT OR UPDATE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION commerce_validate_tenant_relations();
"""

DISABLE = f"""
DROP TRIGGER IF EXISTS {TABLE}_tenant_guard ON {TABLE};
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("commerce", "0009_refunds")]

    operations = [migrations.RunSQL(ENABLE, reverse_sql=DISABLE)]
