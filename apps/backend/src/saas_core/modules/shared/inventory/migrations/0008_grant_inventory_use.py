from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

#: `inventory.use` (ADR-055): zużycie z własnego zapasu i produkty przy wizycie.
#: Ma je każdy, kto pracuje z klientem; podgląd (viewer) nie.
ROLES = ("staff", "manager", "admin", "owner")
PERMISSION = "inventory.use"

DISABLE = "ALTER TABLE organizations_role DISABLE TRIGGER organizations_system_role_immutable;"
ENABLE = "ALTER TABLE organizations_role ENABLE TRIGGER organizations_system_role_immutable;"


def grant(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    for role in role_model.objects.filter(key__in=ROLES, organization=None, organization_type=""):
        if PERMISSION in role.permissions:
            continue
        role.permissions = [*role.permissions, PERMISSION]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


def revoke(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    role_model = apps.get_model("organizations", "Role")
    for role in role_model.objects.filter(key__in=ROLES, organization=None, organization_type=""):
        role.permissions = [value for value in role.permissions if value != PERMISSION]
        role.version += 1
        role.save(update_fields=["permissions", "version", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_rls_v2")]
    operations = [
        migrations.RunSQL(DISABLE, reverse_sql=ENABLE),
        migrations.RunPython(grant, reverse_code=revoke),
        migrations.RunSQL(ENABLE, reverse_sql=DISABLE),
    ]
