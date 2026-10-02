"""The limit on the company's languages enters the plans (ADR-071 pkt 7, plan TL10).

`public_locales.additional.max` counts the languages beyond the first. The
cheapest company plan — Profile — gets 1 in its next version; Site (starter)
and Pro carry no number, which means no limit. A plan version is immutable
(billing 0003), so Profile gets a new version with everything else carried
over, as in 0024 and 0025. Products with their own plans publish theirs in
their own repository.
"""

from typing import Any

from django.db import migrations

PUBLIC_LOCALES_MAX = "public_locales.additional.max"
LIMITS = {"profile": 1}


def publish(apps: Any, _schema_editor: Any) -> None:
    quota_model = apps.get_model("billing", "QuotaDefinition")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    quota_model.objects.update_or_create(
        key=PUBLIC_LOCALES_MAX,
        defaults={
            "name": "Dodatkowe języki firmy",
            "unit": "count",
            "period": "lifetime",
            "description": "Ile języków poza pierwszym może mieć firma; usuwanie zawsze działa.",
            "is_active": True,
        },
    )
    for plan in plan_model.objects.filter(key__in=LIMITS):
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if latest.quotas.get(PUBLIC_LOCALES_MAX) == LIMITS[plan.key]:
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
            quotas={**latest.quotas, PUBLIC_LOCALES_MAX: LIMITS[plan.key]},
            trial_days=latest.trial_days,
            grace_period_days=latest.grace_period_days,
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=published)


def withdraw(apps: Any, _schema_editor: Any) -> None:
    """Points each plan back at its newest version without the limit.

    The published rows stay — immutable, and a subscription may reference them.
    """
    quota_model = apps.get_model("billing", "QuotaDefinition")
    usage_model = apps.get_model("billing", "QuotaUsage")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for plan in plan_model.objects.filter(key__in=LIMITS):
        previous = (
            version_model.objects.filter(plan=plan)
            .exclude(quotas__has_key=PUBLIC_LOCALES_MAX)
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    # The base manager: a tenant-scoped default manager would see no usage.
    if not usage_model._base_manager.filter(quota_definition__key=PUBLIC_LOCALES_MAX).exists():
        quota_model.objects.filter(key=PUBLIC_LOCALES_MAX).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0027_credits_by_quantity")]
    operations = [migrations.RunPython(publish, withdraw)]
