from django.db import migrations

TENANT_TABLES = (
    "notifications_apikey",
    "notifications_notificationmessage",
    "notifications_notificationattempt",
    "notifications_notificationpreference",
    "notifications_webhookendpoint",
    "notifications_webhookdelivery",
    "notifications_webhookattempt",
    "notifications_dataexport",
    "notifications_emailsuppression",
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


CREATE_GUARDS = """
CREATE OR REPLACE FUNCTION notifications_validate_tenant_relations()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'notifications_notificationattempt' AND NOT EXISTS (
        SELECT 1 FROM notifications_notificationmessage parent
        WHERE parent.id = (to_jsonb(NEW)->>'message_id')::uuid
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'notification attempt belongs to another organization' USING ERRCODE = '23514';
    ELSIF TG_TABLE_NAME = 'notifications_webhookdelivery' AND NOT EXISTS (
        SELECT 1 FROM notifications_webhookendpoint parent
        WHERE parent.id = (to_jsonb(NEW)->>'endpoint_id')::uuid
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'webhook delivery belongs to another organization' USING ERRCODE = '23514';
    ELSIF TG_TABLE_NAME = 'notifications_webhookattempt' AND NOT EXISTS (
        SELECT 1 FROM notifications_webhookdelivery parent
        WHERE parent.id = (to_jsonb(NEW)->>'delivery_id')::uuid
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'webhook attempt belongs to another organization' USING ERRCODE = '23514';
    ELSIF TG_TABLE_NAME = 'notifications_apikey'
      AND (to_jsonb(NEW)->>'rotated_from_id') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM notifications_apikey parent
        WHERE parent.id = (to_jsonb(NEW)->>'rotated_from_id')::uuid
          AND parent.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'rotated API key belongs to another organization' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER notifications_attempt_tenant_guard
BEFORE INSERT OR UPDATE ON notifications_notificationattempt
FOR EACH ROW EXECUTE FUNCTION notifications_validate_tenant_relations();
CREATE TRIGGER notifications_webhook_delivery_tenant_guard
BEFORE INSERT OR UPDATE ON notifications_webhookdelivery
FOR EACH ROW EXECUTE FUNCTION notifications_validate_tenant_relations();
CREATE TRIGGER notifications_webhook_attempt_tenant_guard
BEFORE INSERT OR UPDATE ON notifications_webhookattempt
FOR EACH ROW EXECUTE FUNCTION notifications_validate_tenant_relations();
CREATE TRIGGER notifications_api_key_tenant_guard
BEFORE INSERT OR UPDATE ON notifications_apikey
FOR EACH ROW EXECUTE FUNCTION notifications_validate_tenant_relations();
"""

DROP_GUARDS = """
DROP TRIGGER IF EXISTS notifications_attempt_tenant_guard ON notifications_notificationattempt;
DROP TRIGGER IF EXISTS notifications_webhook_delivery_tenant_guard ON notifications_webhookdelivery;
DROP TRIGGER IF EXISTS notifications_webhook_attempt_tenant_guard ON notifications_webhookattempt;
DROP TRIGGER IF EXISTS notifications_api_key_tenant_guard ON notifications_apikey;
DROP FUNCTION IF EXISTS notifications_validate_tenant_relations();
"""


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [
        migrations.RunSQL(_enable_rls(), reverse_sql=_disable_rls()),
        migrations.RunSQL(CREATE_GUARDS, reverse_sql=DROP_GUARDS),
    ]
