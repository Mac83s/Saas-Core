from django.db import migrations


def _function(relations: str, extra_case: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION booking_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[{relations}] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'appointment' THEN 'booking_appointment'
                WHEN 'customer' THEN 'booking_customer'
                WHEN 'service' THEN 'booking_service'
                WHEN 'staff' THEN 'booking_staffmember'
                WHEN 'location' THEN 'booking_location'
                WHEN 'resource' THEN 'booking_resource'{extra_case}
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'booking relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


BASE = (
    "'appointment', 'customer', 'service', 'staff', 'location', 'resource', 'membership', "
    "'invitation'"
)
BASE_CASE = (
    "\n                WHEN 'membership' THEN 'organizations_membership'"
    "\n                WHEN 'invitation' THEN 'organizations_invitation'"
)
#: 0007's guard, now also checking a team member's team, the team and person a
#: customer chose, and the public profile a person is shown to customers with.
WITH_CREWS = _function(
    BASE + ", 'team', 'requested_team', 'requested_staff', 'profile'",
    BASE_CASE
    + "\n                WHEN 'team' THEN 'booking_staffteam'"
    + "\n                WHEN 'requested_team' THEN 'booking_staffteam'"
    + "\n                WHEN 'requested_staff' THEN 'booking_staffmember'"
    + "\n                WHEN 'profile' THEN 'profiles_publicprofile'",
)
PREVIOUS = _function(BASE, BASE_CASE)

TABLES = ("booking_staffteam", "booking_staffteammember")


def _rls() -> str:
    statements: list[str] = []
    for table in TABLES:
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


def _no_rls() -> str:
    statements: list[str] = []
    for table in reversed(TABLES):
        statements.extend([
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ])
    return "\n".join(statements)


MEMBER_GUARD = (
    "CREATE TRIGGER booking_staffteammember_tenant_guard BEFORE INSERT OR UPDATE "
    "ON booking_staffteammember FOR EACH ROW "
    "EXECUTE FUNCTION booking_validate_tenant_relations();"
)
DROP_MEMBER_GUARD = (
    "DROP TRIGGER IF EXISTS booking_staffteammember_tenant_guard ON booking_staffteammember;"
)


class Migration(migrations.Migration):
    dependencies = [("booking", "0009_crews_teams")]

    operations = [
        migrations.RunSQL(_rls(), reverse_sql=_no_rls()),
        migrations.RunSQL(WITH_CREWS, reverse_sql=PREVIOUS),
        migrations.RunSQL(MEMBER_GUARD, reverse_sql=DROP_MEMBER_GUARD),
    ]
