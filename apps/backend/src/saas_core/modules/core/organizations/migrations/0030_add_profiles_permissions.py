from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

# ADR-036 §3: one permission for the whole module. Reading a profile needs only
# membership — the content is meant for the public — so `viewer` and `staff`
# gain nothing here.
ROLE_PERMISSIONS = {
    "manager": ("profiles.manage",),
    "admin": ("profiles.manage",),
    "owner": ("profiles.manage",),
}

DISABLE = "ALTER TABLE organizations_role DISABLE TRIGGER organizations_system_role_immutable;"
ENABLE = "ALTER TABLE organizations_role ENABLE TRIGGER organizations_system_role_immutable;"


def add_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    for role_key, permissions in ROLE_PERMISSIONS.items():
        role = role_model.objects.get(key=role_key, organization=None)
        role.permissions = list(dict.fromkeys([*role.permissions, *permissions]))
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


def remove_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    removed = {permission for values in ROLE_PERMISSIONS.values() for permission in values}
    for role_key in ROLE_PERMISSIONS:
        role = role_model.objects.get(key=role_key, organization=None)
        role.permissions = [value for value in role.permissions if value not in removed]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("organizations", "0029_alter_organizationauditentry_action")]
    operations = [
        migrations.RunSQL(DISABLE, reverse_sql=ENABLE),
        migrations.RunPython(add_permissions, reverse_code=remove_permissions),
        migrations.RunSQL(ENABLE, reverse_sql=DISABLE),
    ]
