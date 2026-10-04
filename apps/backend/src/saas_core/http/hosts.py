from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
# the form, on the platform's host. And only at a host the platform serves
# that company's published site on (`_own_site_read`): the address names the
# company by the form's slug, and the host has to name the same one.
PUBLIC_BOOKING_PREFIX = "/api/v1/booking/public/"

# This layer names no module, so the two that know answer through it. Without
# either — a product without sites, or without the form — no host outside the
# allow-list reads anything here.
#: `host` → the company whose published site the platform serves there, or
#: None. Registered by sites: read as its public renderer reads a host.
_site_host: Callable[[str], Any | None] | None = None
#: An address prefix a site's own pages read under → `rest of the path` → the
#: company that address names, or None.
_site_reads: dict[str, Callable[[str], Any | None]] = {}


def register_site_host(resolver: Callable[[str], Any | None]) -> None:
    global _site_host
    _site_host = resolver


def register_site_reads(prefix: str, owner: Callable[[str], Any | None]) -> None:
    _site_reads[prefix] = owner


def _own_site_read(request: HttpRequest, host: str) -> bool:
    """Whether a company's own site is reading that company's records: `GET`
    or `HEAD` under a registered prefix, at a host of a published site, for
    the company the site belongs to. Another company's site, a domain still
    unverified and a host nobody is served at are all just an unknown host."""
    if request.method not in ("GET", "HEAD") or _site_host is None:
        return False
    for prefix, owner in _site_reads.items():
        if request.path_info.startswith(prefix):
            company = _site_host(host)
            return company is not None and owner(request.path_info[len(prefix) :]) == company
    return False


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
        if (
            not public
            and not validate_host(domain, settings.CONFIGURED_ALLOWED_HOSTS)
            and not _own_site_read(request, str(raw_host))
        ):
            raise DisallowedHost("Host nie należy do konfiguracji aplikacji.")
        return self.get_response(request)
