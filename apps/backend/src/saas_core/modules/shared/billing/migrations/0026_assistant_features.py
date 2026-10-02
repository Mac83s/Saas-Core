"""The assistant's plan features enter the catalogue, in no plan (ADR-076 pkt 8).

ADR-032 named `assistant.text.enabled`, `assistant.site_generation.enabled` and
`assistant.voice.enabled`, but nothing seeded them, so a decision answered
`unknown_feature` and no operator override could name them. Active and in no
plan version, they answer `feature_disabled`: dark for every customer, nothing
new in the plan catalogue (ADR-032 offers only what a version grants), and an
audited operator override is how one pilot organization gets them. The module
that ships the assistant puts them into the plans with `publish_feature` from
its own migration: text in A3, site generation in A4, voice in A8.

They are seeded here because `shared.assistant` does not exist yet; billing 0002
seeds other modules' features the same way. `assistant.actions.monthly` and
`assistant.voice_minutes.monthly` are not seeded: credits are the meter.
"""

from typing import Any

from django.db import migrations

MODULE = "shared.assistant"
FEATURES = {
    "assistant.text.enabled": "Asystent AI w rozmowie tekstowej",
    "assistant.site_generation.enabled": "Strona z rozmowy z asystentem",
    "assistant.voice.enabled": "Asystent AI w rozmowie głosowej",
}


def seed(apps: Any, _schema_editor: Any) -> None:
    feature_model = apps.get_model("billing", "Feature")
    for key, name in FEATURES.items():
        # Also switches back on a feature an earlier rollback only switched off.
        feature_model.objects.update_or_create(
            key=key, defaults={"name": name, "module": MODULE, "is_active": True}
        )


def unseed(apps: Any, _schema_editor: Any) -> None:
    """Deletes a feature nothing names, and switches off one that something does.

    The rule of `withdraw_feature`: an override ever granted keeps its row
    (revoking only stamps it), and a plan version is immutable, with
    subscriptions possibly on it — a version left behind by a later migration's
    rollback still names the key.
    """
    feature_model = apps.get_model("billing", "Feature")
    grant_model = apps.get_model("billing", "EntitlementGrant")
    version_model = apps.get_model("billing", "PlanVersion")

    for key in FEATURES:
        features = feature_model.objects.filter(key=key)
        # The base manager: a tenant-scoped default manager would see no grants.
        if (
            grant_model._base_manager.filter(feature__key=key).exists()
            or version_model.objects.filter(feature_keys__contains=[key]).exists()
        ):
            features.update(is_active=False)
        else:
            features.delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0025_site_templates_quota")]
    operations = [migrations.RunPython(seed, unseed)]
