from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from saas_core.modules.shared.sites.public_views import (
    CaddyDomainAuthorizationView,
    PublicSiteFeedView,
    PublicSiteMediaView,
    PublicSitePageView,
    PublicSiteRobotsView,
    PublicSiteSitemapView,
)
from saas_core.observability.metrics import metrics_view

urlpatterns = [
    path("internal/admin/", admin.site.urls),
    path("internal/metrics/", metrics_view, name="metrics"),
    path(
        "internal/caddy/domains/authorize/",
        CaddyDomainAuthorizationView.as_view(),
        name="caddy-domain-authorize",
    ),
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
    path("api/v1/sites/", include("saas_core.modules.shared.sites.urls")),
    path("api/v1/public/site/", PublicSitePageView.as_view(), name="public-site-page"),
    path(
        "api/v1/public/site/feed.xml",
        PublicSiteFeedView.as_view(),
        name="public-site-feed",
    ),
    path(
        "api/v1/public/site/sitemap.xml",
        PublicSiteSitemapView.as_view(),
        name="public-site-sitemap",
    ),
    path(
        "api/v1/public/site/robots.txt",
        PublicSiteRobotsView.as_view(),
        name="public-site-robots",
    ),
    path(
        "api/v1/public/site/media/<uuid:asset_id>/",
        PublicSiteMediaView.as_view(),
        name="public-site-media",
    ),
    path("api/v1/media/", include("saas_core.modules.shared.media.urls")),
    path(
        "api/v1/notifications/",
        include("saas_core.modules.shared.notifications.urls"),
    ),
    path("api/v1/booking/", include("saas_core.modules.shared.booking.urls")),
    path("api/v1/", include("saas_core.modules.core.health.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path(
        "internal/api-docs/",
        SpectacularSwaggerView.as_view(url_name="openapi-schema"),
        name="api-docs",
    ),
]
