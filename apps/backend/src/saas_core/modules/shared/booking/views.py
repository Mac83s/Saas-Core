from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ParseError, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.api import setting
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled

from . import materials as stock
from . import orders
from .availability import _zone, available_days, available_slots, available_times
from .cancellation import CANCEL_REASONS, REFUND_THRESHOLDS
from .company_settings import (
    CONTACT,
    HORIZON_DAYS,
    online_last_day,
    online_paused,
    self_service_allows,
)
from .consents import BookingConsents
from .consents import shown as consents_shown
from .dispatch import assign_crew, candidates, overview, queue
from .dispatch import requests as waiting_requests
from .facts import staff_facts, staff_history, team_performance
from .flags import appointment_flags
from .item_translations import localized_texts, source_locale, translatable
from .models import (
    Appointment,
    BookingClosure,
    BookingRule,
    Location,
    PublicBookingRoute,
    Resource,
    ResourceGroup,
    SelfServiceRoute,
    Service,
    StaffTeam,
    TimeModel,
)
from .occupancy import MAX_DAYS as MAX_OCCUPANCY_DAYS
from .occupancy import Held, books_stays, occupancy
from .passing import closes_explicitly, has_passed
from .periods import StayPlan, book_stay, move_stay, stay_ends, stay_starts
from .places import appointment_places, has_place_search, search_places
from .presets import Preset, list_presets
from .public import public_choices, public_people, shown_to_customer
from .quote import QuoteChanged, customer_quote, offered_extras, quote_offer, quote_visit
from .rules import (
    copy_closures_to_next_year,
    copy_rules_to_next_year,
    delete_closure,
    delete_rule,
    list_closures,
    list_rules,
    save_closure,
    save_rule,
)
from .security import public_booking_context, token_digest
from .serializers import (
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentDeclineSerializer,
    AppointmentListSerializer,
    AppointmentSerializer,
    AppointmentSettlementAnswerSerializer,
    BookingClosureInputSerializer,
    BookingClosureListSerializer,
    BookingClosurePreviewSerializer,
    BookingClosureSerializer,
    BookingClosureUpdateSerializer,
    BookingQuoteInputSerializer,
    BookingQuoteSerializer,
    BookingRuleInputSerializer,
    BookingRuleListSerializer,
    BookingRulePreviewSerializer,
    BookingRuleSerializer,
    BookingRuleUpdateSerializer,
    CandidateListSerializer,
    CandidateQuerySerializer,
    CatalogCreateSerializer,
    CatalogSerializer,
    CopyYearInputSerializer,
    CopyYearResultSerializer,
    CrewInputSerializer,
    CustomerAnonymizedSerializer,
    DateListSerializer,
    GroupInputSerializer,
    GroupSetupPreviewSerializer,
    GroupSetupSerializer,
    GroupUpdateSerializer,
    MaterialsInputSerializer,
    OccupancySerializer,
    OverviewSerializer,
    PeopleDaySerializer,
    PerformanceSerializer,
    PersonCreateSerializer,
    PersonDetailSerializer,
    PersonHoursInputSerializer,
    PersonHoursPreviewSerializer,
    PersonInvitationInputSerializer,
    PersonInvitationSerializer,
    PersonListQuerySerializer,
    PersonListSerializer,
    PersonPublicInputSerializer,
    PersonServicesInputSerializer,
    PersonUpdateSerializer,
    PlaceInputSerializer,
    PlaceSetupPreviewSerializer,
    PlaceSetupSerializer,
    PlaceUpdateSerializer,
    PresetListSerializer,
    PublicAppointmentCreateSerializer,
    PublicAppointmentSerializer,
    PublicCatalogSerializer,
    PublicConsentsSerializer,
    PublicQuoteAnswerSerializer,
    PublicQuoteInputSerializer,
    QueueSerializer,
    RescheduleSerializer,
    ResourceInputSerializer,
    ResourceSetupPreviewSerializer,
    ResourceSetupSerializer,
    ResourceUpdateSerializer,
    ScheduleCreateSerializer,
    ServiceInputSerializer,
    ServiceSetupPreviewSerializer,
    ServiceSetupSerializer,
    ServiceUpdateSerializer,
    SetupOptionsSerializer,
    SetupSerializer,
    SlotDayListSerializer,
    SlotListSerializer,
    SlotTimeListSerializer,
    StaffFactsSerializer,
    StaffHistorySerializer,
    StaffSlotTimeListSerializer,
    StayInputSerializer,
    StayMoveSerializer,
    StayPlanSerializer,
    TeamInputSerializer,
    TeamListSerializer,
    TeamSerializer,
    TeamUpdateSerializer,
    TimeOffCreatedSerializer,
    TimeOffInputSerializer,
    UnitBlockInputSerializer,
    UnitBlockListSerializer,
    UnitBlockSerializer,
    VisitPlaceInputSerializer,
    VisitPlaceSuggestionListSerializer,
)
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    CreatedAppointment,
    anonymize_customer,
    answer_request,
    appointment_for_tenant,
    cancel_appointment,
    complete_appointment,
    configure_schedule,
    create_appointment,
    create_catalog_item,
    list_appointments,
    list_catalog,
    mark_no_show,
    reschedule_appointment,
    set_appointment_materials,
    set_appointment_place,
    set_service_materials,
    update_staff,
    visible_contacts,
)
from .setup import (
    ServiceSetup,
    list_setup,
    save_group,
    save_location,
    save_resource,
    save_service,
    setup_options,
)
from .staff import (
    Person,
    PersonDetail,
    add_person,
    add_time_off,
    end_person,
    invite_person,
    list_people,
    people_day,
    person_detail,
    remove_time_off,
    restore_person,
    set_person_hours,
    set_person_public,
    set_person_services,
)
from .teams import create_team, delete_team, list_teams, member_ids, update_team
from .titles import appointment_titles
from .units import UnitBlock, add_unit_block, list_unit_blocks, remove_unit_block

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)

#: What a setup write answers besides 2xx (ADR-072 §11).
_SETUP_PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
_PREVIEW = {"x-dry-run": True}
_PREVIEW_NOTE = (
    " Nothing is saved: the answer is the item as the write would leave it, with `changes`, "
    "or the same 400, 404 and 409 the write would answer."
)
_WRITE_NOTE = (
    " A repeated Idempotency-Key answers the first result again; the key reused on another "
    "request is 409 `booking_idempotency_conflict`."
)
_UPDATE_NOTE = (
    " Only the fields sent change. `expected_version` is the version the change was made on; "
    "another one is 409 `booking_version_conflict`." + _WRITE_NOTE
)


def _with_changes(payload: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "changes": changes}


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
    "staff_id",
    UUID,
    OpenApiParameter.QUERY,
    many=True,
    description="Tylko terminy tych osób (parametr można powtórzyć).",
)
NEED_QUERY = OpenApiParameter(
    "need",
    int,
    OpenApiParameter.QUERY,
    description=(
        "Ile osób naraz musi być wolnych (1–10, domyślnie 1); z listą osób "
        "równą jej długości — wszystkie wybrane."
    ),
)


CHOICE_QUERY = [
    OpenApiParameter(
        "team_id",
        UUID,
        OpenApiParameter.QUERY,
        description="Zespół wybrany przez klienta (usługa z wyborem zespołu).",
    ),
    OpenApiParameter(
        "person_id",
        UUID,
        OpenApiParameter.QUERY,
        description="Osoba wybrana przez klienta (usługa z wyborem osoby).",
    ),
]


class BookingThrottle(AnonRateThrottle):
    scope = "booking_public"


