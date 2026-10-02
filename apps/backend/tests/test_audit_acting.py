"""Acting for a person in the organization's history (ADR-076 §6): the row says
through what the membership acted and for which conversation or job, while
`channel` stays the principal and `actor_user` the person."""

from __future__ import annotations

from uuid import uuid7

import pytest

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import (
    OrganizationPermissionDenied,
    authorize,
)
from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.core.organizations.services import update_current_organization
from saas_core.modules.core.organizations.tasks import deferred_tenant_context

pytestmark = pytest.mark.django_db


def member(*, slug: str, role_key: str = "owner") -> Membership:
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug.replace("-", " ").title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    return Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )


def rename(membership: Membership, name: str) -> OrganizationAuditEntry:
    organization = Organization.objects.get(pk=membership.organization_id)
    update_current_organization(changes={"version": organization.version, "name": name})
    return OrganizationAuditEntry.objects.get(
        organization_id=membership.organization_id,
        action=OrganizationAuditAction.ORGANIZATION_UPDATED,
    )


def test_a_change_through_the_assistant_names_the_person_and_the_conversation() -> None:
    owner = member(slug="w-imieniu")
    conversation = f"conversation:{uuid7()}"

    with activate_tenant_context(
        acting_context(context_from_membership(owner), via="assistant", ref=conversation)
    ):
        entry = rename(owner, "Salon Uroda")

    assert entry.actor_user_id == owner.user_id
    assert entry.channel == "membership"
    assert (entry.acting_via, entry.acting_ref, entry.acting_trigger) == (
        "assistant",
        conversation,
        "",
    )


def test_a_person_acting_directly_leaves_acting_empty() -> None:
    owner = member(slug="bez-asystenta")

    with activate_tenant_context(context_from_membership(owner)):
        entry = rename(owner, "Salon Bez Asystenta")
    # Written with no context at all, as a management command or a data fix.
    outside = record_audit(
        organization=Organization.objects.get(pk=owner.organization_id),
        action=OrganizationAuditAction.ORGANIZATION_UPDATED,
        actor=None,
    )

    assert entry.channel == "membership"
    assert (entry.acting_via, entry.acting_ref, entry.acting_trigger) == ("", "", "")
    assert (outside.channel, outside.acting_via, outside.acting_ref, outside.acting_trigger) == (
        "",
        "",
        "",
        "",
    )


def test_deferred_work_of_a_job_writes_its_rows_on_behalf_of_the_person() -> None:
    """The translation automat's job runs later as the membership of the person
    who enabled it, and every row it writes says so, with what started it."""
    owner = member(slug="automat-tlumaczen")
    job = f"translation_job:{uuid7()}"
    trigger = f"api_key:{uuid7()}"

    with deferred_tenant_context(
        organization_id=owner.organization_id,
        membership_id=owner.id,
        actor_id=owner.user_id,
        causation_id="translation-job:test",
        acting_via="ai_translation",
        acting_ref=job,
        acting_trigger=trigger,
    ):
        entry = rename(owner, "Salon Po Tlumaczeniu")

    assert entry.actor_user_id == owner.user_id
    assert entry.channel == "membership"
    assert (entry.acting_via, entry.acting_ref, entry.acting_trigger) == (
        "ai_translation",
        job,
        trigger,
    )


def test_acting_never_widens_what_the_membership_may_do() -> None:
    viewer = member(slug="tylko-podglad", role_key="viewer")

    with activate_tenant_context(
        acting_context(
            context_from_membership(viewer), via="assistant", ref=f"conversation:{uuid7()}"
        )
    ):
        with pytest.raises(OrganizationPermissionDenied):
            authorize(SETTINGS_MANAGE)
        with pytest.raises(OrganizationPermissionDenied):
            rename(viewer, "Cudza Nazwa")

    assert Organization.objects.get(pk=viewer.organization_id).name == "Tylko Podglad"
    assert not OrganizationAuditEntry.objects.filter(
        organization_id=viewer.organization_id
    ).exists()
