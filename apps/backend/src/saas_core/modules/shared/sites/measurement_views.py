from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.shared.notifications.api_key_middleware import IsSessionOrApiKey

from .measurement import read_site_metrics


class SiteMetricsQuerySerializer(serializers.Serializer[dict[str, Any]]):
    since = serializers.DateField()
    until = serializers.DateField()


class SitePageViewCountSerializer(serializers.Serializer[dict[str, Any]]):
    day = serializers.DateField()
    path = serializers.CharField()
    kind = serializers.ChoiceField(choices=["page", "entry", "collection"])
    publication_id = serializers.UUIDField()
    views = serializers.IntegerField()


class SiteInquiryCountSerializer(serializers.Serializer[dict[str, Any]]):
    day = serializers.DateField()
    path = serializers.CharField()
    publication_id = serializers.UUIDField()
    block_position = serializers.IntegerField()
    count = serializers.IntegerField()


class SiteMetricsSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    since = serializers.DateField()
    until = serializers.DateField()
    counter_enabled = serializers.BooleanField()
    page_views = SitePageViewCountSerializer(many=True)
    inquiries = SiteInquiryCountSerializer(many=True)


class SiteMetricsView(APIView):
    """Views and inquiries as daily numbers (ADR-060).

    Reachable with a key only through its own scope, `content:metrics`: a key
    issued to write content does not thereby learn how a customer's site does.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_metrics_retrieve",
        tags=["sites"],
        parameters=[SiteMetricsQuerySerializer],
        responses={
            200: SiteMetricsSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = SiteMetricsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        metrics = read_site_metrics(
            site_id=site_id,
            since=query.validated_data["since"],
            until=query.validated_data["until"],
        )
        response = Response(SiteMetricsSerializer(metrics).data)
        response["Cache-Control"] = "private, no-store"
        return response
