from rest_framework.exceptions import APIException, PermissionDenied

from .context import TenantContext, current_tenant_context


class ActiveOrganizationRequired(APIException):
    status_code = 409
    default_detail = "Wybierz aktywną organizację."
    default_code = "active_organization_required"


class OrganizationPermissionDenied(PermissionDenied):
    default_detail = "Brak uprawnienia do tej operacji."
    default_code = "organization_permission_denied"


def authorize(permission: str, *, owner_only: bool = False) -> TenantContext:
    context = current_tenant_context()
    if context is None:
        raise ActiveOrganizationRequired
    if not context.has_permission(permission) or (owner_only and context.role_key != "owner"):
        raise OrganizationPermissionDenied
    return context
