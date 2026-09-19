from django.db import migrations, models

import saas_core.modules.core.organizations.models


class Migration(migrations.Migration):
    """Every existing organization gets the product's default type (ADR-050).

    Through the column default, not a data migration: the table has forced RLS,
    so an UPDATE here would see no rows and succeed while changing nothing.
    `ADD COLUMN ... DEFAULT` is DDL and fills every row. Which default depends on
    the deployment migrating — `business` here, the product's first type in a
    product repository.
    """

    dependencies = [("organizations", "0035_add_hoofcare_permissions")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="organization_type",
            field=models.CharField(
                default=saas_core.modules.core.organizations.models.default_organization_type,
                max_length=40,
            ),
        ),
    ]
