"""Categories and tags as terms of a site's vocabulary (ADR-079 pkt 2, 3, 7, 11).

Schema only. One new table, `sites_contenttaxonomy`, with forced row-level
security like the two tag tables. New columns on `sites_contenttag` and one on
`sites_contententry`, each with a default in the database, so a row written by
code older than this migration — between `migrate` and the restart — still
inserts. No existing row is rewritten and no existing constraint changes.

Every tag older than the columns reads as closed at its key in every language
(`slug_locked_at` = `LEGACY_TERM_LOCK`, the column's database default): its
address in an archive stays what it was whatever is translated later.

Reversing drops the table and the columns. Categories live in the tag table,
so the reverse first deletes them and what filed entries under them — left
behind, they would read as the site's tags. Lossless only before the first
category is made.
"""

import uuid

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

TAXONOMY_RLS = """
ALTER TABLE sites_contenttaxonomy ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contenttaxonomy FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_taxonomy_tenant_isolation ON sites_contenttaxonomy
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""

DROP_TAXONOMY_RLS = """
DROP POLICY IF EXISTS sites_taxonomy_tenant_isolation ON sites_contenttaxonomy;
ALTER TABLE sites_contenttaxonomy NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contenttaxonomy DISABLE ROW LEVEL SECURITY;
"""

# Runs first on the way back, while the columns are still there. Both tables
# force row-level security and a migration names no tenant, so the force is
# lifted for the table's owner for these two statements and put back.
DELETE_CATEGORIES = """
ALTER TABLE sites_contententrytag NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contenttag NO FORCE ROW LEVEL SECURITY;
DELETE FROM sites_contententrytag
WHERE tag_id IN (SELECT id FROM sites_contenttag WHERE taxonomy_id IS NOT NULL);
DELETE FROM sites_contenttag WHERE taxonomy_id IS NOT NULL;
ALTER TABLE sites_contenttag FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contententrytag FORCE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0060_exchange_rate_table'),
        ('sites', '0053_content_types'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='contententry',
            name='former_slugs',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='contenttag',
            name='former_slugs',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name='contenttag',
            name='locale_slugs',
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name='contenttag',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.RESTRICT, related_name='children', to='sites.contenttag'),
        ),
        migrations.AddField(
            model_name='contenttag',
            name='position',
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name='contenttag',
            name='slug_locked_at',
            field=models.JSONField(blank=True, db_default={'*': '2026-10-08T00:00:00+00:00'}, default=dict),
        ),
        migrations.AlterField(
            model_name='contententry',
            name='state',
            field=models.CharField(choices=[('draft', 'Szkic'), ('published', 'Opublikowany'), ('withdrawn', 'Wycofany'), ('removed', 'Usunięty')], default='draft', max_length=16),
        ),
        migrations.CreateModel(
            name='ContentTaxonomy',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid7, editable=False, primary_key=True, serialize=False)),
                ('key', models.SlugField(max_length=80)),
                ('name', models.CharField(max_length=120)),
                ('hierarchical', models.BooleanField(default=False)),
                ('segment', models.SlugField(max_length=80)),
                ('locale_segments', models.JSONField(blank=True, default=dict)),
                ('former_segments', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('collection', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='taxonomies', to='sites.contentcollection')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_content_taxonomies', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_taxonomies', to='sites.site')),
            ],
            options={
                'ordering': ('organization_id', 'site_id', 'key', 'id'),
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddField(
            model_name='contenttag',
            name='taxonomy',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='terms', to='sites.contenttaxonomy'),
        ),
        migrations.AddConstraint(
            model_name='contenttaxonomy',
            constraint=models.UniqueConstraint(condition=models.Q(('collection__isnull', False)), fields=('organization', 'collection', 'key'), name='sites_taxonomy_org_type_key_uq'),
        ),
        migrations.AddConstraint(
            model_name='contenttaxonomy',
            constraint=models.UniqueConstraint(condition=models.Q(('collection__isnull', True)), fields=('organization', 'site', 'key'), name='sites_taxonomy_org_site_key_uq'),
        ),
        migrations.RunSQL(TAXONOMY_RLS, DROP_TAXONOMY_RLS),
        migrations.RunSQL(migrations.RunSQL.noop, DELETE_CATEGORIES),
    ]
