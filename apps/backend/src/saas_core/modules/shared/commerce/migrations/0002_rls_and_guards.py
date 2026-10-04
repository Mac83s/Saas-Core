from django.db import migrations

TABLES = ("commerce_order", "commerce_orderline", "commerce_ordercounter")
#: A placed line is never rewritten: a correction is the next revision's line.
APPEND_ONLY_TABLES = ("commerce_orderline",)
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# What a row points at is the same company's: a line's order, an order's
# customer.
GUARD = """
CREATE OR REPLACE FUNCTION commerce_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['order', 'customer'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'order' THEN 'commerce_order'
                WHEN 'customer' THEN 'booking_customer'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'commerce relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Deleting is the tenant's erasure alone (`app.erasing_organization_id`,
# ADR-042); nothing updates.
APPEND_ONLY = """
CREATE OR REPLACE FUNCTION commerce_append_only()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.organization_id = NULLIF(
        current_setting('app.erasing_organization_id', true), ''
    )::uuid THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
"""


def enable() -> str:
    statements = [GUARD, APPEND_ONLY]
    for table in TABLES:
        statements.append(
            f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {table}_tenant_isolation ON {table}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION commerce_validate_tenant_relations();
"""
        )
    for table in APPEND_ONLY_TABLES:
        statements.append(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION commerce_append_only();"
        )
    return "\n".join(statements)


def disable() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};" for table in APPEND_ONLY_TABLES
    ]
    for table in TABLES:
        statements.append(
            f"""
DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
        )
    statements.append("DROP FUNCTION IF EXISTS commerce_append_only();")
    statements.append("DROP FUNCTION IF EXISTS commerce_validate_tenant_relations();")
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("commerce", "0001_orders")]

    operations = [migrations.RunSQL(enable(), reverse_sql=disable())]
