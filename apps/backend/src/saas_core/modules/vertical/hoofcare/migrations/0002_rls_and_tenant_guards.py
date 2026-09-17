from django.db import migrations

#: Both tables carry a foreign key to Organization, so ADR-039 makes forced RLS
#: the default and the descriptor declares neither as public nor platform.
TENANT_TABLES = (
    "hoofcare_farm",
    "hoofcare_animal",
)

#: Tables whose rows point at another tenant table. A foreign key says the row
#: exists; it does not say it belongs to the same organization.
RELATION_TABLES = ("hoofcare_animal",)

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION hoofcare_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['farm'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'farm' THEN 'hoofcare_farm'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'hoofcare relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def enable_rls() -> str:
    statements: list[str] = []
    for table in TENANT_TABLES:
        statements.extend([
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (organization_id = NULLIF("
            "current_setting('app.organization_id', true), '')::uuid) "
            "WITH CHECK (organization_id = NULLIF("
            "current_setting('app.organization_id', true), '')::uuid);",
        ])
    return "\n".join(statements)


def disable_rls() -> str:
    statements: list[str] = []
    for table in reversed(TENANT_TABLES):
        statements.extend([
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ])
    return "\n".join(statements)


def create_guards() -> str:
    triggers = "\n".join(
        f"CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION hoofcare_validate_tenant_relations();"
        for table in RELATION_TABLES
    )
    return f"{CREATE_FUNCTION}\n{triggers}"


def drop_guards() -> str:
    triggers = "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};" for table in RELATION_TABLES
    )
    return f"{triggers}\nDROP FUNCTION IF EXISTS hoofcare_validate_tenant_relations();"


class Migration(migrations.Migration):
    dependencies = [("hoofcare", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=enable_rls(), reverse_sql=disable_rls()),
        migrations.RunSQL(sql=create_guards(), reverse_sql=drop_guards()),
    ]
