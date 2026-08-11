from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse
from django.http.request import split_domain_port, validate_host

PUBLIC_SITE_ROUTE = "/api/v1/public/site/"


class DynamicHostValidationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_host = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME", "")
        domain, _port = split_domain_port(str(raw_host).casefold())
        if not domain:
            raise DisallowedHost("Nagłówek Host ma nieprawidłowy format.")
        if request.path_info != PUBLIC_SITE_ROUTE and not validate_host(
            domain,
            settings.CONFIGURED_ALLOWED_HOSTS,
        ):
            raise DisallowedHost("Host nie należy do konfiguracji aplikacji.")
        return self.get_response(request)
