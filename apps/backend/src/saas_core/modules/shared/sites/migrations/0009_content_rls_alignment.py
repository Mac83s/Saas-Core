from django.db import migrations

# The public renderer reads a published entry with no tenant context — there is
# no signed-in user on a visitor's request. Forced row-level security therefore
# hid every entry from it, and the article 404'd.
#
# This matches how the rest of the module already works: sites_page,
# sites_publication and sites_pageversion carry no RLS for the same reason, and
# tenant isolation is enforced by the service layer, which scopes every query to
# the context's organization, plus the cross-tenant trigger below, which the
# database applies whatever the caller does.
DROP_CONTENT_RLS = """
DROP POLICY IF EXISTS sites_entrypub_tenant_isolation ON sites_contententrypublication;
DROP POLICY IF EXISTS sites_entryversion_tenant_isolation ON sites_contententryversion;
DROP POLICY IF EXISTS sites_entry_tenant_isolation ON sites_contententry;
DROP POLICY IF EXISTS sites_collection_tenant_isolation ON sites_contentcollection;
ALTER TABLE sites_contententrypublication NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contententrypublication DISABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententryversion NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contententryversion DISABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententry NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contententry DISABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contentcollection NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contentcollection DISABLE ROW LEVEL SECURITY;
"""

RESTORE_CONTENT_RLS = """
ALTER TABLE sites_contentcollection ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contentcollection FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_collection_tenant_isolation ON sites_contentcollection
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);

ALTER TABLE sites_contententry ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententry FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_entry_tenant_isolation ON sites_contententry
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);

ALTER TABLE sites_contententryversion ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententryversion FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_entryversion_tenant_isolation ON sites_contententryversion
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);

ALTER TABLE sites_contententrypublication ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententrypublication FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_entrypub_tenant_isolation ON sites_contententrypublication
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0008_contentcollection_contententry_and_more"),
    ]

    operations = [
        migrations.RunSQL(DROP_CONTENT_RLS, reverse_sql=RESTORE_CONTENT_RLS),
    ]
