"""The routes a deployment answers on, composed from its modules.

A module that is not in the profile registers nothing: no API prefix, no public
renderer, no internal endpoint. That is the point of the composition — a
`core-only` deployment that still answered `/api/v1/billing/` would be one
product pretending to be two.

Every mount is built inside a function so a disabled module's views are never
imported. Importing them would work (the files are on disk) and then fail
somewhere else, because their models belong to an app the registry never
installed.
"""

from collections.abc import Callable, Collection

from django.conf import settings
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from saas_core.observability.metrics import metrics_view

Route = URLPattern | URLResolver


def _identity_routes() -> list[Route]:
    return [path("api/v1/auth/", include("saas_core.modules.core.identity.urls"))]


def _organization_routes() -> list[Route]:
    return [
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
    ]


def _health_routes() -> list[Route]:
    return [path("api/v1/", include("saas_core.modules.core.health.urls"))]


def _billing_routes() -> list[Route]:
    return [path("api/v1/billing/", include("saas_core.modules.shared.billing.urls"))]


def _media_routes() -> list[Route]:
    return [path("api/v1/media/", include("saas_core.modules.shared.media.urls"))]


def _notification_routes() -> list[Route]:
    return [
        path(
            "api/v1/notifications/",
            include("saas_core.modules.shared.notifications.urls"),
        )
    ]


def _profile_routes() -> list[Route]:
    return [
        path("api/v1/profiles/", include("saas_core.modules.shared.profiles.urls")),
        # The public catalogue (ADR-053), under the same `public` prefix the site
        # renderer uses: unauthenticated, tenant-free, and a slug is what names
        # the tenant. Kept inside the module's routes so a deployment without
        # `shared.profiles` answers nothing rather than importing its views.
        path(
            "api/v1/public/catalog/",
            include("saas_core.modules.shared.profiles.public_urls"),
        ),
    ]


def _booking_routes() -> list[Route]:
    return [path("api/v1/booking/", include("saas_core.modules.shared.booking.urls"))]


def _sites_routes() -> list[Route]:
    from saas_core.modules.shared.sites.public_views import (  # noqa: PLC0415
        CaddyDomainAuthorizationView,
        PublicSiteAtomView,
        PublicSiteFeedView,
        PublicSiteMediaView,
        PublicSitePageView,
        PublicSiteRobotsView,
        PublicSiteSitemapView,
    )

    return [
        # Caddy asks this before issuing a certificate for a customer's domain,
        # so it lives with the module that knows about domains at all.
        path(
            "internal/caddy/domains/authorize/",
            CaddyDomainAuthorizationView.as_view(),
            name="caddy-domain-authorize",
        ),
        path("api/v1/sites/", include("saas_core.modules.shared.sites.urls")),
        path("api/v1/public/site/", PublicSitePageView.as_view(), name="public-site-page"),
        path(
            "api/v1/public/site/feed.xml",
            PublicSiteFeedView.as_view(),
            name="public-site-feed",
        ),
        path(
            "api/v1/public/site/atom.xml",
            PublicSiteAtomView.as_view(),
            name="public-site-atom",
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
    ]


#: Which module owns which routes. Ordered so a reader sees the composition in
#: the same order the profile lists it.
MODULE_ROUTES: dict[str, Callable[[], list[Route]]] = {
    "core.health": _health_routes,
    "core.identity": _identity_routes,
    "core.organizations": _organization_routes,
    "shared.billing": _billing_routes,
    "shared.sites": _sites_routes,
    "shared.seo": lambda: [path("api/v1/seo/", include("saas_core.modules.shared.seo.urls"))],
    "shared.media": _media_routes,
    "shared.notifications": _notification_routes,
    "shared.profiles": _profile_routes,
    "shared.booking": _booking_routes,
    "shared.farms": lambda: [path("api/v1/farms/", include("saas_core.modules.shared.farms.urls"))],
    "shared.inventory": lambda: [
        path("api/v1/inventory/", include("saas_core.modules.shared.inventory.urls"))
    ],
}


def _descriptor_routes(module_id: str) -> list[Route]:
    """Routes of a module core does not name — a product's vertical (ADR-049).

    The descriptor says where its API lives and which Django app serves it, so
    a product adds a module without editing this file.
    """
    descriptor = settings.MODULE_CATALOG[module_id]
    if (
        descriptor.layer != "vertical"
        or descriptor.url_prefix is None
        or descriptor.django_app is None
    ):
        return []
    prefix = descriptor.url_prefix.strip("/")
    return [path(f"{prefix}/", include(f"{descriptor.django_app}.urls"))]


def urlpatterns_for(active_modules: Collection[str]) -> list[Route]:
    """The routing table for one composition.

    A function rather than a module-level constant so a test can ask what
    `core-only` would answer on without booting a second Django.
    """
    active = set(active_modules)
    routes: list[Route] = [
        path("internal/admin/", admin.site.urls),
        path("internal/metrics/", metrics_view, name="metrics"),
    ]
    for module_id, build in MODULE_ROUTES.items():
        if module_id in active:
            routes.extend(build())
    for module_id in sorted(active - set(MODULE_ROUTES)):
        routes.extend(_descriptor_routes(module_id))
    routes += [
        path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
        path(
            "internal/api-docs/",
            SpectacularSwaggerView.as_view(url_name="openapi-schema"),
            name="api-docs",
        ),
    ]
    return routes


def module_route_prefixes(active_modules: Collection[str]) -> dict[str, str]:
    """{static URL prefix: module} for the shared and vertical modules composed.

    What the module gate (ADR-050) looks up to know which module a request
    belongs to. Core routes are left out: core belongs to every organization.
    """
    prefixes: dict[str, str] = {}
    for module_id in active_modules:
        if not module_id.startswith(("shared.", "vertical.")):
            continue
        build = MODULE_ROUTES.get(module_id)
        routes = build() if build is not None else _descriptor_routes(module_id)
        for route in routes:
            prefixes["/" + str(route.pattern).split("<", 1)[0]] = module_id
    return prefixes


urlpatterns = urlpatterns_for(settings.ACTIVE_MODULES)
