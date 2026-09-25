"""Isolation of the image job table (ADR-039): FORCE RLS, the relation trigger, SET LOCAL first.

The suite connects as the table owner, so the policy is proved here under a
role that is neither owner nor BYPASSRLS, and order by comparing query indices.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from psycopg import sql

import test_image_generation_worker as worker_tests
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.image_generation.models import ImageGenerationJob
from saas_core.modules.shared.image_generation.worker import run_job
from test_image_generation_api import generation_client, post
from test_image_generation_worker import FakeProvider, image

job = worker_tests.job
media = worker_tests.media

pytestmark = pytest.mark.django_db

TABLE = "image_generation_imagegenerationjob"
TENANT = (
    "(organization_id = "
    "(NULLIF(current_setting('app.organization_id'::text, true), ''::text))::uuid)"
)


def test_table_forces_rls_with_the_tenant_policy() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
            [TABLE],
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(
            "SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = %s",
            [TABLE],
        )
        assert cursor.fetchall() == [(f"{TABLE}_tenant_isolation", TENANT, TENANT)]


def test_trigger_refuses_a_membership_of_another_organization(job: ImageGenerationJob) -> None:
    _, other = generation_client("imagegen-rls-foreign")
    foreign = Membership.objects.get(organization=other)
    with pytest.raises(IntegrityError), transaction.atomic():
        ImageGenerationJob.all_objects.filter(pk=job.pk).update(membership_id=foreign.id)


def test_run_job_sets_the_tenant_before_reading_the_job(
    job: ImageGenerationJob, media: Any
) -> None:
    with CaptureQueriesContext(connection) as queries:
        run_job(job.organization_id, job.id, provider=FakeProvider(image()))
    statements = [query["sql"] for query in queries.captured_queries]
    first_set = next(i for i, text in enumerate(statements) if "SET LOCAL app.organization" in text)
    first_read = next(i for i, text in enumerate(statements) if f'FROM "{TABLE}"' in text)
    assert first_set < first_read


def test_nonowner_role_sees_only_its_tenant(job: ImageGenerationJob) -> None:
    client, other = generation_client("imagegen-rls-other")
    assert post(client).status_code == 202
    tenants = [job.organization_id, other.id]
    role = sql.Identifier(f"saas_core_imagegen_probe_{uuid4().hex}")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(TABLE), role))
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                for tenant in [None, uuid4(), *tenants]:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(tenant) if tenant else ""],
                    )
                    cursor.execute(
                        sql.SQL("SELECT organization_id FROM {}").format(sql.Identifier(TABLE))
                    )
                    rows = cursor.fetchall()
                    assert {row[0] for row in rows} == ({tenant} if tenant in tenants else set())
                cursor.execute("RESET ROLE")
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(
                sql.SQL("REVOKE SELECT ON {} FROM {}").format(sql.Identifier(TABLE), role)
            )
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))


def test_module_migrations_roll_back_and_forward() -> None:
    from django.db.migrations.executor import MigrationExecutor

    from saas_core.modules.core.organizations.models import Role
    from saas_core.modules.shared.billing.models import (
        CreditOperation,
        Feature,
        Plan,
        QuotaDefinition,
    )

    def state() -> tuple[bool, bool, bool, bool, bool]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [TABLE])
            table = cursor.fetchone()[0]
        plans = Plan.objects.select_related("current_version")
        return (
            table,
            Feature.objects.filter(key="image_generation.enabled", is_active=True).exists(),
            QuotaDefinition.objects.filter(key="image_generation.monthly").exists(),
            CreditOperation.objects.filter(key="image_generation.generate").exists(),
            all(
                "image_generation.enabled" in plan.current_version.feature_keys
                and "image_generation.monthly" in plan.current_version.quotas
                for plan in plans
                if plan.current_version is not None
            )
            and "image_generation.run"
            in Role.objects.get(key="manager", organization=None, organization_type="").permissions,
        )

    assert state() == (True, True, True, True, True)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    MigrationExecutor(connection).migrate([("image_generation", None)])
    with_nothing = state()
    assert with_nothing[:4] == (False, False, False, False)
    assert not any(
        "image_generation.enabled" in plan.current_version.feature_keys
        for plan in Plan.objects.select_related("current_version")
        if plan.current_version is not None
    )
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes("image_generation"))
    assert state() == (True, True, True, True, True)
