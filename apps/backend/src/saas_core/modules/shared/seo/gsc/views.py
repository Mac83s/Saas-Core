from typing import Any
from uuid import UUID

from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..source import SourceError
from . import serializers as s
from . import services

PRIVATE = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}


class GscView(APIView):
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, SourceError):
            # Do not mark the outer tenant transaction for rollback: unknown remote
            # outcomes must retain the erasure fence and original operation identity.
            return Response(
                {
                    "type": "about:blank",
                    "title": "Search Console unavailable",
                    "status": 503 if exc.retryable else 409,
                    "code": exc.code,
                    "detail": "Refresh or retry the saved operation.",
                    "correlation_id": getattr(self.request, "correlation_id", None),
                },
                status=503 if exc.retryable else 409,
                headers=PRIVATE,
                content_type="application/problem+json",
            )
        response = super().handle_exception(exc)
        for key, value in PRIVATE.items():
            response[key] = value
        return response


def validated(cls: Any, value: Any) -> dict[str, Any]:
    serializer = cls(data=value)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


class PrepareView(GscView):
    @method_decorator(csrf_protect)
    @extend_schema(request=s.GscSiteInput, responses=s.GscProperties)
    def post(self, request: Request) -> Response:
        return Response(
            services.prepare(**validated(s.GscSiteInput, request.data)), headers=PRIVATE
        )


class PropertiesView(GscView):
    @extend_schema(parameters=[s.GscSiteInput], responses=s.GscProperties)
    def get(self, request: Request) -> Response:
        return Response(
            services.properties(**validated(s.GscSiteInput, request.query_params)), headers=PRIVATE
        )


class ConnectionView(GscView):
    @extend_schema(parameters=[s.GscSiteInput], responses=s.GscConnection)
    def get(self, request: Request) -> Response:
        return Response(
            services.connection_status(**validated(s.GscSiteInput, request.query_params)),
            headers=PRIVATE,
        )


class AuthorizeView(GscView):
    @method_decorator(csrf_protect)
    @extend_schema(request=s.GscAuthorizeInput, responses=s.GscAuthorization)
    def post(self, request: Request) -> Response:
        return Response(
            services.authorize(request, **validated(s.GscAuthorizeInput, request.data)),
            headers=PRIVATE,
        )


class CallbackView(GscView):
    @extend_schema(
        parameters=[OpenApiParameter(name=name, type=str) for name in ("state", "code", "error")],
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseRedirect:
        try:
            result = services.callback(
                request,
                state=request.query_params.get("state", ""),
                code=request.query_params.get("code", ""),
                denied="error" in request.query_params,
            )
        except (APIException, SourceError):
            result = "pl:failed"
        locale, outcome = result.split(":")
        response = HttpResponseRedirect(
            ("/en" if locale == "en" else "") + "/panel/seo/search-console?result=" + outcome
        )
        for key, value in PRIVATE.items():
            response[key] = value
        return response


class GrantListView(GscView):
    @extend_schema(
        operation_id="seo_gsc_grants_list",
        parameters=[s.GscGrantListQuery],
        responses=s.GscGrantList,
    )
    def get(self, request: Request) -> Response:
        return Response(
            services.list_grants(**validated(s.GscGrantListQuery, request.query_params)),
            headers=PRIVATE,
        )

    @method_decorator(csrf_protect)
    @extend_schema(request=s.GscGrantInput, responses=s.GscGrant)
    def post(self, request: Request) -> Response:
        return Response(
            services.create_grant(**validated(s.GscGrantInput, request.data)), headers=PRIVATE
        )


class GrantView(GscView):
    @extend_schema(responses=s.GscGrant)
    def get(self, request: Request, grant_id: UUID) -> Response:
        return Response(services.read_grant(grant_id), headers=PRIVATE)

    @method_decorator(csrf_protect)
    @extend_schema(
        operation_id="seo_gsc_grant_retry", request=s.StrictSerializer, responses=s.GscGrant
    )
    def post(self, request: Request, grant_id: UUID) -> Response:
        validated(s.StrictSerializer, request.data)
        return Response(services.retry_grant(grant_id), headers=PRIVATE)


class SyncView(GscView):
    @extend_schema(responses=s.GscSyncHistory)
    def get(self, request: Request, grant_id: UUID) -> Response:
        return Response(services.sync_history(grant_id), headers=PRIVATE)

    @method_decorator(csrf_protect)
    @extend_schema(request=s.GscSyncInput, responses=s.GscSync)
    def post(self, request: Request, grant_id: UUID) -> Response:
        return Response(
            services.sync(grant_id=grant_id, **validated(s.GscSyncInput, request.data)),
            headers=PRIVATE,
        )


class MetricsView(GscView):
    @extend_schema(parameters=[s.GscMetricsQuery], responses=s.GscMetrics)
    def get(self, request: Request, grant_id: UUID) -> Response:
        return Response(
            services.metrics(
                grant_id=grant_id, **validated(s.GscMetricsQuery, request.query_params)
            ),
            headers=PRIVATE,
        )


class RevokeView(GscView):
    @method_decorator(csrf_protect)
    @extend_schema(request=s.StrictSerializer, responses=s.GscGrant)
    def post(self, request: Request, grant_id: UUID) -> Response:
        validated(s.StrictSerializer, request.data)
        return Response(services.revoke(grant_id), headers=PRIVATE)


class DisconnectView(GscView):
    @method_decorator(csrf_protect)
    @extend_schema(request=s.GscDisconnectInput, responses=s.GscDisconnected)
    def post(self, request: Request) -> Response:
        data = validated(s.GscDisconnectInput, request.data)
        data.pop("confirm_workspace_disconnect")
        return Response(services.disconnect(**data), headers=PRIVATE)
