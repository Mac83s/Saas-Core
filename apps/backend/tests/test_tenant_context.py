from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

import pytest
from django.contrib.sessions.backends.base import SessionBase
from django.core import signing
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
    ACTING_TRIGGER_KINDS,
    ACTING_VIA,
    MissingTenantContext,
    TenantContext,
    TenantContextTransactionRequired,
    acting_context,
    activate_tenant_context,
    context_from_membership,
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
    TENANT_TASK_CONTEXT_SALT,
    InvalidTenantTaskContext,
    deferred_tenant_context,
    issue_service_task_contract,
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


def test_reminder_service_contract_opens_without_a_membership() -> None:
    organization_id = create_membership().organization_id
    contract = issue_service_task_contract(
        organization_id=organization_id,
        role_key="booking_reminder",
        permissions=frozenset({"booking.reminder.send"}),
        causation_id="booking:reminder",
    )
    Membership.objects.filter(organization_id=organization_id).update(
        status=MembershipStatus.REVOKED, revoked_at=timezone.now()
    )

    with tenant_task_context(contract) as context:
        assert context.principal_kind == "service"
        assert context.membership_id == context.actor_id == organization_id
        assert context.permissions == frozenset({"booking.reminder.send"})


@pytest.mark.parametrize(
    "permissions",
    [set(), {"booking.reminder.send", "booking.appointment.read"}, {"booking.public.read"}],
)
def test_reminder_service_contract_refuses_any_other_scope(permissions: set[str]) -> None:
    contract = issue_service_task_contract(
        organization_id=create_membership().organization_id,
        role_key="booking_reminder",
        permissions=frozenset(permissions),
        causation_id="booking:reminder",
    )

    with pytest.raises(InvalidTenantTaskContext, match="zakres"), tenant_task_context(contract):
        pass


CONVERSATION = f"conversation:{uuid7()}"
JOB = f"translation_job:{uuid7()}"


def a_person() -> TenantContext:
    """A signed-in person's context, without a database row."""
    return TenantContext(
        organization_id=uuid7(),
        membership_id=uuid7(),
        actor_id=uuid7(),
        role_key="owner",
        permissions=frozenset({"organization.read"}),
    )


def test_acting_keeps_every_right_of_the_membership_it_wraps() -> None:
    """ADR-076 §6: acting says through what a person's membership acts. It
    changes neither who acts nor what they may do."""
    person = context_from_membership(create_membership())

    acting = acting_context(person, via="assistant", ref=CONVERSATION)

    assert (acting.acting_via, acting.acting_ref, acting.acting_trigger) == (
        "assistant",
        CONVERSATION,
        "",
    )
    assert replace(acting, acting_via="", acting_ref="") == person
    assert person.acting_via == ""
    for via, ref_kind in ACTING_VIA.items():
        for trigger_kind in ACTING_TRIGGER_KINDS:
            trigger = f"{trigger_kind}:{uuid7()}"
            ref = f"{ref_kind}:{uuid7()}"
            assert acting_context(person, via=via, ref=ref, trigger=trigger).acting_trigger == (
                trigger
            )


