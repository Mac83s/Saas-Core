import uuid

import django.db.models.deletion
from django.db import migrations, models

# What the assistant ran under a person's consent (ADR-076 §3): written and
# read only inside the tenant whose membership consented, so forced row-level
# security like every private tenant table.
FORWARD_SQL = """
ALTER TABLE organizations_commandreceipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations_commandreceipt FORCE ROW LEVEL SECURITY;
CREATE POLICY organizations_commandreceipt_tenant_isolation ON organizations_commandreceipt
USING (organization_id = nullif(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = nullif(current_setting('app.organization_id', true), '')::uuid);
"""

REVERSE_SQL = """
DROP POLICY organizations_commandreceipt_tenant_isolation ON organizations_commandreceipt;
ALTER TABLE organizations_commandreceipt NO FORCE ROW LEVEL SECURITY;
ALTER TABLE organizations_commandreceipt DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0053_organization_public_locales"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommandReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("membership_id", models.UUIDField()),
                ("command", models.CharField(max_length=120)),
                ("idempotency_key", models.CharField(max_length=36)),
                ("request_hash", models.CharField(max_length=64)),
                ("acting_ref", models.CharField(max_length=64)),
                ("result", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "membership_id", "command", "idempotency_key"),
                        name="organizations_command_receipt_uq",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
