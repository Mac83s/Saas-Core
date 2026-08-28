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
    "/api/v1/public/site/feed.xml",
    "/api/v1/public/site/sitemap.xml",
    "/api/v1/public/site/robots.txt",
)
# Media is addressed by asset id, so the tuple above cannot list it.
PUBLIC_MEDIA_PREFIX = "/api/v1/public/site/media/"


class DynamicHostValidationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME", "")
        domain, _port = split_domain_port(str(raw_host).casefold())
        if not domain:
            raise DisallowedHost("Nagłówek Host ma nieprawidłowy format.")
        public = request.path_info in PUBLIC_SITE_ROUTES or request.path_info.startswith(
            PUBLIC_MEDIA_PREFIX
        )
        if not public and not validate_host(
            domain,
            settings.CONFIGURED_ALLOWED_HOSTS,
        ):
            raise DisallowedHost("Host nie należy do konfiguracji aplikacji.")
        return self.get_response(request)
