"""The deployment's own publisher workspace (W9.6.1).

Its pages need versions, publication, rollback and media exactly like a
customer's, so it is an ordinary tenant. What it must not have is the customer
machinery around it — nobody signs up for it, nobody is invited into it, and it
is never billed.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.middleware import (
    ACTIVE_ORGANIZATION_SESSION_KEY,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
    Role,
    WorkspaceKind,
)
from saas_core.modules.core.organizations.platform_workspace import (
    PlatformWorkspaceConflict,
    ensure_platform_workspace,
    platform_workspace_slug,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def operator(*, email: str = "operator@example.test", staff: bool = True) -> User:
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.is_staff = staff
    user.save()
    return user


def confirm_mfa(user: User) -> str:
    """Enrols TOTP and hands back the secret, so a test can sign in with it."""
    from saas_core.modules.core.identity.mfa import (
        begin_totp_enrollment,
        confirm_totp_enrollment,
        current_totp_code,
    )

    enrollment = begin_totp_enrollment(user=user)
    confirm_totp_enrollment(user=user, code=current_totp_code(enrollment.secret))
    return enrollment.secret


def login(client: APIClient, user: User) -> Any:
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    return client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )


def test_exactly_one_publisher_exists_per_deployment() -> None:
    first, created = ensure_platform_workspace()
    assert created is True
    assert first.workspace_kind == WorkspaceKind.PLATFORM
    assert first.slug == platform_workspace_slug()

    # Running the provisioning twice must not make a second publisher.
    again, created_again = ensure_platform_workspace()
    assert created_again is False
    assert again.id == first.id

    # And nothing else may create one either, which is where the partial unique
    # index earns its place: a race between two deploys cannot be caught by an
    # application-level check.
    with pytest.raises(IntegrityError):
        Organization.objects.create(
            name="Drugi wydawca",
            slug="platform-other",
            workspace_kind=WorkspaceKind.PLATFORM,
        )


def test_a_customer_cannot_take_the_workspace_name_and_become_the_publisher() -> None:
    """Somebody registering the deployment's slug first must not inherit the
    platform's pages."""
    Organization.objects.create(
        name="Podszywacz",
        slug=platform_workspace_slug(),
        workspace_kind=WorkspaceKind.BUSINESS,
    )
    with pytest.raises(PlatformWorkspaceConflict):
        ensure_platform_workspace()


