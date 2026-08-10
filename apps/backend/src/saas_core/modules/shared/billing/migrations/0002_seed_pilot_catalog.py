from django.db import migrations

FEATURES = {
    "sites.enabled": ("Strony", "shared.sites"),
    "storage.enabled": ("Pliki i media", "shared.media"),
    "notifications.enabled": ("Powiadomienia", "shared.notifications"),
    "booking.enabled": ("Rezerwacje", "shared.booking"),
    "medical.enabled": ("Funkcje medyczne", "vertical.medical"),
    "custom_domain.enabled": ("Własna domena", "shared.sites"),
}

QUOTAS = {
    "sites.max": ("Liczba stron", "count", "lifetime"),
    "locations.max": ("Liczba lokalizacji", "count", "lifetime"),
    "team_members.max": ("Liczba członków zespołu", "count", "lifetime"),
    "storage.bytes": ("Pojemność plików", "bytes", "lifetime"),
    "email.monthly": ("Wiadomości e-mail", "count", "month"),
    "appointments.monthly": ("Rezerwacje wizyt", "count", "month"),
}

BASE_FEATURES = [
    "sites.enabled",
    "storage.enabled",
    "notifications.enabled",
    "booking.enabled",
    "medical.enabled",
]

PLANS = {
    "starter": {
        "name": "Starter",
        "description": "Plan pilota dla pojedynczego gabinetu.",
        "unit_amount_minor": 14_900,
        "feature_keys": BASE_FEATURES,
        "quotas": {
            "sites.max": 1,
            "locations.max": 1,
            "team_members.max": 5,
            "storage.bytes": 5 * 1024**3,
            "email.monthly": 2_000,
            "appointments.monthly": 1_000,
        },
    },
    "pro": {
        "name": "Pro",
        "description": "Plan pilota dla rozwijającej się placówki.",
        "unit_amount_minor": 29_900,
        "feature_keys": [*BASE_FEATURES, "custom_domain.enabled"],
        "quotas": {
            "sites.max": 3,
            "locations.max": 5,
            "team_members.max": 25,
            "storage.bytes": 50 * 1024**3,
            "email.monthly": 20_000,
            "appointments.monthly": 10_000,
        },
    },
}


def seed_pilot_catalog(apps, schema_editor):
    feature_model = apps.get_model("billing", "Feature")
    quota_model = apps.get_model("billing", "QuotaDefinition")
    plan_model = apps.get_model("billing", "Plan")
    version_model = apps.get_model("billing", "PlanVersion")

    for key, (name, module) in FEATURES.items():
        feature_model.objects.update_or_create(
            key=key,
            defaults={"name": name, "module": module, "is_active": True},
        )
    for key, (name, unit, period) in QUOTAS.items():
        quota_model.objects.update_or_create(
            key=key,
            defaults={
                "name": name,
                "unit": unit,
                "period": period,
                "is_active": True,
            },
        )
    for key, definition in PLANS.items():
        plan, _ = plan_model.objects.update_or_create(
            key=key,
            defaults={
                "name": definition["name"],
                "description": definition["description"],
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
                "unit_amount_minor": definition["unit_amount_minor"],
                "feature_keys": definition["feature_keys"],
                "quotas": definition["quotas"],
                "trial_days": 3,
                "grace_period_days": 7,
            },
        )
        plan_model.objects.filter(pk=plan.pk).update(current_version=version)


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [
        migrations.RunPython(
            seed_pilot_catalog,
            reverse_code=migrations.RunPython.noop,
        )
    ]
