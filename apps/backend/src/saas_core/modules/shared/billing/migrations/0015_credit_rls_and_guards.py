from django.db import migrations

# Credit tables join the default isolation regime of ADR-039 the moment they
# exist, rather than acquiring policies later the way the rest of billing had
# to. The ledger is additionally append-only: a balance that can be corrected
# by editing history is not a balance anybody can trust, so a mistake is fixed
# with a compensating entry.
TENANT_TABLES = (
    "billing_creditbalance",
    "billing_creditpurchase",
    "billing_creditreservation",
    "billing_creditledgerentry",
)


def _enable_rls() -> str:
    statements = []
    for table in TENANT_TABLES:
        policy = f"{table}_tenant_isolation"
        statements.extend([
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"CREATE POLICY {policy} ON {table} "
            "USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);",
        ])
    return "\n".join(statements)


def _disable_rls() -> str:
    statements = []
    for table in reversed(TENANT_TABLES):
        policy = f"{table}_tenant_isolation"
        statements.extend([
            f"DROP POLICY IF EXISTS {policy} ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ])
    return "\n".join(statements)


# Only the ledger links to other tenant rows; a purchase points at a catalog
# pack and a reservation at nothing, so they need no relation guard.
CREATE_GUARDS = """
CREATE OR REPLACE FUNCTION billing_validate_credit_ledger_relations()
RETURNS trigger AS $$
BEGIN
    IF NEW.reservation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM billing_creditreservation parent
        WHERE parent.id = NEW.reservation_id
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'credit ledger entry references a reservation of another organization'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.purchase_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM billing_creditpurchase parent
        WHERE parent.id = NEW.purchase_id
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'credit ledger entry references a purchase of another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER billing_credit_ledger_tenant_guard
BEFORE INSERT OR UPDATE ON billing_creditledgerentry
FOR EACH ROW EXECUTE FUNCTION billing_validate_credit_ledger_relations();

CREATE OR REPLACE FUNCTION billing_reject_append_only_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER billing_credit_ledger_append_only
BEFORE UPDATE OR DELETE ON billing_creditledgerentry
FOR EACH ROW EXECUTE FUNCTION billing_reject_append_only_mutation();
"""

DROP_GUARDS = """
DROP TRIGGER IF EXISTS billing_credit_ledger_append_only ON billing_creditledgerentry;
DROP FUNCTION IF EXISTS billing_reject_append_only_mutation();
DROP TRIGGER IF EXISTS billing_credit_ledger_tenant_guard ON billing_creditledgerentry;
DROP FUNCTION IF EXISTS billing_validate_credit_ledger_relations();
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0014_credits")]

    operations = [
        migrations.RunSQL(_enable_rls(), reverse_sql=_disable_rls()),
        migrations.RunSQL(CREATE_GUARDS, reverse_sql=DROP_GUARDS),
    ]
