"""`assistant.text.enabled` in every plan (ADR-076 §8; owner answer 23 b).

The daily assistant is in every plan and paid with credits. The feature has
been in the catalogue, in no plan, since billing 0026; this publishes it the
only way a published plan changes — a next version of each plan. A
subscription on an earlier version gets it when it moves to the new one.
"""

from typing import Any

from django.db import migrations

from saas_core.modules.shared.billing.feature_migrations import (
    publish_feature,
    withdraw_feature,
)

FEATURE = "assistant.text.enabled"
NAME = "Asystent AI w rozmowie tekstowej"
MODULE = "shared.assistant"


def publish(apps: Any, _schema_editor: Any) -> None:
    publish_feature(apps, key=FEATURE, name=NAME, module=MODULE)


def withdraw(apps: Any, _schema_editor: Any) -> None:
    withdraw_feature(apps, key=FEATURE)
    # Back to where billing 0026 left it: in the catalogue, in no plan — a
    # feature that is switched off answers `feature_disabled`, a missing one
    # `unknown_feature`.
    apps.get_model("billing", "Feature").objects.update_or_create(
        key=FEATURE, defaults={"name": NAME, "module": MODULE, "is_active": True}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0003_grant_role_permissions"),
        ("billing", "0026_assistant_features"),
    ]
    operations = [migrations.RunPython(publish, withdraw)]
