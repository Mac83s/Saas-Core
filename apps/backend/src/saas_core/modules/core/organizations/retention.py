"""Automatic removal of personal data after a time (settings plan D1–D2,
owner answer 37a; ADR-078): which records a company's own setting has
removed, tenant by tenant.

A module that keeps personal data registers a sweep: the rule that says
whether and from when records are due in a company, how to find them and how
to remove them. For data of people outside the company — booking's customers,
the site's enquiries — the rule is the company's own setting
(`company_months`): `off` by default, or a number of months. The removal is
irreversible, so:

- it is the company's own decision: only a value the company saved counts,
  never a product's or the platform's default;
- nothing is removed for `GRACE_DAYS` after that value last changed — a wrong
  click must be survivable, and the owners are told at the change;
- every company is worked on inside its own tenant and its own transaction,
  its setting read there, so a company that has just switched the removal off
  loses nothing;
- one company's failure stops nobody else, a run takes at most `RUN_LIMIT`
  records per company and sweep, and running it again does no harm.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .audit import record_audit
from .context import set_local_organization_id
from .models import Organization, OrganizationSetting
from .pre_tenant import PRE_TENANT_DB

logger = logging.getLogger("saas_core.security")

#: The setting's value while the company has not asked for anything.
OFF = "off"
#: The periods a company may choose, in months (answer 37a).
PERIODS = (12, 24, 36)
#: Nothing is removed for this long after the company's choice last changed.
GRACE_DAYS = 7
#: The most records one run takes from one company for one sweep; the rest
#: the next run.
RUN_LIMIT = 200
#: The history's action for a run that removed something.
RUN_ACTION = "privacy.retention.run"


@dataclass(frozen=True, slots=True)
class Rule:
    """What applies to one company for one sweep now."""

    #: Records from before this moment are due.
    cutoff: datetime
    #: How the period reads in a report and in the history: `24 mies.`, `90 dni`.
    period: str
    #: Nothing is removed before this moment (a grace period); None: no wait.
    starts_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetentionSweep:
    #: What is removed, e.g. `booking.customers`.
    key: str
    #: The rule for a company at a moment, read inside the company's tenant,
    #: or None while nothing is to be removed there: `rule(organization_id,
    #: now)`. `company_months(<setting>)` for a rule the company chooses,
    #: `platform_days(<setting>)` for one the platform sets.
    rule: Callable[[UUID, datetime], Rule | None]
    #: How many records are due in this company at `cutoff` — a read, inside
    #: the company's tenant: `due(organization_id, cutoff)`.
    due: Callable[[UUID, datetime], int]
    #: Removes up to `limit` due records, inside the company's tenant and the
    #: run's transaction, and returns how many: `erase(organization_id,
    #: cutoff, limit)`. It locks what it takes and checks it again.
    erase: Callable[[UUID, datetime, int], int]


@dataclass(frozen=True, slots=True)
class Due:
    organization_id: UUID
    sweep: str
    period: str
    cutoff: datetime
    count: int
    #: Still inside the grace period: a run would not touch it before this.
    waits_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class Removed:
    organization_id: UUID
    sweep: str
    period: str
    count: int


@dataclass(frozen=True, slots=True)
class RunResult:
    removed: tuple[Removed, ...]
    #: Companies whose run failed; the others ran.
    failed: tuple[UUID, ...]


_sweeps: dict[str, RetentionSweep] = {}
#: sweep key → readers of the ids a module must not lose yet (documents inside
#: a statutory period, an open order): `exclusion(organization_id)`.
_exclusions: dict[str, list[Callable[[UUID], Iterable[UUID]]]] = {}


def register_retention_sweep(sweep: RetentionSweep) -> None:
    """From the owner module's `AppConfig.ready`."""
    existing = _sweeps.get(sweep.key)
    if existing is not None and existing != sweep:
        raise ImproperlyConfigured(f"Usuwanie {sweep.key} jest już zarejestrowane inaczej.")
    _sweeps[sweep.key] = sweep


def register_retention_exclusion(
    sweep_key: str, exclusion: Callable[[UUID], Iterable[UUID]]
) -> None:
    """A module that keeps something of a record another module would remove
    says which records must stay for now. The owner of the sweep applies it in
    its own `due` and `erase` through `excluded_ids`."""
    _exclusions.setdefault(sweep_key, []).append(exclusion)


def excluded_ids(sweep_key: str, organization_id: UUID) -> set[UUID]:
    return {
        identifier
        for exclusion in _exclusions.get(sweep_key, ())
        for identifier in exclusion(organization_id)
    }


def registered_sweeps() -> tuple[RetentionSweep, ...]:
    return tuple(_sweeps[key] for key in sorted(_sweeps))


def months_of(value: object) -> int | None:
    """The period a setting's value asks for; None while it is off (or holds
    anything this code does not know — never a reason to remove)."""
    if isinstance(value, str) and value.isdigit() and int(value) in PERIODS:
        return int(value)
    return None


