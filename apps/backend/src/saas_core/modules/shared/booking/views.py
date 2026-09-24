from __future__ import annotations

from datetime import date, datetime
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

from .availability import _zone, available_days, available_slots, available_times
from .models import Location, PublicBookingRoute, Resource, SelfServiceRoute, Service
from .security import public_booking_context, token_digest
from .serializers import (
    AppointmentCreateSerializer,
    AppointmentListSerializer,
    AppointmentSerializer,
    CatalogCreateSerializer,
    CatalogSerializer,
    CustomerAnonymizedSerializer,
    MaterialsInputSerializer,
    PublicAppointmentSerializer,
    PublicCatalogSerializer,
    RescheduleSerializer,
    ScheduleCreateSerializer,
    SlotDayListSerializer,
    SlotListSerializer,
    SlotTimeListSerializer,
    StaffSerializer,
    StaffSlotTimeListSerializer,
    StaffUpdateSerializer,
)
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    anonymize_customer,
    cancel_appointment,
    complete_appointment,
    configure_schedule,
    create_appointment,
    create_catalog_item,
    list_appointments,
    list_catalog,
    reschedule_appointment,
    set_appointment_materials,
    set_service_materials,
    update_staff,
)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
SLOT_QUERY = [
    OpenApiParameter("service_id", UUID, OpenApiParameter.QUERY, required=True),
    OpenApiParameter("location_id", UUID, OpenApiParameter.QUERY, required=True),
]
DAYS_QUERY = [
    *SLOT_QUERY,
    OpenApiParameter("from", date, OpenApiParameter.QUERY, required=True),
    OpenApiParameter("to", date, OpenApiParameter.QUERY, required=True),
]
TIMES_QUERY = [*SLOT_QUERY, OpenApiParameter("date", date, OpenApiParameter.QUERY, required=True)]
STAFF_QUERY = OpenApiParameter(
    "staff_id", UUID, OpenApiParameter.QUERY, description="Tylko terminy tej osoby."
)


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
        "materials": value.materials,
        **({"self_service_token": token} if token else {}),
    }


def _public_appointment_payload(value: Any, token: str | None = None) -> dict[str, Any]:
    """The customer's own visit: not who does it, nor the company's stock sheet."""
    return {
        "id": value.id,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "timezone": value.timezone,
        "service_name": value.service_name,
        "location_name": value.location.name,
        "status": value.status,
        **({"self_service_token": token} if token else {}),
    }


def _slot_query(request: Request, *dates: str) -> tuple[UUID, UUID, list[date]]:
    """service_id, location_id and the named dates of a slot search."""
    try:
        return (
            UUID(request.query_params["service_id"]),
            UUID(request.query_params["location_id"]),
            [date.fromisoformat(request.query_params[name]) for name in dates],
        )
    except (KeyError, ValueError) as error:
        raise ParseError("Nieprawidłowe parametry terminów.") from error


def _staff_query(request: Request) -> list[UUID] | None:
    value = request.query_params.get("staff_id")
    try:
        return [UUID(value)] if value else None
    except ValueError as error:
        raise ParseError("Nieprawidłowe parametry terminów.") from error


def _window_edge(request: Request, name: str) -> datetime | None:
    """One edge of the appointment list's window. Without an offset, a date
    included, it is the organization's wall clock: a date is local midnight."""
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        edge = datetime.fromisoformat(value)
    except ValueError as error:
        raise ParseError("Nieprawidłowe parametry terminów.") from error
    return edge if edge.tzinfo else edge.replace(tzinfo=_zone())


def _materials(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validated lines as plain JSON: they enter the idempotency hash."""
    return [
        {"item_id": str(line["item_id"]), "quantity": str(line["quantity"]), "mode": line["mode"]}
        for line in raw
    ]


def _catalog_payload(value: dict[str, list[Any]], *, public: bool = False) -> dict[str, Any]:
    return {
        "locations": [
            {"id": x.id, "name": x.name, "public_slug": x.public_slug}
            for x in value["locations"]
            if x.active
        ],
        # Who works here is not the public's business (ADR-058 §8).
        **(
            {}
            if public
            else {
                "staff": [
                    {
                        "id": x.id,
                        "name": x.display_name,
                        "public_slug": x.public_slug,
                        "membership_id": x.membership_id,
                    }
                    for x in value["staff"]
                    if x.active
                ]
            }
        ),
        "services": [
            {
                "id": x.id,
                "name": x.name,
                "public_slug": x.public_slug,
                "duration_minutes": x.duration_minutes,
                "appointment_kind": x.appointment_kind,
                # What a visit takes from the warehouse is the company's business.
                **({} if public else {"materials": x.materials}),
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


class BookingSlotDaysView(APIView):
    """Days with a free start, for the day picker (ADR-058 §5)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[*DAYS_QUERY, STAFF_QUERY],
        responses={200: SlotDayListSerializer},
    )
    def get(self, request: Request) -> Response:
        service, location, (start, end) = _slot_query(request, "from", "to")
        staff = _staff_query(request)
        authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response({
            "items": available_days(
                service_id=service,
                location_id=location,
                from_date=start,
                to_date=end,
                staff_ids=staff,
            )
        })


