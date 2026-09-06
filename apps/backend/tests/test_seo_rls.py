from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.db import connection, transaction
from psycopg import sql

import test_seo_audits as seo_tests
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.seo.callbacks import receive_callback
from saas_core.modules.shared.sites.models import Domain, Site
from test_seo_audits import FakeSource, callback_for, order_for
from test_sites_api import sites_client

seo = seo_tests.seo
pytestmark = pytest.mark.django_db


def test_three_audit_tables_with_real_nonowner_role(seo: Any) -> None:
    order_a = order_for(seo)
    receive_callback(*callback_for(order_a, FakeSource(order_a)))
    client, org, user = sites_client(slug="seo-rls-b", role_key="owner")
    EntitlementSnapshot.all_objects.filter(organization=org).update(
        features={"seo.audit.enabled": True, "sites.enabled": True}, quotas={"credits.monthly": 100}
    )
    site = Site.all_objects.create(organization=org, created_by=user, name="B", slug="b")
    Domain.all_objects.create(
        organization=org,
        site=site,
        hostname="b.example.test",
        kind="custom",
        status="verified",
        is_canonical=True,
        created_by=user,
    )
    order_b = order_for((client, org, user, site, seo[4]))
    receive_callback(*callback_for(order_b, FakeSource(order_b)))
    role = sql.Identifier(f"saas_core_seo_probe_{uuid4().hex}")
    tables = ["seo_sourcesitebinding", "seo_auditorder", "seo_auditcallbackreceipt"]
    table_sql = sql.SQL(", ").join(map(sql.Identifier, tables))
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(table_sql, role))
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                cursor.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
                assert cursor.fetchone() == (False, False)
                counts = []
                for tenant in [None, order_a.organization_id, order_b.organization_id]:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(tenant) if tenant else ""],
                    )
                    row_counts = []
                    for table in tables:
                        cursor.execute(
                            sql.SQL("SELECT organization_id FROM {}").format(sql.Identifier(table))
                        )
                        rows = cursor.fetchall()
                        assert rows == ([] if tenant is None else [(tenant,)])
                        row_counts.append(len(rows))
                    counts.append(row_counts)
                cursor.execute("RESET ROLE")
                print(f"SEO three tables nonowner/no tenant,A,B counts: {counts}")
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(sql.SQL("REVOKE SELECT ON {} FROM {}").format(table_sql, role))
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))
