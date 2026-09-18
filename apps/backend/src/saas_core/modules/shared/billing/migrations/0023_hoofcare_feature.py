from django.db import migrations


class Migration(migrations.Migration):
    """Empty on purpose — a node kept so the graph of existing databases holds.

    It used to give every plan of every product a product's feature. Core names
    no product (ADR-049): a vertical publishes its own feature from its own
    migration, so only the product that composes it gets it.
    """

    dependencies = [("billing", "0022_credit_ledger_allows_erasure")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
