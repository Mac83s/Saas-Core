from django.db import migrations

#: Magazyn v1 miał wyłącznie dane testowe (HoofCare, 21.09); właściciel
#: zdecydował, że v2 startuje od zera (ADR-055). TRUNCATE, bo tabele mają
#: wymuszone RLS i DELETE w migracji nie zobaczyłby żadnego wiersza.
CLEAR = "TRUNCATE inventory_inventorymovement, inventory_inventorybalance, inventory_inventoryitem;"


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_grant_role_permissions")]

    operations = [migrations.RunSQL(CLEAR, migrations.RunSQL.noop)]
