"""Execute the proposal policy as a nonowner role, beyond owner-bypassed ORM tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import connection, transaction
from psycopg import sql

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import ContentProposal

pytestmark = pytest.mark.django_db


def test_proposal_metadata_isolated_under_real_nonowner_role() -> None:
    tenants = [
        Organization.objects.create(name=f"RLS {i}", slug=f"proposal-rls-{i}") for i in range(2)
    ]
    for tenant in tenants:
        ContentProposal.all_objects.create(
            organization=tenant,
            resource_type="site_page",
            resource_id=uuid4(),
            version=1,
            summary="Synthetic review",
            risk="low",
            metadata_before={"description": tenant.slug},
        )
    role = sql.Identifier(f"saas_core_proposal_probe_{uuid4().hex}")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON sites_contentproposal TO {}").format(role))
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                cursor.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
                assert cursor.fetchone() == (False, False)
                cursor.execute("SELECT set_config('app.organization_id', '', true)")
                cursor.execute("SELECT count(*) FROM sites_contentproposal")
                assert cursor.fetchone() == (0,)
                counts = [0]
                for tenant in tenants:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)", [str(tenant.id)]
                    )
                    cursor.execute(
                        "SELECT organization_id, metadata_before FROM sites_contentproposal"
                    )
                    rows = cursor.fetchall()
                    assert len(rows) == 1
                    assert rows[0][0] == tenant.id
                    counts.append(len(rows))
                cursor.execute("RESET ROLE")
                print(f"ContentProposal nonowner NOSUPERUSER NOBYPASSRLS: no tenant/A/B = {counts}")
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(sql.SQL("REVOKE SELECT ON sites_contentproposal FROM {}").format(role))
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))
