from django.db import migrations

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION billing_reject_plan_version_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Published plan versions are immutable';
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """
CREATE TRIGGER billing_plan_version_immutable
BEFORE UPDATE OR DELETE ON billing_planversion
FOR EACH ROW EXECUTE FUNCTION billing_reject_plan_version_mutation();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS billing_plan_version_immutable ON billing_planversion;
"""

DROP_FUNCTION = """
DROP FUNCTION IF EXISTS billing_reject_plan_version_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_seed_pilot_catalog")]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
