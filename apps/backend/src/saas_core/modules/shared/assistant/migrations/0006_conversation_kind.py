from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assistant", "0005_profile_version")]

    operations = [
        migrations.AddField(
            model_name="assistantconversation",
            name="kind",
            field=models.CharField(
                choices=[("operate", "Operate"), ("setup", "Setup")],
                default="operate",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="assistantconversation",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", ["operate", "setup"])),
                name="assistant_conv_kind_ck",
            ),
        ),
    ]
