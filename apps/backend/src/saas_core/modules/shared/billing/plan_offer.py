"""Which plans an organization is offered — those of its type (ADR-050)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from saas_core.modules.core.organizations.models import Organization

#: organization type → months an account of that type is free from its
#: creation, as its product declared (`register_free_period`).
_free_months: dict[str, int] = {}


def plan_keys_for_type(organization_type: str) -> tuple[str, ...]:
    """The plans offered to one kind of organization (ADR-050), profile order."""
    known = settings.ORGANIZATION_TYPES.get(organization_type)
    offered = set(known.plan_keys) if known is not None else set()
    return tuple(key for key in settings.BILLING_PLAN_KEYS if key in offered)


def plan_keys_for_organization(organization_id: UUID) -> tuple[str, ...]:
    """The plans the acting organization may buy — those of its type."""
    organization_type = (
        Organization.objects.filter(pk=organization_id)
        .values_list("organization_type", flat=True)
        .first()
    )
    return plan_keys_for_type(organization_type or "")


def register_free_period(organization_type: str, *, months: int) -> None:
    """A product's word, from its `ready()`: an account of this type is free
    for this many months from the day it was created (HoofCare's farm, 6 —
    owner's answer 46a). The plan card of a plan that costs nothing says until
    when. A statement, not enforcement: nothing ends or limits the account
    when the date passes — that waits for the plan the product will then offer.
    """
    if not 1 <= months <= 60:
        raise ValueError("Okres bezpłatny to od 1 do 60 miesięcy.")
    _free_months[organization_type] = months


def free_until(organization: Organization) -> date | None:
    """The last free day of an account of a type with a declared free period,
    in the organization's own zone; None for every other type."""
    months = _free_months.get(organization.organization_type)
    if not months:
        return None
    start = timezone.localtime(organization.created_at, ZoneInfo(organization.timezone)).date()
    year, month = divmod(start.month - 1 + months, 12)
    year, month = start.year + year, month + 1
    # 31 August + 6 months is the last day of February, not the 3rd of March.
    return date(year, month, min(start.day, monthrange(year, month)[1]))
