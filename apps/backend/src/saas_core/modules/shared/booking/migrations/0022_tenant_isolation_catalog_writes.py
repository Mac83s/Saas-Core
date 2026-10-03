from django.db import migrations

TABLE = "booking_catalogtranslationwrite"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

ENABLE = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
"""
DISABLE = f"""
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("booking", "0021_catalog_translation_source")]

    operations = [migrations.RunSQL(ENABLE, reverse_sql=DISABLE)]
