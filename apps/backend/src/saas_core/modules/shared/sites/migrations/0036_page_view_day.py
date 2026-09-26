import uuid

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models

# Written by the public renderer under the tenant its hostname names, read by
# the panel and by automation inside theirs (ADR-060): forced row-level
# security like every private Sites table, and a guard so a row can never name
# another tenant's site.
FORWARD_SQL = """
ALTER TABLE sites_pageviewday ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_pageviewday FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_pageviewday_tenant ON sites_pageviewday
USING (organization_id = nullif(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = nullif(current_setting('app.organization_id', true), '')::uuid);

CREATE FUNCTION sites_pageviewday_tenant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sites_site WHERE id = NEW.site_id
                   AND organization_id = NEW.organization_id) THEN
        RAISE EXCEPTION 'Page view count references another tenant''s site'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sites_pageviewday_tenant_guard BEFORE INSERT OR UPDATE ON sites_pageviewday
FOR EACH ROW EXECUTE FUNCTION sites_pageviewday_tenant_guard();
"""

REVERSE_SQL = """
DROP TRIGGER sites_pageviewday_tenant_guard ON sites_pageviewday;
DROP FUNCTION sites_pageviewday_tenant_guard();
DROP POLICY sites_pageviewday_tenant ON sites_pageviewday;
ALTER TABLE sites_pageviewday NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_pageviewday DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0048_audit_visit_materials"),
        ("sites", "0035_entry_schedule_credential"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageViewDay",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("day", models.DateField()),
                ("path", models.CharField(max_length=500)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("page", "Podstrona"),
                            ("entry", "Wpis"),
                            ("collection", "Kolekcja"),
                        ],
                        max_length=16,
                    ),
                ),
                ("publication_id", models.UUIDField()),
                ("views", models.PositiveBigIntegerField(default=0)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="sites.site",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "site_id", "day", "path"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "site", "day", "path", "publication_id"),
                        name="sites_pageviewday_key_uq",
                    )
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
