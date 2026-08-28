from django.db import migrations, models


class Migration(migrations.Migration):
    """The deployment's own publisher workspace.

    Widening the choices touches no data. The partial unique index is the part
    that matters: it is what makes "exactly one per deployment" true even when
    two deploys run the provisioning command at the same moment.
    """

    dependencies = [
        ("organizations", "0020_alter_organizationauditentry_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="workspace_kind",
            field=models.CharField(
                choices=[
                    ("personal", "Osobista"),
                    ("business", "Firmowa"),
                    ("platform", "Workspace platformy"),
                ],
                default="business",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                condition=models.Q(workspace_kind="platform"),
                fields=("workspace_kind",),
                name="organizations_single_platform_uq",
            ),
        ),
    ]