def test_the_create_organization_api_does_not_offer_the_platform_kind() -> None:
    user = User.objects.create_user(email="founder@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200

    refused = client.post(
        "/api/v1/organizations/",
        {
            "name": "Podszywacz",
            "slug": "podszywacz",
            "workspace_kind": "platform",
            "organization_type": settings.DEFAULT_ORGANIZATION_TYPE,
        },
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert refused.status_code == 400
    assert not Organization.objects.filter(
        workspace_kind=WorkspaceKind.PLATFORM
    ).exists()


def test_entering_the_workspace_requires_confirmed_operator_mfa() -> None:
    """The platform publishes every product's marketing pages, so a stolen
    password there is worth more than one customer's site."""
    workspace, _ = ensure_platform_workspace()
    # Not staff: identity already refuses a staff sign-in without MFA, so an
    # ordinary member is what actually exercises the workspace's own rule.
    person = operator(email="redaktor@example.test", staff=False)
    Membership.objects.create(
        organization=workspace,
        user=person,
        role=Role.objects.get(key="owner", organization=None),
        status=MembershipStatus.ACTIVE,
    )

    client = APIClient(enforce_csrf_checks=True)
    assert login(client, person).status_code == 200
    session = client.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(workspace.id)
    session.save()

    # No MFA: the workspace is simply not entered, and the stale selection is
    # dropped rather than left pointing somewhere the request cannot go.
    without_mfa = client.get("/api/v1/organizations/current/")
    assert without_mfa.status_code == 409

    from saas_core.modules.core.identity.mfa import current_totp_code

    secret = confirm_mfa(person)
    client_with_mfa = APIClient(enforce_csrf_checks=True)
    # With MFA enrolled the sign-in becomes a challenge, which is the point.
    assert login(client_with_mfa, person).status_code == 202
    assert (
        client_with_mfa.post(
            "/api/v1/auth/login/mfa/",
            # A step later than enrolment: the code used to confirm cannot be
            # replayed, which is the whole point of TOTP.
            {"code": current_totp_code(secret, at=timezone.now().timestamp() + 30)},
            format="json",
            HTTP_X_CSRFTOKEN=client_with_mfa.cookies["csrftoken"].value,
        ).status_code
        == 200
    )
    session = client_with_mfa.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(workspace.id)
    session.save()
    assert client_with_mfa.get("/api/v1/organizations/current/").status_code == 200


def test_nobody_is_invited_into_the_platform_workspace() -> None:
    from saas_core.modules.core.organizations.context import (
        TenantContext,
        activate_tenant_context,
    )
    from saas_core.modules.core.organizations.lifecycle import create_invitation
    from saas_core.modules.core.organizations.platform_workspace import (
        PlatformWorkspaceForbidden,
    )

    workspace, _ = ensure_platform_workspace()
    person = operator()
    membership = Membership.objects.create(
        organization=workspace,
        user=person,
        role=Role.objects.get(key="owner", organization=None),
        status=MembershipStatus.ACTIVE,
    )

    class FakeRequest:
        user = person

    with (
        activate_tenant_context(
            TenantContext(
                organization_id=workspace.id,
                membership_id=membership.id,
                actor_id=person.id,
                role_key="owner",
                permissions=frozenset({"organization.members.manage"}),
            )
        ),
        pytest.raises(PlatformWorkspaceForbidden),
    ):
        create_invitation(
            request=FakeRequest(),  # type: ignore[arg-type]
            email="ktos@example.test",
            role_key="editor",
        )


def test_the_deployment_does_not_sell_itself_a_subscription() -> None:
    from saas_core.modules.core.organizations.context import (
        TenantContext,
        activate_tenant_context,
    )
    from saas_core.modules.core.organizations.platform_workspace import (
        PlatformWorkspaceForbidden,
    )
    from saas_core.modules.shared.billing.services import create_setup_checkout

    workspace, _ = ensure_platform_workspace()
    person = operator()
    membership = Membership.objects.create(
        organization=workspace,
        user=person,
        role=Role.objects.get(key="owner", organization=None),
        status=MembershipStatus.ACTIVE,
    )

    with (
        activate_tenant_context(
            TenantContext(
                organization_id=workspace.id,
                membership_id=membership.id,
                actor_id=person.id,
                role_key="owner",
                permissions=frozenset({"organization.billing.manage"}),
            )
        ),
        pytest.raises(PlatformWorkspaceForbidden),
    ):
        create_setup_checkout(plan_key="starter", idempotency_key="platform-checkout")


def test_provisioning_grants_internal_entitlements_through_the_audited_path() -> None:
    """No privileged route around the entitlement checks: the workspace gets
    its features the way an operator would grant them to a customer."""
    from saas_core.modules.core.organizations.models import OrganizationAuditEntry
    from saas_core.modules.shared.billing.models import EntitlementGrant, GrantSource

    person = operator()
    confirm_mfa(person)

    call_command("provision_platform_workspace", operator=person.email)

    workspace = Organization.objects.get(workspace_kind=WorkspaceKind.PLATFORM)
    assert workspace.status == OrganizationStatus.ACTIVE
    assert Membership.objects.filter(
        organization=workspace, user=person, status=MembershipStatus.ACTIVE
    ).exists()

    grants = EntitlementGrant.all_objects.filter(organization=workspace)
    assert sorted(grant.feature.key for grant in grants) == [
        "sites.enabled",
        "storage.enabled",
    ]
    assert all(grant.source == GrantSource.OVERRIDE for grant in grants)
    assert all(grant.granted_by_id == person.id for grant in grants)
    assert OrganizationAuditEntry.objects.filter(organization=workspace).exists()

    # Safe to repeat: a second run adds neither a workspace nor a second grant.
    call_command("provision_platform_workspace", operator=person.email)
    assert Organization.objects.filter(workspace_kind=WorkspaceKind.PLATFORM).count() == 1
    assert EntitlementGrant.all_objects.filter(organization=workspace).count() == 2


def test_provisioning_refuses_an_actor_who_is_not_an_operator_with_mfa() -> None:
    plain = operator(email="nie-operator@example.test", staff=False)
    with pytest.raises(CommandError):
        call_command("provision_platform_workspace", operator=plain.email)

    staff_without_mfa = operator(email="bez-mfa@example.test")
    with pytest.raises(CommandError):
        call_command("provision_platform_workspace", operator=staff_without_mfa.email)

    assert not Organization.objects.filter(
        workspace_kind=WorkspaceKind.PLATFORM
    ).exists()


def test_a_customer_membership_never_reaches_the_platform_workspace() -> None:
    """The foreign-tenant case: belonging to one organization must not select
    another, whatever the session claims."""
    workspace, _ = ensure_platform_workspace()
    outsider = User.objects.create_user(email="klient@example.test", password=PASSWORD)
    outsider.status = UserStatus.ACTIVE
    outsider.save()
    own = Organization.objects.create(
        name="Klient", slug="klient", status=OrganizationStatus.ACTIVE
    )
    Membership.objects.create(
        organization=own,
        user=outsider,
        role=Role.objects.get(key="owner", organization=None),
        status=MembershipStatus.ACTIVE,
    )

    client = APIClient(enforce_csrf_checks=True)
    assert login(client, outsider).status_code == 200
    session = client.session
    session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(workspace.id)
    session.save()

    assert client.get("/api/v1/organizations/current/").status_code == 409
