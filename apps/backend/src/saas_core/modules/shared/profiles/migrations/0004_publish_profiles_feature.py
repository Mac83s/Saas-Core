from typing import Any

from django.db import migrations

from saas_core.modules.shared.billing.feature_migrations import publish_feature, withdraw_feature

FEATURE_KEY = "profiles.enabled"


def publish(apps: Any, _schema_editor: Any) -> None:
    """ADR-053 §9: every plan gets it.

    The business card is the floor of the offer, so this feature is not what
    separates a plan from another — it exists so publishing into the public
    catalogue is gated by the same mechanism as every other feature, and so a
    suspended or unpaid tenant stops appearing under it.
    """
    publish_feature(apps, key=FEATURE_KEY, name="Wizytówka i katalog", module="shared.profiles")


def withdraw(apps: Any, _schema_editor: Any) -> None:
    withdraw_feature(apps, key=FEATURE_KEY)


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0003_catalog_entry"),
        ("billing", "0023_hoofcare_feature"),
    ]
    operations = [migrations.RunPython(publish, reverse_code=withdraw)]
