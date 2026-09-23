from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sites", "0031_pageblock_decoration")]

    operations = [
        migrations.AddField(
            model_name="pageblock",
            name="presentation",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="pageversion",
            name="presentation",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
