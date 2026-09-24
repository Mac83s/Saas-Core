from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid7

import pytest
from django.contrib.sessions.backends.base import SessionBase
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.middleware import MANAGED_SESSION_KEY
from saas_core.modules.core.identity.models import User, UserSession, UserStatus
from saas_core.modules.core.identity.tokens import digest_secret
from saas_core.modules.core.organizations.context import (
    MissingTenantContext,
    TenantContext,
    TenantContextTransactionRequired,
    activate_tenant_context,
    current_tenant_context,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.middleware import (
    ACTIVE_ORGANIZATION_SESSION_KEY,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    issue_tenant_task_contract,
    tenant_task_context,
)
from saas_core.observability import correlation_id

pytestmark = pytest.mark.django_db(transaction=True)


def tenant_probe(_request: HttpRequest) -> JsonResponse:
    context = current_tenant_context()
    if context is None:
        return JsonResponse({"active": False})
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.organization_id', true)")
        database_organization_id = cursor.fetchone()[0]
    return JsonResponse({
        "active": True,
        "organization_id": str(context.organization_id),
        "role": context.role_key,
        "permissions": sorted(context.permissions),
        "database_organization_id": database_organization_id,
    })


urlpatterns = [
    path("api/v1/tenant-probe/", tenant_probe),
    path("", include("saas_core.config.urls")),
]


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def create_active_user() -> User:
    user = User.objects.create_user(email="tenant@example.com")
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def create_membership(
    *,
    user: User | None = None,
    organization_status: str = OrganizationStatus.ACTIVE,
    membership_status: str = MembershipStatus.ACTIVE,
) -> Membership:
    actor = user or create_active_user()
    owner_role, _ = Role.objects.get_or_create(
        key="owner",
        organization=None,
        organization_type="",
        defaults={
            "name": "Owner",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["owner"]),
            "is_immutable": True,
        },
    )
    organization = Organization.objects.create(
        name=f"Organization {uuid7()}",
        slug=f"organization-{uuid7()}",
        status=organization_status,
        archived_at=(
            timezone.now() if organization_status == OrganizationStatus.ARCHIVED else None
        ),
    )
    return Membership.objects.create(
        organization=organization,
        user=actor,
        role=owner_role,
        status=membership_status,
    )


