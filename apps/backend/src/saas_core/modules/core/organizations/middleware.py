from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.http import HttpRequest, HttpResponse, JsonResponse

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User

from .context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from .models import (
    WORKING_ORGANIZATION_STATUSES,
    Membership,
    MembershipStatus,
    WorkspaceKind,
)
from .pre_tenant import PRE_TENANT_DB
from .security_settings import membership_requires_mfa

ACTIVE_ORGANIZATION_SESSION_KEY = "organizations_active_organization_id"
TENANT_CONTEXT_EXEMPT_PATHS = {
    "/api/v1/organizations/",
    "/api/v1/invitations/accept/",
    "/api/v1/session/active-organization/",
}
#: What a person must still reach when their company requires two-factor
#: sign-in and they have none (answer 35a): turning it on, signing out, their
#: own account. Switching to another company is exempt above.
MFA_SETUP_PATHS = ("/api/v1/auth/",)


class _MfaMissing:
    """The company requires 2FA of this membership and the account has none."""


MFA_MISSING = _MfaMissing()


class TenantContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            not request.path.startswith("/api/v1/")
            or request.path in TENANT_CONTEXT_EXEMPT_PATHS
            or not request.user.is_authenticated
        ):
            return self.get_response(request)

        with transaction.atomic():
            context = self._resolve_context(request)
            if context is MFA_MISSING:
                if request.path.startswith(MFA_SETUP_PATHS):
                    return self.get_response(request)
                return _mfa_required()
            if context is None:
                return self.get_response(request)
            assert isinstance(context, TenantContext)

            cast(Any, request).tenant_context = context
            with activate_tenant_context(context):
                set_local_organization_id(context.organization_id)
                return self.get_response(request)

    def _resolve_context(self, request: HttpRequest) -> TenantContext | _MfaMissing | None:
        raw_organization_id = request.session.get(ACTIVE_ORGANIZATION_SESSION_KEY)
        try:
            organization_id = UUID(raw_organization_id)
        except (TypeError, ValueError, AttributeError):
            request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
            return None

        user = cast(User, request.user)
        # ADR-041: the question "does this account belong to that organization"
        # is asked before the answer could set a tenant, so it goes through the
        # door. The lock lives only as long as the read: it never protected
        # anything the request could not have read a moment earlier, and
        # holding it for the whole request would keep a second connection open
        # for every authenticated call.
        with transaction.atomic(using=PRE_TENANT_DB):
            membership = self._membership_for(request, organization_id=organization_id)
        if membership is None:
            request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
            return None
        # The platform's own workspace publishes every product's marketing
        # pages, so a stolen password there is worth more than one customer's
        # site. The requirement sits on entering the workspace rather than on a
        # list of "high-risk" endpoints, because that list is never complete.
        if membership.organization.workspace_kind == WorkspaceKind.PLATFORM and (
            not has_confirmed_mfa(user)
        ):
            request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
            return None
        # A company may require two-factor sign-in of its people (35a). The
        # requirement is read under the company's tenant, and the account's
        # 2FA only when the requirement covers this membership.
        set_local_organization_id(membership.organization_id)
        if membership_requires_mfa(membership) and not has_confirmed_mfa(user):
            return MFA_MISSING
        return context_from_membership(membership)

    def _membership_for(
        self, request: HttpRequest, *, organization_id: UUID
    ) -> Membership | None:
        user = cast(User, request.user)
        return (
            Membership.objects.using(PRE_TENANT_DB)
            .select_for_update()
            .select_related("organization", "role")
            .filter(
                organization_id=organization_id,
                user_id=user.pk,
                status=MembershipStatus.ACTIVE,
                organization__status__in=WORKING_ORGANIZATION_STATUSES,
            )
            .filter(
                Q(role__organization__isnull=True) | Q(role__organization_id=F("organization_id"))
            )
            .first()
        )


def _mfa_required() -> JsonResponse:
    """The same shape as every other refusal; the panel shows the 2FA setup."""
    return JsonResponse(
        {
            "type": "about:blank",
            "title": "Wymagana weryfikacja dwuetapowa",
            "status": 403,
            "detail": (
                "Ta firma wymaga weryfikacji dwuetapowej. Włącz ją w ustawieniach konta, "
                "aby pracować w tej firmie."
            ),
            "code": "organization_mfa_required",
        },
        status=403,
        content_type="application/problem+json",
    )
