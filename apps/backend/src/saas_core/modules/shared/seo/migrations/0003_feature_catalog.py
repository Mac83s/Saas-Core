from typing import Any

from django.db import migrations


def seed(apps: Any, schema_editor: Any) -> None:
    apps.get_model("billing", "Feature").objects.get_or_create(
        key="seo.audit.enabled",
        defaults={"name": "SEO audits", "module": "shared.seo", "is_active": True},
    )


def unseed(apps: Any, schema_editor: Any) -> None:
    apps.get_model("billing", "Feature").objects.filter(key="seo.audit.enabled").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("seo", "0002_tenant_isolation"),
        ("billing", "0022_credit_ledger_allows_erasure"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
