"""The limit on an organization's own site templates (ADR-063) enters the plans.

Owner's decision of 2026-09-29 (answer c): a limit in every company plan —
Profile 3, Site (starter) 10, Pro 50 active templates, sections and pages
together. `sites.templates.max` is enforced since F4-B; until now no plan had
it, so nobody had a limit. A plan version is immutable (billing 0003), so each
plan gets its next version with the quota added and everything else carried
over, as in 0024. Plans without a site editor have no entry and stay as they
are.
"""

from typing import Any

from django.db import migrations

TEMPLATES_MAX = "sites.templates.max"
LIMITS = {"profile": 3, "starter": 10, "pro": 50}


def publish(apps: Any, _schema_editor: Any) -> None:
    quota_model = apps.get_model("billing", "QuotaDefinition")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    quota_model.objects.update_or_create(
        key=TEMPLATES_MAX,
        defaults={
            "name": "Szablony firmy",
            "unit": "count",
            "period": "lifetime",
            "description": "Ile aktywnych szablonów sekcji i stron może mieć organizacja.",
            "is_active": True,
        },
    )
    for plan in plan_model.objects.filter(key__in=LIMITS):
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if latest.quotas.get(TEMPLATES_MAX) == LIMITS[plan.key]:
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
            quotas={**latest.quotas, TEMPLATES_MAX: LIMITS[plan.key]},
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
            .exclude(quotas__has_key=TEMPLATES_MAX)
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    # The base manager: a tenant-scoped default manager would see no usage.
    if not usage_model._base_manager.filter(quota_definition__key=TEMPLATES_MAX).exists():
        quota_model.objects.filter(key=TEMPLATES_MAX).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0024_pages_quota")]
    operations = [migrations.RunPython(publish, withdraw)]
