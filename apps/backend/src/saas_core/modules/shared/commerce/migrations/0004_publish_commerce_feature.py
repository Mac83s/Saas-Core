from typing import Any

from django.db import migrations

from saas_core.modules.shared.billing.feature_migrations import publish_feature, withdraw_feature

#: In every plan (ADR-073 §1): stays and the shop are in every plan, and both
#: need the order. A subscription on an earlier plan version gets it when it
#: moves to this one; until then its bookings go on without orders.
FEATURE_KEY = "commerce.enabled"


def publish(apps: Any, _schema_editor: Any) -> None:
    publish_feature(apps, key=FEATURE_KEY, name="Zamówienia", module="shared.commerce")


def withdraw(apps: Any, _schema_editor: Any) -> None:
    withdraw_feature(apps, key=FEATURE_KEY)


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0003_grant_role_permissions"),
        ("billing", "0028_public_locales_quota"),
    ]
    operations = [migrations.RunPython(publish, reverse_code=withdraw)]
