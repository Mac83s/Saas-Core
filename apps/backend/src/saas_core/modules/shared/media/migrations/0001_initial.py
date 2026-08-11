import uuid

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

ENABLE_MEDIA_ASSET_RLS = """
ALTER TABLE media_mediaasset ENABLE ROW LEVEL SECURITY;
ALTER TABLE media_mediaasset FORCE ROW LEVEL SECURITY;
CREATE POLICY media_asset_tenant_isolation ON media_mediaasset
USING (
    organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
)
WITH CHECK (
    organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
);
"""

DISABLE_MEDIA_ASSET_RLS = """
DROP POLICY IF EXISTS media_asset_tenant_isolation ON media_mediaasset;
ALTER TABLE media_mediaasset NO FORCE ROW LEVEL SECURITY;
ALTER TABLE media_mediaasset DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizations", "0014_add_media_role_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaAsset",
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
                ("original_filename", models.CharField(max_length=160)),
                ("object_key", models.CharField(max_length=240, unique=True)),
                ("declared_mime", models.CharField(max_length=80)),
                ("detected_mime", models.CharField(blank=True, max_length=80)),
                ("expected_size", models.PositiveBigIntegerField()),
                ("actual_size", models.PositiveBigIntegerField(blank=True, null=True)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("width", models.PositiveIntegerField(blank=True, null=True)),
                ("height", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "Oczekuje na upload"),
                            ("uploaded", "Przesłany"),
                            ("scanning", "Skanowany"),
                            ("ready", "Gotowy"),
                            ("rejected", "Odrzucony"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("quota_reservation_key", models.CharField(max_length=120, unique=True)),
                ("quota_committed", models.BooleanField(default=False)),
                ("rejection_code", models.CharField(blank=True, max_length=80)),
                ("upload_expires_at", models.DateTimeField()),
                ("uploaded_at", models.DateTimeField(blank=True, null=True)),
                ("scanned_at", models.DateTimeField(blank=True, null=True)),
                ("ready_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("idempotency_key", models.CharField(max_length=120)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_media_assets",
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
            ],
            options={
                "ordering": ("organization_id", "-created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["organization", "state", "created_at"],
                        name="media_asset_org_state_idx",
                    ),
                    models.Index(
                        fields=["organization", "id"],
                        name="media_asset_org_id_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "created_by", "idempotency_key"),
                        name="media_asset_org_actor_idem_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("expected_size__gte", 1)),
                        name="media_asset_expected_size_positive_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("actual_size__isnull", True),
                            ("actual_size__gte", 1),
                            _connector="OR",
                        ),
                        name="media_asset_actual_size_positive_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("quota_committed", False),
                            ("state", "ready"),
                            _connector="OR",
                        ),
                        name="media_asset_quota_only_ready_ck",
                    ),
                ],
            },
            managers=[("all_objects", django.db.models.manager.Manager())],
        ),
        migrations.RunSQL(ENABLE_MEDIA_ASSET_RLS, reverse_sql=DISABLE_MEDIA_ASSET_RLS),
    ]
