from django.db import migrations

ROLE_UPDATES = {
    "manager": [
        "organization.read",
        "organization.members.read",
        "organization.members.manage_limited",
    ],
    "admin": [
        "organization.read",
        "organization.members.read",
        "organization.members.manage_limited",
        "organization.members.manage",
        "organization.settings.manage",
    ],
    "owner": [
        "organization.read",
        "organization.members.read",
        "organization.members.manage_limited",
        "organization.members.manage",
        "organization.settings.manage",
        "organization.billing.manage",
        "organization.ownership.transfer",
        "organization.archive",
    ],
}


def refine_system_roles(apps, schema_editor):
    role_model = apps.get_model("organizations", "Role")
    for key, permissions in ROLE_UPDATES.items():
        role_model.objects.filter(key=key, organization=None).update(
            permissions=permissions,
            version=2,
        )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_seed_system_roles")]

    operations = [
        migrations.RunPython(refine_system_roles, reverse_code=migrations.RunPython.noop),
    ]
