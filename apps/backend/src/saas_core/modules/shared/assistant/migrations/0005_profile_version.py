import uuid
from typing import Any

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

TABLE = "assistant_assistantprofileversion"
TENANT = "NULLIF(current_setting('app.organization_id', true), '')::uuid"


def _enable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"CREATE POLICY {TABLE}_tenant_isolation ON {TABLE} "
            f"USING (organization_id = {TENANT}) "
            f"WITH CHECK (organization_id = {TENANT})"
        )


def _disable(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
        cursor.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0004_publish_text_feature"),
        ("organizations", "0059_inventory_audit_actions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantProfileVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("document", models.JSONField()),
                ("membership_id", models.UUIDField()),
                ("acting_via", models.CharField(blank=True, max_length=20)),
                ("conversation_id", models.UUIDField(blank=True, null=True)),
                ("idempotency_key", models.CharField(max_length=160)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
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
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "version"),
                        name="assistant_profile_version_unique",
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "idempotency_key"),
                        name="assistant_profile_key_unique",
                    ),
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        # The company's own rows from the first one (ADR-022): the table never
        # exists without its policy.
        migrations.RunPython(_enable, _disable),
    ]
