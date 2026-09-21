from typing import Any

from django.db import migrations

from saas_core.modules.shared.billing.feature_migrations import publish_feature, withdraw_feature

FEATURE_KEY = "inventory.enabled"


def publish(apps: Any, _schema_editor: Any) -> None:
    publish_feature(apps, key=FEATURE_KEY, name="Magazyn materiałów", module="shared.inventory")


def withdraw(apps: Any, _schema_editor: Any) -> None:
    withdraw_feature(apps, key=FEATURE_KEY)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_rls_and_tenant_guards"),
        ("billing", "0023_hoofcare_feature"),
    ]
    operations = [migrations.RunPython(publish, reverse_code=withdraw)]
