from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from saas_core.observability.metrics import metrics_view

urlpatterns = [
    path("internal/admin/", admin.site.urls),
    path("internal/metrics/", metrics_view, name="metrics"),
    path("api/v1/auth/", include("saas_core.modules.core.identity.urls")),
    path(
        "api/v1/organizations/",
        include("saas_core.modules.core.organizations.urls"),
    ),
    path(
        "api/v1/session/",
        include("saas_core.modules.core.organizations.session_urls"),
    ),
    path(
        "api/v1/invitations/",
        include("saas_core.modules.core.organizations.invitation_urls"),
    ),
    path("api/v1/billing/", include("saas_core.modules.shared.billing.urls")),
    path("api/v1/", include("saas_core.modules.core.health.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path(
        "internal/api-docs/",
        SpectacularSwaggerView.as_view(url_name="openapi-schema"),
        name="api-docs",
    ),
]
