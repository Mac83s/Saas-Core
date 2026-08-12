from django.db import migrations

TENANT_TABLES = (
    "booking_servicestaff",
    "booking_servicelocation",
    "booking_serviceresource",
    "booking_availabilityrule",
    "booking_timeoff",
    "booking_appointment",
    "booking_appointmentstatushistory",
    "booking_appointmentstaffallocation",
    "booking_appointmentresourceallocation",
    "booking_bookingmutation",
)

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION booking_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'appointment', 'customer', 'service', 'staff', 'location', 'resource'
    ] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'appointment' THEN 'booking_appointment'
                WHEN 'customer' THEN 'booking_customer'
                WHEN 'service' THEN 'booking_service'
                WHEN 'staff' THEN 'booking_staffmember'
                WHEN 'location' THEN 'booking_location'
                WHEN 'resource' THEN 'booking_resource'
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


def create_guards() -> str:
    triggers = "\n".join(
        f"CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION booking_validate_tenant_relations();"
        for table in TENANT_TABLES
    )
    return CREATE_FUNCTION + "\n" + triggers


def drop_guards() -> str:
    triggers = "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};" for table in TENANT_TABLES
    )
    return triggers + "\nDROP FUNCTION IF EXISTS booking_validate_tenant_relations();"


class Migration(migrations.Migration):
    dependencies = [("booking", "0002_rls_and_tenant_guards")]
    operations = [migrations.RunSQL(create_guards(), reverse_sql=drop_guards())]
