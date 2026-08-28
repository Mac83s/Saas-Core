"""Tenant context for requests authenticated by an API key.

Separate from `TenantContextMiddleware` for a structural reason, not a stylistic
one: that middleware lives in `core`, and the API key model lives in `shared`,
which `core` may not import. It also answers a different question — the session
middleware asks *which organization did this person select*, while this one asks
*which organization does this credential belong to*, and a credential belongs to
exactly one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import uuid7

from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework.permissions import BasePermission

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization, OrganizationStatus

from .models import ApiKey
from .services import authenticate_api_key

API_KEY_PRINCIPAL = "api_key"
API_KEY_SCHEME = "Bearer "

# Every scope the key carries becomes a permission, so a service written against
# the same domain calls as the panel is limited by the key rather than by a
# parallel authorization path.
SCOPE_PERMISSIONS: dict[str, frozenset[str]] = {
    "content:read": frozenset({"site.content.edit"}),
    "content:draft": frozenset({"site.content.edit"}),
    "content:publish": frozenset({"site.content.edit", "site.publish"}),
}


def _problem(detail: str, code: str, status: int) -> JsonResponse:
    return JsonResponse(
        {
            "type": "about:blank",
            "title": "Żądanie nie może zostać obsłużone",
            "status": status,
            "code": code,
            "detail": detail,
            "correlation_id": None,
        },
        status=status,
        content_type="application/problem+json",
    )


class ApiKeyTenantContextMiddleware:
    """Resolves a `Bearer sc_live_…` credential into a tenant context.

    Runs before the session middleware's equivalent and simply does nothing when
    no key is present, so the panel is untouched.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        header = request.headers.get("Authorization", "")
        if not request.path.startswith("/api/v1/") or not header.startswith(
            API_KEY_SCHEME
        ):
            return self.get_response(request)

        raw = header[len(API_KEY_SCHEME) :].strip()
        scopes = _requested_scopes(request)
        route = None
        for scope in scopes:
            route = authenticate_api_key(raw, required_scope=scope)
            if route is not None:
                break
        if route is None:
            # One message for an unknown key, a revoked key and a key without
            # the scope: telling them apart would help someone probing for
            # valid prefixes.
            return _problem(
                "Klucz API jest nieprawidłowy albo nie ma wymaganego zakresu.",
                "api_key_invalid",
                401,
            )

        organization = Organization.objects.filter(
            pk=route.organization_id, status=OrganizationStatus.ACTIVE
        ).first()
        if organization is None:
            return _problem(
                "Organizacja tego klucza nie jest aktywna.",
                "api_key_organization_inactive",
                403,
            )

        # Audit rows reference a real person, and the honest answer to "who did
        # this" is the operator who issued the credential. A synthetic id would
        # break every audit write and tell nobody anything.
        api_key = ApiKey.all_objects.filter(pk=route.api_key_id).first()
        if api_key is None:
            return _problem(
                "Klucz API jest nieprawidłowy albo nie ma wymaganego zakresu.",
                "api_key_invalid",
                401,
            )

        permissions: set[str] = set()
        for scope in route.scopes:
            permissions |= SCOPE_PERMISSIONS.get(scope, frozenset())
        context = TenantContext(
            organization_id=organization.id,
            # No membership exists for a key; the id is synthetic so audit rows
            # stay well-formed. `principal_kind` is what the domain services
            # actually branch on.
            membership_id=uuid7(),
            actor_id=api_key.created_by_id,
            role_key="integration",
            permissions=frozenset(permissions),
            principal_kind=API_KEY_PRINCIPAL,
            credential_id=api_key.id,
        )
        with transaction.atomic():
            cast(Any, request).tenant_context = context
            with activate_tenant_context(context):
                set_local_organization_id(organization.id)
                return self.get_response(request)


def _requested_scopes(request: HttpRequest) -> tuple[str, ...]:
    """The scopes that could authorize this request, widest last.

    A read is satisfied by any content scope; a write needs at least `draft`.
    Checked here so a key limited to reading cannot reach a write endpoint even
    if the view forgets to say so.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return ("content:read", "content:draft", "content:publish")
    if request.path.endswith("/publication/"):
        return ("content:publish",)
    return ("content:draft", "content:publish")


class IsSessionOrApiKey(BasePermission):
    """Accepts a signed-in person or a request the API-key middleware resolved.

    `IsAuthenticated` alone would reject every integration: an API key
    authenticates an organization, not a Django user, so `request.user` stays
    anonymous by design. What the caller may then *do* is decided by the domain
    services from the context's permissions and `principal_kind`, which is where
    the automation limits already live.
    """

    def has_permission(self, request: Any, view: Any) -> bool:
        if getattr(request.user, "is_authenticated", False):
            return True
        context = getattr(request, "tenant_context", None)
        return context is not None and context.principal_kind == API_KEY_PRINCIPAL