@pytest.mark.parametrize(
    "acting",
    [
        pytest.param({"acting_via": "mcp", "acting_ref": CONVERSATION}, id="unknown-via"),
        pytest.param({"acting_via": "assistant", "acting_ref": JOB}, id="ref-of-another-kind"),
        pytest.param(
            {"acting_via": "assistant", "acting_ref": "conversation:42"}, id="ref-not-a-uuid"
        ),
        pytest.param(
            {"acting_via": "assistant", "acting_ref": f"conversation:{str(uuid7()).upper()}"},
            id="ref-not-canonical",
        ),
        pytest.param({"acting_via": "assistant"}, id="via-without-ref"),
        pytest.param(
            {
                "acting_via": "assistant",
                "acting_ref": CONVERSATION,
                "acting_trigger": f"webhook:{uuid7()}",
            },
            id="unknown-trigger-kind",
        ),
        pytest.param(
            {"acting_via": "assistant", "acting_ref": CONVERSATION, "acting_trigger": "schedule"},
            id="trigger-without-id",
        ),
        pytest.param({"acting_ref": CONVERSATION}, id="ref-without-via"),
        pytest.param({"acting_trigger": f"user:{uuid7()}"}, id="trigger-without-via"),
    ],
)
def test_acting_refuses_an_unknown_vocabulary(acting: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        replace(a_person(), **acting)


def test_acting_refuses_a_non_membership_principal_and_nesting() -> None:
    """Only a person's own membership acts for that person: a key or a service
    acting "for" somebody would borrow a standing it never had. Acting does
    not stack, and asking for it names a known channel."""
    person = a_person()
    for principal_kind in ("api_key", "service", "image_generation_job"):
        with pytest.raises(ValueError, match="membership"):
            acting_context(
                replace(person, principal_kind=principal_kind),
                via="assistant",
                ref=CONVERSATION,
            )
    acting = acting_context(person, via="assistant", ref=CONVERSATION)
    with pytest.raises(ValueError, match="zagnieżdżania"):
        acting_context(acting, via="ai_translation", ref=JOB)
    with pytest.raises(ValueError, match="kanał"):
        acting_context(person, via="", ref="")


def test_a_task_contract_carries_acting_and_never_an_opened_gate() -> None:
    """Work queued while the membership acts for its person (version 3) runs
    acting so too: a task that dropped it would act as the person deciding
    directly, past every person-only gate. The labels a consent opened for one
    run are never carried — the task starts with every gate shut."""
    membership = create_membership()
    person = context_for(membership)
    acting = acting_context(person, via="assistant", ref=CONVERSATION)

    with activate_tenant_context(acting):
        contract = issue_tenant_task_contract(causation_id="acting:task")
    with activate_tenant_context(person):
        plain = issue_tenant_task_contract(causation_id="person:task")

    with tenant_task_context(contract) as context:
        assert (context.acting_via, context.acting_ref, context.acting_opened) == (
            "assistant",
            CONVERSATION,
            frozenset(),
        )
    with tenant_task_context(plain) as context:
        assert context.acting_via == ""
    assert signing.loads(plain, salt=TENANT_TASK_CONTEXT_SALT)["version"] == 2

    payload = signing.loads(contract, salt=TENANT_TASK_CONTEXT_SALT)
    for forged in (
        {**payload, "version": 2},
        {**payload, "acting_via": ""},
        {**payload, "acting_ref": "conversation:not-a-uuid"},
        {**payload, "principal_kind": "service"},
    ):
        signed = signing.dumps(forged, salt=TENANT_TASK_CONTEXT_SALT, compress=True)
        with pytest.raises(InvalidTenantTaskContext), tenant_task_context(signed):
            pass


def test_deferred_context_reapplies_acting_and_refuses_an_inactive_membership() -> None:
    """Work a translation job does later runs as the membership of the person
    who enabled it, asked again at that moment, and still marked as acting."""
    membership = create_membership()
    stored: dict[str, Any] = {
        "organization_id": membership.organization_id,
        "membership_id": membership.id,
        "actor_id": membership.user_id,
        "causation_id": "translation-job:test",
    }
    trigger = f"api_key:{uuid7()}"

    with deferred_tenant_context(
        **stored, acting_via="ai_translation", acting_ref=JOB, acting_trigger=trigger
    ) as context:
        assert current_tenant_context() is context
        assert (context.acting_via, context.acting_ref, context.acting_trigger) == (
            "ai_translation",
            JOB,
            trigger,
        )
        assert replace(
            context, acting_via="", acting_ref="", acting_trigger=""
        ) == context_from_membership(membership)
    with deferred_tenant_context(**stored) as context:
        assert context.acting_via == ""
    assert current_tenant_context() is None

    Membership.objects.filter(pk=membership.pk).update(
        status=MembershipStatus.REVOKED,
        revoked_at=timezone.now(),
    )
    with (
        pytest.raises(InvalidTenantTaskContext, match="aktywny"),
        deferred_tenant_context(**stored, acting_via="ai_translation", acting_ref=JOB),
    ):
        pass


def test_deferred_context_refuses_acting_that_does_not_hold() -> None:
    """A stored right to act whose acting does not hold is refused like a
    membership that is gone, never quietly run as the person directly."""
    membership = create_membership()
    stored: dict[str, Any] = {
        "organization_id": membership.organization_id,
        "membership_id": membership.id,
        "actor_id": membership.user_id,
        "causation_id": "translation-job:broken",
    }

    for acting in (
        {"acting_ref": JOB},
        {"acting_via": "ai_translation", "acting_ref": CONVERSATION},
        {"acting_via": "ai_translation", "acting_ref": JOB, "acting_trigger": "schedule:jutro"},
    ):
        with (
            pytest.raises(InvalidTenantTaskContext, match="w imieniu osoby"),
            deferred_tenant_context(**stored, **acting),
        ):
            pass
    assert current_tenant_context() is None


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
