import importlib
import uuid

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models

_UNITS = importlib.import_module(
    "saas_core.modules.shared.booking.migrations.0016_units_groups_and_blocks"
)
_EXTRAS = importlib.import_module("saas_core.modules.shared.booking.migrations.0027_extras")
#: 0027's guard, now also checking the form field a translation names.
WITH_FIELDS = _UNITS._function(
    _UNITS.CREWS + ", 'group', 'time_off', 'requested_group', 'category', 'extra', 'field'",
    _UNITS.CREWS_CASE
    + "\n                WHEN 'group' THEN 'booking_resourcegroup'"
    + "\n                WHEN 'time_off' THEN 'booking_timeoff'"
    + "\n                WHEN 'requested_group' THEN 'booking_resourcegroup'"
    + "\n                WHEN 'category' THEN 'booking_participantcategory'"
    + "\n                WHEN 'extra' THEN 'booking_extra'"
    + "\n                WHEN 'field' THEN 'booking_formfield'",
)

#: A form field names its offer, its translation the field: each the organization's own.
TABLES = ("booking_formfield", "booking_formfieldtranslation")
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"
ENABLE = "\n".join(
    f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {table}_tenant_isolation ON {table}
USING (organization_id = {TENANT})
WITH CHECK (organization_id = {TENANT});
CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION booking_validate_tenant_relations();
"""
    for table in TABLES
)
DISABLE = "\n".join(
    f"""
DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
    for table in reversed(TABLES)
)


class Migration(migrations.Migration):
    """An offer's own form fields and what a customer answered to them
    (ADR-072 §8, slice 5j): two tenant tables under forced row-level security
    with the relation guard, and the answers frozen on the booking. Reversing
    drops the tables and the column with what they hold."""

    dependencies = [
        ('booking', '0037_appointment_channel'),
        ('organizations', '0059_inventory_audit_actions'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='form_answers',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name='FormField',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid7, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=160)),
                ('kind', models.CharField(choices=[('text', 'Tekst'), ('number', 'Liczba'), ('choice', 'Wybór z listy'), ('date', 'Data'), ('consent', 'Zgoda')], default='text', max_length=16)),
                ('options', models.TextField(blank=True)),
                ('mandatory', models.BooleanField(default=False)),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('active', models.BooleanField(default=True)),
                ('version', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='form_fields', to='booking.service')),
            ],
            options={
                'ordering': ('organization_id', 'service_id', 'position', 'name', 'id'),
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='FormFieldTranslation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid7, editable=False, primary_key=True, serialize=False)),
                ('locale', models.CharField(max_length=10)),
                ('texts', models.JSONField(blank=True, default=dict)),
                ('provenance', models.JSONField(blank=True, default=dict)),
                ('version', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('field', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='translations', to='booking.formfield')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
            ],
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddConstraint(
            model_name='formfield',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'choice'), models.Q(('options', ''), _negated=True)), models.Q(models.Q(('kind', 'choice'), _negated=True), ('options', '')), _connector='OR'), name='booking_formfield_options_ck'),
        ),
        migrations.AddConstraint(
            model_name='formfieldtranslation',
            constraint=models.UniqueConstraint(fields=('organization', 'field', 'locale'), name='booking_formfield_tr_uq'),
        ),
        migrations.AddConstraint(
            model_name='formfieldtranslation',
            constraint=models.CheckConstraint(condition=models.Q(('locale__regex', '^[a-z]{2}$')), name='booking_formfield_tr_locale_ck'),
        ),
        migrations.RunSQL(WITH_FIELDS, reverse_sql=_EXTRAS.WITH_EXTRAS),
        migrations.RunSQL(ENABLE, reverse_sql=DISABLE),
    ]
