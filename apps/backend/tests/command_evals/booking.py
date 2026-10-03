"""Evals of the assistant's service and working-hours commands
(`shared/booking/command_declarations.py`, ADR-072 §11)."""

from __future__ import annotations

from datetime import time
from typing import Any

from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.booking.models import (
    AvailabilityRule,
    Location,
    Service,
    ServiceLocation,
    StaffMember,
)

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
}
