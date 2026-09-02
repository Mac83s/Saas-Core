from django.db import migrations

# ADR-039: forced row-level security is the default regime for a tenant table.
# Sites had it on five tables and left the rest to the service layer, because
# the public renderer serves a visitor who has no tenant context. The renderer
# reads six tables directly — domain, site, publication, collection, entry and
# entry publication — and those stay open, declared as `backend.publicTables`
# in the module descriptor. Everything below is working state that nothing
# reads without a tenant: drafts, versions, blocks, translations, redirects,
# onboarding, automation grants and the mutation journals. They now get the
# policy media and booking already have.
PRIVATE_TABLES = (
    "sites_domainmutation",
    "sites_siteonboardingdraft",
    "sites_siteonboardingmutation",
    "sites_page",
    "sites_pagetranslation",
    "sites_pagetranslationmutation",
    "sites_siteredirect",
    "sites_pageversion",
    "sites_pageblock",
    "sites_contententryversion",
    "sites_contentautomationgrant",
)


def _enable(table: str) -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {table}_tenant_isolation ON {table}
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
"""


def _disable(table: str) -> str:
    return f"""
DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("sites", "0023_content_proposal_rls")]

    operations = [
        migrations.RunSQL(
            "".join(_enable(table) for table in PRIVATE_TABLES),
            "".join(_disable(table) for table in reversed(PRIVATE_TABLES)),
        )
    ]
