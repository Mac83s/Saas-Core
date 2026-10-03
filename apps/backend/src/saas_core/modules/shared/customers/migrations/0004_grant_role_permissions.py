from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

#: The company's documents for its customers are read by whoever runs the
#: company and written by whoever answers for it.
ROLE_PERMISSIONS = {
    "manager": ("customers.read",),
    "admin": ("customers.read", "customers.manage"),
    "owner": ("customers.read", "customers.manage"),
}

DISABLE = "ALTER TABLE organizations_role DISABLE TRIGGER organizations_system_role_immutable;"
ENABLE = "ALTER TABLE organizations_role ENABLE TRIGGER organizations_system_role_immutable;"


def add_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    for role_key, permissions in ROLE_PERMISSIONS.items():
        role = role_model.objects.get(key=role_key, organization=None, organization_type="")
        missing = [value for value in permissions if value not in role.permissions]
        if not missing:
            continue
        role.permissions = [*role.permissions, *missing]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


def remove_permissions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    removed = {permission for values in ROLE_PERMISSIONS.values() for permission in values}
    for role_key in ROLE_PERMISSIONS:
        role = role_model.objects.get(key=role_key, organization=None, organization_type="")
        role.permissions = [value for value in role.permissions if value not in removed]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0003_documents_rls_and_guards"),
        ("organizations", "0059_inventory_audit_actions"),
    ]
    operations = [
        migrations.RunSQL(DISABLE, reverse_sql=ENABLE),
        migrations.RunPython(add_permissions, reverse_code=remove_permissions),
        migrations.RunSQL(ENABLE, reverse_sql=DISABLE),
    ]
