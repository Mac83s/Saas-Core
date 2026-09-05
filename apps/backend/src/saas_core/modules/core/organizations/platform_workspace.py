"""The deployment's own workspace.

SaaS Core publishes its customers' sites, and it also has to publish its own —
the marketing pages and the blog of MedPlano, Tanie strony and whatever comes
next. Those pages need versions, publication, rollback and media exactly like a
customer's, so they belong in an organization rather than in a second CMS.

What they must not have is the customer machinery around it. This workspace is
never signed up for, never invited into, and never billed: the operator
provisions it, and everything else about it stays an ordinary tenant so no
renderer, no service and no query needs to know it is special.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from .audit import record_audit
from .context import set_local_organization_id
from .models import (
    Organization,
    OrganizationAuditAction,
    OrganizationStatus,
    WorkspaceKind,
)
from .pre_tenant import PRE_TENANT_DB


class PlatformWorkspaceForbidden(APIException):
    status_code = 403
    default_detail = "Ta operacja nie jest dostępna dla workspace'u platformy."
    default_code = "platform_workspace_forbidden"


class PlatformWorkspaceConflict(APIException):
    status_code = 409
    default_detail = "Deployment ma już workspace platformy."
    default_code = "platform_workspace_conflict"


def platform_workspace_slug() -> str:
    """One workspace per deployment, named after it.

    Derived rather than configured: two deployments sharing a database would
    otherwise be one careless environment variable away from writing into each
    other's marketing pages.
    """
    return f"platform-{settings.DEPLOYMENT}"


def platform_workspace() -> Organization | None:
    # ADR-041: "does this deployment already have a publisher" is a question
    # about the registry, and there is no tenant it could be asked inside.
    return (
        Organization.objects.using(PRE_TENANT_DB)
        .filter(workspace_kind=WorkspaceKind.PLATFORM)
        .first()
    )


def is_platform_workspace(organization: Organization | Any) -> bool:
    return getattr(organization, "workspace_kind", None) == WorkspaceKind.PLATFORM


def assert_not_platform(organization: Organization | Any) -> None:
    """Guards the customer-facing flows.

    Called in the services rather than only in the views: the panel is not the
    only caller, and a flow that reopens this by forgetting a check in one new
    endpoint is exactly what the plan asks to prevent.
    """
    if is_platform_workspace(organization):
        raise PlatformWorkspaceForbidden


@transaction.atomic
def ensure_platform_workspace(*, name: str | None = None) -> tuple[Organization, bool]:
    """Creates the deployment's workspace, or returns the one that exists.

    Idempotent by slug and guarded by a partial unique index, so running the
    provisioning command twice — or racing two deploys — cannot end with two
    publishers for one deployment.
    """
    slug = platform_workspace_slug()
    # Same question as above, asked by name: the operator provisioning this has
    # no organization selected, because the one being looked for is the one
    # that may not exist yet.
    existing = Organization.objects.using(PRE_TENANT_DB).filter(slug=slug).first()
    if existing is not None:
        if not is_platform_workspace(existing):
            # Somebody's ordinary organization already holds the name this
            # deployment needs. Turning it into the publisher would hand them
            # the platform's pages, so it stops here for a person to resolve.
            raise PlatformWorkspaceConflict
        return existing, False

    organization = Organization(
        name=name or f"{settings.SITES_PLATFORM_DOMAIN}",
        slug=slug,
        workspace_kind=WorkspaceKind.PLATFORM,
        status=OrganizationStatus.ACTIVE,
        default_locale=settings.SITES_DEFAULT_LOCALE,
    )
    organization.full_clean(validate_unique=False)
    # The identifier exists before the row does, so the workspace and its audit
    # entry are written under the policy that guards them.
    set_local_organization_id(organization.id)
    try:
        organization.save()
    except IntegrityError as error:
        # The partial unique index refused a second publisher.
        raise PlatformWorkspaceConflict from error
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.ORGANIZATION_CREATED,
        actor=None,
        target_type="organization",
        target_id=organization.id,
        metadata={"workspace_kind": WorkspaceKind.PLATFORM, "deployment": settings.DEPLOYMENT},
    )
    return organization, True
