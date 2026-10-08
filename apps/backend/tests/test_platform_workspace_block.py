"""`in_platform_workspace`: the block a product's own module runs inside the
deployment's workspace (ADR-080, „Uzupełnienie PR1c").

Its public pages stand on the platform's host, where no hostname names a
tenant, and its operator's commands have no request at all — so they find the
workspace through the pre-tenant door, by this one name. Who may call it is
counted in `test_pre_tenant_door.py`; what it does is held here.

The test database connects as the owner of the tables and row-level security
does not apply to it. What these tests hold is what stays observable either
way: the statements and their order — one constant question at the door, then
`SET LOCAL` before anything the block reads, in the same transaction — and
what the setting is once the block has ended. That the policies then let
exactly the workspace's rows through is shown on a running stack, under the
application's role.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from saas_core.modules.core.organizations.api import (
    PlatformWorkspaceMissing,
    in_platform_workspace,
)
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    current_tenant_context,
    local_organization_setting,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationStatus,
    WorkspaceKind,
)
from saas_core.modules.core.organizations.platform_workspace import platform_workspace_slug

pytestmark = pytest.mark.django_db


def _organization(slug: str, *, platform: bool = False) -> Organization:
    return Organization.objects.create(
        name=slug,
        slug=platform_workspace_slug() if platform else slug,
        status=OrganizationStatus.ACTIVE,
        workspace_kind=WorkspaceKind.PLATFORM if platform else WorkspaceKind.BUSINESS,
    )


def _member_of(organization: Organization) -> TenantContext:
    return TenantContext(
        organization_id=organization.id,
        membership_id=organization.id,
        actor_id=organization.id,
        role_key="owner",
        permissions=frozenset(),
    )


def _door(sql: str) -> bool:
    return '"organizations_organization"' in sql and "'platform'" in sql


def test_the_block_sets_the_workspaces_tenant_before_anything_it_reads() -> None:
    workspace = _organization("block-publisher", platform=True)
    _organization("block-company")

    with (
        CaptureQueriesContext(connection) as captured,
        in_platform_workspace() as organization_id,
    ):
        inside = local_organization_setting()
        read = list(Organization.objects.filter(pk=organization_id).values_list("slug"))

    assert organization_id == workspace.id
    assert isinstance(organization_id, UUID)
    assert inside == str(workspace.id)
    assert read == [(platform_workspace_slug(),)]
    statements = [query["sql"] for query in captured.captured_queries]
    # One constant question at the door, and it selects the identifier alone,
    # by the kind of workspace and by this deployment's name.
    doors = [sql for sql in statements if _door(sql)]
    assert len(doors) == 1
    assert doors[0].split(" FROM ")[0] == 'SELECT "organizations_organization"."id" AS "id"'
    assert f"'{platform_workspace_slug()}'" in doors[0]
    # Then the tenant, then the block's own read — nothing ends in between.
    tenant = next(
        index
        for index, sql in enumerate(statements)
        if sql.startswith("SET LOCAL app.organization_id")
    )
    assert str(workspace.id) in statements[tenant]
    own = next(
        index
        for index, sql in enumerate(statements)
        if '"organizations_organization"."slug"' in sql and not _door(sql)
    )
    assert statements.index(doors[0]) < tenant < own
    assert not any(
        sql.startswith(("RELEASE SAVEPOINT", "ROLLBACK", "COMMIT"))
        for sql in statements[tenant:own]
    )


def test_a_deployment_without_a_workspace_says_so() -> None:
    # A company, and a publisher of another deployment in the same database.
    _organization("block-nobody")
    Organization.objects.create(
        name="other",
        slug="platform-another-deployment",
        status=OrganizationStatus.ACTIVE,
        workspace_kind=WorkspaceKind.PLATFORM,
    )
    entered = False

    with pytest.raises(PlatformWorkspaceMissing) as refused, in_platform_workspace():
        entered = True

    assert not entered
    # An answer a view may let through as it is, and a command prints.
    assert refused.value.status_code == 503
    assert refused.value.default_code == "platform_workspace_missing"
    assert "provision_platform_workspace" in str(refused.value.detail)


def test_the_callers_own_tenant_is_put_back_when_the_block_ends() -> None:
    """A tenant setting outlives the release of a savepoint. Called inside
    somebody's open transaction, the block would otherwise leave the rest of
    it running as the platform's workspace."""
    workspace = _organization("block-nested", platform=True)
    company = _organization("block-nested-company")

    with transaction.atomic():
        set_local_organization_id(company.id)
        with in_platform_workspace():
            assert local_organization_setting() == str(workspace.id)
        assert local_organization_setting() == str(company.id)

        # A block that fails is rolled back to where it began, setting and all.
        with pytest.raises(RuntimeError), in_platform_workspace():
            assert local_organization_setting() == str(workspace.id)
            raise RuntimeError
        assert local_organization_setting() == str(company.id)

        # And one that asks for its work to be undone (a command's dry run).
        with in_platform_workspace():
            transaction.set_rollback(True)
        assert local_organization_setting() == str(company.id)

        # Blocks inside one another end where each began.
        with in_platform_workspace():
            with transaction.atomic():
                set_local_organization_id(company.id)
            with in_platform_workspace():
                pass
            assert local_organization_setting() == str(company.id)
        assert local_organization_setting() == str(company.id)


