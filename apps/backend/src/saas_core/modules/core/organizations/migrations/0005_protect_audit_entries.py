from django.db import migrations

CREATE_APPEND_ONLY_TRIGGER = """
CREATE OR REPLACE FUNCTION organizations_prevent_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'organization audit entries are append-only'
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_audit_append_only
BEFORE UPDATE OR DELETE ON organizations_organizationauditentry
FOR EACH ROW EXECUTE FUNCTION organizations_prevent_audit_mutation();
"""

DROP_APPEND_ONLY_TRIGGER = """
DROP TRIGGER IF EXISTS organizations_audit_append_only
ON organizations_organizationauditentry;
DROP FUNCTION IF EXISTS organizations_prevent_audit_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0004_invitation_organizationauditentry"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_APPEND_ONLY_TRIGGER,
            reverse_sql=DROP_APPEND_ONLY_TRIGGER,
        ),
    ]
