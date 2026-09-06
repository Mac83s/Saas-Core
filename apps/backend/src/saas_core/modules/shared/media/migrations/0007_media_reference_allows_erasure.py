from django.db import migrations

# ADR-042: usunięcie tenanta jest usunięciem, więc append-only dostaje jedną
# nazwaną furtkę — zawężoną do organizacji wskazanej w `app.erasing_organization_id`.
# Bez tej zmiany organizacja, która kiedykolwiek załączyła plik, jest nieusuwalna.
ALLOW_ERASURE = """
CREATE OR REPLACE FUNCTION media_protect_reference()
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
    RAISE EXCEPTION 'media reference is append-only'
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
"""

REFUSE_ALWAYS = """
CREATE OR REPLACE FUNCTION media_protect_reference()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'media reference is append-only'
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("media", "0006_alter_mediareference_owner_type")]

    operations = [migrations.RunSQL(ALLOW_ERASURE, reverse_sql=REFUSE_ALWAYS)]