def _idem(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    return value


def _crew_payload(value: Any) -> list[dict[str, Any]]:
    """Everybody on the visit, the lead first; for a called-off visit, who was."""
    allocations = list(value.staff_allocations.all())
    active = [item for item in allocations if item.active]
    rows = active or (allocations if value.status == "canceled" else [])
    people = list({item.staff_id: item.staff for item in rows}.values())
    people.sort(key=lambda person: (person.id != value.staff_id,))
    return [
        {
            "staff_id": person.id,
            "name": person.display_name,
            "membership_id": person.membership_id,
            "lead": person.id == value.staff_id,
        }
        for person in people
    ]


@dataclass(frozen=True, slots=True)
class _Known:
    """What a list asks once for all its visits: the places, flags and names
    the modules know, and whose customer contact the caller sees."""

    places: Mapping[UUID, str]
    flags: Mapping[UUID, list[str]]
    contacts: set[UUID]
    titles: Mapping[UUID, str]
    #: The order of each priced visit, for a caller who may read orders.
    orders: Mapping[UUID, dict[str, Any]]


def _known(items: Sequence[Any]) -> _Known:
    ids = [item.id for item in items]
    return _Known(
        appointment_places(ids),
        appointment_flags({item.id: item.service.appointment_kind for item in items}),
        visible_contacts(ids),
        appointment_titles(ids),
        # Only a booking with a price has an order (ADR-073 §3).
        orders.links([item.id for item in items if item.quote and item.quote["lines"]]),
    )


def _appointment_payload(
    value: Any, token: str | None = None, known: _Known | None = None
) -> dict[str, Any]:
    """`known`: what a list already asked; one visit asks for itself."""
    if known is None:
        known = _known([value])
    seen = value.id in known.contacts
    return {
        "id": value.id,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "timezone": value.timezone,
        "service_name": value.service_name,
        "service_id": value.service_id,
        "status": value.status,
        "hold_expires_at": value.hold_expires_at,
        "order": known.orders.get(value.id),
        "passed": has_passed(value),
        "closes_explicitly": closes_explicitly(value.service.appointment_kind),
        "customer_name": value.customer.display_name,
        # A module's name for the visit (a herd visit's farm), shown before
        # the customer's; empty when no module knows one.
        "title": known.titles.get(value.id, ""),
        "staff_id": value.staff_id,
        # A stay takes a unit and nobody (ADR-072 §2).
        "staff_name": value.staff.display_name if value.staff else None,
        "staff_membership_id": value.staff.membership_id if value.staff else None,
        "time_model": value.service.time_model,
        "location_name": value.location.name,
        # The visit's own place first, then the module that knows it (ADR-066).
        "place": value.place_town or known.places.get(value.id),
        "place_town": value.place_town,
        # The street can be the customer's home: the same people as the phone
        # see it (ADR-067); the town is everybody's.
        "place_address": value.place_address if seen else "",
        "customer_phone": value.customer.phone if seen else None,
        "customer_email": value.customer.email if seen else None,
        "appointment_kind": value.service.appointment_kind,
        "flags": known.flags.get(value.id, []),
        "resource_name": value.resource.name if value.resource else None,
        "resource_id": value.resource_id,
        "materials": value.materials,
        "takes_materials": stock.takes_materials(value.service.appointment_kind),
        **({"self_service_token": token} if token else {}),
        "crew": _crew_payload(value),
        "staff_required": value.staff_required,
        "needs_assignment": value.needs_assignment,
        "auto_assigned": value.auto_assigned,
        "crew_version": value.crew_version,
        "queue_reason": value.queue_reason,
        "queued_at": value.queued_at,
        "requested_team": (
            {"id": value.requested_team.id, "name": value.requested_team.name}
            if value.requested_team
            else None
        ),
        "requested_staff_id": value.requested_staff_id,
        "customer_notes": value.customer_notes,
        "quote": value.quote,
    }


def _queue_payload(value: Any, known: _Known) -> dict[str, Any]:
    return {
        **_appointment_payload(value, known=known),
        "customer_phone": value.customer.phone,
        "customer_email": value.customer.email,
    }


def _public_appointment_payload(value: Any, token: str | None = None) -> dict[str, Any]:
    """The customer's own visit: not the company's stock sheet, and of the
    people only what the customer chose or may see (ADR-058 §8)."""
    team, person = shown_to_customer(value)
    return {
        "id": value.id,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "timezone": value.timezone,
        # In the customer's language when the company translated it, frozen at
        # booking; a visit from before has only the company's (TL12c).
        "service_name": value.customer_service_name or value.service_name,
        "location_name": value.location.name,
        "status": value.status,
        "hold_expires_at": value.hold_expires_at,
        # The transfer's details while the booking waits for its payment, and
        # of a confirmed one whose rest is due by a transfer.
        "payment": (
            orders.awaited(value) if value.status in ("pending_payment", "confirmed") else None
        ),
        "settlement": _customer_settlement(value),
        "team_name": team,
        "person_name": person,
        **({"self_service_token": token} if token else {}),
        "self_service": _self_service(value),
        "quote": customer_quote(value.quote),
    }


def _customer_settlement(value: Any) -> dict[str, Any] | None:
    """What comes back of what the customer paid: before they give the
    booking up, what its terms would give back now; afterwards, what the
    company is still to give back."""
    money = orders.settlement(value)
    if money is None:
        return None
    return {
        "currency": money["currency"],
        "paid_minor": money["paid_minor"],
        "refund_minor": (
            money["refund_owed_minor"]
            if value.status == "canceled"
            else money["by_terms"]["refund_minor"]
        ),
    }


def _self_service(value: Any) -> dict[str, Any]:
    """What the link may still do, by the booking's own terms (B4)."""
    now = timezone.now()
    open_to = {
        "reschedule": ("confirmed",),
        "cancel": ("confirmed", "pending_payment", "pending_request"),
    }
    # A booking that waits — for the company's answer or for its payment —
    # can be given up, not moved (ADR-072 §9: only a confirmed one is moved).
    allows = {
        action: value.status in open_to[action] and self_service_allows(value, action, now)
        for action in ("reschedule", "cancel")
    }
    return {
        **allows,
        "until": value.starts_at - timedelta(hours=value.self_service_cutoff_hours)
        if any(allows.values())
        else None,
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
    values = request.query_params.getlist("staff_id")
    try:
        return [UUID(value) for value in values] if values else None
    except ValueError as error:
        raise ParseError("Nieprawidłowe parametry terminów.") from error


def _choice_query(request: Request) -> tuple[UUID | None, UUID | None]:
    """The team or person a customer chose on the public form, if any."""

    def one(name: str) -> UUID | None:
        value = request.query_params.get(name)
        return UUID(value) if value else None

    try:
        return one("team_id"), one("person_id")
    except ValueError as error:
        raise ParseError("Nieprawidłowe parametry terminów.") from error


def _need_query(request: Request) -> int:
    try:
        need = int(request.query_params.get("need", 1))
    except ValueError as error:
        raise ParseError("Nieprawidłowa liczba osób.") from error
    if not 1 <= need <= 10:
        raise ParseError("Nieprawidłowa liczba osób.")
    return need


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
                **(
                    {}
                    if public
                    else {
                        "staff_count": x.staff_count,
                        "public_staff_choice": x.public_staff_choice,
                        "materials": x.materials,
                        # A module that takes its own material (HoofCare) has none here.
                        "takes_materials": stock.takes_materials(x.appointment_kind),
                    }
                ),
            }
            for x in value["services"]
            if x.active
        ],
        "resources": [
            {"id": x.id, "name": x.name, "kind": x.kind} for x in value["resources"] if x.active
        ],
        **({} if public else {"place_search": has_place_search()}),
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
        parameters=[*DAYS_QUERY, STAFF_QUERY, NEED_QUERY],
        responses={200: SlotDayListSerializer},
    )
    def get(self, request: Request) -> Response:
        service, location, (start, end) = _slot_query(request, "from", "to")
        staff = _staff_query(request)
        need = _need_query(request)
        authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response({
            "items": available_days(
                service_id=service,
                location_id=location,
                from_date=start,
                to_date=end,
                staff_ids=staff,
                need=need,
            )
        })


class BookingSlotTimesView(APIView):
    """Every free start of one day with who is free for it (ADR-058 §5)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[*TIMES_QUERY, STAFF_QUERY, NEED_QUERY],
        responses={200: StaffSlotTimeListSerializer},
    )
    def get(self, request: Request) -> Response:
        service, location, (day,) = _slot_query(request, "date")
        staff = _staff_query(request)
        need = _need_query(request)
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
                    service_id=service, location_id=location, day=day, staff_ids=staff, need=need
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
            OpenApiParameter(
                "limit",
                int,
                OpenApiParameter.QUERY,
                description="Najwyżej tyle wizyt, od najwcześniejszej (1–500, domyślnie 500).",
            ),
        ],
        responses={200: AppointmentListSerializer, 400: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        mine = request.query_params.get("mine", "").lower() in {"1", "true"}
        staff = _staff_query(request)
        try:
            limit = int(request.query_params.get("limit", 500))
        except ValueError as error:
            raise ParseError("Nieprawidłowy limit wizyt.") from error
        items = list_appointments(
            starts_from=_window_edge(request, "from"),
            starts_until=_window_edge(request, "to"),
            staff_id=staff[0] if staff else None,
            mine=mine,
            limit=limit,
        )
        known = _known(items)
        return Response({"items": [_appointment_payload(x, known=known) for x in items]})

    @extend_schema(
        operation_id="booking_appointment_create",
        summary="Book a visit",
        description="Books a free start of a service at a place, for the people named or — "
        "with none named — the least busy free ones the service needs. The price is worked "
        "out and frozen in the booking (`quote`); with `quote_digest` a price other than the "
        "one shown is 409 `quote_changed`. A taken time is 409 `slot_unavailable`. The same "
        "Idempotency-Key answers the first booking again (200).",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=AppointmentCreateSerializer,
        responses={
            201: AppointmentSerializer,
            200: AppointmentSerializer,
            **_SETUP_PROBLEMS,
        },
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
        operation_id="booking_appointment_reschedule",
        summary="Move a visit to another time",
        description="Moves a confirmed visit with its people; all of them have to be free "
        "then, or 409 `slot_unavailable` names who is not. A visit that has a price is "
        "priced again for the new time; with `quote_digest` a price other than the one shown "
        "is 409 `quote_changed`. A stay moves by its dates (400 `stay_moves_by_dates`).",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=RescheduleSerializer,
        responses={200: AppointmentSerializer, **_SETUP_PROBLEMS},
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
        operation_id="booking_appointment_cancel",
        summary="Call a booking off",
        tags=["booking"],
        description="The company calls a booking off; the customer is told by e-mail. What "
        "the customer paid is settled with the booking's order: everything goes back — or, "
        "with the reason `balance_overdue`, what the booking's refund thresholds give "
        "(`GET …/settlement/` says both before anybody decides). The company then marks "
        "the refund on the order when it has given the money back. A visit that took "
        "place is 409 `appointment_not_changeable`; the same Idempotency-Key answers the "
        "first result again.",
        parameters=[IDEMPOTENCY],
        request=AppointmentCancelSerializer,
        responses={
            200: AppointmentSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response(
            _appointment_payload(
                cancel_appointment(
                    appointment_id=appointment_id,
                    idempotency_key=_idem(request),
                    principal_ref=str(context.actor_id),
                    **self._reason(request),
                )
            )
        )

    @staticmethod
    def _reason(request: Request) -> dict[str, Any]:
        serializer = AppointmentCancelSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        return cast(dict[str, Any], serializer.validated_data)


class AppointmentSettlementView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_appointment_settlement_retrieve",
        summary="What calling a booking off does with what its customer paid",
        description="What the customer has paid for the booking, what its own refund "
        "thresholds give back now and whether the rest of its price is late — read before "
        "calling it off. Writes nothing. Null where nothing was paid.",
        tags=["booking"],
        responses={
            200: AppointmentSettlementAnswerSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, appointment_id: UUID) -> Response:
        del request
        context = authorize_entitled(
            BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ
        )
        appointment = appointment_for_tenant(context.organization_id, appointment_id)
        if appointment is None:
            raise NotFound("Rezerwacja nie istnieje.")
        return Response({"settlement": orders.settlement(appointment)})


def _answer(request: Request, appointment_id: UUID, *, accept: bool) -> Response:
    """The company's answer to a booking made „on request” (ADR-072 §9)."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    said: dict[str, Any] = {}
    if not accept:
        serializer = AppointmentDeclineSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        said = cast(dict[str, Any], serializer.validated_data)
    return Response(
        _appointment_payload(
            answer_request(
                appointment_id=appointment_id,
                accept=accept,
                idempotency_key=_idem(request),
                principal_ref=str(context.actor_id),
                **said,
            )
        )
    )


