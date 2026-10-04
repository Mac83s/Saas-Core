"""Stays on the company's public form and on a customer's own link (ADR-072,
phase 5a): the arrival and departure days of an offer booked from–to, what a
stay would cost, the booking itself, and moving one's own stay by its dates.

Everything here runs in the public form's service scope, so it finds only
what the company offers online (`periods._offer`), and a write never books a
price the customer was not shown: `quote_digest` is required as soon as the
quote has something to show.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization

from .consents import BookingConsents
from .models import Appointment
from .periods import StayPlan, book_stay, move_stay, stay_ends, stay_starts
from .quote import QuoteChanged, customer_quote
from .security import public_booking_context
from .serializers import (
    CustomerInputSerializer,
    DateListSerializer,
    PublicAppointmentSerializer,
    PublicConsentsInputSerializer,
    PublicQuoteSerializer,
    _extras,
    _participants,
)
from .services import CreatedAppointment
from .views import (
    _PREVIEW,
    IDEMPOTENCY,
    BookingThrottle,
    _idem,
    _public_appointment_payload,
    _query_date,
    _query_uuid,
    _route,
    _self,
    _SelfServiceView,
)

_PROBLEMS = {
    400: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}

_TARGET = [
    OpenApiParameter("service_id", UUID, OpenApiParameter.QUERY, required=True),
    OpenApiParameter(
        "group_id",
        UUID,
        OpenApiParameter.QUERY,
        description="Any unit of this group of the offer (`stays[].groups`).",
    ),
    OpenApiParameter(
        "resource_id",
        UUID,
        OpenApiParameter.QUERY,
        description="Only this unit of the offer (`stays[].units`). With neither, any "
        "unit the offer lists.",
    ),
]


def _required_digest() -> serializers.CharField:
    return serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="The `digest` of the quote the customer was shown. Required as soon as "
        "the stay has a price: without it, or when the price is another one by now, the "
        "answer is 409 `quote_changed` with the quote to show in `detail.quote`, and "
        "nothing is saved.",
    )


class _StayTargetSerializer(serializers.Serializer[dict[str, Any]]):
    service_id = serializers.UUIDField(help_text="An offer from `stays` of the form's catalogue.")
    group_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Any free unit of this group — the server picks the least busy one that "
        "takes the people who come.",
    )
    resource_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="This very unit. With neither, any unit the offer lists.",
    )
    start_date = serializers.DateField(help_text="Arrival day (nights) or first day (days).")
    end_date = serializers.DateField(
        help_text="Departure day (nights) or last day, included (days)."
    )
    participants = _participants()
    extras = _extras()


class PublicStayQuoteInputSerializer(_StayTargetSerializer):
    """The stay a customer is about to book, to be checked and priced."""

    locale = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10,
        help_text="The customer's language, for the lines' names; one the company does not "
        "have is answered in its own.",
    )


class PublicStayPlanSerializer(serializers.Serializer[dict[str, Any]]):
    """A stay that can be booked as asked, as the customer reads it."""

    starts_at = serializers.DateTimeField(help_text="When the stay begins (check-in, pickup).")
    ends_at = serializers.DateTimeField(help_text="When it ends (check-out, return).")
    length = serializers.IntegerField(help_text="Nights or days.")
    range_unit = serializers.CharField(help_text="`night` or `day`.")
    quote = PublicQuoteSerializer(
        allow_null=True, help_text="Null — the stay has no price to show."
    )


class PublicStayCreateSerializer(_StayTargetSerializer):
    """The customer names the offer, what they book of it, the dates and who
    comes; which unit of a group it is, is the server's pick (ADR-072 §3)."""

    customer = CustomerInputSerializer()
    #: „Uwagi”: for the company's eyes only, never in an e-mail.
    customer_notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    quote_digest = _required_digest()
    consents = PublicConsentsInputSerializer(
        required=False,
        help_text="The company's documents the customer accepted; required as soon as the "
        "company has one in force in the booking's language.",
    )


class PublicStayMoveSerializer(serializers.Serializer[dict[str, Any]]):
    start_date = serializers.DateField(help_text="The new arrival day or first day.")
    end_date = serializers.DateField(help_text="The new departure day or last day.")
    quote_digest = _required_digest()


