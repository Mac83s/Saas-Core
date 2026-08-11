from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

ROLE_MEDIA_PERMISSIONS = {
    "manager": ("media.read", "media.manage"),
    "admin": ("media.read", "media.manage"),
    "owner": ("media.read", "media.manage"),
}

DISABLE_ROLE_GUARD = """
ALTER TABLE organizations_role
DISABLE TRIGGER organizations_system_role_immutable;
"""

ENABLE_ROLE_GUARD = """
ALTER TABLE organizations_role
ENABLE TRIGGER organizations_system_role_immutable;
"""


def add_media_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    for role_key, media_permissions in ROLE_MEDIA_PERMISSIONS.items():
        role = role_model.objects.get(key=role_key, organization=None)
        role.permissions = list(dict.fromkeys([*role.permissions, *media_permissions]))
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


def remove_media_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    removed = {permission for values in ROLE_MEDIA_PERMISSIONS.values() for permission in values}
    for role_key in ROLE_MEDIA_PERMISSIONS:
        role = role_model.objects.get(key=role_key, organization=None)
        role.permissions = [
            permission for permission in role.permissions if permission not in removed
        ]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("organizations", "0013_add_sites_role_permissions")]

    operations = [
        migrations.RunSQL(DISABLE_ROLE_GUARD, reverse_sql=ENABLE_ROLE_GUARD),
        migrations.RunPython(add_media_permissions, reverse_code=remove_media_permissions),
        migrations.RunSQL(ENABLE_ROLE_GUARD, reverse_sql=DISABLE_ROLE_GUARD),
    ]
