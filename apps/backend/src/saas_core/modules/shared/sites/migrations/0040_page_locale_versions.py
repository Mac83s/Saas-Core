import uuid

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

# ADR-070: a language version of a page body is tenant working state like a
# page version — forced row-level security, append-only with the ADR-042
# erasure door, and a guard so a row can name only its own tenant's page,
# translation and source version. The translation's two body pointers may
# name only a version of that same translation.
FORWARD_SQL = """
ALTER TABLE sites_pagelocaleversion ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_pagelocaleversion FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_pagelocaleversion_tenant_isolation ON sites_pagelocaleversion
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);

CREATE FUNCTION sites_pagelocaleversion_links() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sites_pagetranslation
        WHERE id = NEW.translation_id
          AND page_id = NEW.page_id
          AND site_id = NEW.site_id
          AND locale = NEW.locale
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'language version names another page, language or organization'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM sites_pageversion
        WHERE id = NEW.source_version_id
          AND page_id = NEW.page_id
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'language version is bound to a version of another page'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sites_pagelocaleversion_links BEFORE INSERT ON sites_pagelocaleversion
FOR EACH ROW EXECUTE FUNCTION sites_pagelocaleversion_links();
CREATE TRIGGER sites_pagelocaleversion_append_only
BEFORE UPDATE OR DELETE ON sites_pagelocaleversion
FOR EACH ROW EXECUTE FUNCTION sites_reject_append_only_mutation();

CREATE FUNCTION sites_pagetranslation_body_links() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.body_current_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM sites_pagelocaleversion
            WHERE id = NEW.body_current_id AND translation_id = NEW.id
              AND organization_id = NEW.organization_id))
       OR (NEW.body_pending_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM sites_pagelocaleversion
            WHERE id = NEW.body_pending_id AND translation_id = NEW.id
              AND organization_id = NEW.organization_id)) THEN
        RAISE EXCEPTION 'translation body points at another translation''s version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sites_pagetranslation_body_links
BEFORE INSERT OR UPDATE OF body_current_id, body_pending_id ON sites_pagetranslation
FOR EACH ROW EXECUTE FUNCTION sites_pagetranslation_body_links();
"""

REVERSE_SQL = """
DROP TRIGGER sites_pagetranslation_body_links ON sites_pagetranslation;
DROP FUNCTION sites_pagetranslation_body_links();
DROP TRIGGER sites_pagelocaleversion_append_only ON sites_pagelocaleversion;
DROP TRIGGER sites_pagelocaleversion_links ON sites_pagelocaleversion;
DROP FUNCTION sites_pagelocaleversion_links();
DROP POLICY sites_pagelocaleversion_tenant_isolation ON sites_pagelocaleversion;
ALTER TABLE sites_pagelocaleversion NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_pagelocaleversion DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0051_audit_crews_teams"),
        ("sites", "0039_page_soft_delete"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="pagetranslation",
            name="body_version",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="pagetranslation",
            name="pending_reason",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.CreateModel(
            name="PageLocaleVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("locale", models.CharField(max_length=10)),
                ("number", models.PositiveBigIntegerField()),
                ("structure_signature", models.CharField(max_length=64)),
                ("units", models.JSONField(default=dict)),
                ("content_hash", models.CharField(max_length=64)),
                ("created_by_credential", models.UUIDField(blank=True, null=True)),
                ("origin", models.CharField(blank=True, default="", max_length=24)),
                ("origin_ref", models.CharField(blank=True, default="", max_length=160)),
                ("idempotency_key", models.CharField(max_length=120)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_page_locale_versions",
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
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="locale_versions",
                        to="sites.page",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="sites.site",
                    ),
                ),
                (
                    "source_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="locale_versions",
                        to="sites.pageversion",
                    ),
                ),
                (
                    "translation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="body_versions",
                        to="sites.pagetranslation",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "translation_id", "number"),
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddField(
            model_name="pagetranslation",
            name="body_current",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="sites.pagelocaleversion",
            ),
        ),
        migrations.AddField(
            model_name="pagetranslation",
            name="body_pending",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="sites.pagelocaleversion",
            ),
        ),
        migrations.AddIndex(
            model_name="pagelocaleversion",
            index=models.Index(
                fields=["organization", "page", "locale"], name="sites_localever_page_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="pagelocaleversion",
            index=models.Index(
                fields=["organization", "source_version"], name="sites_localever_source_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="pagelocaleversion",
            constraint=models.UniqueConstraint(
                fields=("organization", "translation", "number"),
                name="sites_localever_org_tr_number_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="pagelocaleversion",
            constraint=models.UniqueConstraint(
                fields=("organization", "translation", "created_by", "idempotency_key"),
                name="sites_localever_org_tr_actor_idem_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="pagelocaleversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("number__gte", 1)), name="sites_localever_number_positive_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="pagelocaleversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("locale__regex", "^[a-z]{2}$")),
                name="sites_localever_locale_format_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
