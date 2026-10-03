from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .search_visibility import read_search_visibility


class SearchVisibilityLanguageSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField(help_text="The language's code, e.g. `de`.")
    name = serializers.CharField(help_text="The language's own name, e.g. Deutsch.")
    home_url = serializers.CharField(
        allow_null=True,
        help_text="The site's home in this language; null when the home page has no "
        "published version in it.",
    )
    llms_url = serializers.CharField(
        allow_null=True,
        help_text="The `llms.txt` of this language; null when the site has nothing to list in it.",
    )


class SearchVisibilitySiteSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    name = serializers.CharField()
    origin = serializers.CharField(
        allow_null=True,
        help_text="The address the site calls its own; null before the first publication "
        "or without a verified address.",
    )
    sitemap_url = serializers.CharField(allow_null=True)
    robots_url = serializers.CharField(allow_null=True)
    languages = SearchVisibilityLanguageSerializer(
        many=True,
        help_text="The languages the site answers in now, its own first. A language of "
        "the company the site is not written in is not listed.",
    )


class SearchVisibilitySerializer(serializers.Serializer[dict[str, Any]]):
    sites = SearchVisibilitySiteSerializer(many=True)


class SearchVisibilityView(APIView):
    """What search engines and language models are pointed at, per site and
    language (TL19): only addresses that answer now."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_search_visibility_retrieve",
        summary="Read where search engines and language models read the company's sites",
        description="Per site: the sitemap and robots.txt, and per language the site "
        "answers in now its home address and its llms.txt. Lists only addresses that "
        "answer now.",
        tags=["sites"],
        responses={
            200: SearchVisibilitySerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        response = Response(SearchVisibilitySerializer(read_search_visibility()).data)
        response["Cache-Control"] = "private, no-store"
        return response
