import uuid

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    """`Customer` becomes a model of this app in state only (ADR-073 §2).

    The table `booking_customer`, its RLS policy and its relation guard stay
    where booking's migrations made them; nothing is copied and nothing in the
    database changes. Booking's 0029 drops its own state of the model.
    """

    initial = True

    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Customer",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid7,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("display_name", models.CharField(max_length=160)),
                        ("email", models.EmailField(blank=True, max_length=254)),
                        ("phone", models.CharField(blank=True, max_length=40)),
                        ("contact_hash", models.CharField(max_length=64)),
                        ("locale", models.CharField(default="pl", max_length=10)),
                        ("anonymized_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "organization",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="+",
                                to="organizations.organization",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "booking_customer",
                        "ordering": ("organization_id", "-created_at", "id"),
                        "indexes": [
                            models.Index(
                                fields=["organization", "contact_hash"],
                                name="booking_customer_contact_idx",
                            )
                        ],
                        "constraints": [
                            models.CheckConstraint(
                                condition=models.Q(("locale__regex", "^[a-z]{2}$")),
                                name="booking_customer_locale_format_ck",
                            )
                        ],
                    },
                    managers=[
                        ("all_objects", django.db.models.manager.Manager()),
                    ],
                ),
            ],
            database_operations=[],
        ),
    ]
