from django.db import migrations, models

POLICY_CHOICES = [
    ("manual", "Tylko ludzie"),
    ("proposed", "Propozycje do akceptacji"),
    ("automated", "Automatyzacja treści"),
]


class Migration(migrations.Migration):
    """Adds the middle setting between "only people" and "only the automation".

    Widening a choices list touches no data: every stored `manual` and
    `automated` row stays valid, and no row can hold `proposed` until somebody
    sets it.
    """

    dependencies = [
        ("sites", "0010_contentautomationgrant"),
    ]

    operations = [
        migrations.AlterField(
            model_name="page",
            name="automation_policy",
            field=models.CharField(
                choices=POLICY_CHOICES, default="manual", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="contentcollection",
            name="automation_policy",
            field=models.CharField(
                choices=POLICY_CHOICES, default="manual", max_length=16
            ),
        ),
        migrations.AddField(
            model_name="pageversion",
            name="created_by_credential",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contententryversion",
            name="created_by_credential",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
