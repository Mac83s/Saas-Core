from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.views import View
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .public_feeds import (
    render_site_feed,
    render_site_robots,
    render_site_sitemap,
)
from .public_media import serve_public_media
from .publication_routing import (
    PublicSiteNotFound,
    public_page_payload,
    resolve_public_page,
)
from .serializers import PublicSitePageSerializer
from .tls import authorize_tls_hostname


class CaddyDomainAuthorizationView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request: Request) -> Response:
        decision = authorize_tls_hostname(request.query_params.get("domain", ""))
        if decision.allowed:
            return Response(status=204)
        return Response(status=429 if decision.reason == "rate_limited" else 404)


class PublicSitePageView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="public_site_page_retrieve",
        tags=["public-sites"],
        parameters=[
            OpenApiParameter(
                name="path",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
            )
        ],
        responses={
            200: PublicSitePageSerializer,
            308: None,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        host = str(request.META.get("HTTP_HOST", ""))
        page = resolve_public_page(host=host, path=request.query_params.get("path", ""))
        if page.redirect_url is not None:
            response = Response(status=308)
            response["Location"] = page.redirect_url
            return response
        return Response(public_page_payload(page))


class PublicSiteFeedView(View):
    """Plain Django, deliberately.

    DRF negotiates a renderer before the handler runs and this view has none to
    offer — it builds the document itself. A feed reader (and our own proxy)
    sends `Accept: application/xml`, which DRF answered 406 without ever
    reaching the code below.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        try:
            return render_site_feed(host=str(request.META.get("HTTP_HOST", "")))
        except PublicSiteNotFound:
            return HttpResponseNotFound()


class PublicSiteSitemapView(View):
    """See `PublicSiteFeedView`: plain Django for the same reason."""

    def get(self, request: HttpRequest) -> HttpResponse:
        try:
            return render_site_sitemap(host=str(request.META.get("HTTP_HOST", "")))
        except PublicSiteNotFound:
            return HttpResponseNotFound()


class PublicSiteRobotsView(View):
    """See `PublicSiteFeedView`: plain Django, no renderer to negotiate."""

    def get(self, request: HttpRequest) -> HttpResponse:
        try:
            return render_site_robots(host=str(request.META.get("HTTP_HOST", "")))
        except PublicSiteNotFound:
            return HttpResponseNotFound()


class PublicSiteMediaView(View):
    """See `PublicSiteFeedView`: plain Django, and the bytes are the response."""

    def get(self, request: HttpRequest, asset_id: UUID) -> HttpResponse:
        try:
            return serve_public_media(
                host=str(request.META.get("HTTP_HOST", "")), asset_id=asset_id
            )
        except PublicSiteNotFound:
            return HttpResponseNotFound()
