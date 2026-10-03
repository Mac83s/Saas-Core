"""Phase 10 (M3, M4): an item's minimum in one place and a category's own
number of days before a lot counts as expiring. Both nullable: null inherits,
so every existing row keeps today's behaviour."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0010_rls_lots"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventorybalance",
            name="minimum_quantity",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="inventorycategory",
            name="expiring_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="inventorybalance",
            constraint=models.CheckConstraint(
                condition=models.Q(("minimum_quantity__gte", 0)),
                name="inventory_balance_minimum_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventorycategory",
            constraint=models.CheckConstraint(
                condition=models.Q(("expiring_days__gte", 1), ("expiring_days__lte", 365)),
                name="inventory_category_expiring_days_ck",
            ),
        ),
    ]
