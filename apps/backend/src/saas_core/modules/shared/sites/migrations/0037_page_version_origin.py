from django.db import migrations, models

# Two columns on an append-only table. Adding a column with a constant default
# rewrites no row, so the append-only trigger (a row trigger) never fires;
# existing versions read as "" — origin unknown.


class Migration(migrations.Migration):
    dependencies = [("sites", "0036_page_view_day")]

    operations = [
        migrations.AddField(
            model_name="pageversion",
            name="origin",
            field=models.CharField(blank=True, default="", max_length=24),
        ),
        migrations.AddField(
            model_name="pageversion",
            name="origin_ref",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
    ]
