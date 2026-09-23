from django.db import migrations

#: Nowe tabele magazynu v2 (ADR-055): każda ma klucz do Organization, więc
#: ADR-039 każe wymusić RLS — jak w 0002 dla pierwszych trzech.
NEW_TENANT_TABLES = (
    "inventory_inventorycategory",
    "inventory_stocklocation",
    "inventory_supplier",
    "inventory_stockdocument",
    "inventory_stockdocumentline",
    "inventory_documentsequence",
    "inventory_stockreservation",
)

#: Klucz obcy mówi, że wiersz istnieje, nie czyj jest. Strażnik sprawdza każdą
#: parę (kolumna, tabela) z argumentów wyzwalacza.
RELATIONS = {
    "inventory_inventoryitem": ("category_id", "inventory_inventorycategory"),
    "inventory_inventorybalance": (
        "item_id",
        "inventory_inventoryitem",
        "location_id",
        "inventory_stocklocation",
    ),
    "inventory_inventorymovement": (
        "item_id",
        "inventory_inventoryitem",
        "location_id",
        "inventory_stocklocation",
        "document_id",
        "inventory_stockdocument",
    ),
    "inventory_stockdocument": (
        "source_location_id",
        "inventory_stocklocation",
        "target_location_id",
        "inventory_stocklocation",
        "supplier_id",
        "inventory_supplier",
        "corrects_id",
        "inventory_stockdocument",
    ),
    "inventory_stockdocumentline": (
        "document_id",
        "inventory_stockdocument",
        "item_id",
        "inventory_inventoryitem",
    ),
    "inventory_stockreservation": (
        "item_id",
        "inventory_inventoryitem",
        "location_id",
        "inventory_stocklocation",
    ),
}
V1_RELATION_TABLES = ("inventory_inventorybalance", "inventory_inventorymovement")

GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION inventory_validate_tenant_relations_v2()
RETURNS trigger AS $$
DECLARE
    pair_index integer := 0;
    reference text;
    relation_ok boolean;
BEGIN
    WHILE pair_index < TG_NARGS LOOP
        reference := to_jsonb(NEW) ->> TG_ARGV[pair_index];
        IF reference IS NOT NULL THEN
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1::uuid AND organization_id = $2)',
                TG_ARGV[pair_index + 1]
            ) INTO relation_ok USING reference, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'inventory relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        pair_index := pair_index + 2;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _policy(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (organization_id = NULLIF("
        "current_setting('app.organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = NULLIF("
        "current_setting('app.organization_id', true), '')::uuid);",
    ]


def forward() -> str:
    statements = [statement for table in NEW_TENANT_TABLES for statement in _policy(table)]
    statements.extend(
        f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};" for table in V1_RELATION_TABLES
    )
    statements.append("DROP FUNCTION IF EXISTS inventory_validate_tenant_relations();")
    statements.append(GUARD_FUNCTION)
    for table, pairs in RELATIONS.items():
        arguments = ", ".join(f"'{value}'" for value in pairs)
        statements.append(
            f"CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION inventory_validate_tenant_relations_v2({arguments});"
        )
    return "\n".join(statements)


def backward() -> str:
    statements = [f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};" for table in RELATIONS]
    statements.append("DROP FUNCTION IF EXISTS inventory_validate_tenant_relations_v2();")
    for table in reversed(NEW_TENANT_TABLES):
        statements.extend([
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ])
    # Strażnik v1 wraca razem ze schematem v1 w cofnięciu 0006.
    from importlib import import_module

    v1 = import_module("saas_core.modules.shared.inventory.migrations.0002_rls_and_tenant_guards")
    statements.append(v1.create_guards())
    return "\n".join(statements)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0006_inventory_v2")]

    operations = [migrations.RunSQL(sql=forward(), reverse_sql=backward())]
