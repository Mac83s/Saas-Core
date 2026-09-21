from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sites", "0030_site_inquiry")]

    operations = [
        migrations.AddField(
            model_name="pageblock",
            name="decoration",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
