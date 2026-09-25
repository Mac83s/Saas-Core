from django.db import migrations

#: Partie (0009): nowa tabela firmy i nowe klucze w wierszu dokumentu i ruchu.
#: ADR-039 każe wymusić RLS, a strażnik z 0007 sprawdza, że partia należy do
#: tej samej firmy co wiersz, który na nią wskazuje.
LOT_TABLE = "inventory_inventorylot"

BEFORE = {
    "inventory_inventorymovement": (
        "item_id",
        "inventory_inventoryitem",
        "location_id",
        "inventory_stocklocation",
        "document_id",
        "inventory_stockdocument",
    ),
    "inventory_stockdocumentline": (
        "document_id",
        "inventory_stockdocument",
        "item_id",
        "inventory_inventoryitem",
    ),
}
AFTER = {
    LOT_TABLE: ("item_id", "inventory_inventoryitem"),
    "inventory_inventorymovement": (
        *BEFORE["inventory_inventorymovement"],
        "lot_id",
        LOT_TABLE,
    ),
    "inventory_stockdocumentline": (
        *BEFORE["inventory_stockdocumentline"],
        "lot_id",
        LOT_TABLE,
    ),
}


def _guards(relations: dict[str, tuple[str, ...]]) -> list[str]:
    statements = []
    for table, pairs in relations.items():
        arguments = ", ".join(f"'{value}'" for value in pairs)
        statements.append(f"DROP TRIGGER IF EXISTS {table}_tenant_guard ON {table};")
        statements.append(
            f"CREATE TRIGGER {table}_tenant_guard BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION inventory_validate_tenant_relations_v2({arguments});"
        )
    return statements


def forward() -> str:
    return "\n".join([
        f"ALTER TABLE {LOT_TABLE} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {LOT_TABLE} FORCE ROW LEVEL SECURITY;",
        f"CREATE POLICY {LOT_TABLE}_tenant_isolation ON {LOT_TABLE} "
        "USING (organization_id = NULLIF("
        "current_setting('app.organization_id', true), '')::uuid) "
        "WITH CHECK (organization_id = NULLIF("
        "current_setting('app.organization_id', true), '')::uuid);",
        *_guards(AFTER),
    ])


def backward() -> str:
    return "\n".join([
        f"DROP TRIGGER IF EXISTS {LOT_TABLE}_tenant_guard ON {LOT_TABLE};",
        *_guards(BEFORE),
        f"DROP POLICY IF EXISTS {LOT_TABLE}_tenant_isolation ON {LOT_TABLE};",
        f"ALTER TABLE {LOT_TABLE} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {LOT_TABLE} DISABLE ROW LEVEL SECURITY;",
    ])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_lots")]

    operations = [migrations.RunSQL(sql=forward(), reverse_sql=backward())]
