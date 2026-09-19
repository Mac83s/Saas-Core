from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .availability import available_slots
from .models import Location, PublicBookingRoute, Resource, SelfServiceRoute, Service, StaffMember
from .security import public_booking_context, token_digest
from .serializers import (
    AppointmentCreateSerializer,
    AppointmentListSerializer,
    AppointmentSerializer,
    CatalogCreateSerializer,
    CatalogSerializer,
    CustomerAnonymizedSerializer,
    RescheduleSerializer,
    ScheduleCreateSerializer,
    SlotListSerializer,
    StaffSerializer,
    StaffUpdateSerializer,
)
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    anonymize_customer,
    cancel_appointment,
    configure_schedule,
    create_appointment,
    create_catalog_item,
    list_appointments,
    list_catalog,
    reschedule_appointment,
    update_staff,
)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class BookingThrottle(AnonRateThrottle):
    scope = "booking_public"


def _idem(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    return value


def _appointment_payload(value: Any, token: str | None = None) -> dict[str, Any]:
    return {
        "id": value.id,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "timezone": value.timezone,
        "service_name": value.service_name,
        "status": value.status,
        "customer_name": value.customer.display_name,
        "staff_id": value.staff_id,
        "staff_name": value.staff.display_name,
        "staff_membership_id": value.staff.membership_id,
        "location_name": value.location.name,
        "resource_name": value.resource.name if value.resource else None,
        **({"self_service_token": token} if token else {}),
    }


def _catalog_payload(value: dict[str, list[Any]], *, public: bool = False) -> dict[str, Any]:
    return {
        "locations": [
            {"id": x.id, "name": x.name, "public_slug": x.public_slug}
            for x in value["locations"]
            if x.active
        ],
        "staff": [
            {
                "id": x.id,
                "name": x.display_name,
                "public_slug": x.public_slug,
                # Who on the team has an account is not the public's business.
                "membership_id": None if public else x.membership_id,
            }
            for x in value["staff"]
            if x.active
        ],
        "services": [
            {
                "id": x.id,
                "name": x.name,
                "public_slug": x.public_slug,
                "duration_minutes": x.duration_minutes,
                "appointment_kind": x.appointment_kind,
            }
            for x in value["services"]
            if x.active
        ],
        "resources": [
            {"id": x.id, "name": x.name, "kind": x.kind} for x in value["resources"] if x.active
        ],
    }


@method_decorator(csrf_protect, name="dispatch")
class BookingCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["booking"], responses={200: CatalogSerializer})
    def get(self, request: Request) -> Response:
        del request
        return Response(_catalog_payload(list_catalog()))

    @extend_schema(
        tags=["booking"],
        request=CatalogCreateSerializer,
        responses={201: dict, 400: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = CatalogCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        kind = data.pop("kind")
        name = data.pop("name")
        if kind != "service":
            data.pop("appointment_kind", None)
        if kind == "staff":
            data = {
                "display_name": name,
                "public_slug": data.get("public_slug", ""),
                "membership_id": data.get("membership_id"),
            }
        elif kind == "resource":
            data = {"name": name, "kind": data.get("resource_kind", "generic")}
        else:
            data["name"] = name
        return Response({"id": create_catalog_item(kind=kind, data=data).id}, status=201)


@method_decorator(csrf_protect, name="dispatch")
class BookingStaffView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=StaffUpdateSerializer,
        responses={
            200: StaffSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request, staff_id: UUID) -> Response:
        serializer = StaffUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "name" in data:
            data["display_name"] = data.pop("name")
        staff = update_staff(staff_id=staff_id, data=data)
        return Response({
            "id": staff.id,
            "name": staff.display_name,
            "public_slug": staff.public_slug,
            "membership_id": staff.membership_id,
        })


@method_decorator(csrf_protect, name="dispatch")
class BookingScheduleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["booking"], request=ScheduleCreateSerializer, responses={201: dict})
    def post(self, request: Request) -> Response:
        serializer = ScheduleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        kind = data.pop("kind")
        return Response({"id": configure_schedule(kind=kind, data=data).id}, status=201)


class BookingSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[
            OpenApiParameter("service_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("location_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("from", date, OpenApiParameter.QUERY),
            OpenApiParameter("to", date, OpenApiParameter.QUERY),
        ],
        responses={200: SlotListSerializer},
    )
    def get(self, request: Request) -> Response:
        try:
            service = UUID(request.query_params["service_id"])
            location = UUID(request.query_params["location_id"])
            start = date.fromisoformat(request.query_params["from"])
            end = date.fromisoformat(request.query_params["to"])
        except (KeyError, ValueError) as error:
            raise ParseError("Nieprawidłowe parametry terminów.") from error
        authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response({
            "items": [
                {
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "staff_id": item.staff_id,
                    "resource_id": item.resource_id,
                }
                for item in available_slots(
                    service_id=service,
                    location_id=location,
                    from_date=start,
                    to_date=end,
                )
            ]
        })


@method_decorator(csrf_protect, name="dispatch")
class AppointmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[
            OpenApiParameter(
                "mine",
                bool,
                OpenApiParameter.QUERY,
                description="Tylko wizyty pracownika kalendarza powiązanego z moim kontem.",
            )
        ],
        responses={200: AppointmentListSerializer},
    )
    def get(self, request: Request) -> Response:
        mine = request.query_params.get("mine", "").lower() in {"1", "true"}
        return Response({"items": [_appointment_payload(x) for x in list_appointments(mine=mine)]})

    @extend_schema(
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=AppointmentCreateSerializer,
        responses={201: AppointmentSerializer},
    )
    def post(self, request: Request) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        s = AppointmentCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        result = create_appointment(
            **data,
            customer_data=customer,
            idempotency_key=_idem(request),
            principal_ref=str(context.actor_id),
        )
        return Response(
            _appointment_payload(result.appointment, result.token),
            status=201 if result.created else 200,
        )


