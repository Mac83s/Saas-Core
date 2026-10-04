from django.db import migrations

TABLES = ("commerce_payment", "commerce_ledgerentry")
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# What a row points at is the same company's: a line's and a payment's order,
# an order's customer, a ledger entry's order and payment.
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
    FOREACH relation_name IN ARRAY ARRAY[{relations}] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'order' THEN 'commerce_order'
                WHEN 'payment' THEN 'commerce_payment'
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


def enable() -> str:
    statements = [GUARD.format(relations="'order', 'payment', 'customer'")]
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
    # The ledger is the money's history: nothing in it is ever rewritten
    # (`commerce_append_only` from 0002; deleting is the tenant's erasure alone).
    statements.append(
        "CREATE TRIGGER commerce_ledgerentry_append_only BEFORE UPDATE OR DELETE "
        "ON commerce_ledgerentry FOR EACH ROW EXECUTE FUNCTION commerce_append_only();"
    )
    return "\n".join(statements)


def disable() -> str:
    statements = [
        "DROP TRIGGER IF EXISTS commerce_ledgerentry_append_only ON commerce_ledgerentry;"
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
    # The guard as 0002 left it, without the payment.
    statements.append(GUARD.format(relations="'order', 'customer'"))
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("commerce", "0005_payments_and_ledger")]

    operations = [migrations.RunSQL(enable(), reverse_sql=disable())]
