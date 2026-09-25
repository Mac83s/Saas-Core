"""The offer (ADR-059 pkt 9): the feature on every plan, an attempt limit, a price.

Owner's decision of 2026-09-24: all plans, 2 credits per image. The attempt
limit counts every try, refused and failed ones included, so a loop of blocked
prompts cannot burn the product's shared OpenAI spend limit. Numbers are
provisional, like `pages.max` in billing 0024: profile 50, starter 200, pro
1000, every other plan 50 — a product plan must not be left without the quota,
or `consume_quota` would refuse there and the feature would be dark.
"""

from typing import Any

from django.db import migrations

from saas_core.modules.shared.billing.feature_migrations import publish_feature, withdraw_feature

FEATURE = "image_generation.enabled"
QUOTA = "image_generation.monthly"
OPERATION = "image_generation.generate"
LIMITS = {"profile": 50, "starter": 200, "pro": 1000}
DEFAULT_LIMIT = 50


def publish(apps: Any, _schema_editor: Any) -> None:
    publish_feature(
        apps, key=FEATURE, name="Generowanie obrazów AI", module="shared.image-generation"
    )
    quota_model = apps.get_model("billing", "QuotaDefinition")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")
    quota_model.objects.update_or_create(
        key=QUOTA,
        defaults={
            "name": "Próby generowania obrazów",
            "unit": "count",
            "period": "month",
            "description": "Ile razy w miesiącu organizacja może zlecić wygenerowanie obrazu.",
            "is_active": True,
        },
    )
    for plan in plan_model.objects.all():
        limit = LIMITS.get(plan.key, DEFAULT_LIMIT)
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if latest.quotas.get(QUOTA) == limit:
            # Published before and rolled back: point the plan at it again.
            plan_model.objects.filter(pk=plan.pk).update(current_version=latest)
            continue
        published = version_model.objects.create(
            plan=plan,
            version=latest.version + 1,
            currency=latest.currency,
            billing_interval=latest.billing_interval,
            unit_amount_minor=latest.unit_amount_minor,
            feature_keys=list(latest.feature_keys),
            quotas={**latest.quotas, QUOTA: limit},
            trial_days=latest.trial_days,
            grace_period_days=latest.grace_period_days,
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=published)
    apps.get_model("billing", "CreditOperation").objects.update_or_create(
        key=OPERATION,
        defaults={
            "name": "Wygenerowanie obrazu AI",
            "description": "Jeden obraz z opisu tekstowego, pobierany po gotowym pliku.",
            "cost": 2,
            "is_active": True,
        },
    )


def withdraw(apps: Any, _schema_editor: Any) -> None:
    """The quota first, then the feature: each points plans at an older version."""
    quota_model = apps.get_model("billing", "QuotaDefinition")
    usage_model = apps.get_model("billing", "QuotaUsage")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")
    operation_model = apps.get_model("billing", "CreditOperation")
    reservation_model = apps.get_model("billing", "CreditReservation")

    for plan in plan_model.objects.all():
        previous = (
            version_model.objects.filter(plan=plan)
            .exclude(quotas__has_key=QUOTA)
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    # The base manager: a tenant-scoped default manager would see no rows.
    if not usage_model._base_manager.filter(quota_definition__key=QUOTA).exists():
        quota_model.objects.filter(key=QUOTA).delete()
    withdraw_feature(apps, key=FEATURE)
    operations = operation_model.objects.filter(key=OPERATION)
    if reservation_model._base_manager.filter(operation_key=OPERATION).exists():
        operations.update(is_active=False)
    else:
        operations.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("image_generation", "0002_tenant_isolation"),
        ("billing", "0024_pages_quota"),
        ("media", "0008_mediaasset_ai_origin"),
    ]
    operations = [migrations.RunPython(publish, withdraw)]
