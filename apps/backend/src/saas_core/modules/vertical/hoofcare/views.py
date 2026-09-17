from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .models import Farm
from .serializers import (
    AnimalInputSerializer,
    AnimalSerializer,
    FarmInputSerializer,
    FarmSerializer,
    HerdVisitSerializer,
)
from .services import create_animal, create_farm, list_animals, list_farms, list_visits

MODULE_ID = "vertical.hoofcare"

ModuleSerializer = inline_serializer(
    name="HoofCareModule",
    fields={"module": serializers.CharField(), "version": serializers.IntegerField()},
)


class ModuleView(APIView):
    """What this deployment composed. Cheap probe for the panel and for deploys."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ModuleSerializer, operation_id="hoofcare_module", tags=["hoofcare"])
    def get(self, request: Request) -> Response:
        payload: dict[str, Any] = {"module": MODULE_ID, "version": 1}
        return Response(payload)


@method_decorator(csrf_protect, name="dispatch")
class FarmListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: FarmSerializer(many=True), 403: ProblemDetailsSerializer},
        operation_id="hoofcare_farm_list",
        tags=["hoofcare"],
    )
    def get(self, request: Request) -> Response:
        return Response(FarmSerializer(list_farms(), many=True).data)

    @extend_schema(
        request=FarmInputSerializer,
        responses={201: FarmSerializer, 400: ProblemDetailsSerializer},
        operation_id="hoofcare_farm_create",
        tags=["hoofcare"],
    )
    def post(self, request: Request) -> Response:
        serializer = FarmInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        farm = create_farm(data=dict(serializer.validated_data))
        return Response(FarmSerializer(farm).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class AnimalListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("farm_id", str, description="Ogranicz do gospodarstwa.")],
        responses={200: AnimalSerializer(many=True), 403: ProblemDetailsSerializer},
        operation_id="hoofcare_animal_list",
        tags=["hoofcare"],
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("farm_id")
        farm_id = UUID(raw) if raw else None
        return Response(AnimalSerializer(list_animals(farm_id=farm_id), many=True).data)

    @extend_schema(
        request=AnimalInputSerializer,
        responses={201: AnimalSerializer, 404: ProblemDetailsSerializer},
        operation_id="hoofcare_animal_create",
        tags=["hoofcare"],
    )
    def post(self, request: Request) -> Response:
        serializer = AnimalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        farm_id = data.pop("farm_id")
        try:
            animal = create_animal(farm_id=farm_id, data=data)
        except Farm.DoesNotExist as error:
            raise NotFound("Nie ma takiego gospodarstwa.") from error
        return Response(AnimalSerializer(animal).data, status=201)


class HerdVisitListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: HerdVisitSerializer(many=True), 403: ProblemDetailsSerializer},
        operation_id="hoofcare_visit_list",
        tags=["hoofcare"],
    )
    def get(self, request: Request) -> Response:
        return Response(HerdVisitSerializer(list_visits(), many=True).data)
