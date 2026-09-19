"""An organization reaches only the modules its type composes (ADR-050).

The product decides per organization type which shared and vertical modules
exist for it — a farm in HoofCare has no website builder. The menu hides them,
but the menu is not a security boundary, so the API answers 404 for them here,
in one place, rather than in every view. Mounted after the tenant middleware,
because the answer depends on which organization is acting; a request without
an organization (public pages, sign-in) is not this middleware's to judge.
"""

from collections.abc import Callable
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from saas_core.modules.core.organizations.context import current_tenant_context
from saas_core.modules.core.organizations.models import Organization


class ModuleGateMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        # Longest first, so a nested prefix wins over the one containing it.
        self._prefixes: list[tuple[str, str]] | None = None

    def __call__(self, request: HttpRequest) -> HttpResponse:
        module_id = self._module_for(request.path)
        context = current_tenant_context()
        if (
            module_id is not None
            and context is not None
            and module_id not in self._modules_of(context.organization_id)
        ):
            return JsonResponse(
                {
                    "type": "about:blank",
                    "title": "Nie znaleziono",
                    "status": 404,
                    "detail": "Ta funkcja nie jest dostępna dla tego typu organizacji.",
                    "code": "module_not_available",
                },
                status=404,
                content_type="application/problem+json",
            )
        return self.get_response(request)

    def _module_for(self, path: str) -> str | None:
        if self._prefixes is None:
            # Imported late: the URL table imports every composed module's views.
            from saas_core.config.urls import module_route_prefixes  # noqa: PLC0415

            self._prefixes = sorted(
                module_route_prefixes(settings.ACTIVE_MODULES).items(),
                key=lambda item: len(item[0]),
                reverse=True,
            )
        for prefix, module_id in self._prefixes:
            if path.startswith(prefix):
                return module_id
        return None

    @staticmethod
    def _modules_of(organization_id: UUID) -> frozenset[str]:
        organization_type = (
            Organization.objects.filter(pk=organization_id)
            .values_list("organization_type", flat=True)
            .first()
        )
        known = settings.ORGANIZATION_TYPES.get(organization_type or "")
        # A type the catalogue no longer has reaches nothing optional; a module
        # an organization cannot explain is not one it should be served.
        return known.modules if known is not None else frozenset()
