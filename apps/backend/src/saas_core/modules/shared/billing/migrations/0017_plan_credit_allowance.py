from typing import Any

from django.db import migrations

# The figures ADR-040 and the credit design agreed on. Publishing them is a new
# plan version rather than an edit: a published version is immutable in the
# model and in the database (trigger from 0003), which is exactly what stops a
# customer's allowance from moving under them.
#
# The amounts do not change, only what the plan grants — so a subscription that
# stays on the old version keeps paying the same price and simply has no
# allowance until it moves.
PLAN_ALLOWANCES = {"profile": 50, "starter": 200, "pro": 1000}
ALLOWANCE_QUOTA_KEY = "credits.monthly"


def publish_versions_with_allowance(apps: Any, schema_editor: Any) -> None:
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for plan_key, allowance in PLAN_ALLOWANCES.items():
        plan = plan_model.objects.filter(key=plan_key).first()
        if plan is None:
            continue
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if latest.quotas.get(ALLOWANCE_QUOTA_KEY) == allowance:
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
            quotas={**latest.quotas, ALLOWANCE_QUOTA_KEY: allowance},
            trial_days=latest.trial_days,
            grace_period_days=latest.grace_period_days,
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=published)


def unpublish(apps: Any, schema_editor: Any) -> None:
    """Points each plan back at the version before the allowance.

    The published row itself stays: it is immutable and something may already
    reference it, so going back means choosing an older current version, not
    pretending the newer one never existed.
    """
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for plan_key in PLAN_ALLOWANCES:
        plan = plan_model.objects.filter(key=plan_key).first()
        if plan is None:
            continue
        previous = (
            version_model.objects.filter(plan=plan)
            .exclude(quotas__has_key=ALLOWANCE_QUOTA_KEY)
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)


class Migration(migrations.Migration):
    dependencies = [("billing", "0016_seed_credit_catalog")]

    operations = [migrations.RunPython(publish_versions_with_allowance, unpublish)]
