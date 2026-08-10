from django.db import migrations

CREATE_IMMUTABLE_ROLE_TRIGGER = """
CREATE OR REPLACE FUNCTION organizations_prevent_system_role_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.scope = 'system' AND OLD.is_immutable THEN
        RAISE EXCEPTION 'system roles are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_system_role_immutable
BEFORE UPDATE OR DELETE ON organizations_role
FOR EACH ROW EXECUTE FUNCTION organizations_prevent_system_role_mutation();
"""

DROP_IMMUTABLE_ROLE_TRIGGER = """
DROP TRIGGER IF EXISTS organizations_system_role_immutable ON organizations_role;
DROP FUNCTION IF EXISTS organizations_prevent_system_role_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0005_protect_audit_entries"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_IMMUTABLE_ROLE_TRIGGER,
            reverse_sql=DROP_IMMUTABLE_ROLE_TRIGGER,
        ),
    ]
