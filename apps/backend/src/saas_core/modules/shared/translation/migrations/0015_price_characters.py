"""`translation.characters` priced and switched on (TL7; answer 54a of 03.10).

One credit for 1,000 visible source characters in one target language, the
price the evals supported (USD cost per unit well under a credit with
Claude Sonnet 5.5). A reservation keeps the price it was made at, so a later
change of X never rewrites what somebody was already charged.
"""

from typing import Any

from django.db import migrations

OPERATION = "translation.characters"
PRICE = 1


def price(apps: Any, _schema_editor: Any) -> None:
    apps.get_model("billing", "CreditOperation").objects.filter(key=OPERATION).update(
        cost=PRICE, is_active=True
    )


def unprice(apps: Any, _schema_editor: Any) -> None:
    # Back to "not priced yet": the engine reads that as not offered.
    apps.get_model("billing", "CreditOperation").objects.filter(key=OPERATION).update(
        cost=0, is_active=False
    )


class Migration(migrations.Migration):
    dependencies = [("translation", "0014_automation_carry")]
    operations = [migrations.RunPython(price, unprice)]
