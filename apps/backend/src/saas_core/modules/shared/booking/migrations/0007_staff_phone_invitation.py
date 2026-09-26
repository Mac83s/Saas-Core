import django.db.models.deletion
from django.db import migrations, models


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


BASE = "'appointment', 'customer', 'service', 'staff', 'location', 'resource', 'membership'"
MEMBERSHIP_CASE = "\n                WHEN 'membership' THEN 'organizations_membership'"
#: 0005's guard, now also checking that the invitation a person was added under
#: belongs to the organization whose calendar it is in.
WITH_INVITATION = _function(
    BASE + ", 'invitation'",
    MEMBERSHIP_CASE + "\n                WHEN 'invitation' THEN 'organizations_invitation'",
)
PREVIOUS = _function(BASE, MEMBERSHIP_CASE)


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0006_service_and_visit_materials"),
        ("organizations", "0048_audit_visit_materials"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffmember",
            name="phone",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="staffmember",
            name="invitation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="organizations.invitation",
            ),
        ),
        migrations.AddConstraint(
            model_name="staffmember",
            constraint=models.UniqueConstraint(
                condition=models.Q(("invitation__isnull", False)),
                fields=("organization", "invitation"),
                name="booking_staff_org_invitation_uq",
            ),
        ),
        migrations.RunSQL(WITH_INVITATION, reverse_sql=PREVIOUS),
    ]
