"""The roles an organization's own work is signed with are the modules' to
declare (ADR-073 §5): core knows no module's names, and a contract whose role
nobody registered — or that carries more than the role allows — is refused."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from saas_core.modules.core.organizations import service_scopes
from saas_core.modules.core.organizations.api import register_service_scope
from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    issue_service_task_contract,
    tenant_task_context,
)
from test_tenant_context import create_membership


@pytest.fixture(autouse=True)
def own_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test declares into a copy and leaves the modules' scopes as they were."""
    monkeypatch.setattr(service_scopes, "_scopes", dict(service_scopes._scopes))


#: The roles each module's own work is signed with: (role, permissions, exact).
DECLARED = {
    "shared.booking": [
        ("public_booking", {"booking.public.read", "booking.public.manage"}, False),
        ("booking_reminder", {"booking.reminder.send"}, True),
        ("booking_requests", {"booking.request.expire"}, True),
        ("booking_notify", set(), False),
    ],
    "shared.sites": [("public_site_inquiry", {"sites.inquiry.submit"}, True)],
    "shared.commerce": [("commerce_deadlines", {"commerce.deadlines.run"}, True)],
    "shared.inventory": [("inventory_notifications", set(), False)],
    "shared.translation": [("translation_notifications", set(), False)],
}


def test_every_module_declares_the_roles_of_its_own_work() -> None:
    """Core's list is gone: a role exists exactly where its module is composed."""
    for module, roles in DECLARED.items():
        for role, permissions, exact in roles:
            scope = service_scopes.service_scope(role)
            if module not in settings.ACTIVE_MODULES:
                assert scope is None, role
                continue
            assert scope is not None, role
            assert (scope.permissions, scope.exact) == (frozenset(permissions), exact), role


def test_a_scope_takes_another_modules_permission_unless_it_is_exact() -> None:
    register_service_scope("test_public", {"a.read"})
    register_service_scope("test_public", {"b.pay"})
    register_service_scope("test_job", {"job.run"}, exact=True)
    # The same declaration again is no change.
    register_service_scope("test_job", {"job.run"}, exact=True)

    assert service_scopes._scopes["test_public"].permissions == {"a.read", "b.pay"}
    with pytest.raises(ImproperlyConfigured):
        register_service_scope("test_job", {"other.run"})
    with pytest.raises(ImproperlyConfigured):
        register_service_scope("test_public", {"a.read"}, exact=True)


@pytest.mark.django_db
def test_a_contract_opens_only_within_its_registered_scope() -> None:
    organization_id = create_membership().organization_id
    register_service_scope("test_public", {"a.read", "b.pay"})
    register_service_scope("test_job", {"job.run"}, exact=True)

    def opens(role_key: str, permissions: set[str]) -> bool:
        contract = issue_service_task_contract(
            organization_id=organization_id,
            role_key=role_key,
            permissions=frozenset(permissions),
            causation_id="test",
        )
        try:
            with tenant_task_context(contract) as context:
                return context.role_key == role_key and context.principal_kind == "service"
        except InvalidTenantTaskContext:
            return False

    # A part of an open scope is fine; an exact one carries all of it or nothing opens.
    assert opens("test_public", {"a.read"}) and opens("test_public", set())
    assert not opens("test_public", {"a.read", "c.other"})
    assert opens("test_job", {"job.run"})
    assert not opens("test_job", set())
    assert not opens("nobody_declared", set())