class PublicStayMovePreviewSerializer(serializers.Serializer[dict[str, Any]]):
    start_date = serializers.DateField(help_text="The new arrival day or first day.")
    end_date = serializers.DateField(help_text="The new departure day or last day.")


def _plan_payload(plan: StayPlan) -> dict[str, Any]:
    """The plan without the unit: of a group the booking takes whichever is
    free then, and the company's net, tax and ids stay the company's."""
    return {
        "starts_at": plan.stay.starts_at,
        "ends_at": plan.stay.ends_at,
        "length": plan.stay.length,
        "range_unit": plan.service.range_unit,
        "quote": customer_quote(plan.quote.snapshot()) if plan.quote is not None else None,
    }


def _target(request: Request) -> tuple[UUID, UUID | None, UUID | None]:
    """The offer asked about, and the unit or the group of it."""
    service_id = _query_uuid(request, "service_id")
    if service_id is None:
        raise serializers.ValidationError({"service_id": "Podaj ofertę."}, code="required")
    return service_id, _query_uuid(request, "resource_id"), _query_uuid(request, "group_id")


class _PublicStayView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]


class PublicStayStartsView(_PublicStayView):
    @extend_schema(
        operation_id="public_booking_stay_starts",
        summary="List the days a stay booked on the form can begin on",
        description="Days in the window on which a unit is free for the shortest stay the "
        "season allows from that day — closed days, the season's rules and its window ahead "
        "applied (ADR-072 §5). One search spans at most 92 days and never goes past "
        "`online.period_last_day`. An offer that is not on the form is 404.",
        tags=["public-booking"],
        parameters=[
            *_TARGET,
            OpenApiParameter("from", date, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("to", date, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: DateListSerializer, 400: ProblemDetailsSerializer, 404: _PROBLEMS[404]},
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service_id, resource_id, group_id = _target(request)
        with public_booking_context(route.organization_id):
            days = stay_starts(
                service_id=service_id,
                resource_id=resource_id,
                group_id=group_id,
                from_date=_query_date(request, "from"),
                to_date=_query_date(request, "to"),
            )
        return Response({"items": days})


class PublicStayEndsView(_PublicStayView):
    @extend_schema(
        operation_id="public_booking_stay_ends",
        summary="List the days a stay beginning on a day can end on",
        description="Departure days (nights) or last days (days) a stay from `start` can "
        "have on a free unit, the season of the arrival day applied. An offer that is not "
        "on the form is 404.",
        tags=["public-booking"],
        parameters=[
            *_TARGET,
            OpenApiParameter("start", date, OpenApiParameter.QUERY, required=True),
        ],
        responses={200: DateListSerializer, 400: ProblemDetailsSerializer, 404: _PROBLEMS[404]},
    )
    def get(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        service_id, resource_id, group_id = _target(request)
        with public_booking_context(route.organization_id):
            days = stay_ends(
                service_id=service_id,
                resource_id=resource_id,
                group_id=group_id,
                start_date=_query_date(request, "start"),
            )
        return Response({"items": days})


class PublicStayQuoteView(_PublicStayView):
    @extend_schema(
        operation_id="public_booking_stay_quote",
        summary="Check a stay from the booking form and work out what it would cost",
        description="Plans the stay exactly as a booking would — a broken season rule is "
        "400 with its code (`rule_min_length`, `rule_start_weekday`, `closed_day`…), more "
        "people than a unit takes 400 `unit_capacity_exceeded`, taken dates 409 "
        "`slot_unavailable` — and answers its instants, its length and its price as the "
        "customer reads it: gross, the lines in their language, the deposit, how they pay "
        "and what giving it up gives back. Nothing is saved or held. Send `quote.digest` "
        "back as `quote_digest` when booking.",
        tags=["public-booking"],
        request=PublicStayQuoteInputSerializer,
        responses={200: PublicStayPlanSerializer, **_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        s = PublicStayQuoteInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        asked = data.pop("locale", "") or None
        with public_booking_context(route.organization_id):
            organization = Organization.objects.get(pk=route.organization_id)
            plan = book_stay(
                **data,
                customer_data={
                    "locale": asked if asked in organization_content_locales(organization) else ""
                },
                idempotency_key="",
                principal_ref="",
                preview=True,
            )
            assert isinstance(plan, StayPlan)
            return Response(_plan_payload(plan))


class PublicStayCreateView(_PublicStayView):
    @extend_schema(
        operation_id="public_booking_stay_create",
        summary="Book a stay or a rental from a company's booking form",
        description="Books an offer from `stays` from–to on the unit named, or on the least "
        "busy free unit of the group named that takes the people who come. The price is "
        "worked out and frozen in the booking (`quote`); a stay with a price needs the "
        "`quote_digest` of the quote shown (`POST …/stays/quote/`): without it, or with "
        "another price by now, the answer is 409 `quote_changed` with the quote in "
        "`detail.quote`. Refusals as in the quote; a paused form is 409 `booking_paused`, "
        "an arrival past `online.period_last_day` 409 `beyond_booking_horizon`. The "
        "company's documents in force in the booking's language (`GET …/consents/`) must be "
        "named in `consents.documents` (409 `documents_changed` otherwise). An offer that "
        "asks for money first answers `pending_payment` with the transfer's details in "
        "`payment`; one taken on request `pending_request`. The same Idempotency-Key "
        "answers the first booking again (200).",
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=PublicStayCreateSerializer,
        responses={201: PublicAppointmentSerializer, 200: PublicAppointmentSerializer, **_PROBLEMS},
    )
    def post(self, request: Request, public_slug: str) -> Response:
        route = _route(public_slug)
        s = PublicStayCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        customer = data.pop("customer")
        accepted = BookingConsents(
            documents=tuple((data.pop("consents", None) or {}).get("documents", ()))
        )
        data["customer_notes"] = data.pop("customer_notes", "").strip()
        with public_booking_context(route.organization_id):
            try:
                result = book_stay(
                    **data,
                    consents=accepted,
                    customer_data=customer,
                    idempotency_key=_idem(request),
                    principal_ref="public",
                )
            except QuoteChanged as changed:
                raise QuoteChanged(changed.quote, customer=True) from None
            assert isinstance(result, CreatedAppointment)
            payload = _public_appointment_payload(result.appointment, result.token)
        return Response(payload, status=201 if result.created else 200)


class SelfServiceStayMoveView(_SelfServiceView):
    @extend_schema(
        operation_id="booking_self_service_stay_move",
        summary="Move one's own stay to other dates",
        description="The customer moves the stay their link names, within what the booking "
        "allows (409 `appointment_not_changeable` otherwise): it keeps its unit when that "
        "is free then, otherwise takes another free one of the group it was booked in. "
        "The stay is priced again for the same people; one with a price needs the "
        "`quote_digest` of the quote shown (`POST …/stay/preview/`), 409 `quote_changed` "
        "otherwise. Rules and taken dates as for a booking. An unknown, expired or revoked "
        "link is 404.",
        tags=["public-booking"],
        parameters=[IDEMPOTENCY],
        request=PublicStayMoveSerializer,
        responses={200: PublicAppointmentSerializer, **_PROBLEMS},
    )
    def post(self, request: Request, token: str) -> Response:
        route = _self(token)
        s = PublicStayMoveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with public_booking_context(route.organization_id):
            try:
                moved = move_stay(
                    appointment_id=route.appointment_id,
                    idempotency_key=_idem(request),
                    principal_ref=route.token_digest,
                    **s.validated_data,
                )
            except QuoteChanged as changed:
                raise QuoteChanged(changed.quote, customer=True) from None
            assert isinstance(moved, Appointment)
            payload = _public_appointment_payload(moved)
        return Response(payload)


class SelfServiceStayMovePreviewView(_SelfServiceView):
    @extend_schema(
        operation_id="booking_self_service_stay_move_preview",
        summary="Check a move of one's own stay without making it",
        description="Answers what `booking_self_service_stay_move` would — the stay's new "
        "instants, length and price as the customer reads it — or the same 400, 404 and "
        "409. Nothing is saved.",
        tags=["public-booking"],
        request=PublicStayMovePreviewSerializer,
        responses={200: PublicStayPlanSerializer, **_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, token: str) -> Response:
        route = _self(token)
        s = PublicStayMovePreviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with public_booking_context(route.organization_id):
            plan = move_stay(
                appointment_id=route.appointment_id,
                idempotency_key="",
                principal_ref="",
                preview=True,
                **s.validated_data,
            )
            assert isinstance(plan, StayPlan)
            return Response(_plan_payload(plan))
