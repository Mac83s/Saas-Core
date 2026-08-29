from django.db import migrations

# The other content tables force row-level security, so these two must as well:
# a taxonomy that leaks tells one customer what subjects another writes about,
# and a join table with no policy is the easiest place for a query to wander.
CREATE_TAG_GUARDS = """
ALTER TABLE sites_contenttag ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contenttag FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_tag_tenant_isolation ON sites_contenttag
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);

ALTER TABLE sites_contententrytag ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contententrytag FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_entrytag_tenant_isolation ON sites_contententrytag
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""

DROP_TAG_GUARDS = """
DROP POLICY IF EXISTS sites_tag_tenant_isolation ON sites_contenttag;
ALTER TABLE sites_contenttag NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contenttag DISABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sites_entrytag_tenant_isolation ON sites_contententrytag;
ALTER TABLE sites_contententrytag NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contententrytag DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("sites", "0018_content_tags")]

    operations = [migrations.RunSQL(CREATE_TAG_GUARDS, DROP_TAG_GUARDS)]