class BookingSlotTimesView(APIView):
    """Every free start of one day with who is free for it (ADR-058 §5)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[*TIMES_QUERY, STAFF_QUERY],
        responses={200: StaffSlotTimeListSerializer},
    )
    def get(self, request: Request) -> Response:
        service, location, (day,) = _slot_query(request, "date")
        staff = _staff_query(request)
        authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response({
            "items": [
                {
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "staff": [
                        {"staff_id": staff_id, "resource_id": resource_id}
                        for staff_id, resource_id in item.staff.items()
                    ],
                }
                for item in available_times(
                    service_id=service, location_id=location, day=day, staff_ids=staff
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
            ),
            OpenApiParameter(
                "from",
                str,
                OpenApiParameter.QUERY,
                description=(
                    "Wizyty zaczynające się od tej chwili: data (północ w strefie organizacji) "
                    "albo data i czas ISO 8601."
                ),
            ),
            OpenApiParameter(
                "to",
                str,
                OpenApiParameter.QUERY,
                description="Wizyty zaczynające się przed tą chwilą (bez niej); format jak `from`.",
            ),
            OpenApiParameter(
                "staff_id", UUID, OpenApiParameter.QUERY, description="Tylko wizyty tej osoby."
            ),
        ],
        responses={200: AppointmentListSerializer, 400: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        mine = request.query_params.get("mine", "").lower() in {"1", "true"}
        staff = _staff_query(request)
        items = list_appointments(
            starts_from=_window_edge(request, "from"),
            starts_until=_window_edge(request, "to"),
            staff_id=staff[0] if staff else None,
            mine=mine,
        )
        return Response({"items": [_appointment_payload(x) for x in items]})

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
        if "materials" in data:
            data["materials"] = _materials(data["materials"])
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


@method_decorator(csrf_protect, name="dispatch")
class AppointmentCompleteView(APIView):
    """Wizyta się odbyła: produkty schodzą z magazynu (RW, WZ)."""

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
                complete_appointment(
                    appointment_id=appointment_id,
                    idempotency_key=_idem(request),
                    principal_ref=str(context.actor_id),
                )
            )
        )


@method_decorator(csrf_protect, name="dispatch")
class AppointmentMaterialsView(APIView):
    """Produkty jednej wizyty; rezerwacja stanu idzie za nimi."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=MaterialsInputSerializer,
        responses={200: AppointmentSerializer},
    )
    def put(self, request: Request, appointment_id: UUID) -> Response:
        s = MaterialsInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        value = set_appointment_materials(
            appointment_id=appointment_id, materials=_materials(s.validated_data["materials"])
        )
        return Response(_appointment_payload(value))


@method_decorator(csrf_protect, name="dispatch")
class ServiceMaterialsView(APIView):
    """Produkty, które zabiera każda wizyta tej usługi."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=MaterialsInputSerializer,
        responses={200: MaterialsInputSerializer},
    )
    def put(self, request: Request, service_id: UUID) -> Response:
        s = MaterialsInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service = set_service_materials(
            service_id=service_id, materials=_materials(s.validated_data["materials"])
        )
        return Response({"materials": service.materials})


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

    @extend_schema(tags=["public-booking"], responses={200: PublicCatalogSerializer})
    def get(self, request: Request, public_slug: str) -> Response:
        del request
        route = _route(public_slug)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            org = route.organization_id
            value: dict[str, list[Any]] = {
                "locations": list(Location.all_objects.filter(organization_id=org)),
                "services": list(Service.all_objects.filter(organization_id=org)),
                "resources": list(Resource.all_objects.filter(organization_id=org)),
            }
            return Response(_catalog_payload(value, public=True))


class PublicBookingSlotsView(APIView):
    """Kept for compatibility; each start once, without who takes it (ADR-058 §8)."""

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
        responses={200: SlotTimeListSerializer},
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
            slots = available_slots(
                service_id=service, location_id=location, from_date=start, to_date=end
            )
            return Response({
                "items": [
                    {"starts_at": starts_at, "ends_at": ends_at}
                    for starts_at, ends_at in dict.fromkeys((x.starts_at, x.ends_at) for x in slots)
                ]
            })


class PublicBookingDaysView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        tags=["public-booking"], parameters=DAYS_QUERY, responses={200: SlotDayListSerializer}
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service, location, (start, end) = _slot_query(request, "from", "to")
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            return Response({
                "items": available_days(
                    service_id=service, location_id=location, from_date=start, to_date=end
                )
            })


class PublicBookingTimesView(APIView):
    """Free starts of one day, once each: who is free is the company's business."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        tags=["public-booking"], parameters=TIMES_QUERY, responses={200: SlotTimeListSerializer}
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service, location, (day,) = _slot_query(request, "date")
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            return Response({
                "items": [
                    {"starts_at": item.starts_at, "ends_at": item.ends_at}
                    for item in available_times(service_id=service, location_id=location, day=day)
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
        responses={201: PublicAppointmentSerializer},
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
            payload = _public_appointment_payload(result.appointment, result.token)
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

    @extend_schema(tags=["public-booking"], responses={200: PublicAppointmentSerializer})
    def get(self, request: Request, token: str) -> Response:
        del request
        route = _self(token)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            from .models import Appointment

            value = (
                Appointment.all_objects.select_related("location")
                .filter(pk=route.appointment_id)
                .first()
            )
            if not value:
                raise NotFound("Rezerwacja nie istnieje.")
            return Response(_public_appointment_payload(value))


class SelfServiceRescheduleView(SelfServiceAppointmentView):
    @extend_schema(
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=RescheduleSerializer,
        responses={200: PublicAppointmentSerializer},
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
            payload = _public_appointment_payload(value)
        return Response(payload)


class SelfServiceCancelView(SelfServiceAppointmentView):
    @extend_schema(
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: PublicAppointmentSerializer},
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
            payload = _public_appointment_payload(value)
        return Response(payload)