@method_decorator(csrf_protect, name="dispatch")
class AppointmentRescheduleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=RescheduleSerializer,
        responses={200: AppointmentSerializer},
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        s = RescheduleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        value = reschedule_appointment(
            appointment_id=appointment_id,
            idempotency_key=_idem(request),
            principal_ref=str(context.actor_id),
            **s.validated_data,
        )
        return Response(_appointment_payload(value))


@method_decorator(csrf_protect, name="dispatch")
class AppointmentCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: AppointmentSerializer},
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response(
            _appointment_payload(
                cancel_appointment(
                    appointment_id=appointment_id,
                    idempotency_key=_idem(request),
                    principal_ref=str(context.actor_id),
                )
            )
        )


class CustomerAnonymizeView(AppointmentCancelView):
    @extend_schema(
        tags=["booking"],
        request=None,
        responses={200: CustomerAnonymizedSerializer},
    )
    def post(self, request: Request, customer_id: UUID) -> Response:
        del request
        customer = anonymize_customer(customer_id)
        return Response({"id": customer.id, "anonymized_at": customer.anonymized_at})


def _route(public_slug: str) -> PublicBookingRoute:
    if not settings.PUBLIC_BOOKING_ENABLED:
        raise NotFound("Kalendarz nie istnieje.")
    route = PublicBookingRoute.objects.filter(public_slug=public_slug, active=True).first()
    if not route:
        raise NotFound("Kalendarz nie istnieje.")
    return route


class PublicBookingCatalogView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(tags=["public-booking"], responses={200: CatalogSerializer})
    def get(self, request: Request, public_slug: str) -> Response:
        del request
        route = _route(public_slug)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            org = route.organization_id
            value: dict[str, list[Any]] = {
                "locations": list(Location.all_objects.filter(organization_id=org)),
                "staff": list(StaffMember.all_objects.filter(organization_id=org)),
                "services": list(Service.all_objects.filter(organization_id=org)),
                "resources": list(Resource.all_objects.filter(organization_id=org)),
            }
            return Response(_catalog_payload(value, public=True))


class PublicBookingSlotsView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        tags=["public-booking"],
        parameters=[
            OpenApiParameter("service_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("location_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("from", date, OpenApiParameter.QUERY),
            OpenApiParameter("to", date, OpenApiParameter.QUERY),
        ],
        responses={200: SlotListSerializer},
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        try:
            service = UUID(request.query_params["service_id"])
            location = UUID(request.query_params["location_id"])
            start = date.fromisoformat(request.query_params["from"])
            end = date.fromisoformat(request.query_params["to"])
        except (KeyError, ValueError) as error:
            raise ParseError("Nieprawidłowe parametry terminów.") from error
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            return Response({
                "items": [
                    {
                        "starts_at": x.starts_at,
                        "ends_at": x.ends_at,
                        "staff_id": x.staff_id,
                        "resource_id": x.resource_id,
                    }
                    for x in available_slots(
                        service_id=service, location_id=location, from_date=start, to_date=end
                    )
                ]
            })


class PublicBookingCreateView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=AppointmentCreateSerializer,
        responses={201: AppointmentSerializer},
    )
    def post(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        s = AppointmentCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.manage", BOOKING_ENABLED)
            result = create_appointment(
                **data,
                customer_data=customer,
                idempotency_key=_idem(request),
                principal_ref="public",
            )
            payload = _appointment_payload(result.appointment, result.token)
        return Response(payload, status=201 if result.created else 200)


def _self(token: str) -> SelfServiceRoute:
    route = SelfServiceRoute.objects.filter(
        token_digest=token_digest(token), revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).first()
    if not route:
        raise NotFound("Rezerwacja nie istnieje.")
    return route


class SelfServiceAppointmentView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(tags=["public-booking"], responses={200: AppointmentSerializer})
    def get(self, request: Request, token: str) -> Response:
        del request
        route = _self(token)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            from .models import Appointment

            value = (
                Appointment.all_objects.select_related("customer", "staff", "location", "resource")
                .filter(pk=route.appointment_id)
                .first()
            )
            if not value:
                raise NotFound("Rezerwacja nie istnieje.")
            return Response(_appointment_payload(value))


class SelfServiceRescheduleView(SelfServiceAppointmentView):
    @extend_schema(
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=RescheduleSerializer,
        responses={200: AppointmentSerializer},
    )
    def post(self, request: Request, token: str) -> Response:
        route = _self(token)
        s = RescheduleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.manage", BOOKING_ENABLED)
            value = reschedule_appointment(
                appointment_id=route.appointment_id,
                idempotency_key=_idem(request),
                principal_ref=route.token_digest,
                **s.validated_data,
            )
            payload = _appointment_payload(value)
        return Response(payload)


class SelfServiceCancelView(SelfServiceAppointmentView):
    @extend_schema(
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: AppointmentSerializer},
    )
    def post(self, request: Request, token: str) -> Response:
        route = _self(token)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.manage", BOOKING_ENABLED)
            value = cancel_appointment(
                appointment_id=route.appointment_id,
                idempotency_key=_idem(request),
                principal_ref=route.token_digest,
            )
            payload = _appointment_payload(value)
        return Response(payload)
