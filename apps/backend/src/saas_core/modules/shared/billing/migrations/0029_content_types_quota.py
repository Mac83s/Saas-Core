"""The limit on a site's content types enters the plans (ADR-079 pkt 21).

`sites.content_types.additional.max` counts the switched-on content types of
one site beyond its first: 0 is the blog alone. The owner's defaults of
2026-10-08, his to change: Profile 0, Site (starter) 1, Pro 10. A plan version
is immutable (billing 0003), so each plan gets a new version with everything
else carried over, as in 0024, 0025 and 0028; a subscription keeps the version
it bought, and one on a version without the number has no limit. The
definition has to exist wherever the guard runs — without it the guard refuses
everybody (`unknown_quota`) — so it arrives in the same release. Products with
their own plans publish theirs in their own repository, before their profile
switches `features.contentTypes` on.
"""

from typing import Any

from django.db import migrations

CONTENT_TYPES_MAX = "sites.content_types.additional.max"
LIMITS = {"profile": 0, "starter": 1, "pro": 10}


def publish(apps: Any, _schema_editor: Any) -> None:
    quota_model = apps.get_model("billing", "QuotaDefinition")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    quota_model.objects.update_or_create(
        key=CONTENT_TYPES_MAX,
        defaults={
            "name": "Dodatkowe typy treści na stronie",
            "unit": "count",
            "period": "lifetime",
            "description": (
                "Ile włączonych typów treści poza pierwszym może mieć jedna strona; "
                "typy już założone działają zawsze."
            ),
            "is_active": True,
        },
    )
    for plan in plan_model.objects.filter(key__in=LIMITS):
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if latest.quotas.get(CONTENT_TYPES_MAX) == LIMITS[plan.key]:
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
            quotas={**latest.quotas, CONTENT_TYPES_MAX: LIMITS[plan.key]},
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
            .exclude(quotas__has_key=CONTENT_TYPES_MAX)
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    # The base manager: a tenant-scoped default manager would see no usage.
    if not usage_model._base_manager.filter(quota_definition__key=CONTENT_TYPES_MAX).exists():
        quota_model.objects.filter(key=CONTENT_TYPES_MAX).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0028_public_locales_quota")]
    operations = [migrations.RunPython(publish, withdraw)]
