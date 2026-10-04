import uuid

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models

TABLE = "booking_presetinterest"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

ENABLE = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
"""
DISABLE = f"""
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    """A company's sign-up for a preset that is announced and not ready yet,
    with what it says it lacks (ADR-072 §10, slice 5g): a tenant's table under
    forced row-level security. Reversing drops the table with its rows."""

    dependencies = [
        ("booking", "0035_unit_exact_location"),
        ("organizations", "0059_inventory_audit_actions"),
    ]

    operations = [
        migrations.CreateModel(
            name="PresetInterest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("preset_id", models.CharField(max_length=80)),
                ("preset_version", models.PositiveIntegerField()),
                ("note", models.TextField(blank=True)),
                ("created_by", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
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
                "ordering": ("organization_id", "preset_id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "preset_id"), name="booking_preset_interest_uq"
                    )
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunSQL(ENABLE, DISABLE),
    ]
