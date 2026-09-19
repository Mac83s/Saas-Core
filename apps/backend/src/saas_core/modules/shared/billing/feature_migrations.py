"""Publishing a module's plan feature from the module's own migration.

A module outside the pilot catalogue (the farm register, a product's vertical,
ADR-049) adds its entitlement to the plans from a migration of its own. Those
migrations run with historical models, so these take `apps` and use nothing but
`apps.get_model`: they must keep working for every migration that calls them.
"""

from __future__ import annotations

from typing import Any


def publish_feature(apps: Any, *, key: str, name: str, module: str) -> None:
    """Adds the feature to every plan the only way a published plan changes.

    A plan version is immutable in the model and in the database (trigger from
    billing 0003), so granting an existing plan a new feature means publishing
    the next version and pointing the plan at it — not editing what customers
    already bought. Prices and quotas are carried over unchanged; the only
    difference is the feature.

    The consequence is deliberate: a subscription staying on the previous
    version does not get the module until it moves to this one. That is the same
    rule that keeps somebody's allowance from changing under them.

    Every current plan gets it. The pilot catalogue does not price modules
    separately, and a product that composes the module has no plan under which
    its own feature should be dark. Selling modules apart is a catalogue
    decision, and this is not the place to make it quietly.
    """
    feature_model = apps.get_model("billing", "Feature")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    feature_model.objects.update_or_create(
        key=key, defaults={"name": name, "module": module, "is_active": True}
    )
    for plan in plan_model.objects.all():
        latest = version_model.objects.filter(plan=plan).order_by("-version").first()
        if latest is None:
            continue
        if key in latest.feature_keys:
            # Published before and rolled back: the version still exists, the
            # plan only has to point at it again.
            plan_model.objects.filter(pk=plan.pk).update(current_version=latest)
            continue
        published = version_model.objects.create(
            plan=plan,
            version=latest.version + 1,
            currency=latest.currency,
            billing_interval=latest.billing_interval,
            unit_amount_minor=latest.unit_amount_minor,
            feature_keys=[*latest.feature_keys, key],
            quotas=dict(latest.quotas),
            trial_days=latest.trial_days,
            grace_period_days=latest.grace_period_days,
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=published)


def withdraw_feature(apps: Any, *, key: str) -> None:
    """Points each plan back at the version before the feature.

    The published row stays: it is immutable and a subscription may already
    reference it, so going back means choosing an older current version rather
    than pretending the newer one never existed. An override ever granted on the
    feature keeps its row too (revoking only stamps it) and protects the
    feature, so the feature is switched off rather than deleted then.
    """
    feature_model = apps.get_model("billing", "Feature")
    grant_model = apps.get_model("billing", "EntitlementGrant")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for plan in plan_model.objects.all():
        previous = (
            version_model.objects.filter(plan=plan)
            .exclude(feature_keys__contains=[key])
            .order_by("-version")
            .first()
        )
        if previous is not None:
            plan_model.objects.filter(pk=plan.pk).update(current_version=previous)
    features = feature_model.objects.filter(key=key)
    # The base manager: a tenant-scoped default manager would see no grants.
    if grant_model._base_manager.filter(feature__key=key).exists():
        features.update(is_active=False)
    else:
        features.delete()
