"""`translation.characters`, seeded inactive (ADR-069 pkt 23 and 25).

One unit is 1,000 visible source characters in one target language. Its price
X follows from the cost the evals measure (TL7) and arrives as a billing data
migration; until then the operation is inactive, billing prices it at zero,
and the engine reads that as "not priced yet" — translation is not offered to
customers rather than given away.
"""

from typing import Any

from django.db import migrations

OPERATION = "translation.characters"


def seed(apps: Any, _schema_editor: Any) -> None:
    apps.get_model("billing", "CreditOperation").objects.get_or_create(
        key=OPERATION,
        defaults={
            "name": "Tłumaczenie AI",
            "description": "1000 widocznych znaków tekstu źródłowego w jednym języku docelowym.",
            "cost": 0,
            "unit": "1000_characters",
            "is_active": False,
        },
    )


def unseed(apps: Any, _schema_editor: Any) -> None:
    operations = apps.get_model("billing", "CreditOperation").objects.filter(key=OPERATION)
    reservations = apps.get_model("billing", "CreditReservation")
    # The base manager: a tenant-scoped default manager would see no rows.
    if reservations._base_manager.filter(operation_key=OPERATION).exists():
        operations.update(is_active=False)
    else:
        operations.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("translation", "0002_tenant_isolation"),
        ("billing", "0027_credits_by_quantity"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