@method_decorator(csrf_protect, name="dispatch")
class AppointmentAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_appointment_accept",
        summary="Accept a booking request",
        description="The company takes a booking that waits for its answer "
        "(`pending_request`): its order gets its number and the booking is confirmed — or, "
        "where the offer asks for money first, waits for that payment (`pending_payment`) "
        "and the customer gets the transfer's details. A booking that no longer waits for an "
        "answer is 409 `appointment_not_changeable`. The same Idempotency-Key answers the "
        "first result again.",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={
            200: AppointmentSerializer,
            400: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        return _answer(request, appointment_id, accept=True)


@method_decorator(csrf_protect, name="dispatch")
class AppointmentDeclineView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_appointment_decline",
        summary="Decline a booking request",
        description="The company does not take a booking that waits for its answer "
        "(`pending_request`): the booking lets its time go (`canceled`), its draft order is "
        "canceled and the customer is told — with the company's own `reason`, when it "
        "gives one. A booking that no longer waits for an answer is 409 "
        "`appointment_not_changeable`. The same Idempotency-Key answers the first result "
        "again.",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=AppointmentDeclineSerializer,
        responses={
            200: AppointmentSerializer,
            400: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        return _answer(request, appointment_id, accept=False)


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
class AppointmentNoShowView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_appointment_no_show",
        summary="Mark that the customer did not come",
        description="Closes a confirmed visit that has begun as `no_show` (UX-031): it leaves "
        "the assignment queue, counts neither as done nor as canceled, the people and the "
        "resource are free from now, the customer's self-service link stops working and "
        "products reserved for it return to stock. Before its start it is 409 "
        "`visit_not_started_yet`; a visit that is not confirmed (completed, canceled) is 409 "
        "`appointment_not_changeable`. There is no undo." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: AppointmentSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        return Response(
            _appointment_payload(
                mark_no_show(
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
class AppointmentPlaceView(APIView):
    """„Miejsce wizyty” of a booked visit (ADR-066)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        summary="Set where a visit takes place",
        description=(
            "Sets the visit's town and, optionally, street and number. Both empty "
            "clear it, and the calendar falls back to what a module knows. The same "
            "place again changes nothing. A called-off visit cannot be changed "
            "(appointment_not_changeable)."
        ),
        request=VisitPlaceInputSerializer,
        responses={
            200: AppointmentSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, appointment_id: UUID) -> Response:
        s = VisitPlaceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        value = set_appointment_place(
            appointment_id=appointment_id,
            town=s.validated_data["town"],
            address=s.validated_data.get("address", ""),
        )
        return Response(_appointment_payload(value))


class BookingPlacesView(APIView):
    """The company's places a module keeps (a farm, say), for the visit form."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        summary="Places a visit can take place at",
        description=(
            "Places the company keeps in its modules, matched by name or town; "
            "choosing one fills a visit's place_town and place_address. Empty "
            "when no module offers places (catalog.place_search is false)."
        ),
        parameters=[
            OpenApiParameter(
                "q", str, OpenApiParameter.QUERY, description="Part of a name or a town."
            ),
            OpenApiParameter(
                "limit",
                int,
                OpenApiParameter.QUERY,
                description="At most this many (1–500, default 200).",
            ),
        ],
        responses={
            200: VisitPlaceSuggestionListSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", 200))
        except ValueError as error:
            raise ParseError("Nieprawidłowy limit miejsc.") from error
        items = search_places(request.query_params.get("q", ""), limit)
        return Response({
            "items": [{"name": x.name, "town": x.town, "address": x.address} for x in items]
        })


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


def _localize(payload: dict[str, Any], value: dict[str, list[Any]], locale: str) -> None:
    """Names of the public catalogue in the visitor's language, where the
    company translated them (TL12b)."""
    for key, kind in (
        ("locations", "location"),
        ("services", "service"),
        ("resources", "resource"),
    ):
        names = localized_texts(translatable(kind), value[key], locale)
        for item in payload.get(key, []):
            text = names.get(item["id"], {})
            if "name" in text:
                item["name"] = text["name"]
            if "description" in text and "description" in item:
                item["description"] = text["description"]


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

    @extend_schema(
        operation_id="public_booking_catalog",
        summary="What a company's booking form offers",
        description="The places, services and units a visitor can book, and the teams and "
        "people the form lets them choose. With `locale` (a language of the company) names "
        "come in that language where the company translated them, otherwise in its own; "
        "`locale` in the answer is the language asked for when the company has it.",
        tags=["public-booking"],
        parameters=[
            OpenApiParameter(
                "locale",
                str,
                OpenApiParameter.QUERY,
                description="A language code, e.g. de; one the company does not have is "
                "answered in its own.",
            )
        ],
        responses={200: PublicCatalogSerializer},
        extensions={
            "x-quality-exempt": {
                "error-400": "An unknown language is answered in the company's own.",
            }
        },
    )
    def get(self, request: Request, public_slug: str) -> Response:
        asked = request.query_params.get("locale") or None
        route = _route(public_slug)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            org = route.organization_id
            value: dict[str, list[Any]] = {
                # Only what the company offers online (B2); the panel sees all.
                "locations": list(Location.all_objects.filter(organization_id=org, online=True)),
                # Stays are booked on the website from phase 5 (ADR-072 §1).
                "services": list(
                    Service.all_objects.filter(
                        organization_id=org, time_model=TimeModel.SLOT, online=True
                    )
                ),
                "resources": list(Resource.all_objects.filter(organization_id=org)),
            }
            payload = _catalog_payload(value, public=True)
            choices = public_choices(org, [x for x in value["services"] if x.active])
            organization = Organization.objects.get(pk=org)
            locale = (
                asked
                if asked in organization_content_locales(organization)
                and asked != source_locale(organization)
                else None
            )
            if locale is not None:
                _localize(payload, value, locale)
            paused, resume_on = online_paused(_zone().key)
            offers = {x.id: x for x in value["services"]}
            for item in payload["services"]:
                teams, people = choices.services.get(item["id"], ([], []))
                offer = offers[item["id"]]
                item.update(
                    staff_choice=offer.public_staff_choice,
                    team_ids=teams,
                    person_ids=people,
                    # Whether the booking waits for the company's answer.
                    confirmation=offer.confirmation,
                    response_hours=offer.response_hours,
                )
            team_names = dict(choices.teams)
            if locale is not None:
                names = localized_texts(
                    translatable("team"),
                    StaffTeam.all_objects.filter(organization_id=org, pk__in=list(team_names)),
                    locale,
                )
                team_names = {
                    key: names.get(key, {}).get("name", name) for key, name in team_names.items()
                }
            return Response({
                **payload,
                "locale": locale or source_locale(organization),
                "teams": [{"id": key, "name": name} for key, name in team_names.items()],
                "people": [{"id": key, "name": name} for key, name in choices.people],
                "extras": offered_extras(
                    organization, [x for x in value["services"] if x.active], locale
                ),
                "timezone": _zone().key,
                "currency": organization.currency,
                "online": {
                    "paused": paused,
                    "resume_on": resume_on,
                    "horizon_days": setting(HORIZON_DAYS),
                    "last_day": online_last_day(_zone().key),
                    "contact": setting(CONTACT),
                },
                "locales": list(organization_content_locales(organization)),
            })


class PublicBookingConsentsView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        operation_id="public_booking_consents",
        summary="What a customer accepts before booking",
        description="The company's booking terms and privacy policy in force, each with the "
        "statement the customer ticks and the address where it is read. Only documents with "
        "a text in the booking's language are listed — never a text in another language. "
        "Send each `text_id` back in `consents.documents` when booking.",
        tags=["public-booking"],
        parameters=[
            OpenApiParameter(
                "locale",
                str,
                OpenApiParameter.QUERY,
                description="The customer's language, e.g. de; one the company does not "
                "have is answered in its first.",
            )
        ],
        responses={200: PublicConsentsSerializer, 404: ProblemDetailsSerializer},
        extensions={
            "x-quality-exempt": {
                "error-400": "An unknown language is answered in the company's first.",
            }
        },
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            return Response(consents_shown(request.query_params.get("locale")))


class PublicBookingSlotsView(APIView):
    """Each start once, without who takes it (ADR-058 §8). Kept for API
    consumers, not for the old public form: that one needs a staff_id per slot,
    so the backend and frontend of this change deploy together."""

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
            # Online, nothing past the company's horizon (B3).
            end = min(end, online_last_day(_zone().key))
            slots = (
                available_slots(
                    service_id=service, location_id=location, from_date=start, to_date=end
                )
                if start <= end
                else []
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
        tags=["public-booking"],
        parameters=[*DAYS_QUERY, *CHOICE_QUERY],
        responses={200: SlotDayListSerializer},
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service, location, (start, end) = _slot_query(request, "from", "to")
        team, person = _choice_query(request)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            staff, need = public_people(
                route.organization_id, service, team_id=team, person_id=person
            )
            end = min(end, online_last_day(_zone().key))
            return Response({
                "items": available_days(
                    service_id=service,
                    location_id=location,
                    from_date=start,
                    to_date=end,
                    staff_ids=staff,
                    need=need,
                )
                if start <= end
                else []
            })


class PublicBookingTimesView(APIView):
    """Free starts of one day, once each: who is free is the company's business."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        tags=["public-booking"],
        parameters=[*TIMES_QUERY, *CHOICE_QUERY],
        responses={200: SlotTimeListSerializer},
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service, location, (day,) = _slot_query(request, "date")
        team, person = _choice_query(request)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            staff, need = public_people(
                route.organization_id, service, team_id=team, person_id=person
            )
            if day > online_last_day(_zone().key):
                return Response({"items": []})
            return Response({
                "items": [
                    {"starts_at": item.starts_at, "ends_at": item.ends_at}
                    for item in available_times(
                        service_id=service,
                        location_id=location,
                        day=day,
                        staff_ids=staff,
                        need=need,
                    )
                ]
            })


class PublicBookingCreateView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        operation_id="public_booking_appointment_create",
        summary="Book a visit from a company's booking form",
        description="Books a free start of a service the company offers online; the server "
        "picks the people, within the team or the person the customer chose. The price is "
        "worked out and frozen in the booking (`quote`); with `quote_digest` a price other "
        "than the one shown is 409 `quote_changed`, with the new one in `detail.quote`. A "
        "taken time is 409 `slot_unavailable`, a paused form 409 `booking_paused`. The "
        "company's documents in force in the booking's language (`GET …/consents/`) must be "
        "named in `consents.documents`: one missing or replaced is 409 `documents_changed` "
        "with the ones to show in `detail.documents`; each accepted document becomes a line "
        "of the consent journal. The same Idempotency-Key answers the first booking again "
        "(200).",
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=PublicAppointmentCreateSerializer,
        responses={
            201: PublicAppointmentSerializer,
            200: PublicAppointmentSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        # Unknown fields are dropped: a staff_id from an old form is not a pick.
        s = PublicAppointmentCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        team = data.pop("team_id", None)
        person = data.pop("person_id", None)
        notes = data.pop("customer_notes", "").strip()
        accepted = BookingConsents(
            documents=tuple((data.pop("consents", None) or {}).get("documents", ()))
        )
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.manage", BOOKING_ENABLED)
            # A choice the service does not offer is refused, not dropped.
            public_people(route.organization_id, data["service_id"], team_id=team, person_id=person)
            try:
                result = create_appointment(
                    **data,
                    consents=accepted,
                    team_id=team,
                    requested_staff_id=person,
                    customer_notes=notes,
                    customer_data=customer,
                    idempotency_key=_idem(request),
                    principal_ref="public",
                )
            except QuoteChanged as changed:
                raise QuoteChanged(changed.quote, customer=True) from None
            payload = _public_appointment_payload(result.appointment, result.token)
        return Response(payload, status=201 if result.created else 200)


class PublicBookingQuoteView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        operation_id="public_booking_quote",
        summary="Work out what a visit from the booking form would cost",
        description="The price of a service the company offers online at `starts_at`, with "
        "the extras picked, as the customer reads it: gross, the lines in their language, "
        "the deposit and how they pay. Nothing is saved or held. Send `digest` back as "
        "`quote_digest` when booking. `quote` is null when the service has no price. A "
        "time the price list has no price for is 400 `price_missing`.",
        tags=["public-booking"],
        request=PublicQuoteInputSerializer,
        responses={
            200: PublicQuoteAnswerSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
        extensions=_PREVIEW,
    )
    def post(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        s = PublicQuoteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.read", BOOKING_ENABLED)
            service = Service.all_objects.filter(
                organization_id=route.organization_id,
                pk=data["service_id"],
                active=True,
                online=True,
                time_model=TimeModel.SLOT,
            ).first()
            if service is None:
                raise NotFound("Nie ma takiej usługi.")
            organization = Organization.objects.get(pk=route.organization_id)
            asked = data.get("locale") or None
            quote = quote_visit(
                service=service,
                starts_at=data["starts_at"],
                extras=data.get("extras"),
                locale=asked if asked in organization_content_locales(organization) else None,
            )
            return Response({"quote": customer_quote(quote.snapshot())})


def _self(token: str) -> SelfServiceRoute:
    route = SelfServiceRoute.objects.filter(
        token_digest=token_digest(token), revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).first()
    if not route:
        raise NotFound("Rezerwacja nie istnieje.")
    return route


class _SelfServiceView(APIView):
    """A customer's own link: no account, the token is all."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]


class SelfServiceAppointmentView(_SelfServiceView):
    @extend_schema(
        operation_id="booking_self_service_retrieve",
        summary="Read one's own visit",
        description="The visit the customer's link names: its time, service and place, what "
        "the link may still do, and the price it was booked at. An unknown, expired or "
        "revoked link is 404.",
        tags=["public-booking"],
        responses={200: PublicAppointmentSerializer, 404: ProblemDetailsSerializer},
    )
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


class SelfServiceRescheduleView(_SelfServiceView):
    @extend_schema(
        operation_id="booking_self_service_reschedule",
        summary="Move one's own visit to another time",
        description="The customer moves the visit their link names, within what the booking "
        "allows (409 `appointment_not_changeable` otherwise). A taken time is 409 "
        "`slot_unavailable`; a visit that has a price is priced again for the new time. An "
        "unknown, expired or revoked link is 404.",
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=RescheduleSerializer,
        responses={
            200: PublicAppointmentSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, token: str) -> Response:
        route = _self(token)
        s = RescheduleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with public_booking_context(route.organization_id):
            authorize_entitled("booking.public.manage", BOOKING_ENABLED)
            try:
                value = reschedule_appointment(
                    appointment_id=route.appointment_id,
                    idempotency_key=_idem(request),
                    principal_ref=route.token_digest,
                    **s.validated_data,
                )
            except QuoteChanged as changed:
                raise QuoteChanged(changed.quote, customer=True) from None
            payload = _public_appointment_payload(value)
        return Response(payload)


class SelfServiceCancelView(_SelfServiceView):
    @extend_schema(
        operation_id="booking_self_service_cancel",
        summary="Cancel one's own visit",
        description="The customer cancels the visit their link names, within what the "
        "booking allows (409 `appointment_not_changeable` otherwise); the link stops "
        "working. The same Idempotency-Key answers the first result again.",
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={
            200: PublicAppointmentSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
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


def _person_payload(person: Person) -> dict[str, Any]:
    staff = person.staff
    return {
        "id": staff.id,
        "name": staff.display_name,
        "public_slug": staff.public_slug,
        "membership_id": staff.membership_id,
        "invitation_id": staff.invitation_id,
        "phone": staff.phone if person.private else None,
        "active": staff.active,
        "service_ids": person.service_ids,
        "has_hours": person.has_hours,
        "team_ids": person.team_ids,
        "public_name": person.public_name,
        "created_at": staff.created_at,
    }


def _person_detail_payload(detail: PersonDetail) -> dict[str, Any]:
    private = detail.person.private
    return {
        **_person_payload(detail.person),
        "hours": [
            {
                "id": rule.id,
                "weekday": rule.weekday,
                "local_start": rule.local_start,
                "local_end": rule.local_end,
                "location_id": rule.location_id,
                "location_name": rule.location.name,
            }
            for rule in detail.hours
        ],
        "time_off": [
            {
                "id": item.id,
                "starts_at": item.starts_at,
                "ends_at": item.ends_at,
                "reason": item.reason if private else None,
            }
            for item in detail.time_off
        ],
        "hours_version": detail.person.staff.hours_version,
    }


@method_decorator(csrf_protect, name="dispatch")
class StaffListView(APIView):
    """The company's people (ADR-058 §1). The team screen joins them with the
    organization's memberships and invitations; nobody drops off the list."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="api_v1_booking_staff_list",
        tags=["booking"],
        parameters=[PersonListQuerySerializer],
        responses={200: PersonListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        query = PersonListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        people = list_people(mine=query.validated_data["mine"])
        return Response({"items": [_person_payload(person) for person in people]})

    @extend_schema(
        operation_id="booking_staff_create",
        summary="Add a person to the team",
        description="The entry, the invitation when an e-mail is given, the services and "
        "hours when the person takes visits, and the teams they join — all or nothing."
        + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PersonCreateSerializer,
        responses={201: PersonDetailSerializer, 200: PersonDetailSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        serializer = PersonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        saved = add_person(
            name=data["name"],
            phone=data["phone"],
            invitation=data.get("invitation"),
            membership_id=data.get("membership_id"),
            service_ids=data["service_ids"],
            hours=data.get("hours"),
            copy_hours_from=data.get("copy_hours_from"),
            team_ids=data.get("team_ids"),
            idempotency_key=_idem(request),
        )
        return Response(
            _person_detail_payload(person_detail(saved.item_id)),
            status=200 if saved.replayed else 201,
        )


@method_decorator(csrf_protect, name="dispatch")
class StaffDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        responses={
            200: PersonDetailSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, staff_id: UUID) -> Response:
        del request
        return Response(_person_detail_payload(person_detail(staff_id)))

    @extend_schema(
        tags=["booking"],
        request=PersonUpdateSerializer,
        responses={
            200: PersonDetailSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request, staff_id: UUID) -> Response:
        serializer = PersonUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "name" in data:
            data["display_name"] = data.pop("name")
        update_staff(staff_id=staff_id, data=data)
        return Response(_person_detail_payload(person_detail(staff_id)))


@method_decorator(csrf_protect, name="dispatch")
class StaffServicesView(APIView):
    """What the person does; with hours, the calendar offers them for it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=PersonServicesInputSerializer,
        responses={
            200: PersonDetailSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, staff_id: UUID) -> Response:
        serializer = PersonServicesInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        detail = set_person_services(
            staff_id=staff_id, service_ids=serializer.validated_data["service_ids"]
        )
        return Response(_person_detail_payload(detail))


@method_decorator(csrf_protect, name="dispatch")
class StaffHoursView(APIView):
    """The person's week: management always, the person where the product lets
    them (owner's answer 7)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_staff_hours_set",
        summary="Replace a person's weekly hours",
        description="Replaces the person's whole week; an empty list clears it. Management "
        "sets anyone's hours, a person their own where the product allows it. A service the "
        "person does becomes bookable where they work. `expected_version` is the week's "
        "`hours_version`; another one is 409 `booking_version_conflict`." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PersonHoursInputSerializer,
        responses={200: PersonDetailSerializer, **_SETUP_PROBLEMS},
    )
    def put(self, request: Request, staff_id: UUID) -> Response:
        serializer = PersonHoursInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = set_person_hours(
            staff_id=staff_id,
            rules=serializer.validated_data["rules"],
            expected_version=serializer.validated_data["expected_version"],
            idempotency_key=_idem(request),
        )
        return Response(_person_detail_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class StaffHoursPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_staff_hours_set_preview",
        summary="Check a person's new weekly hours without saving them",
        description="Validates the week as `booking_staff_hours_set` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=PersonHoursInputSerializer,
        responses={200: PersonHoursPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, staff_id: UUID) -> Response:
        serializer = PersonHoursInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = set_person_hours(
            staff_id=staff_id,
            rules=serializer.validated_data["rules"],
            expected_version=serializer.validated_data["expected_version"],
            preview=True,
        )
        return Response(_with_changes(_person_detail_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class StaffTimeOffView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=TimeOffInputSerializer,
        responses={
            201: TimeOffCreatedSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, staff_id: UUID) -> Response:
        serializer = TimeOffInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, conflicts = add_time_off(staff_id=staff_id, **serializer.validated_data)
        return Response(
            {
                "time_off": {
                    "id": item.id,
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "reason": item.reason,
                },
                "conflicts": conflicts,
            },
            status=201,
        )


@method_decorator(csrf_protect, name="dispatch")
class TimeOffDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        responses={204: None, 403: ProblemDetailsSerializer, 404: ProblemDetailsSerializer},
    )
    def delete(self, request: Request, time_off_id: UUID) -> Response:
        del request
        remove_time_off(time_off_id=time_off_id)
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class StaffInvitationView(APIView):
    """An account for a person added without one; accepting links it here."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=PersonInvitationInputSerializer,
        responses={
            201: PersonInvitationSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, staff_id: UUID) -> Response:
        serializer = PersonInvitationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = invite_person(
            request=cast(HttpRequest, request),
            staff_id=staff_id,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
        )
        return Response(
            {
                "id": invitation.id,
                "email": invitation.email,
                "role": invitation.role.key,
                "status": invitation.status,
                "expires_at": invitation.expires_at,
            },
            status=201,
        )


@method_decorator(csrf_protect, name="dispatch")
class StaffEndView(APIView):
    """ "Remove from the company"; refused while the person leads planned visits."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=None,
        responses={
            200: PersonDetailSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, staff_id: UUID) -> Response:
        end_person(request=cast(HttpRequest, request), staff_id=staff_id)
        return Response(_person_detail_payload(person_detail(staff_id)))


@method_decorator(csrf_protect, name="dispatch")
class StaffRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=None,
        responses={200: PersonDetailSerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request, staff_id: UUID) -> Response:
        del request
        restore_person(staff_id=staff_id)
        return Response(_person_detail_payload(person_detail(staff_id)))


@method_decorator(csrf_protect, name="dispatch")
class StaffPublicView(APIView):
    """„Pokazuj klientom”: the person's name on the booking form, or not."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=PersonPublicInputSerializer,
        responses={200: PersonDetailSerializer, 403: ProblemDetailsSerializer},
    )
    def put(self, request: Request, staff_id: UUID) -> Response:
        s = PersonPublicInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        set_person_public(staff_id=staff_id, **s.validated_data)
        return Response(_person_detail_payload(person_detail(staff_id)))


class StaffAvailabilityView(APIView):
    """Who works, is away and is busy on one day (ADR-058 §9)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[
            OpenApiParameter(
                "date",
                date,
                OpenApiParameter.QUERY,
                description="Dzień w strefie organizacji; bez niego: dziś.",
            )
        ],
        responses={
            200: PeopleDaySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        value = request.query_params.get("date")
        try:
            day = date.fromisoformat(value) if value else None
        except ValueError as error:
            raise ParseError("Nieprawidłowa data.") from error
        day, zone, people = people_day(day)
        return Response({
            "date": day,
            "timezone": zone,
            "items": [
                {
                    "staff_id": person.staff_id,
                    "works": [{"starts_at": a, "ends_at": b} for a, b in person.works],
                    "time_off": [
                        {"starts_at": a, "ends_at": b, "reason": reason}
                        for a, b, reason in person.time_off
                    ],
                    "busy": [{"starts_at": a, "ends_at": b} for a, b in person.busy],
                }
                for person in people
            ],
        })


def _team_payload(team: Any) -> dict[str, Any]:
    return {"id": team.id, "name": team.name, "member_ids": member_ids(team)}


@method_decorator(csrf_protect, name="dispatch")
class TeamListView(APIView):
    """Standing groups of people (ADR-058 §2)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        operation_id="api_v1_booking_teams_list",
        responses={200: TeamListSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"items": [_team_payload(team) for team in list_teams()]})

    @extend_schema(
        tags=["booking"],
        request=TeamInputSerializer,
        responses={201: TeamSerializer, 400: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        s = TeamInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        team = create_team(**s.validated_data)
        return Response(_team_payload(team), status=201)


@method_decorator(csrf_protect, name="dispatch")
class TeamDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        request=TeamUpdateSerializer,
        responses={200: TeamSerializer, 400: ProblemDetailsSerializer},
    )
    def patch(self, request: Request, team_id: UUID) -> Response:
        s = TeamUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        team = update_team(team_id=team_id, **s.validated_data)
        return Response(_team_payload(team))

    @extend_schema(tags=["booking"], responses={204: None})
    def delete(self, request: Request, team_id: UUID) -> Response:
        del request
        delete_team(team_id=team_id)
        return Response(status=204)


class BookingQueueView(APIView):
    """„Do przydzielenia”: vacancies and people the system chose (ADR-058 §3)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["booking"], responses={200: QueueSerializer})
    def get(self, request: Request) -> Response:
        del request
        items = queue()
        known = _known(items)
        return Response({"items": [_queue_payload(item, known) for item in items]})


class BookingRequestsView(APIView):
    """„Prośby”: customers' bookings that wait for the company's answer."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_requests_list",
        summary="List the booking requests that wait for the company's answer",
        description="Customers' bookings of services taken on request that nobody has "
        "answered yet (`pending_request`), each with the customer's contact and "
        "`hold_expires_at` — until when the company answers before the request expires; "
        "the one that expires first comes first. Answer with `POST "
        "…/appointments/<id>/accept/` or `…/decline/`. For whoever manages bookings.",
        tags=["booking"],
        responses={200: QueueSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        items = waiting_requests()
        known = _known(items)
        return Response({"items": [_queue_payload(item, known) for item in items]})


class BookingOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["booking"], responses={200: OverviewSerializer})
    def get(self, request: Request) -> Response:
        del request
        value = overview()
        return Response({
            "bookable_staff": value.bookable_staff,
            "teams": value.teams,
            "waiting": value.waiting,
            "requests": value.requests,
            "stays": books_stays(),
        })


class AppointmentCandidatesView(APIView):
    """Who is free for one visit, and why not when they are not (ADR-058 §9)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[CandidateQuerySerializer],
        responses={200: CandidateListSerializer},
    )
    def get(self, request: Request, appointment_id: UUID) -> Response:
        query = CandidateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items = candidates(appointment_id=appointment_id, everyone=query.validated_data["everyone"])
        return Response({
            "items": [
                {
                    "staff_id": item.staff.id,
                    "name": item.staff.display_name,
                    "team_ids": item.team_ids,
                    "account": item.account,
                    "phone": item.staff.phone or None,
                    "does_service": item.does_service,
                    "state": item.status.state,
                    "until": item.status.until,
                    "hours": [
                        {"starts_at": start, "ends_at": end} for start, end in item.status.hours
                    ],
                    "on_visit": item.on_visit,
                    "lead": item.lead,
                    "day_visits": item.day_visits,
                    "day_minutes": item.day_minutes,
                    "next_free": item.next_free,
                }
                for item in items
            ]
        })


@method_decorator(csrf_protect, name="dispatch")
class AppointmentCrewView(APIView):
    """Puts exactly these people on a visit; the same people again is „Zostaw”."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=CrewInputSerializer,
        responses={
            200: AppointmentSerializer,
            400: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        s = CrewInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        value = assign_crew(
            appointment_id=appointment_id,
            staff_ids=data["staff_ids"],
            lead_id=data.get("lead_id"),
            expected_version=data["expected_version"],
            notify_staff=data["notify"],
            idempotency_key=_idem(request),
            principal_ref=str(context.actor_id),
        )
        return Response(_appointment_payload(value))


def _service_setup_payload(value: ServiceSetup) -> dict[str, Any]:
    service = value.service
    return {
        "id": service.id,
        "name": service.name,
        "appointment_kind": service.appointment_kind,
        "time_model": service.time_model,
        "range_unit": service.range_unit,
        "range_start_local": service.range_start_local,
        "range_end_local": service.range_end_local,
        "group_ids": value.group_ids,
        "duration_minutes": service.duration_minutes,
        "buffer_before_minutes": service.buffer_before_minutes,
        "buffer_after_minutes": service.buffer_after_minutes,
        "minimum_notice_minutes": service.minimum_notice_minutes,
        "staff_count": service.staff_count,
        "public_staff_choice": service.public_staff_choice,
        "slot_step_minutes": service.slot_step_minutes,
        "online": service.online,
        "confirmation": service.confirmation,
        "response_hours": service.response_hours,
        "payment_policy": service.payment_policy,
        "deposit_percent": service.deposit_percent,
        "transfer_due_days": service.transfer_due_days,
        "balance_due_days_before": service.balance_due_days_before,
        "cancellation_refunds": service.cancellation_refunds,
        "cancellation_applies_to": service.cancellation_applies_to,
        "active": service.active,
        "draft": service.draft,
        "preset_id": service.preset_id or None,
        "preset_version": service.preset_version,
        "staff_ids": value.staff_ids,
        "location_ids": value.location_ids,
        "resource_ids": value.resource_ids,
        "materials": service.materials,
        "takes_materials": stock.takes_materials(service.appointment_kind),
        "version": service.version,
        "future_bookings": value.future_bookings,
    }


def _place_payload(value: Location) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "address": value.address,
        "active": value.active,
        "online": value.online,
        "version": value.version,
    }


def _resource_payload(value: Resource) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "active": value.active,
        "group_id": value.group_id,
        "location_id": value.location_id,
        "capacity": value.capacity,
        "description": value.description,
        "version": value.version,
    }


def _group_payload(value: ResourceGroup) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "description": value.description,
        "active": value.active,
        "version": value.version,
    }


def _block_payload(value: UnitBlock) -> dict[str, Any]:
    block = value.block
    return {
        "id": block.id,
        "resource_id": block.resource_id,
        "starts_at": block.starts_at,
        "ends_at": block.ends_at,
        "reason": block.reason,
        "source": block.source,
        "holds": value.holds,
    }


class BookingSetupView(APIView):
    """Ustawienia › Usługi i grafik: everything, switched-off items included."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_retrieve",
        summary="Read services, places, resources and people as setup edits them",
        description="Every service with who does it, where and with which resource, every "
        "place and resource, switched-off ones included, and the company's current people. "
        "Each item carries the version a change of it names.",
        tags=["booking"],
        responses={200: SetupSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        value = list_setup()
        return Response({
            "services": [_service_setup_payload(item) for item in value.services],
            "locations": [_place_payload(item) for item in value.locations],
            "resources": [_resource_payload(item) for item in value.resources],
            "groups": [_group_payload(item) for item in value.groups],
            "staff": [
                {"id": item.id, "name": item.display_name, "hours_version": item.hours_version}
                for item in value.staff
            ],
            "appointment_kinds": [
                {"key": key, "label": label} for key, label in value.appointment_kinds.items()
            ],
        })


class BookingSetupOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_options_retrieve",
        summary="Read what can be set on a service, with bounds and defaults",
        description="Every setting of an offer: type, bounds, unit, variants with labels, the "
        "default a new service gets and a description. The entries have the shape of the "
        "company settings registry (ADR-078).",
        tags=["booking"],
        responses={200: SetupOptionsSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({
            "keys": setup_options(),
            "refund_thresholds": REFUND_THRESHOLDS,
            "cancel_reasons": list(CANCEL_REASONS),
        })


def _preset_payload(item: Preset) -> dict[str, Any]:
    return {
        "id": item.id,
        "version": item.version,
        "readiness": item.readiness,
        "labels": item.labels,
        "time_model": item.time_model,
        "booked_subject": item.booked_subject,
        "booked_staff": item.booked_staff,
        "place": item.place,
        "required_inputs": list(item.required_inputs),
        "catalog_category": item.catalog_category,
        "online_booking": item.online_booking,
    }


class BookingPresetListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_presets_list",
        summary="List what the company may start an offer from",
        description="The presets of ADR-072 §10 in the order a company sees them, each in "
        "its latest version: ready ones can be applied, the rest are announced. This list "
        "is the only source a panel, a site or the assistant chooses from.",
        tags=["booking"],
        responses={200: PresetListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"presets": [_preset_payload(item) for item in list_presets()]})


@method_decorator(csrf_protect, name="dispatch")
class SetupServiceListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_service_create",
        summary="Add a service",
        description="Creates a service with who does it, where, the resource a visit takes "
        "and the products it uses." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ServiceInputSerializer,
        responses={201: ServiceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = ServiceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_service(
            service_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_service_setup_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class SetupServiceCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_service_create_preview",
        summary="Check a new service without adding it",
        description="Validates a new service as `booking_setup_service_create` would."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=ServiceInputSerializer,
        responses={200: ServiceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = ServiceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_service(service_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_service_setup_payload(saved.value), saved.changes))


def _update(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    values = dict(data)
    return values, values.pop("expected_version")


@method_decorator(csrf_protect, name="dispatch")
class SetupServiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_service_update",
        summary="Change a service",
        description="Changes a service's settings, people, places, resource or products; "
        "booked visits keep what they were booked with." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ServiceUpdateSerializer,
        responses={200: ServiceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, service_id: UUID) -> Response:
        s = ServiceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_service(
            service_id=service_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_service_setup_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class SetupServiceUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_service_update_preview",
        summary="Check a change to a service without saving it",
        description="Validates a change as `booking_setup_service_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=ServiceUpdateSerializer,
        responses={200: ServiceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, service_id: UUID) -> Response:
        s = ServiceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_service(
            service_id=service_id, data=data, expected_version=version, preview=True
        )
        return Response(_with_changes(_service_setup_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupLocationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_location_create",
        summary="Add a place of work",
        description="Creates a place where the company works and takes visits." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PlaceInputSerializer,
        responses={201: PlaceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = PlaceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_location(
            location_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_place_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class SetupLocationCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_location_create_preview",
        summary="Check a new place without adding it",
        description="Validates a new place as `booking_setup_location_create` would."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=PlaceInputSerializer,
        responses={200: PlaceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = PlaceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_location(location_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_place_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupLocationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_location_update",
        summary="Change a place of work",
        description="Renames a place, changes its address or switches it off." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PlaceUpdateSerializer,
        responses={200: PlaceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, location_id: UUID) -> Response:
        s = PlaceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_location(
            location_id=location_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_place_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class SetupLocationUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_location_update_preview",
        summary="Check a change to a place without saving it",
        description="Validates a change as `booking_setup_location_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=PlaceUpdateSerializer,
        responses={200: PlaceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, location_id: UUID) -> Response:
        s = PlaceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_location(
            location_id=location_id, data=data, expected_version=version, preview=True
        )
        return Response(_with_changes(_place_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupResourceListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_resource_create",
        summary="Add a resource",
        description="Creates a resource — a room, a chair, a device — that a visit can take."
        + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ResourceInputSerializer,
        responses={201: ResourceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = ResourceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_resource(
            resource_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_resource_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class SetupResourceCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_resource_create_preview",
        summary="Check a new resource without adding it",
        description="Validates a new resource as `booking_setup_resource_create` would."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=ResourceInputSerializer,
        responses={200: ResourceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = ResourceInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_resource(resource_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_resource_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupResourceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_resource_update",
        summary="Change a resource",
        description="Renames a resource or switches it off." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ResourceUpdateSerializer,
        responses={200: ResourceSetupSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, resource_id: UUID) -> Response:
        s = ResourceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_resource(
            resource_id=resource_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_resource_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class SetupResourceUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_resource_update_preview",
        summary="Check a change to a resource without saving it",
        description="Validates a change as `booking_setup_resource_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=ResourceUpdateSerializer,
        responses={200: ResourceSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, resource_id: UUID) -> Response:
        s = ResourceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_resource(
            resource_id=resource_id, data=data, expected_version=version, preview=True
        )
        return Response(_with_changes(_resource_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupGroupListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_group_create",
        summary="Add a group of identical units",
        description="Creates a pool of identical units (e.g. „Domek 6-os.”); a booking of the "
        "group gets a free unit of it. A unit joins a group through its own `group_id`."
        + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=GroupInputSerializer,
        responses={201: GroupSetupSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = GroupInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_group(
            group_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_group_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class SetupGroupCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_group_create_preview",
        summary="Check a new group without adding it",
        description="Validates a new group as `booking_setup_group_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=GroupInputSerializer,
        responses={200: GroupSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = GroupInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_group(group_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_group_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class SetupGroupDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_group_update",
        summary="Change a group of units",
        description="Renames a group, changes its description or switches it off." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=GroupUpdateSerializer,
        responses={200: GroupSetupSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, group_id: UUID) -> Response:
        s = GroupUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_group(
            group_id=group_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_group_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class SetupGroupUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_setup_group_update_preview",
        summary="Check a change to a group without saving it",
        description="Validates a change as `booking_setup_group_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=GroupUpdateSerializer,
        responses={200: GroupSetupPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, group_id: UUID) -> Response:
        s = GroupUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_group(group_id=group_id, data=data, expected_version=version, preview=True)
        return Response(_with_changes(_group_payload(saved.value), saved.changes))


_BLOCK_WINDOW = [
    OpenApiParameter(
        "from", datetime, OpenApiParameter.QUERY, required=True, description="Window start."
    ),
    OpenApiParameter(
        "to", datetime, OpenApiParameter.QUERY, required=True, description="Window end."
    ),
]


@method_decorator(csrf_protect, name="dispatch")
class UnitBlockListView(APIView):
    """A unit's blocks: the company keeps it for itself (ADR-072 §4)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_unit_blocks_list",
        summary="List a unit's blocks in a window",
        description="The unit's blocks — manual and imported — that touch the window, "
        "oldest first.",
        tags=["booking"],
        parameters=_BLOCK_WINDOW,
        responses={200: UnitBlockListSerializer, **_SETUP_PROBLEMS},
    )
    def get(self, request: Request, resource_id: UUID) -> Response:
        window = _window(request)
        items = list_unit_blocks(
            resource_id=resource_id, starts_from=window[0], starts_until=window[1]
        )
        return Response({"items": [_block_payload(item) for item in items]})

    @extend_schema(
        operation_id="booking_unit_block_create",
        summary="Block a unit for a while",
        description="Keeps the unit for the company (a renovation, own use). A block over a "
        "booking or another block of the unit is 409 `unit_busy`." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=UnitBlockInputSerializer,
        responses={201: UnitBlockSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request, resource_id: UUID) -> Response:
        s = UnitBlockInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = add_unit_block(
            resource_id=resource_id, **s.validated_data, idempotency_key=_idem(request)
        )
        return Response(_block_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class UnitBlockPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_unit_block_create_preview",
        summary="Check a unit's block without saving it",
        description="Answers as `booking_unit_block_create` would, 409 `unit_busy` included."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=UnitBlockInputSerializer,
        responses={200: UnitBlockSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, resource_id: UUID) -> Response:
        s = UnitBlockInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = add_unit_block(resource_id=resource_id, **s.validated_data, preview=True)
        return Response(_block_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class UnitBlockDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_unit_block_delete",
        summary="Remove a unit's block",
        description="Lets the unit's time go; only a manual block can be removed here, an "
        "imported one goes with its calendar." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        responses={204: None, **_SETUP_PROBLEMS},
    )
    def delete(self, request: Request, block_id: UUID) -> Response:
        remove_unit_block(time_off_id=block_id, idempotency_key=_idem(request))
        return Response(status=204)


def _window(request: Request) -> tuple[datetime, datetime]:
    values = []
    for name in ("from", "to"):
        raw = request.query_params.get(name, "")
        value = parse_datetime(raw) if raw else None
        if value is None or value.tzinfo is None:
            raise ValidationError({name: "Podaj chwilę ze strefą (ISO 8601)."}, code="invalid")
        values.append(value)
    if values[1] <= values[0]:
        raise ValidationError({"to": "Koniec okna musi być po jego początku."}, code="invalid")
    return values[0], values[1]


def _rule_payload(value: BookingRule) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "service_id": value.service_id,
        "group_id": value.group_id,
        "resource_id": value.resource_id,
        "starts_on": value.starts_on,
        "ends_on": value.ends_on,
        "min_length": value.min_length,
        "max_length": value.max_length,
        "length_multiple": value.length_multiple,
        "start_weekdays": value.start_weekdays,
        "end_weekdays": value.end_weekdays,
        "notice_hours": value.notice_hours,
        "window_days": value.window_days,
        "closed": value.closed,
        "buffer_after_minutes": value.buffer_after_minutes,
        "active": value.active,
        "version": value.version,
    }


def _closure_payload(value: BookingClosure) -> dict[str, Any]:
    return {
        "id": value.id,
        "location_id": value.location_id,
        "starts_on": value.starts_on,
        "ends_on": value.ends_on,
        "note": value.note,
        "version": value.version,
    }


_VERSION_QUERY = OpenApiParameter(
    "expected_version",
    int,
    OpenApiParameter.QUERY,
    required=True,
    description="The version the deletion was decided on; another one is 409 "
    "`booking_version_conflict`.",
)


def _expected(request: Request) -> int:
    raw = request.query_params.get("expected_version", "")
    if not raw.isdigit() or int(raw) < 1:
        raise ValidationError({"expected_version": "Podaj wersję, którą usuwasz."}, code="required")
    return int(raw)


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleListView(APIView):
    """Seasons of offers, groups and units (ADR-072 §5)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rules_list",
        summary="List the seasons' booking rules",
        description="Every season of the company's offers, groups and units, switched-off "
        "ones included, by first day.",
        tags=["booking"],
        responses={200: BookingRuleListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"items": [_rule_payload(item) for item in list_rules()]})

    @extend_schema(
        operation_id="booking_rule_create",
        summary="Add a season's booking rules",
        description="Rules for exactly one offer, group or unit on local dates: shortest and "
        "longest booking, whole weeks, arrival and departure weekdays, notice, how far ahead, "
        "closed, the break after. For a day the unit's rule beats its group's, which beats "
        "the offer's; between two of one kind the later start." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=BookingRuleInputSerializer,
        responses={201: BookingRuleSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = BookingRuleInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_rule(rule_id=None, data=dict(s.validated_data), idempotency_key=_idem(request))
        return Response(_rule_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rule_create_preview",
        summary="Check a season's rules without adding them",
        description="Validates a season as `booking_rule_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=BookingRuleInputSerializer,
        responses={200: BookingRulePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = BookingRuleInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_rule(rule_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_rule_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rule_update",
        summary="Change a season's rules",
        description="Changes a season's dates or rules, or switches it off." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=BookingRuleUpdateSerializer,
        responses={200: BookingRuleSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, rule_id: UUID) -> Response:
        s = BookingRuleUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_rule(
            rule_id=rule_id, data=data, expected_version=version, idempotency_key=_idem(request)
        )
        return Response(_rule_payload(saved.value))

    @extend_schema(
        operation_id="booking_rule_delete",
        summary="Delete a season's rules",
        description="Removes the season; bookings made under it keep what they were booked "
        "with." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY, _VERSION_QUERY],
        responses={204: None, **_SETUP_PROBLEMS},
    )
    def delete(self, request: Request, rule_id: UUID) -> Response:
        delete_rule(
            rule_id=rule_id, expected_version=_expected(request), idempotency_key=_idem(request)
        )
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rule_update_preview",
        summary="Check a change to a season without saving it",
        description="Validates a change as `booking_rule_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=BookingRuleUpdateSerializer,
        responses={200: BookingRulePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, rule_id: UUID) -> Response:
        s = BookingRuleUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_rule(rule_id=rule_id, data=data, expected_version=version, preview=True)
        return Response(_with_changes(_rule_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleCopyYearView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rules_copy_year",
        summary="Copy a year's seasons to the next year",
        description="Every season starting in `year` again a year later, as new rules; the "
        "weekdays move, so check the dates after." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=CopyYearInputSerializer,
        responses={201: CopyYearResultSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_rules_to_next_year(
            year=s.validated_data["year"], idempotency_key=_idem(request)
        )
        return Response({"count": len(saved.value)}, status=201)


@method_decorator(csrf_protect, name="dispatch")
class BookingRuleCopyYearPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_rules_copy_year_preview",
        summary="Count the seasons a copy to the next year would make",
        description="Answers as `booking_rules_copy_year` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=CopyYearInputSerializer,
        responses={200: CopyYearResultSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_rules_to_next_year(year=s.validated_data["year"], preview=True)
        return Response({"count": len(saved.value)})


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureListView(APIView):
    """Days the company or a place is closed (B11, ADR-078 pkt 17)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closures_list",
        summary="List the days the company or a place is closed",
        description="Every closure, by first day.",
        tags=["booking"],
        responses={200: BookingClosureListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"items": [_closure_payload(item) for item in list_closures()]})

    @extend_schema(
        operation_id="booking_closure_create",
        summary="Close the company or a place on some days",
        description="No booking starts on these local days — not from the website, not from "
        "the panel — whatever the hours or the seasons say." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=BookingClosureInputSerializer,
        responses={201: BookingClosureSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = BookingClosureInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_closure(
            closure_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_closure_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closure_create_preview",
        summary="Check a closure without adding it",
        description="Validates a closure as `booking_closure_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=BookingClosureInputSerializer,
        responses={200: BookingClosurePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = BookingClosureInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_closure(closure_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_closure_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closure_update",
        summary="Change a closure",
        description="Changes a closure's days, place or note." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=BookingClosureUpdateSerializer,
        responses={200: BookingClosureSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, closure_id: UUID) -> Response:
        s = BookingClosureUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_closure(
            closure_id=closure_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_closure_payload(saved.value))

    @extend_schema(
        operation_id="booking_closure_delete",
        summary="Open the days of a closure again",
        description="Removes the closure; its days take bookings again." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY, _VERSION_QUERY],
        responses={204: None, **_SETUP_PROBLEMS},
    )
    def delete(self, request: Request, closure_id: UUID) -> Response:
        delete_closure(
            closure_id=closure_id,
            expected_version=_expected(request),
            idempotency_key=_idem(request),
        )
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closure_update_preview",
        summary="Check a change to a closure without saving it",
        description="Validates a change as `booking_closure_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=BookingClosureUpdateSerializer,
        responses={200: BookingClosurePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, closure_id: UUID) -> Response:
        s = BookingClosureUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_closure(
            closure_id=closure_id, data=data, expected_version=version, preview=True
        )
        return Response(_with_changes(_closure_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureCopyYearView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closures_copy_year",
        summary="Copy a year's closures to the next year",
        description="Every closure starting in `year` again a year later (Christmas recurs)."
        + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=CopyYearInputSerializer,
        responses={201: CopyYearResultSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_closures_to_next_year(
            year=s.validated_data["year"], idempotency_key=_idem(request)
        )
        return Response({"count": len(saved.value)}, status=201)


@method_decorator(csrf_protect, name="dispatch")
class BookingClosureCopyYearPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_closures_copy_year_preview",
        summary="Count the closures a copy to the next year would make",
        description="Answers as `booking_closures_copy_year` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=CopyYearInputSerializer,
        responses={200: CopyYearResultSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_closures_to_next_year(year=s.validated_data["year"], preview=True)
        return Response({"count": len(saved.value)})


def _plan_payload(plan: StayPlan) -> dict[str, Any]:
    return {
        "resource_id": plan.unit.id,
        "resource_name": plan.unit.name,
        "starts_at": plan.stay.starts_at,
        "ends_at": plan.stay.ends_at,
        "length": plan.stay.length,
        "range_unit": plan.service.range_unit,
        "quote": plan.quote.snapshot() if plan.quote is not None else None,
    }


def _query_date(request: Request, name: str) -> date:
    raw = request.query_params.get(name, "")
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise ValidationError({name: "Podaj datę (RRRR-MM-DD)."}, code="invalid") from error


def _query_uuid(request: Request, name: str) -> UUID | None:
    raw = request.query_params.get(name, "")
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as error:
        raise ValidationError({name: "Nieprawidłowy identyfikator."}, code="invalid") from error


_STAY_TARGET = [
    OpenApiParameter("service_id", UUID, OpenApiParameter.QUERY, required=True),
    OpenApiParameter("resource_id", UUID, OpenApiParameter.QUERY, description="Only this unit."),
    OpenApiParameter(
        "group_id", UUID, OpenApiParameter.QUERY, description="Any unit of this group."
    ),
]


class StayStartsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_starts_list",
        summary="List the days a stay can begin on",
        description="Days in the window a unit is free for the shortest stay the season "
        "allows from that day, closed days and the season's rules applied (ADR-072 §5). "
        "One query; the window spans at most BOOKING_PERIOD_HORIZON_DAYS.",
        tags=["booking"],
        parameters=[
            *_STAY_TARGET,
            OpenApiParameter("from", date, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("to", date, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: DateListSerializer, **_SETUP_PROBLEMS},
    )
    def get(self, request: Request) -> Response:
        service_id = _query_uuid(request, "service_id")
        if service_id is None:
            raise ValidationError({"service_id": "Podaj usługę."}, code="required")
        days = stay_starts(
            service_id=service_id,
            resource_id=_query_uuid(request, "resource_id"),
            group_id=_query_uuid(request, "group_id"),
            from_date=_query_date(request, "from"),
            to_date=_query_date(request, "to"),
        )
        return Response({"items": days})


class StayEndsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_ends_list",
        summary="List the days a stay beginning on a day can end on",
        description="Departure days (nights) or last days (days) a stay from `start` can "
        "have on a free unit, the season of the arrival day applied.",
        tags=["booking"],
        parameters=[
            *_STAY_TARGET,
            OpenApiParameter("start", date, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: DateListSerializer, **_SETUP_PROBLEMS},
    )
    def get(self, request: Request) -> Response:
        service_id = _query_uuid(request, "service_id")
        if service_id is None:
            raise ValidationError({"service_id": "Podaj usługę."}, code="required")
        days = stay_ends(
            service_id=service_id,
            resource_id=_query_uuid(request, "resource_id"),
            group_id=_query_uuid(request, "group_id"),
            start_date=_query_date(request, "start"),
        )
        return Response({"items": days})


@method_decorator(csrf_protect, name="dispatch")
class BookingQuoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_quote",
        summary="Work out what a booking would cost",
        description="The price of a visit at `starts_at`, or of a stay from `start_date` to "
        "`end_date` on the unit a booking would take, for the people who come: lines with "
        "net, tax and gross, and the totals. Nothing is saved and nothing is held. A booking "
        "works the price out again and keeps it; send it the `digest` as `quote_digest` and "
        "a price that changed in between answers 409 `quote_changed`. An offer without a "
        "price list answers no lines. Refusals name the field: `price_missing`, "
        "`unit_capacity_exceeded`, `participants_required`, and what a stay's rules refuse. "
        "With `price_only` the answer is what the price list says for that time whether or "
        "not it could be booked — for a preview of the price list. Each line names the price "
        "it came from (`price_rule_id`).",
        tags=["booking"],
        request=BookingQuoteInputSerializer,
        responses={200: BookingQuoteSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = BookingQuoteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        data["locale"] = data.get("locale") or None
        return Response(quote_offer(**data).snapshot())


@method_decorator(csrf_protect, name="dispatch")
class StayCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_create",
        summary="Book a stay or a rental",
        description="Books a range offer from–to on a unit, or on the least busy free unit of "
        "a group. A broken season rule is 400 with its code (`rule_min_length`, "
        "`rule_start_weekday`, `closed_day`…), taken dates 409 `slot_unavailable`. The same "
        "Idempotency-Key answers the first booking again.",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=StayInputSerializer,
        responses={201: AppointmentSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        s = StayInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        result = book_stay(
            **data,
            customer_data=customer,
            idempotency_key=_idem(request),
            principal_ref=str(context.actor_id),
        )
        assert isinstance(result, CreatedAppointment)
        return Response(
            _appointment_payload(result.appointment, result.token),
            status=201 if result.created else 200,
        )


@method_decorator(csrf_protect, name="dispatch")
class StayPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_create_preview",
        summary="Check a stay without booking it",
        description="Which unit a booking would take, its instants and length — or the "
        "same 400 and 409 the booking would answer. Nothing is saved.",
        tags=["booking"],
        request=StayInputSerializer,
        responses={200: StayPlanSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = StayInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        plan = book_stay(
            **data,
            customer_data=customer,
            idempotency_key="",
            principal_ref="",
            preview=True,
        )
        assert isinstance(plan, StayPlan)
        return Response(_plan_payload(plan))


@method_decorator(csrf_protect, name="dispatch")
class StayMoveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_move",
        summary="Move a stay to other dates",
        description="Keeps the unit when it is free then, otherwise takes another free unit "
        "of the group the stay was booked in. Rules and closed days as for a booking.",
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=StayMoveSerializer,
        responses={200: AppointmentSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
        s = StayMoveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        moved = move_stay(
            appointment_id=appointment_id,
            **s.validated_data,
            idempotency_key=_idem(request),
            principal_ref=str(context.actor_id),
        )
        assert isinstance(moved, Appointment)
        return Response(_appointment_payload(moved))


@method_decorator(csrf_protect, name="dispatch")
class StayMovePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_stay_move_preview",
        summary="Check a move of a stay without making it",
        description="Answers as `booking_stay_move` would; nothing is saved.",
        tags=["booking"],
        request=StayMoveSerializer,
        responses={200: StayPlanSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, appointment_id: UUID) -> Response:
        s = StayMoveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        plan = move_stay(
            appointment_id=appointment_id,
            **s.validated_data,
            idempotency_key="",
            principal_ref="",
            preview=True,
        )
        assert isinstance(plan, StayPlan)
        return Response(_plan_payload(plan))


_PERIOD = [
    OpenApiParameter("from", date, OpenApiParameter.QUERY, description="Pierwszy dzień okresu."),
    OpenApiParameter(
        "to", date, OpenApiParameter.QUERY, description="Ostatni dzień; bez niego: dziś."
    ),
]


def _period_days(request: Request) -> tuple[date | None, date | None]:
    try:
        return tuple(  # type: ignore[return-value]
            date.fromisoformat(value) if (value := request.query_params.get(name)) else None
            for name in ("from", "to")
        )
    except ValueError as error:
        raise ParseError("Nieprawidłowa data.") from error


class StaffFactsView(APIView):
    """A person's results (team plan, phase 5): one's own, or anybody's for the
    owner and the administrator."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=_PERIOD,
        responses={
            200: StaffFactsSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, staff_id: UUID) -> Response:
        first, last = _period_days(request)
        return Response(StaffFactsSerializer(staff_facts(staff_id, first, last)).data)


class StaffHistoryView(APIView):
    """What happened to a person, newest first, a page at a time."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[
            *_PERIOD,
            OpenApiParameter("kind", str, OpenApiParameter.QUERY, description="Jeden rodzaj."),
            OpenApiParameter(
                "before", datetime, OpenApiParameter.QUERY, description="Starsze niż ta chwila."
            ),
        ],
        responses={
            200: StaffHistorySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, staff_id: UUID) -> Response:
        first, last = _period_days(request)
        value = request.query_params.get("before")
        try:
            before = datetime.fromisoformat(value) if value else None
        except ValueError as error:
            raise ParseError("Nieprawidłowa chwila.") from error
        return Response(
            StaffHistorySerializer(
                staff_history(
                    staff_id,
                    first,
                    last,
                    kind=request.query_params.get("kind", ""),
                    before=before,
                )
            ).data
        )


class PerformanceView(APIView):
    """Everybody's numbers side by side: the owner's and administrator's view."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["booking"],
        parameters=[
            *_PERIOD,
            OpenApiParameter("team", UUID, OpenApiParameter.QUERY, description="Jeden zespół."),
        ],
        responses={
            200: PerformanceSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        first, last = _period_days(request)
        value = request.query_params.get("team")
        try:
            team = UUID(value) if value else None
        except ValueError as error:
            raise ParseError("Nieprawidłowy zespół.") from error
        return Response(PerformanceSerializer(team_performance(first, last, team_id=team)).data)


def _held_title(item: Held, titles: Mapping[UUID, str]) -> str:
    """A block says why; a booking goes by its module's name, else the customer's."""
    if item.block is not None:
        return item.block.reason
    assert item.appointment is not None
    return titles.get(item.appointment.id) or item.appointment.customer.display_name


def _held_price(item: Held) -> dict[str, Any]:
    """What a booking shown comes to, from its frozen quote; nothing for a
    block, a booking without a price and somebody else's."""
    quote = item.appointment.quote if item.appointment is not None and not item.hidden else None
    if not quote or not quote.get("lines"):
        return {"gross_minor": None, "currency": None}
    return {"gross_minor": quote["gross_minor"], "currency": quote["currency"]}


class BookingOccupancyView(APIView):
    """Obłożenie: units against days (ADR-072 phase 2d)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_occupancy_retrieve",
        summary="Read what holds each unit, day by day",
        description="Every active unit (of one group with `group_id`) with what holds it from "
        "`from` to `to`, local days included: stays, visits that take the unit, and blocks — "
        "a block that could not take its time is listed too. Closed days of the company or "
        f"of a unit's place come with it. At most {MAX_OCCUPANCY_DAYS} days per read. A "
        "booking of somebody else's that the caller may not see (a product's "
        "`appointmentsOfOthersPermission`, UX-023) comes with its time only: no "
        "`appointment_id`, `title` or `status`.",
        tags=["booking"],
        parameters=[
            OpenApiParameter("from", date, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("to", date, OpenApiParameter.QUERY, required=True),
            OpenApiParameter(
                "group_id",
                UUID,
                OpenApiParameter.QUERY,
                description="Only the units of this group.",
            ),
        ],
        responses={
            200: OccupancySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        value = occupancy(
            first=_query_date(request, "from"),
            last=_query_date(request, "to"),
            group_id=_query_uuid(request, "group_id"),
        )
        bookings = [item.appointment for item in value.held if item.appointment is not None]
        titles = appointment_titles([item.id for item in bookings])
        return Response({
            "date_from": value.first,
            "date_to": value.last,
            "timezone": value.timezone,
            "units": [
                {
                    "id": unit.id,
                    "name": unit.name,
                    "group_id": unit.group_id,
                    "group_name": unit.group.name if unit.group else None,
                    "location_id": unit.location_id,
                    "capacity": unit.capacity,
                }
                for unit in value.units
            ],
            "held": [
                {
                    "unit_id": item.unit_id,
                    "kind": item.kind,
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    "appointment_id": (
                        item.appointment.id if item.appointment and not item.hidden else None
                    ),
                    "block_id": item.block.id if item.block else None,
                    "title": "" if item.hidden else _held_title(item, titles),
                    "status": (
                        item.appointment.status if item.appointment and not item.hidden else ""
                    ),
                    **_held_price(item),
                }
                for item in value.held
            ],
            "closures": [_closure_payload(item) for item in value.closures],
        })