def days_of(value: object) -> int | None:
    """The period in days a platform setting asks for; None for anything that
    is not a whole number of at least one day — like `months_of`, never a
    reason to remove: zero or less would make everything due at once."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return int(value) if int(value) >= 1 else None
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


def company_months(setting_key: str) -> Callable[[UUID, datetime], Rule | None]:
    """The rule of a sweep the company itself switches on: `off` or a number
    of months in `setting_key`. Read from the company's own row on purpose — a
    default from a product or the platform never starts a removal — and
    nothing is removed for `GRACE_DAYS` after that row last changed."""

    def rule(organization_id: UUID, now: datetime) -> Rule | None:
        row = (
            OrganizationSetting.objects.filter(organization_id=organization_id, key=setting_key)
            .values_list("value", "updated_at")
            .first()
        )
        months = months_of(row[0]) if row is not None else None
        if row is None or months is None:
            return None
        return Rule(
            cutoff=cutoff_for(months, now),
            period=f"{months} mies.",
            starts_at=row[1] + timedelta(days=GRACE_DAYS),
        )

    return rule


def platform_days(setting_key: str) -> Callable[[UUID, datetime], Rule | None]:
    """The rule of a sweep the platform sets for every company: a number of
    days in the platform setting `setting_key`. No grace period — it is not a
    company's click that could have been a mistake — so the setting's own
    minimum is the guard: a value below one day is no rule at all here, and
    whoever registers the sweep declares a sensible `minimum` on the key."""

    def rule(_organization_id: UUID, now: datetime) -> Rule | None:
        from .platform_settings import platform_setting  # noqa: PLC0415

        days = days_of(platform_setting(setting_key))
        if days is None:
            return None
        return Rule(cutoff=now - timedelta(days=days), period=f"{days} dni")

    return rule


def dry_run(now: datetime | None = None) -> list[Due]:
    """What a run would remove now, company by company, and what still waits
    for its grace period. Changes nothing. A company's own rule is listed even
    with nothing due yet; a rule the platform sets only where something is."""
    moment = now or timezone.now()
    found: list[Due] = []
    for organization_id in _organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            for sweep in registered_sweeps():
                rule = sweep.rule(organization_id, moment)
                if rule is None:
                    continue
                waits = rule.starts_at is not None and rule.starts_at > moment
                count = sweep.due(organization_id, rule.cutoff)
                if not count and rule.starts_at is None:
                    # A rule the platform sets holds in every company, so it is
                    # listed only where something is due; a company's own rule
                    # is listed from the moment the company switched it on.
                    continue
                found.append(
                    Due(
                        organization_id=organization_id,
                        sweep=sweep.key,
                        period=rule.period,
                        cutoff=rule.cutoff,
                        count=count,
                        waits_until=rule.starts_at if waits else None,
                    )
                )
    return found


def run(now: datetime | None = None, *, limit: int = RUN_LIMIT) -> RunResult:
    """Removes what the companies' own settings ask for. Each company in its
    own transaction and tenant, like the billing sweeps (ADR-039); its setting
    is read there, so what a preview promised binds nobody once the company
    said off. A company that fails is logged and the next one runs."""
    moment = now or timezone.now()
    removed: list[Removed] = []
    failed: list[UUID] = []
    for organization_id in _organization_ids():
        try:
            with transaction.atomic():
                set_local_organization_id(organization_id)
                done = _run_company(organization_id, moment, limit)
        except Exception:
            failed.append(organization_id)
            logger.exception(
                "privacy_retention_run_failed", extra={"organization_id": str(organization_id)}
            )
        else:
            # Counted only once the company's transaction has committed: one
            # whose commit fails is reported as failed, never as removed too.
            removed += done
    return RunResult(removed=tuple(removed), failed=tuple(failed))


def _run_company(organization_id: UUID, moment: datetime, limit: int) -> list[Removed]:
    done: list[Removed] = []
    for sweep in registered_sweeps():
        rule = sweep.rule(organization_id, moment)
        if rule is None or (rule.starts_at is not None and rule.starts_at > moment):
            continue
        count = sweep.erase(organization_id, rule.cutoff, limit)
        if not count:
            continue
        # One history row per run and company: counts, never a person.
        record_audit(
            organization=Organization.objects.get(pk=organization_id),
            action=RUN_ACTION,
            actor=None,
            target_type="organization",
            target_id=organization_id,
            metadata={"sweep": sweep.key, "period": rule.period, "removed": count},
        )
        done.append(
            Removed(
                organization_id=organization_id,
                sweep=sweep.key,
                period=rule.period,
                count=count,
            )
        )
    return done


def _organization_ids() -> list[UUID]:
    # ADR-041: a sweep visits every company on purpose; the list is the read.
    return list(
        Organization.objects.using(PRE_TENANT_DB)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
