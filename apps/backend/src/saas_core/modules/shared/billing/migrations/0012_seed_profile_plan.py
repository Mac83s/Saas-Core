from typing import Any

from django.db import migrations


def seed_profile_plan(apps: Any, schema_editor: Any) -> None:
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")
    plan, _ = plan_model.objects.update_or_create(
        key="profile",
        defaults={
            "name": "Profil",
            "description": "Prosty profil firmy na subdomenie platformy.",
            "is_public": True,
            "is_active": True,
        },
    )
    version, _ = version_model.objects.get_or_create(
        plan=plan,
        version=1,
        defaults={
            "currency": "PLN",
            "billing_interval": "month",
            "unit_amount_minor": 9_900,
            "feature_keys": [
                "sites.enabled",
                "storage.enabled",
                "notifications.enabled",
                "booking.enabled",
                        ],
            "quotas": {
                "sites.max": 1,
                "locations.max": 1,
                "team_members.max": 2,
                "storage.bytes": 1024**3,
                "email.monthly": 500,
                "appointments.monthly": 250,
            },
            "trial_days": 14,
            "grace_period_days": 7,
        },
    )
    plan_model.objects.filter(pk=plan.pk).update(current_version=version)


class Migration(migrations.Migration):
    dependencies = [("billing", "0011_billinginvoicedocument")]

    operations = [migrations.RunPython(seed_profile_plan, migrations.RunPython.noop)]
