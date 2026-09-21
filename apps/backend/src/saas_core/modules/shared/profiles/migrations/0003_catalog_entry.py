"""Catalogue placement on the profile, and the public catalogue table itself.

ADR-053. `profiles_catalogentry` deliberately gets **no row-level security**:
it is declared in `backend.publicTables` of `shared.profiles` because the public
catalogue reads it before any tenant is known — the slug is what names the
tenant, exactly as a hostname is for `sites_domain`. `profiles_publicprofile`
and its translations keep forced RLS, unchanged by this migration.

What the table does get is the module's cross-tenant relation trigger, extended
to cover `site`: a catalogue row may only point at a photo, a profile and a site
belonging to the organization that owns it.
"""

import uuid

import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models

RELATIONS_WITH_SITE = """
CREATE OR REPLACE FUNCTION profiles_validate_tenant_relations()
RETURNS trigger AS $$
DECLARE
    payload jsonb := to_jsonb(NEW);
    relation_name text;
    relation_id uuid;
    relation_table text;
    relation_ok boolean;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['photo', 'membership', 'profile', 'site'] LOOP
        IF payload ? (relation_name || '_id')
           AND payload->>(relation_name || '_id') IS NOT NULL THEN
            relation_id := (payload->>(relation_name || '_id'))::uuid;
            relation_table := CASE relation_name
                WHEN 'photo' THEN 'media_mediaasset'
                WHEN 'membership' THEN 'organizations_membership'
                WHEN 'profile' THEN 'profiles_publicprofile'
                WHEN 'site' THEN 'sites_site'
            END;
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1 AND organization_id = $2)',
                relation_table
            ) INTO relation_ok USING relation_id, NEW.organization_id;
            IF NOT relation_ok THEN
                RAISE EXCEPTION 'profile relation belongs to another organization'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

RELATIONS_WITHOUT_SITE = RELATIONS_WITH_SITE.replace(
    "ARRAY['photo', 'membership', 'profile', 'site']",
    "ARRAY['photo', 'membership', 'profile']",
).replace("                WHEN 'site' THEN 'sites_site'\n", "")

ATTACH = (
    "CREATE TRIGGER profiles_catalogentry_tenant_relations "
    "BEFORE INSERT OR UPDATE ON profiles_catalogentry "
    "FOR EACH ROW EXECUTE FUNCTION profiles_validate_tenant_relations()"
)
DETACH = "DROP TRIGGER IF EXISTS profiles_catalogentry_tenant_relations ON profiles_catalogentry"


class Migration(migrations.Migration):
    dependencies = [
        ("media", "0007_media_reference_allows_erasure"),
        ("organizations", "0042_audit_herd_pushed"),
        ("profiles", "0002_rls_and_tenant_guards"),
        ("sites", "0029_site_appearance"),
    ]

    operations = [
        migrations.AddField(
            model_name="publicprofile",
            name="category",
            field=models.SlugField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="publicprofile",
            name="city_slug",
            field=models.SlugField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="publicprofile",
            name="layout",
            field=models.CharField(
                choices=[
                    ("card", "Wizytówka"),
                    ("cover", "Ze zdjęciem na całą szerokość"),
                    ("compact", "Zwięzła"),
                ],
                default="card",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="CatalogEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("slug", models.SlugField(max_length=120)),
                ("city_slug", models.SlugField(max_length=80)),
                ("city", models.CharField(max_length=120)),
                ("category", models.SlugField(max_length=64)),
                ("display_name", models.CharField(max_length=160)),
                ("headline", models.CharField(blank=True, max_length=200)),
                ("published_at", models.DateTimeField()),
                (
                    "search",
                    django.contrib.postgres.search.SearchVectorField(editable=False, null=True),
                ),
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
                (
                    "photo",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="catalog_entries",
                        to="media.mediaasset",
                    ),
                ),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="catalog_entry",
                        to="profiles.publicprofile",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="catalog_entries",
                        to="sites.site",
                    ),
                ),
            ],
            options={
                "ordering": ("city_slug", "display_name", "id"),
                "indexes": [
                    models.Index(
                        fields=["city_slug", "category"], name="profiles_catalog_filter_idx"
                    ),
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["search"], name="profiles_catalog_search_idx"
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("city_slug", "slug"), name="profiles_catalog_city_slug_uq"
                    )
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
    ]
    operations += [
        migrations.RunSQL(RELATIONS_WITH_SITE, RELATIONS_WITHOUT_SITE),
        migrations.RunSQL(ATTACH, DETACH),
    ]
