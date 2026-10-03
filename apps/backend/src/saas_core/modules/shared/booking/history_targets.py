"""What the company's history calls the calendar's objects (UX-055).

A visit is its service and its start, never the customer: the history is read
by whoever manages settings, and the calendar decides who sees whose visits.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from saas_core.modules.core.organizations.api import HistoryTarget, register_history_target
from saas_core.modules.core.organizations.models import Organization

from .models import Appointment, Service, StaffMember


def _zone(organization_id: UUID) -> ZoneInfo:
    name = Organization.objects.filter(pk=organization_id).values_list("timezone", flat=True)
    try:
        return ZoneInfo(name.first() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _appointments(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    zone = _zone(organization_id)
    return {
        visit.id: HistoryTarget(
            label=visit.service.name,
            at=visit.starts_at,
            href="/panel/calendar?view=day&date="
            + timezone.localtime(visit.starts_at, zone).date().isoformat(),
        )
        for visit in Appointment.all_objects.filter(
            organization_id=organization_id, pk__in=ids
        ).select_related("service")
    }


def _staff(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        person.id: HistoryTarget(label=person.display_name, href=f"/panel/team/{person.id}")
        for person in StaffMember.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def _services(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    return {
        service.id: HistoryTarget(label=service.name, href="/panel/settings/services")
        for service in Service.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def register_history_targets() -> None:
    register_history_target("appointment", _appointments)
    register_history_target("staff", _staff)
    register_history_target("service", _services)
