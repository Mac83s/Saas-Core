"""Evals of the assistant's service, place and working-hours commands
(`shared/booking/command_declarations.py`, ADR-072 §11), of its units, price
list and draft removal (`shared/booking/pricing_commands.py`), of its seasons
(`shared/booking/season_commands.py`) and of its answers to bookings made on
request (`shared/booking/request_commands.py`)."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any
from uuid import uuid7

from django.db.models import F
from django.utils import timezone

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.booking.models import (
    Appointment,
    AvailabilityRule,
    BookingMutation,
    BookingRule,
    Extra,
    Location,
    ParticipantCategory,
    PriceBasis,
    PriceRule,
    RangeUnit,
    Resource,
    ResourceGroup,
    Service,
    ServiceGroup,
    ServiceLocation,
    StaffMember,
    TimeModel,
    VatCode,
)
from saas_core.modules.shared.customers.models import Customer
from saas_core.modules.shared.notifications.security import encrypt_secret

from . import CommandEval

ROLLED_BACK = "ADR-072 §11: the setup preview runs the write in a savepoint it rolls back"


def _company(context: TenantContext) -> None:
    """Booking in the plan, one place, one person working mornings, one service."""
    organization_id = context.organization_id
    EntitlementSnapshot.all_objects.create(
        organization_id=organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"booking.enabled": True},
        quotas={},
        sources={"booking.enabled": {"kind": "plan"}},
    )
    place = Location.all_objects.create(
        organization_id=organization_id, name="Centrum", public_slug="centrum"
    )
    person = StaffMember.all_objects.create(
        organization_id=organization_id, display_name="Ola", public_slug="ola"
    )
    AvailabilityRule.all_objects.create(
        organization_id=organization_id,
        staff=person,
        location=place,
        weekday=0,
        local_start=time(8),
        local_end=time(12),
    )
    service = Service.all_objects.create(
        organization_id=organization_id,
        name="Konsultacja",
        public_slug="konsultacja",
        duration_minutes=30,
    )
    ServiceLocation.all_objects.create(
        organization_id=organization_id, service=service, location=place
    )


def _first(model: type[Any], context: TenantContext) -> Any:
    return model.all_objects.filter(organization_id=context.organization_id).first()


def _state(context: TenantContext) -> dict[str, Any]:
    organization_id = context.organization_id
    return {
        "services": sorted(
            Service.all_objects.filter(organization_id=organization_id).values_list(
                "name", "duration_minutes", "active", "version"
            )
        ),
        "places": sorted(
            Location.all_objects.filter(organization_id=organization_id).values_list(
                "name", "address", "active", "version"
            )
        ),
        "hours": sorted(
            AvailabilityRule.all_objects.filter(
                organization_id=organization_id, active=True
            ).values_list("weekday", "local_start", "local_end")
        ),
        "hours_versions": sorted(
            StaffMember.all_objects.filter(organization_id=organization_id).values_list(
                "hours_version", flat=True
            )
        ),
        "people": sorted(
            StaffMember.all_objects.filter(organization_id=organization_id).values_list(
                "display_name", flat=True
            )
        ),
    }


def _service_fields(**given: Any) -> dict[str, Any]:
    fields = dict.fromkeys((
        "name",
        "duration_minutes",
        "buffer_before_minutes",
        "buffer_after_minutes",
        "minimum_notice_minutes",
        "staff_count",
        "public_staff_choice",
        "slot_step_minutes",
        "staff_ids",
        "location_ids",
        "resource_ids",
    ))
    return {**fields, **given}


def _preset_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys((
        "version",
        "name",
        "duration_minutes",
        "staff_ids",
        "location_ids",
    ))
    return {"preset_id": "core.specialist_visit", **fields, **given}


def _person_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys(("phone", "service_ids", "hours", "invitation"))
    return {**fields, **given}


def _week(context: TenantContext, start: str, end: str) -> dict[str, Any]:
    return {
        "staff_id": str(_first(StaffMember, context).id),
        "rules": [
            {
                "weekday": 1,
                "local_start": start,
                "local_end": end,
                "location_id": str(_first(Location, context).id),
            }
        ],
    }


def _stay_company(context: TenantContext) -> None:
    """The same company with a stay that is still a draft: one unit in its
    pool, a base price, an extra and a participant category."""
    _company(context)
    organization_id = context.organization_id
    stay = Service.all_objects.create(
        organization_id=organization_id,
        name="Domki",
        public_slug="domki",
        time_model=TimeModel.RANGE,
        range_unit=RangeUnit.NIGHT,
        range_start_local=time(16),
        range_end_local=time(11),
        duration_minutes=None,
        staff_count=0,
        active=False,
        draft=True,
    )
    group = ResourceGroup.all_objects.create(organization_id=organization_id, name="Domki")
    ServiceGroup.all_objects.create(organization_id=organization_id, service=stay, group=group)
    Resource.all_objects.create(organization_id=organization_id, name="Domki 1", group=group)
    PriceRule.all_objects.create(
        organization_id=organization_id,
        service=stay,
        basis=PriceBasis.PER_TIME_UNIT,
        amount_minor=40000,
        currency="PLN",
        vat_code=VatCode.REDUCED,
    )
    Extra.all_objects.create(
        organization_id=organization_id,
        service=stay,
        name="Sprzątanie końcowe",
        amount_minor=15000,
        currency="PLN",
    )
    ParticipantCategory.all_objects.create(organization_id=organization_id, name="Dziecko")


def _stay(context: TenantContext) -> Service:
    return Service.all_objects.get(organization_id=context.organization_id, name="Domki")


def _price_state(context: TenantContext) -> dict[str, Any]:
    organization_id = context.organization_id
    return {
        **_state(context),
        "units": sorted(
            Resource.all_objects.filter(organization_id=organization_id).values_list(
                "name", "capacity", "active"
            )
        ),
        "groups": sorted(
            ResourceGroup.all_objects.filter(organization_id=organization_id).values_list(
                "name", flat=True
            )
        ),
        "prices": sorted(
            PriceRule.all_objects.filter(organization_id=organization_id).values_list(
                "amount_minor", "basis", "vat_code", "active", "version"
            )
        ),
        "extras": sorted(
            Extra.all_objects.filter(organization_id=organization_id).values_list(
                "name", "amount_minor", "kind", "active", "version"
            )
        ),
        "categories": sorted(
            ParticipantCategory.all_objects.filter(organization_id=organization_id).values_list(
                "name", "counts_towards_capacity", "active", "version"
            )
        ),
    }


def _bump(model: type[Any]) -> Any:
    """Moves the version the preview read."""

    def stale(context: TenantContext) -> None:
        model.all_objects.filter(organization_id=context.organization_id).update(
            version=F("version") + 1
        )

    return stale


def _price_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys((
        "price_id",
        "service_id",
        "group_id",
        "resource_id",
        "name",
        "starts_on",
        "ends_on",
        "weekdays",
        "local_from",
        "local_to",
        "basis",
        "amount_minor",
        "vat_code",
        "included_people",
        "extra_person_amount_minor",
        "extra_person_per_time_unit",
        "category_prices",
        "length_discounts",
        "active",
    ))
    return {**fields, **given}


def _extra_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys((
        "extra_id",
        "service_id",
        "name",
        "kind",
        "basis",
        "amount_minor",
        "vat_code",
        "mandatory",
        "max_quantity",
        "active",
    ))
    return {**fields, **given}


def _season_company(context: TenantContext) -> None:
    """The stay with a season of its own: July and August, a week at least."""
    _stay_company(context)
    BookingRule.all_objects.create(
        organization_id=context.organization_id,
        service=_stay(context),
        name="Sezon wysoki",
        starts_on=date(2027, 7, 1),
        ends_on=date(2027, 8, 31),
        min_length=7,
    )


def _season_state(context: TenantContext) -> dict[str, Any]:
    return {
        **_price_state(context),
        "seasons": sorted(
            BookingRule.all_objects.filter(organization_id=context.organization_id).values_list(
                "starts_on", "ends_on", "min_length", "start_weekdays", "active", "version"
            )
        ),
    }


def _season_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys((
        "season_id",
        "service_id",
        "group_id",
        "resource_id",
        "name",
        "starts_on",
        "ends_on",
        "min_length",
        "max_length",
        "length_multiple",
        "start_weekdays",
        "end_weekdays",
        "notice_hours",
        "window_days",
        "closed",
        "buffer_after_minutes",
        "active",
    ))
    return {**fields, **given}


def _request_company(context: TenantContext) -> None:
    """The company with one customer's booking that waits for its answer."""
    _company(context)
    organization_id = context.organization_id
    service = _first(Service, context)
    starts = timezone.now() + timedelta(days=10)
    Appointment.all_objects.create(
        organization_id=organization_id,
        # No address: nothing is queued for a customer nobody can write to.
        customer=Customer.all_objects.create(
            organization_id=organization_id, display_name="Jan Nowak", contact_hash=uuid7().hex
        ),
        service=service,
        staff=_first(StaffMember, context),
        location=_first(Location, context),
        starts_at=starts,
        ends_at=starts + timedelta(minutes=30),
        occupied_from=starts,
        occupied_until=starts + timedelta(minutes=30),
        timezone="Europe/Warsaw",
        service_name=service.name,
        status="pending_request",
        hold_expires_at=timezone.now() + timedelta(hours=12),
        self_service_token_ciphertext=encrypt_secret(uuid7().hex),
        self_service_expires_at=starts,
    )


