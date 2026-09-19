from django.db import migrations, models


class Migration(migrations.Migration):
    """System roles per organization type (ADR-050).

    The existing roles keep an empty type: they are core's global roles, still
    used by every type that declares none of its own. The key of a system role
    becomes unique within its type rather than globally.
    """

    dependencies = [("organizations", "0036_organization_type")]

    operations = [
        migrations.AddField(
            model_name="role",
            name="organization_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.RemoveConstraint(
            model_name="role",
            name="organizations_role_system_key_uq",
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                condition=models.Q(organization__isnull=True),
                fields=("organization_type", "key"),
                name="organizations_role_system_type_key_uq",
            ),
        ),
    ]
