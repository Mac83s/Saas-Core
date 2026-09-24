from django.db import migrations, models


class Migration(migrations.Migration):
    """A call-back form (core.contact_form v2) may come without an e-mail or a
    message. Model validation only; the columns do not change."""

    dependencies = [("sites", "0032_page_presentation")]

    operations = [
        migrations.AlterField(
            model_name="siteinquiry",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AlterField(
            model_name="siteinquiry",
            name="message",
            field=models.TextField(blank=True, max_length=5000),
        ),
    ]
