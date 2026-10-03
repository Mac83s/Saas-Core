"""Automatic removal of personal data after a time (settings plan D1–D2,
owner answer 37a; ADR-078): which records a company's own setting would have
removed, tenant by tenant.

A module that keeps personal data of people outside the company — booking's
customers, the site's enquiries — registers a sweep: the setting that turns
it on (`off` by default, or a number of months) and how to find what is due.
The removal is irreversible, so it is the company's own decision; a company
whose setting is off is never looked at beyond that one read.

This is the mechanism without the removal: `dry_run()` only counts. Nothing
here deletes or changes a record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .context import set_local_organization_id
from .models import Organization
from .pre_tenant import PRE_TENANT_DB
from .settings_service import setting

#: The setting's value while the company has not asked for anything.
OFF = "off"
#: The periods a company may choose, in months (answer 37a).
PERIODS = (12, 24, 36)


@dataclass(frozen=True, slots=True)
class RetentionSweep:
    #: What is removed, e.g. `booking.customers`.
    key: str
    #: The company's setting: `off` or a number of months as text.
    setting: str
    #: How many records are due in this company at `cutoff` — a read, inside
    #: the company's tenant: `due(organization_id, cutoff)`.
    due: Callable[[UUID, datetime], int]


@dataclass(frozen=True, slots=True)
class Due:
    organization_id: UUID
    sweep: str
    months: int
    cutoff: datetime
    count: int


_sweeps: dict[str, RetentionSweep] = {}


def register_retention_sweep(sweep: RetentionSweep) -> None:
    """From the owner module's `AppConfig.ready`."""
    existing = _sweeps.get(sweep.key)
    if existing is not None and existing != sweep:
        raise ImproperlyConfigured(f"Usuwanie {sweep.key} jest już zarejestrowane inaczej.")
    _sweeps[sweep.key] = sweep


def registered_sweeps() -> tuple[RetentionSweep, ...]:
    return tuple(_sweeps[key] for key in sorted(_sweeps))


def months_of(value: object) -> int | None:
    """The period a setting's value asks for; None while it is off (or holds
    anything this code does not know — never a reason to remove)."""
    if isinstance(value, str) and value.isdigit() and int(value) in PERIODS:
        return int(value)
    return None


def cutoff_for(months: int, now: datetime | None = None) -> datetime:
    """The moment `months` calendar months before `now`: what ended before it
    is due. A day the earlier month does not have becomes its last one."""
    moment = now or timezone.now()
    index = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    for day in (moment.day, 30, 29, 28):
        try:
            return moment.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise AssertionError("every month has a 28th")


def dry_run(now: datetime | None = None) -> list[Due]:
    """What a run would remove now, company by company. Each company is read
    inside its own tenant and its own transaction — like the billing sweeps
    (ADR-039), a query across companies would return nothing under RLS — and
    its setting is read there too, so a company that switched the removal off
    a moment ago is not counted. Changes nothing."""
    moment = now or timezone.now()
    # ADR-041: a sweep visits every company on purpose; the list is the read.
    identifiers = list(
        Organization.objects.using(PRE_TENANT_DB)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    found: list[Due] = []
    for organization_id in identifiers:
        with transaction.atomic():
            set_local_organization_id(organization_id)
            for sweep in registered_sweeps():
                months = months_of(setting(sweep.setting, organization_id=organization_id))
                if months is None:
                    continue
                cutoff = cutoff_for(months, moment)
                found.append(
                    Due(
                        organization_id=organization_id,
                        sweep=sweep.key,
                        months=months,
                        cutoff=cutoff,
                        count=sweep.due(organization_id, cutoff),
                    )
                )
    return found
