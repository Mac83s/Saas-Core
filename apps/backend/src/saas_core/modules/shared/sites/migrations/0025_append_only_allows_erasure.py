from django.db import migrations

# ADR-042: usunięcie tenanta jest usunięciem, więc append-only dostaje jedną
# nazwaną furtkę — zawężoną do organizacji wskazanej w `app.erasing_organization_id`.
# Bez tej zmiany organizacja, która kiedykolwiek zapisała wersję strony albo publikację, jest nieusuwalna.
ALLOW_ERASURE = """
CREATE OR REPLACE FUNCTION sites_reject_append_only_mutation()
RETURNS trigger AS $$
BEGIN
    -- ADR-042: the one exception to append-only. It opens for a DELETE of rows
    -- belonging to the organization named in `app.erasing_organization_id` and
    -- for nothing else. An identifier rather than a boolean on purpose: a flag
    -- set by mistake would open every tenant's history at once.
    IF TG_OP = 'DELETE'
       AND to_jsonb(OLD) ? 'organization_id'
       AND to_jsonb(OLD)->>'organization_id' IS NOT NULL
       AND (to_jsonb(OLD)->>'organization_id')::uuid
           = NULLIF(current_setting('app.erasing_organization_id', true), '')::uuid
    THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
"""

REFUSE_ALWAYS = """
CREATE OR REPLACE FUNCTION sites_reject_append_only_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("sites", "0024_private_tables_rls")]

    operations = [migrations.RunSQL(ALLOW_ERASURE, reverse_sql=REFUSE_ALWAYS)]
