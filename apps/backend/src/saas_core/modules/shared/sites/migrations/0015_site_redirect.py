import uuid

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Addresses that now answer somewhere else.

    A published URL is locked because every link and every search result points
    at it. This table is what lets one move without the old address going dark.
    """

    dependencies = [
        ("sites", "0014_content_purpose"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteRedirect",
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
                ("locale", models.CharField(max_length=10)),
                ("from_path", models.CharField(max_length=300)),
                ("to_path", models.CharField(max_length=300)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_site_redirects",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="redirects",
                        to="sites.page",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="redirects",
                        to="sites.site",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "site_id", "from_path"),
            },
            managers=[("all_objects", django.db.models.manager.Manager())],
        ),
        migrations.AddConstraint(
            model_name="siteredirect",
            constraint=models.UniqueConstraint(
                fields=("organization", "site", "from_path"),
                name="sites_redirect_org_site_from_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="siteredirect",
            constraint=models.CheckConstraint(
                condition=~models.Q(from_path=models.F("to_path")),
                name="sites_redirect_not_self_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="siteredirect",
            index=models.Index(
                fields=["organization", "site", "to_path"],
                name="sites_redirect_target_idx",
            ),
        ),
    ]
