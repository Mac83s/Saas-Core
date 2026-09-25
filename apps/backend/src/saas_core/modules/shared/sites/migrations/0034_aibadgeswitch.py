# ADR-059 pkt 7: the operator switch for the visible AI marking. A platform
# table without an organization, so no RLS and no publicTables entry.
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0033_inquiry_contact_optional"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AiBadgeSwitch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("visible", models.BooleanField()),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "changed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reason", ""), _negated=True),
                        name="sites_aibadgeswitch_reason_ck",
                    )
                ],
            },
        ),
    ]
