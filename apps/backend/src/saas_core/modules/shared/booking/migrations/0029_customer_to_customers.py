import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """The customer's model leaves booking in state only (ADR-073 §2): the
    table keeps its name, its rows, its RLS policy and its relation guard, and
    a visit's foreign key keeps pointing at the same column."""

    dependencies = [
        ("booking", "0028_service_payment_policy"),
        ("customers", "0001_customer_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="appointment",
                    name="customer",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="customers.customer",
                    ),
                ),
                migrations.DeleteModel(name="Customer"),
            ],
            database_operations=[],
        ),
    ]
