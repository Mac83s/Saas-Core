from django.db import migrations

# The other content tables force row-level security and this one carries the
# reasoning behind a customer's unpublished work — which competitor was cited,
# which query is being chased. It is not the table to leave open.
CREATE_PROPOSAL_GUARDS = """
ALTER TABLE sites_contentproposal ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_contentproposal FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_proposal_tenant_isolation ON sites_contentproposal
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""

DROP_PROPOSAL_GUARDS = """
DROP POLICY IF EXISTS sites_proposal_tenant_isolation ON sites_contentproposal;
ALTER TABLE sites_contentproposal NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_contentproposal DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("sites", "0022_content_proposal")]

    operations = [migrations.RunSQL(CREATE_PROPOSAL_GUARDS, DROP_PROPOSAL_GUARDS)]
