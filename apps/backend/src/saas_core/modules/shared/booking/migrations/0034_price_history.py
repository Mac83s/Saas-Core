import uuid

import django.db.models.deletion
import django.db.models.manager
import django.utils.timezone
from django.db import migrations, models

TABLE = "booking_pricehistoryentry"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"

# The record begins here: one line for every price that exists, so the price
# list of any later moment is read from the record alone. The rules' table
# forces row-level security; a role that is held to it would copy nothing and
# say nothing, so such a role is refused instead (migrations run as the
# database's owner role, which reads past policies).
BASELINE = f"""
DO $$
BEGIN
    IF row_security_active('booking_pricerule') THEN
        RAISE EXCEPTION
            'booking.0034: this role is held to row-level security on booking_pricerule; '
            'the baseline of the price history would miss every price. Run migrations as '
            'the role that owns the database.';
    END IF;
END $$;
INSERT INTO {TABLE} (
    id, organization_id, rule_id, change, state, amount_minor,
    previous_amount_minor, currency, actor_id, acting_via, recorded_at
)
SELECT
    gen_random_uuid(), rule.organization_id, rule.id, 'baseline', to_jsonb(rule),
    rule.amount_minor, NULL, rule.currency, NULL, '', now()
FROM booking_pricerule AS rule;
"""

# Nothing in the record is ever rewritten. Deleting is the tenant's erasure
# alone (`app.erasing_organization_id`, ADR-042).
ENABLE = f"""
CREATE OR REPLACE FUNCTION booking_append_only()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.organization_id = NULLIF(
        current_setting('app.erasing_organization_id', true), ''
    )::uuid THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION booking_append_only();
"""
DISABLE = f"""
DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE};
DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS booking_append_only();
"""


class Migration(migrations.Migration):
    """The record of prices (ADR-072 §6; ADR-073, slice 4i): an append-only
    line for every write of a price, and a baseline line for every price that
    exists when the record begins. Reversing drops the table with its lines."""

    dependencies = [
        ("booking", "0033_unit_content_and_offer_window"),
        ("organizations", "0059_inventory_audit_actions"),
    ]

    operations = [
        migrations.CreateModel(
            name="PriceHistoryEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("rule_id", models.UUIDField()),
                (
                    "change",
                    models.CharField(
                        choices=[
                            ("baseline", "Stan początkowy"),
                            ("created", "Dodana"),
                            ("updated", "Zmieniona"),
                            ("deleted", "Usunięta"),
                        ],
                        max_length=8,
                    ),
                ),
                ("state", models.JSONField()),
                ("amount_minor", models.PositiveIntegerField()),
                ("previous_amount_minor", models.PositiveIntegerField(blank=True, null=True)),
                ("currency", models.CharField(max_length=3)),
                ("actor_id", models.UUIDField(blank=True, null=True)),
                ("acting_via", models.CharField(blank=True, max_length=32)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                "ordering": ("organization_id", "-recorded_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["organization", "rule_id", "recorded_at"],
                        name="booking_pricehist_rule_idx",
                    ),
                    models.Index(
                        fields=["organization", "recorded_at"],
                        name="booking_pricehist_time_idx",
                    ),
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunSQL(BASELINE, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(ENABLE, reverse_sql=DISABLE),
    ]
