from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse
from django.http.request import split_domain_port, validate_host

# Every public projection is addressed by the visitor's own host, so none of
# them can be answered under the panel's allow-list.
PUBLIC_SITE_ROUTES = (
    "/api/v1/public/site/",
    "/api/v1/public/site/inquiries/",
    "/api/v1/public/site/feed.xml",
    "/api/v1/public/site/atom.xml",
    "/api/v1/public/site/llms.txt",
    "/api/v1/public/site/sitemap.xml",
    "/api/v1/public/site/robots.txt",
)
# Media is addressed by asset id, so the tuple above cannot list it.
PUBLIC_MEDIA_PREFIX = "/api/v1/public/site/media/"
# What a company's booking form says to anybody — its offers, its free days —
# is read by the blocks of the company's own site from the visitor's browser,
# at the site's host (ADR-072, slice 5d). Reads only: a booking is made on
# the form, on the platform's host. The address names the company by the
# form's slug, so the host decides nothing here.
PUBLIC_BOOKING_PREFIX = "/api/v1/booking/public/"


class DynamicHostValidationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME", "")
        domain, _port = split_domain_port(str(raw_host).casefold())
        if not domain:
            raise DisallowedHost("Nagłówek Host ma nieprawidłowy format.")
        public = (
            request.path_info in PUBLIC_SITE_ROUTES
            or request.path_info.startswith(PUBLIC_MEDIA_PREFIX)
            or (
                request.method in ("GET", "HEAD")
                and request.path_info.startswith(PUBLIC_BOOKING_PREFIX)
            )
        )
        if not public and not validate_host(
            domain,
            settings.CONFIGURED_ALLOWED_HOSTS,
        ):
            raise DisallowedHost("Host nie należy do konfiguracji aplikacji.")
        return self.get_response(request)