def authenticated_client(membership: Membership) -> APIClient:
    client = APIClient()
    client.force_login(membership.user)
    session: SessionBase = client.session
    assert session.session_key is not None
    tracking = UserSession.objects.create(
        user=membership.user,
        session_key_hash=digest_secret(session.session_key),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    session[MANAGED_SESSION_KEY] = str(tracking.id)
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(membership.organization_id)
    session.save()
    return client


def context_for(membership: Membership) -> TenantContext:
    return TenantContext(
        organization_id=membership.organization_id,
        membership_id=membership.id,
        actor_id=membership.user_id,
        role_key=membership.role.key,
        permissions=frozenset(membership.role.permissions),
    )


def test_missing_context_fails_closed_without_database_transaction() -> None:
    with pytest.raises(MissingTenantContext):
        require_tenant_context()

    with pytest.raises(TenantContextTransactionRequired):
        set_local_organization_id(uuid7())


def test_context_is_immutable_and_reset_after_exception() -> None:
    membership = create_membership()
    context = context_for(membership)

    with pytest.raises(RuntimeError, match="stop"), activate_tenant_context(context):
        assert require_tenant_context() is context
        with pytest.raises((AttributeError, TypeError)):
            context.role_key = "viewer"  # type: ignore[misc]
        raise RuntimeError("stop")

    assert current_tenant_context() is None


@override_settings(ROOT_URLCONF=__name__)
def test_middleware_uses_only_server_session_and_sets_database_context() -> None:
    membership = create_membership()
    other_membership = create_membership(user=membership.user)
    client = authenticated_client(membership)

    response = client.get(
        "/api/v1/tenant-probe/",
        {"organization_id": str(other_membership.organization_id)},
        HTTP_X_ORGANIZATION_ID=str(other_membership.organization_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "organization_id": str(membership.organization_id),
        "role": "owner",
        "permissions": sorted(membership.role.permissions),
        "database_organization_id": str(membership.organization_id),
    }
    assert current_tenant_context() is None


@pytest.mark.parametrize(
    ("organization_status", "membership_status"),
    [
        (OrganizationStatus.SUSPENDED, MembershipStatus.ACTIVE),
        (OrganizationStatus.ARCHIVED, MembershipStatus.ACTIVE),
        (OrganizationStatus.ACTIVE, MembershipStatus.SUSPENDED),
        (OrganizationStatus.ACTIVE, MembershipStatus.REVOKED),
    ],
)
@override_settings(ROOT_URLCONF=__name__)
def test_middleware_clears_invalid_active_organization(
    organization_status: str,
    membership_status: str,
) -> None:
    membership = create_membership(
        organization_status=organization_status,
        membership_status=MembershipStatus.ACTIVE,
    )
    if membership_status != MembershipStatus.ACTIVE:
        Membership.objects.filter(pk=membership.pk).update(
            status=membership_status,
            revoked_at=(
                timezone.now()
                if membership_status in {MembershipStatus.REVOKED, MembershipStatus.LEFT}
                else None
            ),
        )
    client = authenticated_client(membership)

    response = client.get("/api/v1/tenant-probe/")

    assert response.status_code == 200
    assert response.json() == {"active": False}
    assert ACTIVE_ORGANIZATION_SESSION_KEY not in client.session
    assert current_tenant_context() is None


@override_settings(ROOT_URLCONF=__name__)
def test_middleware_rejects_membership_with_cross_tenant_custom_role() -> None:
    membership = create_membership()
    other_membership = create_membership(user=membership.user)
    other_role = Role.objects.create(
        organization=other_membership.organization,
        key="custom-admin",
        name="Custom admin",
        scope=RoleScope.ORGANIZATION,
        permissions=list(SYSTEM_ROLE_PERMISSIONS["owner"]),
    )
    Membership.objects.filter(pk=membership.pk).update(role=other_role)
    client = authenticated_client(membership)

    response = client.get("/api/v1/tenant-probe/")

    assert response.status_code == 200
    assert response.json() == {"active": False}
    assert ACTIVE_ORGANIZATION_SESSION_KEY not in client.session


def test_a_task_locks_its_membership_but_not_the_organization_row() -> None:
    """A task holds its transaction for its whole body; locking the joined
    organization row with it made every request that references the
    organization (a foreign key checked at COMMIT) wait on the task, and a
    media task waiting for an asset such a request held deadlocked (24.09)."""
    from django.test.utils import CaptureQueriesContext

    membership = create_membership()
    with activate_tenant_context(context_for(membership)):
        contract = issue_tenant_task_contract(causation_id="lock-test")
    with CaptureQueriesContext(connection) as queries, tenant_task_context(contract):
        pass
    locks = [q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]]
    assert len(locks) == 1
    assert locks[0].endswith('FOR UPDATE OF "organizations_membership"'), locks[0]


def test_signed_task_contract_revalidates_membership_and_restores_context() -> None:
    membership = create_membership()
    request_correlation_id = str(uuid7())
    outer_correlation_token = correlation_id.set(request_correlation_id)
    try:
        with activate_tenant_context(context_for(membership)):
            contract = issue_tenant_task_contract(causation_id="test-task")
    finally:
        correlation_id.reset(outer_correlation_token)

    with tenant_task_context(contract) as context:
        assert context.organization_id == membership.organization_id
        assert correlation_id.get() == request_correlation_id
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.organization_id', true)")
            assert cursor.fetchone()[0] == str(membership.organization_id)

    assert current_tenant_context() is None
    assert correlation_id.get() is None


@pytest.mark.parametrize("contract", ["", "not-a-signed-contract"])
def test_task_rejects_missing_or_invalid_contract(contract: str) -> None:
    with pytest.raises(InvalidTenantTaskContext), tenant_task_context(contract):
        pass


def test_task_contract_is_bound_to_expected_causation_payload() -> None:
    membership = create_membership()
    with activate_tenant_context(context_for(membership)):
        contract = issue_tenant_task_contract(causation_id="media-upload:one")

    with (
        pytest.raises(InvalidTenantTaskContext, match="payloadu"),
        tenant_task_context(contract, expected_causation_id="media-upload:two"),
    ):
        pass

    with tenant_task_context(contract, expected_causation_id="media-upload:one"):
        assert current_tenant_context() is not None


def test_task_rejects_contract_after_membership_is_revoked() -> None:
    membership = create_membership()
    with activate_tenant_context(context_for(membership)):
        contract = issue_tenant_task_contract(causation_id="revoke-test")
    Membership.objects.filter(pk=membership.pk).update(
        status=MembershipStatus.REVOKED,
        revoked_at=timezone.now(),
    )

    with (
        pytest.raises(InvalidTenantTaskContext, match="aktywnego membership"),
        tenant_task_context(contract),
    ):
        pass


def test_task_contract_contains_uuid_correlation_id_without_request_context() -> None:
    membership = create_membership()
    with activate_tenant_context(context_for(membership)):
        contract = issue_tenant_task_contract(causation_id="scheduled-task")

    with tenant_task_context(contract):
        assert UUID(correlation_id.get() or "").version == 7


def test_first_sensitive_tenant_model_has_forced_rls() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'media_mediaasset'::regclass
            """
        )
        assert cursor.fetchone() == (True, True)
