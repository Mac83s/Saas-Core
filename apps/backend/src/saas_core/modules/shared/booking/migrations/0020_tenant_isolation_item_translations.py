from django.db import migrations

TABLES = (
    "booking_servicetranslation",
    "booking_locationtranslation",
    "booking_resourcetranslation",
    "booking_resourcegrouptranslation",
    "booking_staffteamtranslation",
)
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# The item a translation names (service, location, resource, group, team) is
# the organization's own: the guard of 0018 already knows each of them.
ENABLE = "\n".join(
    f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {table}_tenant_isolation ON {table}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION booking_validate_tenant_relations();
"""
    for table in TABLES
)
DISABLE = "\n".join(
    f"""
DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):
    dependencies = [("booking", "0019_item_translations")]

    operations = [migrations.RunSQL(ENABLE, reverse_sql=DISABLE)]
