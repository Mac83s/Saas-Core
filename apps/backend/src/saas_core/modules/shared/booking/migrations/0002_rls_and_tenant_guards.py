from django.db import migrations

TENANT_TABLES = (
    "booking_location",
    "booking_staffmember",
    "booking_resource",
    "booking_service",
    "booking_servicestaff",
    "booking_servicelocation",
    "booking_serviceresource",
    "booking_availabilityrule",
    "booking_timeoff",
    "booking_customer",
    "booking_appointment",
    "booking_appointmentstatushistory",
    "booking_appointmentstaffallocation",
    "booking_appointmentresourceallocation",
    "booking_bookingmutation",
)


def enable_rls() -> str:
    statements: list[str] = []
    for table in TENANT_TABLES:
        statements.extend([
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (organization_id = NULLIF("
            "current_setting('app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF("
            "current_setting('app.organization_id', true), '')::uuid);",
        ])
    return "\n".join(statements)


def disable_rls() -> str:
    statements: list[str] = []
    for table in reversed(TENANT_TABLES):
        statements.extend([
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ])
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("booking", "0001_initial")]
    operations = [migrations.RunSQL(enable_rls(), reverse_sql=disable_rls())]
