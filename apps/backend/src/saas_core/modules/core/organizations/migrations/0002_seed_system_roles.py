from django.db import migrations

SYSTEM_ROLES = {
    "viewer": ("Viewer", ["organization.read"]),
    "staff": (
        "Staff",
        ["organization.read", "organization.members.read"],
    ),
    "manager": (
        "Manager",
        [
            "organization.read",
            "organization.members.read",
            "organization.members.manage",
        ],
    ),
    "admin": (
        "Admin",
        [
            "organization.read",
            "organization.members.read",
            "organization.members.manage",
            "organization.settings.manage",
        ],
    ),
    "owner": (
        "Owner",
        [
            "organization.read",
            "organization.members.read",
            "organization.members.manage",
            "organization.settings.manage",
            "organization.billing.manage",
            "organization.ownership.transfer",
            "organization.archive",
        ],
    ),
}


def seed_system_roles(apps, schema_editor):
    role_model = apps.get_model("organizations", "Role")
    for key, (name, permissions) in SYSTEM_ROLES.items():
        role_model.objects.update_or_create(
            key=key,
            organization=None,
            defaults={
                "name": name,
                "scope": "system",
                "permissions": permissions,
                "is_immutable": True,
                "version": 1,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [
        migrations.RunPython(seed_system_roles, reverse_code=migrations.RunPython.noop),
    ]
