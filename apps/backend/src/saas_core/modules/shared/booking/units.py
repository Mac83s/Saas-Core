"""A unit's blocks: the company keeps a cottage or a court for itself (ADR-072 §4).

A block holds its time the way a booking does — with its own
`AppointmentResourceAllocation`, under the same exclusion constraint — so a
block and a guest racing for one night cannot both win, and the database says
which. A block over a booking or over another block of the unit is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, OperationalError, transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .crew import lost_slot_race
from .models import AppointmentResourceAllocation, Resource, TimeOff, TimeOffSource
from .setup import Saved, _manage, setup_write

UNIT_BLOCKED = "booking.unit.blocked"
UNIT_UNBLOCKED = "booking.unit.unblocked"


class UnitBusy(APIException):
    status_code = 409
    default_detail = "Ta jednostka jest wtedy zajęta — przez rezerwację albo inną blokadę."
    default_code = "unit_busy"


@dataclass(frozen=True, slots=True)
class UnitBlock:
    block: TimeOff
    #: False for a block that could not take its time (an import over a booking,
    #: a block from before the constraint covered blocks); it still keeps the
    #: unit busy in search.
    holds: bool


def hold(block: TimeOff) -> None:
    """Gives a unit's block the allocation that holds its time, or refuses
    the block with 409 `unit_busy` when the unit is taken then."""
    assert block.resource_id is not None
    try:
        with transaction.atomic():
            AppointmentResourceAllocation.all_objects.create(
                organization_id=block.organization_id,
                time_off=block,
                resource_id=block.resource_id,
                occupied_range=(block.starts_at, block.ends_at),
            )
    except (IntegrityError, OperationalError) as error:
        if not lost_slot_race(error):
            raise
        raise UnitBusy from error


def list_unit_blocks(
    *, resource_id: UUID, starts_from: datetime, starts_until: datetime
) -> list[UnitBlock]:
    """The unit's blocks that touch the window, oldest first."""
    _, organization = _manage(FeatureOperation.READ)
    resource = _resource(organization, resource_id)
    blocks = list(
        TimeOff.all_objects.filter(
            resource=resource, ends_at__gt=starts_from, starts_at__lt=starts_until
        ).order_by("starts_at", "id")
    )
    held = set(
        AppointmentResourceAllocation.all_objects.filter(
            time_off__in=blocks, active=True
        ).values_list("time_off_id", flat=True)
    )
    return [UnitBlock(block, block.id in held) for block in blocks]


@transaction.atomic
def add_unit_block(
    *,
    resource_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    reason: str = "",
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[UnitBlock]:
    """Blocks the unit from `starts_at` to `ends_at` (a renovation, own use)."""
    context, organization = _manage()
    return setup_write(
        context=context,
        action="unit.block",
        target_id=resource_id,
        request={"starts_at": starts_at, "ends_at": ends_at, "reason": reason},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_block(context, organization, resource_id, starts_at, ends_at, reason),
        replay=lambda item_id: _saved_block(
            TimeOff.all_objects.get(pk=item_id), created=True, replayed=True
        ),
    )


@transaction.atomic
def remove_unit_block(*, time_off_id: UUID, idempotency_key: str) -> None:
    """Lets the unit's time go; a booking can take it again at once."""
    context, organization = _manage()

    def write() -> Saved[None]:
        block = (
            TimeOff.all_objects.select_for_update()
            .filter(
                organization=organization,
                pk=time_off_id,
                resource__isnull=False,
                source=TimeOffSource.MANUAL,
            )
            .first()
        )
        if block is None:
            raise NotFound("Nie ma takiej blokady.")
        resource_id = block.resource_id
        block.delete()
        _audit(organization, context, UNIT_UNBLOCKED, resource_id, {})
        return Saved(None, time_off_id, 0, False)

    setup_write(
        context=context,
        action="unit.unblock",
        target_id=time_off_id,
        request={},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=lambda item_id: Saved(None, item_id, 0, False, replayed=True),
    )


def _resource(organization: Organization, resource_id: UUID) -> Resource:
    resource = Resource.all_objects.filter(organization=organization, pk=resource_id).first()
    if resource is None:
        raise NotFound("Nie ma takiej jednostki.")
    return resource


def _write_block(
    context: TenantContext,
    organization: Organization,
    resource_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
) -> Saved[UnitBlock]:
    resource = _resource(organization, resource_id)
    if ends_at <= starts_at:
        raise ValidationError(
            {"ends_at": "Koniec blokady musi być po jej początku."}, code="end_before_start"
        )
    block = TimeOff.all_objects.create(
        organization=organization,
        resource=resource,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason.strip(),
        source=TimeOffSource.MANUAL,
    )
    hold(block)
    # Never the reason: history is forever, and a note can name a person.
    _audit(
        organization,
        context,
        UNIT_BLOCKED,
        resource.id,
        {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()},
    )
    return _saved_block(block, created=True)


def _saved_block(block: TimeOff, *, created: bool, replayed: bool = False) -> Saved[UnitBlock]:
    holds = AppointmentResourceAllocation.all_objects.filter(time_off=block, active=True).exists()
    return Saved(UnitBlock(block, holds), block.id, 1, created, {}, replayed)


def _audit(
    organization: Organization,
    context: TenantContext,
    action: str,
    resource_id: UUID | None,
    metadata: dict[str, Any],
) -> None:
    record_audit(
        organization=organization,
        action=action,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="resource",
        target_id=resource_id,
        metadata=metadata,
    )
