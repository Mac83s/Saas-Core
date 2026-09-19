from typing import Any

from django.db import migrations

FEATURE_KEY = "farms.enabled"
FEATURE = ("Rejestr gospodarstw", "shared.farms")


def publish_versions_with_farms(apps: Any, _schema_editor: Any) -> None:
    """Adds the module's entitlement the only way a published plan changes.

    A plan version is immutable in the model and in the database (trigger from
    0003), so granting an existing plan a new feature means publishing the next
    version and pointing the plan at it — not editing what customers already
    bought. Prices and quotas are carried over unchanged; the only difference is
    the feature.

    The consequence is deliberate and worth saying out loud: a subscription
    staying on the previous version does not get the module until it moves to
    this one. That is the same rule that keeps somebody's allowance from
    changing under them.

    Every current plan gets it. The pilot catalogue does not price modules
    separately, and a product that composes this module has no plan under which
    its own core feature should be dark. Selling modules apart is a catalogue
    decision, and this is not the migration that should make it quietly.
    """
    feature_model = apps.get_model("billing", "Feature")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    label, owner = FEATURE
    feature_model.objects.update_or_create(
        key=FEATURE_KEY, defaults={"name": label, "module": owner}
    )

    for plan in plan_model.objects.all():
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None or FEATURE_KEY in latest.feature_keys:
            continue
        published = version_model.objects.create(
            plan=plan,
            version=latest.version + 1,
            currency=latest.currency,
            billing_interval=latest.billing_interval,
            unit_amount_minor=latest.unit_amount_minor,
            feature_keys=[*latest.feature_keys, FEATURE_KEY],
            quotas=dict(latest.quotas),
            trial_days=latest.trial_days,
            grace_period_days=latest.grace_period_days,
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=published)


def unpublish(apps: Any, _schema_editor: Any) -> None:
    """Points each plan back at the version before the feature.

    The published row stays: it is immutable and a subscription may already
    reference it, so going back means choosing an older current version rather
    than pretending the newer one never existed.
    """
    feature_model = apps.get_model("billing", "Feature")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for plan in plan_model.objects.all():
        previous = (
            version_model.objects.filter(plan=plan)
            .exclude(feature_keys__contains=[FEATURE_KEY])
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    feature_model.objects.filter(key=FEATURE_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("farms", "0002_rls_and_tenant_guards"),
        ("billing", "0023_hoofcare_feature"),
    ]
    operations = [migrations.RunPython(publish_versions_with_farms, reverse_code=unpublish)]
