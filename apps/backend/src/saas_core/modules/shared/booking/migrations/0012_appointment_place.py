from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("booking", "0011_grant_staff_performance")]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="place_town",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="appointment",
            name="place_address",
            field=models.CharField(blank=True, max_length=240),
        ),
    ]
