from django.db import migrations

# ADR-039 closed the last gap in the default isolation regime. shared.billing
# predates the RLS list of ADR-022 and was the only module whose tenant tables
# were guarded by application code alone — the subscription a company pays us
# with, its checkout, trial, invoices, entitlements and quota counters.
#
# The migration lands only now because the sweeps had to be rewritten first:
# lifecycle, reconciliation, override expiry and quota release used to ask for
# every organization's rows in one query, which under forced RLS answers with
# nothing rather than failing. They walk organizations now, and the Stripe
# processor resolves the tenant from BillingProfile before touching a tenant
# row.
TENANT_TABLES = (
    "billing_entitlementgrant",
    "billing_entitlementsnapshot",
    "billing_billingsubscription",
    "billing_billingcheckout",
    "billing_billingtrialactivation",
    "billing_billinglifecycleaction",
    "billing_billingnotice",
    "billing_billingreconciliation",
    "billing_billinginvoicedocument",
    "billing_quotausage",
    "billing_quotareservation",
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


# A foreign key is checked by the system regardless of row-level security, so
# a child row could still name a parent in another organization while claiming
# to belong to this one. These are the parent links that stay inside a tenant.
CREATE_GUARDS = """
CREATE OR REPLACE FUNCTION billing_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    parent_table text;
    parent_column text;
    parent_id uuid;
    found boolean;
BEGIN
    FOR parent_table, parent_column IN
        SELECT * FROM (VALUES
            ('billing_billingcheckout', 'checkout_id'),
            ('billing_billingsubscription', 'subscription_id'),
            ('billing_billinglifecycleaction', 'lifecycle_action_id'),
            ('billing_quotausage', 'usage_id')
        ) AS links(t, c)
    LOOP
        parent_id := (to_jsonb(NEW)->>parent_column)::uuid;
        CONTINUE WHEN parent_id IS NULL;
        EXECUTE format(
            'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
            parent_table
        ) INTO found USING parent_id, NEW.organization_id;
        IF NOT found THEN
            RAISE EXCEPTION 'billing row references % of another organization', parent_table
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER billing_trial_activation_tenant_guard
BEFORE INSERT OR UPDATE ON billing_billingtrialactivation
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
CREATE TRIGGER billing_lifecycle_action_tenant_guard
BEFORE INSERT OR UPDATE ON billing_billinglifecycleaction
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
CREATE TRIGGER billing_notice_tenant_guard
BEFORE INSERT OR UPDATE ON billing_billingnotice
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
CREATE TRIGGER billing_reconciliation_tenant_guard
BEFORE INSERT OR UPDATE ON billing_billingreconciliation
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
CREATE TRIGGER billing_invoice_document_tenant_guard
BEFORE INSERT OR UPDATE ON billing_billinginvoicedocument
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
CREATE TRIGGER billing_quota_reservation_tenant_guard
BEFORE INSERT OR UPDATE ON billing_quotareservation
FOR EACH ROW EXECUTE FUNCTION billing_validate_tenant_relations();
"""

DROP_GUARDS = """
DROP TRIGGER IF EXISTS billing_quota_reservation_tenant_guard ON billing_quotareservation;
DROP TRIGGER IF EXISTS billing_invoice_document_tenant_guard ON billing_billinginvoicedocument;
DROP TRIGGER IF EXISTS billing_reconciliation_tenant_guard ON billing_billingreconciliation;
DROP TRIGGER IF EXISTS billing_notice_tenant_guard ON billing_billingnotice;
DROP TRIGGER IF EXISTS billing_lifecycle_action_tenant_guard ON billing_billinglifecycleaction;
DROP TRIGGER IF EXISTS billing_trial_activation_tenant_guard ON billing_billingtrialactivation;
DROP FUNCTION IF EXISTS billing_validate_tenant_relations();
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0012_seed_profile_plan")]

    operations = [
        migrations.RunSQL(_enable_rls(), reverse_sql=_disable_rls()),
        migrations.RunSQL(CREATE_GUARDS, reverse_sql=DROP_GUARDS),
    ]