def _request(context: TenantContext) -> Appointment:
    return Appointment.all_objects.get(organization_id=context.organization_id)


def _request_state(context: TenantContext) -> dict[str, Any]:
    organization_id = context.organization_id
    return {
        "bookings": sorted(
            Appointment.all_objects.filter(organization_id=organization_id).values_list(
                "status", "starts_at"
            )
        ),
        "answers": sorted(
            BookingMutation.all_objects.filter(organization_id=organization_id).values_list(
                "action", flat=True
            )
        ),
    }


def _moved(context: TenantContext) -> None:
    """The request is for other days than the person agreed about."""
    Appointment.all_objects.filter(organization_id=context.organization_id).update(
        starts_at=F("starts_at") + timedelta(days=1), ends_at=F("ends_at") + timedelta(days=1)
    )


def _quote_fields(**given: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys((
        "starts_at",
        "start_date",
        "end_date",
        "resource_id",
        "group_id",
        "participants",
        "extras",
        "price_only",
    ))
    return {**fields, **given}


EVALS = {
    "booking.setup.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"services": True},
        wrong_field="services",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_company,
    ),
    "booking.offer.create@1": CommandEval(
        arguments=lambda context: _service_fields(
            name="Masaż",
            duration_minutes=60,
            location_ids=[str(_first(Location, context).id)],
        ),
        wrong_arguments=_service_fields(name="Masaż", duration_minutes="godzina"),
        wrong_field="duration_minutes",
        stale="nie dotyczy: nowa usługa nie ma jeszcze wersji",
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.offer.update@1": CommandEval(
        arguments=lambda context: {
            "service_id": str(_first(Service, context).id),
            **_service_fields(name="Konsultacja online", duration_minutes=45),
        },
        wrong_arguments={
            "service_id": "00000000-0000-0000-0000-000000000000",
            **_service_fields(public_staff_choice="nobody"),
        },
        wrong_field="public_staff_choice",
        stale=lambda context: (
            Service.all_objects.filter(organization_id=context.organization_id).update(
                version=F("version") + 1
            )
            and None
        ),
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.location.save@1": CommandEval(
        arguments=lambda context: {
            "location_id": str(_first(Location, context).id),
            "name": "Centrum, parter",
            "address": "ul. Długa 1, Olsztyn",
        },
        # A new place without a name: refused by the panel's own serializer.
        wrong_arguments={"location_id": None, "name": None, "address": "ul. Długa 1"},
        wrong_field="name",
        stale=lambda context: (
            Location.all_objects.filter(organization_id=context.organization_id).update(
                version=F("version") + 1
            )
            and None
        ),
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.staff.hours.set@1": CommandEval(
        arguments=lambda context: _week(context, "09:00", "17:00"),
        # Refused by the service, not the schema: the field is the rule's.
        wrong_arguments=lambda context: _week(context, "17:00", "09:00"),
        wrong_field="rules.0.local_end",
        stale=lambda context: (
            StaffMember.all_objects.filter(organization_id=context.organization_id).update(
                hours_version=F("hours_version") + 1
            )
            and None
        ),
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.staff.add@1": CommandEval(
        arguments=lambda context: _person_fields(
            name="Marta",
            hours={
                "weekdays": [1, 2],
                "local_start": "09:00",
                "local_end": "15:00",
                "location_id": str(_first(Location, context).id),
            },
        ),
        # Refused by the panel's own serializer: a person has a name.
        wrong_arguments=_person_fields(name=""),
        wrong_field="name",
        stale="nie dotyczy: nowa osoba nie ma jeszcze wersji",
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.preset.list@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"presets": True},
        wrong_field="presets",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_company,
    ),
    "booking.preset.apply@1": CommandEval(
        arguments=lambda context: _preset_fields(
            name="Masaż",
            duration_minutes=60,
            location_ids=[str(_first(Location, context).id)],
        ),
        # Refused by the service, not the schema: the preset is announced, not ready.
        wrong_arguments=_preset_fields(preset_id="core.hourly_space", name="Kort"),
        wrong_field="preset_id",
        stale="nie dotyczy: nowa usługa nie ma jeszcze wersji",
        state=_state,
        prepare=_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.offer.units.set@1": CommandEval(
        arguments=lambda context: {
            "service_id": str(_stay(context).id),
            "count": 3,
            "capacity": 6,
            "location_id": None,
        },
        # Refused by the service, not the schema: a unit is never removed by a count.
        wrong_arguments=lambda context: {
            "service_id": str(_stay(context).id),
            "count": 1,
            "capacity": "sześć",
            "location_id": None,
        },
        wrong_field="capacity",
        stale=lambda context: (
            Service.all_objects.filter(pk=_stay(context).pk).update(version=F("version") + 1)
            and None
        ),
        state=_price_state,
        prepare=_stay_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.prices.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"prices": True},
        wrong_field="prices",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_price_state,
        prepare=_stay_company,
    ),
    "booking.price.save@1": CommandEval(
        arguments=lambda context: _price_fields(
            price_id=str(_first(PriceRule, context).id), amount_minor=45000
        ),
        # Refused by the panel's own serializer: a new price needs its amount.
        wrong_arguments=lambda context: _price_fields(
            service_id=str(_stay(context).id), basis="per_time_unit"
        ),
        wrong_field="amount_minor",
        stale=_bump(PriceRule),
        state=_price_state,
        prepare=_stay_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.participant_category.save@1": CommandEval(
        arguments=lambda context: {
            "category_id": str(_first(ParticipantCategory, context).id),
            "name": "Dziecko do 12 lat",
            "counts_towards_capacity": None,
            "active": None,
        },
        # Refused by the service: the company has this category already.
        wrong_arguments={
            "category_id": None,
            "name": "dziecko",
            "counts_towards_capacity": None,
            "active": None,
        },
        wrong_field="name",
        stale=_bump(ParticipantCategory),
        state=_price_state,
        prepare=_stay_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.extra.save@1": CommandEval(
        arguments=lambda context: _extra_fields(
            extra_id=str(_first(Extra, context).id), amount_minor=18000
        ),
        # Refused by the panel's own serializer: a new extra needs its amount.
        wrong_arguments=lambda context: _extra_fields(
            service_id=str(_stay(context).id), name="Pościel"
        ),
        wrong_field="amount_minor",
        stale=_bump(Extra),
        state=_price_state,
        prepare=_stay_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.quote.read@1": CommandEval(
        arguments=lambda context: {
            "service_id": str(_stay(context).id),
            **_quote_fields(start_date="2027-07-01", end_date="2027-07-04", price_only=True),
        },
        wrong_arguments=lambda context: {
            "service_id": str(_stay(context).id),
            **_quote_fields(start_date="2027-07-01", end_date="2027-07-04", price_only="tak"),
        },
        wrong_field="price_only",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_price_state,
        prepare=_stay_company,
    ),
    "booking.seasons.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"seasons": True},
        wrong_field="seasons",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_season_state,
        prepare=_season_company,
    ),
    "booking.season.save@1": CommandEval(
        arguments=lambda context: _season_fields(
            season_id=str(_first(BookingRule, context).id), min_length=5, start_weekdays=[5]
        ),
        # Refused by the panel's own serializer: a new season needs its dates.
        wrong_arguments=lambda context: _season_fields(
            service_id=str(_stay(context).id), min_length=7
        ),
        wrong_field="starts_on",
        stale=_bump(BookingRule),
        state=_season_state,
        prepare=_season_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.offer.discard@1": CommandEval(
        arguments=lambda context: {"service_id": str(_stay(context).id)},
        # Refused by the service: this one was never a draft.
        wrong_arguments=lambda context: {
            "service_id": str(
                Service.all_objects.get(
                    organization_id=context.organization_id, name="Konsultacja"
                ).id
            )
        },
        wrong_field="service_id",
        stale=lambda context: (
            Service.all_objects.filter(pk=_stay(context).pk).update(version=F("version") + 1)
            and None
        ),
        state=_price_state,
        prepare=_stay_company,
        preview_rolls_back=ROLLED_BACK,
    ),
    "booking.requests.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"waiting": True},
        wrong_field="waiting",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_request_state,
        prepare=_request_company,
    ),
    "booking.request.accept@1": CommandEval(
        arguments=lambda context: {"request_id": str(_request(context).id)},
        wrong_arguments={"request_id": "ta z rana"},
        wrong_field="request_id",
        stale=_moved,
        state=_request_state,
        prepare=_request_company,
    ),
    "booking.request.decline@1": CommandEval(
        arguments=lambda context: {
            "request_id": str(_request(context).id),
            "reason": "W tym terminie mamy remont.",
        },
        # Refused as the panel refuses it: no link in words that go out by mail.
        wrong_arguments=lambda context: {
            "request_id": str(_request(context).id),
            "reason": "Zapraszamy na www.inna-firma.example",
        },
        wrong_field="reason",
        stale=_moved,
        state=_request_state,
        prepare=_request_company,
    ),
}
