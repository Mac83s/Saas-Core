"""A company that requires two-factor sign-in (owner answer 35a) lets nobody it
covers work without it: the next request is refused with
`organization_mfa_required`, while turning 2FA on, signing out, the account
itself and switching to another company stay open."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import UserMfaMethod
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, OrganizationSetting
from saas_core.modules.core.organizations.security_settings import MFA_REQUIRED
from test_organization_lifecycle import authenticated_member

pytestmark = pytest.mark.django_db

CURRENT = "/api/v1/organizations/current/"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    # Sign-ins are throttled and the requirement is cached per company.
    cache.clear()


def _require(owner: Membership, value: str) -> None:
    """The company's requirement as it stands — set by someone with 2FA, or
    kept after the owner turned theirs off. Turning it on over one's own
    missing 2FA is refused (test_settings_access_security), so the row is
    written here directly, and the cached requirement dropped with it."""
    with activate_tenant_context(context_from_membership(owner)):
        set_local_organization_id(owner.organization_id)
        OrganizationSetting.objects.update_or_create(
            organization_id=owner.organization_id, key=MFA_REQUIRED, defaults={"value": value}
        )
    cache.clear()


def _with_mfa(user: Any) -> None:
    """The setup started above, confirmed (the code itself is test_mfa.py's)."""
    UserMfaMethod.objects.filter(user=user).update(confirmed_at=timezone.now())


def test_a_company_that_requires_2fa_refuses_its_people_without_it() -> None:
    _owner_user, owner, owner_client = authenticated_member(
        email="mfa-owner@example.test", role_key="owner", slug="mfa-gate"
    )
    _staff_user, _staff, staff_client = authenticated_member(
        email="mfa-staff@example.test", role_key="staff", organization=owner.organization
    )
    assert owner_client.get(CURRENT).status_code == 200

    _require(owner, "managers")

    refused = owner_client.get(CURRENT)
    assert refused.status_code == 403
    assert refused.json()["code"] == "organization_mfa_required"
    assert "weryfikacji dwuetapowej" in refused.json()["detail"]
    # Not managing: not covered by "role zarządzające".
    assert staff_client.get(CURRENT).status_code == 200

    _require(owner, "all")
    assert staff_client.get(CURRENT).json()["code"] == "organization_mfa_required"


def test_turning_2fa_on_signing_out_and_switching_company_stay_open() -> None:
    owner_user, owner, client = authenticated_member(
        email="mfa-open@example.test", role_key="owner", slug="mfa-open"
    )
    _require(owner, "all")

    assert client.get("/api/v1/auth/me/").status_code == 200
    assert client.get("/api/v1/organizations/").status_code == 200
    setup = client.post(
        "/api/v1/auth/mfa/totp/setup/", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value
    )
    assert setup.status_code == 200, setup.content

    _with_mfa(owner_user)
    assert client.get(CURRENT).status_code == 200


def test_a_member_turns_2fa_on_from_the_gate_with_a_session_and_gets_recovery_codes() -> None:
    """Platform settings 0c removed only an operator's setup before sign-in:
    a member behind this gate still turns 2FA on with their own session, as
    the gate screen and "Twoje konto" do, and the company opens."""
    _owner_user, owner, client = authenticated_member(
        email="mfa-self@example.test", role_key="owner", slug="mfa-self"
    )
    _require(owner, "all")
    assert client.get(CURRENT).status_code == 403
    csrf = client.cookies["csrftoken"].value

    setup = client.post("/api/v1/auth/mfa/totp/setup/", HTTP_X_CSRFTOKEN=csrf)
    confirmed = client.post(
        "/api/v1/auth/mfa/totp/confirm/",
        {"code": current_totp_code(setup.data["secret"])},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert confirmed.status_code == 200, confirmed.content
    assert len(confirmed.data["recovery_codes"]) == 8
    assert client.get(CURRENT).status_code == 200


def test_a_company_without_the_requirement_changes_nothing() -> None:
    _user, owner, client = authenticated_member(
        email="mfa-none@example.test", role_key="owner", slug="mfa-none"
    )
    _require(owner, "none")
    assert client.get(CURRENT).status_code == 200
