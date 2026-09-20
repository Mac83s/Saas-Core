from __future__ import annotations

from typing import cast
from uuid import UUID

from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .serializers import (
    AnimalHealthEntrySerializer,
    AnimalInputSerializer,
    AnimalSerializer,
    AnimalUpdateSerializer,
    FarmActivationCodeSerializer,
    FarmActivationRedeemSerializer,
    FarmInputSerializer,
    FarmSerializer,
    FarmShareSerializer,
    FarmTakeoverSerializer,
    FarmUpdateSerializer,
    SpeciesListSerializer,
)
from .services import (
    create_animal,
    create_farm,
    get_farm,
    list_animals,
    list_farms,
    list_health_entries,
    update_animal,
    update_farm,
)
from .sharing import (
    issue_activation_code,
    list_shares,
    redeem_activation_code,
    revoke_share,
)
from .species import SPECIES

ERRORS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
}
SEARCH = OpenApiParameter("q", str, description="Szukaj po nazwie, miejscowości, hodowcy, numerze.")


@method_decorator(csrf_protect, name="dispatch")
class FarmListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[SEARCH],
        responses={200: FarmSerializer(many=True), **ERRORS},
        operation_id="farms_list",
        tags=["farms"],
    )
    def get(self, request: Request) -> Response:
        farms = list_farms(search=request.query_params.get("q", "").strip())
        return Response(FarmSerializer(farms, many=True).data)

    @extend_schema(
        request=FarmInputSerializer,
        responses={201: FarmSerializer, **ERRORS},
        operation_id="farms_create",
        tags=["farms"],
    )
    def post(self, request: Request) -> Response:
        serializer = FarmInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        farm = create_farm(request=cast(HttpRequest, request), data=dict(serializer.validated_data))
        return Response(FarmSerializer(farm).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class FarmDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: FarmSerializer, **ERRORS}, operation_id="farms_read", tags=["farms"]
    )
    def get(self, request: Request, farm_id: UUID) -> Response:
        return Response(FarmSerializer(get_farm(farm_id)).data)

    @extend_schema(
        request=FarmUpdateSerializer,
        responses={200: FarmSerializer, **ERRORS},
        operation_id="farms_update",
        tags=["farms"],
    )
    def patch(self, request: Request, farm_id: UUID) -> Response:
        serializer = FarmUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        farm = update_farm(
            request=cast(HttpRequest, request),
            farm_id=farm_id,
            data=dict(serializer.validated_data),
        )
        return Response(FarmSerializer(farm).data)


@method_decorator(csrf_protect, name="dispatch")
class AnimalListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("farm_id", UUID, description="Ogranicz do gospodarstwa."),
            OpenApiParameter("q", str, description="Szukaj po numerze, numerze roboczym, imieniu."),
        ],
        responses={200: AnimalSerializer(many=True), **ERRORS},
        operation_id="farms_animal_list",
        tags=["farms"],
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("farm_id")
        try:
            farm_id = UUID(raw) if raw else None
        except ValueError as error:
            raise ParseError("Nieprawidłowy identyfikator gospodarstwa.") from error
        animals = list_animals(farm_id=farm_id, search=request.query_params.get("q", "").strip())
        return Response(AnimalSerializer(animals, many=True).data)

    @extend_schema(
        request=AnimalInputSerializer,
        responses={201: AnimalSerializer, **ERRORS},
        operation_id="farms_animal_create",
        tags=["farms"],
    )
    def post(self, request: Request) -> Response:
        serializer = AnimalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        farm_id = data.pop("farm_id")
        animal = create_animal(request=cast(HttpRequest, request), farm_id=farm_id, data=data)
        return Response(AnimalSerializer(animal).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class AnimalDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AnimalUpdateSerializer,
        responses={200: AnimalSerializer, **ERRORS},
        operation_id="farms_animal_update",
        tags=["farms"],
    )
    def patch(self, request: Request, animal_id: UUID) -> Response:
        serializer = AnimalUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        animal = update_animal(
            request=cast(HttpRequest, request),
            animal_id=animal_id,
            data=dict(serializer.validated_data),
        )
        return Response(AnimalSerializer(animal).data)


class AnimalHealthView(APIView):
    """What happened to this animal, as the register knows it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: AnimalHealthEntrySerializer(many=True), **ERRORS},
        operation_id="farms_animal_health_list",
        tags=["farms"],
    )
    def get(self, request: Request, animal_id: UUID) -> Response:
        return Response(
            AnimalHealthEntrySerializer(list_health_entries(animal_id=animal_id), many=True).data
        )


class SpeciesView(APIView):
    """The species catalogue; inactive ones are listed so a client can say "soon"."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: SpeciesListSerializer}, operation_id="farms_species", tags=["farms"]
    )
    def get(self, request: Request) -> Response:
        return Response([
            {"key": species.key, "label": species.label, "active": species.active}
            for species in SPECIES.values()
        ])


@method_decorator(csrf_protect, name="dispatch")
class FarmActivationCodeView(APIView):
    """The code a company hands the farmer for one of its cards (ADR-051)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={201: FarmActivationCodeSerializer, **ERRORS},
        operation_id="farms_activation_code_issue",
        tags=["farms"],
    )
    def post(self, request: Request, farm_id: UUID) -> Response:
        code, expires_at = issue_activation_code(
            request=cast(HttpRequest, request), farm_id=farm_id
        )
        return Response(
            FarmActivationCodeSerializer({"code": code, "expires_at": expires_at}).data,
            status=201,
        )


@method_decorator(csrf_protect, name="dispatch")
class FarmActivationRedeemView(APIView):
    """The farmer takes the herd over with the code (ADR-051)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=FarmActivationRedeemSerializer,
        responses={201: FarmTakeoverSerializer, **ERRORS},
        operation_id="farms_activation_redeem",
        tags=["farms"],
    )
    def post(self, request: Request) -> Response:
        serializer = FarmActivationRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = redeem_activation_code(
            request=cast(HttpRequest, request), code=serializer.validated_data["code"]
        )
        return Response(FarmTakeoverSerializer(result).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class FarmShareListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: FarmShareSerializer(many=True), **ERRORS},
        operation_id="farms_share_list",
        tags=["farms"],
    )
    def get(self, request: Request, farm_id: UUID) -> Response:
        return Response(FarmShareSerializer(list_shares(farm_id=farm_id), many=True).data)


@method_decorator(csrf_protect, name="dispatch")
class FarmShareRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: FarmShareSerializer, **ERRORS},
        operation_id="farms_share_revoke",
        tags=["farms"],
    )
    def post(self, request: Request, share_id: UUID) -> Response:
        share = revoke_share(request=cast(HttpRequest, request), share_id=share_id)
        return Response(FarmShareSerializer(share).data)
