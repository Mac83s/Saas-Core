from django.db import migrations

#: Wszystkie trzy tabele mają klucz do Organization, więc ADR-039 każe wymusić
#: RLS. Magazyn jednej firmy nie ma prawa pojawić się w zapytaniu drugiej —
#: także wtedy, gdy zapytanie zapomni o filtrze.
TENANT_TABLES = (
    "inventory_inventoryitem",
    "inventory_inventorybalance",
    "inventory_inventorymovement",
)

#: Wiersze, które wskazują na pozycję katalogu: klucz obcy mówi, że pozycja
#: istnieje, nie czyja jest.
RELATION_TABLES = ("inventory_inventorybalance", "inventory_inventorymovement")

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION inventory_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    relation_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM inventory_inventoryitem
        WHERE id = NEW.item_id AND organization_id = NEW.organization_id
    ) INTO relation_ok;
    IF NOT relation_ok THEN
        RAISE EXCEPTION 'inventory relation belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
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
        "FOR EACH ROW EXECUTE FUNCTION inventory_validate_tenant_relations();"
        for table in RELATION_TABLES
    )
    return f"{CREATE_FUNCTION}\n{triggers}"


def drop_guards() -> str:
    triggers = "\n".join(
        f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};" for table in RELATION_TABLES
    )
    return f"{triggers}\nDROP FUNCTION IF EXISTS inventory_validate_tenant_relations();"


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=enable_rls(), reverse_sql=disable_rls()),
        migrations.RunSQL(sql=create_guards(), reverse_sql=drop_guards()),
    ]
