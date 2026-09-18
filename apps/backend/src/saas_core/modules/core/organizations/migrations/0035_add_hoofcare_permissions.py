from django.db import migrations


class Migration(migrations.Migration):
    """Empty on purpose — a node kept so the graph of existing databases holds.

    It used to grant a product's permissions to the system roles of every
    product. Core names no product (ADR-049): a vertical grants its own
    permissions from its own migration.
    """

    dependencies = [("organizations", "0034_add_gsc_permissions")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