@pytest.mark.django_db(transaction=True)
def test_on_its_own_the_block_is_one_transaction_and_asks_nothing_more() -> None:
    """As a view or a command calls it: no transaction is open, so there is
    no setting to put back — the block's transaction ends and the setting
    with it. The two statements of the nested case are not paid here."""
    workspace = _organization("block-alone", platform=True)
    assert not connection.in_atomic_block

    with (
        CaptureQueriesContext(connection) as captured,
        in_platform_workspace() as organization_id,
    ):
        assert connection.in_atomic_block
        assert local_organization_setting() == str(workspace.id)

    assert organization_id == workspace.id
    assert not connection.in_atomic_block
    statements = [query["sql"] for query in captured.captured_queries]
    # The door; then one transaction with the tenant set first and this
    # test's own question inside it.
    assert [sql.split(" ")[0] for sql in statements] == [
        "SELECT",
        "BEGIN",
        "SET",
        "SELECT",
        "COMMIT",
    ]
    assert _door(statements[0])
    assert "set_config" not in " ".join(statements)
    # Nothing is left behind on the connection.
    assert local_organization_setting() == ""


def test_nothing_set_before_the_block_is_nothing_set_after_it() -> None:
    workspace = _organization("block-unset", platform=True)

    with transaction.atomic():
        assert local_organization_setting() == ""
        with in_platform_workspace():
            assert local_organization_setting() == str(workspace.id)
        # Empty reads as no tenant: the policies compare with NULLIF(…, '').
        assert local_organization_setting() == ""


def test_a_signed_in_visitor_is_still_a_visitor_inside_the_block() -> None:
    """The panel's session rides on every request of its origin, so a
    visitor signed in to their own company carries its context onto the
    product's public pages. Inside the block the database is set to the
    platform's workspace; a service that asked who acts must not be told
    „that company"."""
    workspace = _organization("block-context", platform=True)
    company = _organization("block-context-company")
    theirs = _member_of(company)

    with activate_tenant_context(theirs):
        with in_platform_workspace():
            assert current_tenant_context() is None
            with pytest.raises(RuntimeError):
                require_tenant_context()
        assert current_tenant_context() == theirs
        with pytest.raises(RuntimeError), in_platform_workspace():
            raise RuntimeError
        assert current_tenant_context() == theirs

    # The workspace's own member — an operator's command — stays who they are.
    operator = _member_of(workspace)
    with activate_tenant_context(operator), in_platform_workspace():
        assert current_tenant_context() == operator
    # And a block may set its own context, as a command does for its operator.
    with in_platform_workspace(), activate_tenant_context(operator):
        assert require_tenant_context() == operator
    assert current_tenant_context() is None


def test_the_identifier_may_leave_the_block_as_a_command_takes_it() -> None:
    """A command reads the workspace's row inside the block and then runs
    its own transactions — one per record, a dry run rolled back — each
    setting its tenant. The block does not have to hold them."""
    workspace = _organization("block-command", platform=True)

    with in_platform_workspace() as organization_id:
        organization: Any = Organization.objects.get(pk=organization_id)

    assert organization == workspace
    # Loaded through the application's own connection, not the door's.
    assert organization._state.db == "default"
    for _record in range(2):
        with transaction.atomic():
            set_local_organization_id(organization.id)
            assert local_organization_setting() == str(workspace.id)
