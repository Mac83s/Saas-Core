"""Seasons and closures (ADR-072 §5, ADR-078 pkt 17, phase 2b).

A `BookingRule` is a dated layer over an offer, a group or a unit: for a day
the most specific active rule that covers it applies, and between two of one
kind the later start. A `BookingClosure` closes the company or one of its
places on whole local days, and always restricts — no rule opens it again.

Both are setup items (§11): every write has a key with a receipt, a change
names the version it was made on, and runs as a preview. „Copy to next year”
copies a year's seasons or closures to the next one; the Saturdays move, so
the company checks the dates afterwards.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import audit_snapshot, field_changes, record_audit
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .models import (
    BookingClosure,
    BookingRule,
    Extra,
    Location,
    ParticipantCategory,
    PriceRule,
    Resource,
    ResourceGroup,
    Service,
)
from .setup import Saved, _manage, _own, check_version, setup_write

RULE_CHANGED = "booking.rule.changed"
CLOSURE_CHANGED = "booking.closure.changed"
PRICE_CHANGED = "booking.price.changed"
CATEGORY_CHANGED = "booking.participant_category.changed"
EXTRA_CHANGED = "booking.extra.changed"
#: What the history names as the changed item, by the action that changed it.
_TARGETS = {
    RULE_CHANGED: "booking_rule",
    CLOSURE_CHANGED: "booking_closure",
    PRICE_CHANGED: "booking_price",
    CATEGORY_CHANGED: "booking_participant_category",
    EXTRA_CHANGED: "booking_extra",
}

_RULE_FIELDS = (
    "name",
    "service_id",
    "group_id",
    "resource_id",
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
)
_CLOSURE_FIELDS = ("location_id", "starts_on", "ends_on", "note")
_SCOPES = (("service_id", Service), ("group_id", ResourceGroup), ("resource_id", Resource))


def list_rules() -> list[BookingRule]:
    _, organization = _manage(FeatureOperation.READ)
    return list(BookingRule.all_objects.filter(organization=organization))


def list_closures() -> list[BookingClosure]:
    _, organization = _manage(FeatureOperation.READ)
    return list(BookingClosure.all_objects.filter(organization=organization))


@transaction.atomic
def save_rule(
    *,
    rule_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[BookingRule]:
    """A season of an offer, a group or a unit — exactly one of `service_id`,
    `group_id`, `resource_id`."""
    context, organization = _manage()
    created = rule_id is None
    return setup_write(
        context=context,
        action="rule.create" if created else "rule.update",
        target_id=rule_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write(
            context,
            organization,
            BookingRule,
            rule_id,
            data,
            expected_version,
            _RULE_FIELDS,
            _check_rule,
            RULE_CHANGED,
        ),
        replay=lambda item_id: _replay(BookingRule, organization, item_id, created),
    )


@transaction.atomic
def save_closure(
    *,
    closure_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[BookingClosure]:
    """Days the company — or with `location_id` one of its places — is closed."""
    context, organization = _manage()
    created = closure_id is None
    return setup_write(
        context=context,
        action="closure.create" if created else "closure.update",
        target_id=closure_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write(
            context,
            organization,
            BookingClosure,
            closure_id,
            data,
            expected_version,
            _CLOSURE_FIELDS,
            _check_closure,
            CLOSURE_CHANGED,
        ),
        replay=lambda item_id: _replay(BookingClosure, organization, item_id, created),
    )


@transaction.atomic
def delete_rule(*, rule_id: UUID, expected_version: int, idempotency_key: str) -> None:
    _delete(BookingRule, "rule.delete", rule_id, expected_version, idempotency_key, RULE_CHANGED)


@transaction.atomic
def delete_closure(*, closure_id: UUID, expected_version: int, idempotency_key: str) -> None:
    _delete(
        BookingClosure,
        "closure.delete",
        closure_id,
        expected_version,
        idempotency_key,
        CLOSURE_CHANGED,
    )


@transaction.atomic
def copy_rules_to_next_year(
    *, year: int, idempotency_key: str = "", preview: bool = False
) -> Saved[list[BookingRule]]:
    """Every season that starts in `year`, again a year later, as new rules."""
    context, organization = _manage()
    return setup_write(
        context=context,
        action="rule.copy_year",
        target_id=None,
        request={"year": year},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _copy(context, organization, BookingRule, year, RULE_CHANGED),
        replay=lambda _id: Saved([], organization.id, 0, True, replayed=True),
    )


@transaction.atomic
def copy_closures_to_next_year(
    *, year: int, idempotency_key: str = "", preview: bool = False
) -> Saved[list[BookingClosure]]:
    """Every closure that starts in `year`, again a year later (Christmas recurs)."""
    context, organization = _manage()
    return setup_write(
        context=context,
        action="closure.copy_year",
        target_id=None,
        request={"year": year},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _copy(context, organization, BookingClosure, year, CLOSURE_CHANGED),
        replay=lambda _id: Saved([], organization.id, 0, True, replayed=True),
    )


def rule_for(
    rules: Iterable[BookingRule],
    *,
    day: date,
    service_id: UUID,
    group_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> BookingRule | None:
    """The rule that applies on `day`: the unit's over its group's over the
    offer's; between two of one kind, the later start, then the later made."""
    covering = [
        rule
        for rule in rules
        if rule.active
        and rule.starts_on <= day <= rule.ends_on
        and (
            (rule.resource_id is not None and rule.resource_id == resource_id)
            or (rule.group_id is not None and rule.group_id == group_id)
            or (rule.service_id is not None and rule.service_id == service_id)
        )
    ]
    if not covering:
        return None
    return max(
        covering,
        key=lambda rule: (
            2 if rule.resource_id else 1 if rule.group_id else 0,
            rule.starts_on,
            rule.created_at,
        ),
    )


def next_year(day: date) -> date:
    """The same date a year later; 29 February becomes 28 February."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def _check_rule(organization: Organization, rule: BookingRule) -> None:
    scopes = [name for name, _model in _SCOPES if getattr(rule, name) is not None]
    if len(scopes) != 1:
        raise ValidationError(
            {"service_id": "Sezon dotyczy jednej usługi, jednej grupy albo jednej jednostki."},
            code="one_scope",
        )
    for name, model in _SCOPES:
        if getattr(rule, name) is not None:
            _own(model, organization, [getattr(rule, name)], name)
    _check_dates(rule.starts_on, rule.ends_on)
    if (
        rule.min_length is not None
        and rule.max_length is not None
        and rule.max_length < rule.min_length
    ):
        raise ValidationError(
            {"max_length": "Najdłuższy pobyt nie może być krótszy niż najkrótszy."},
            code="max_below_min",
        )
    for name in ("start_weekdays", "end_weekdays"):
        days = getattr(rule, name)
        if any(not 0 <= day <= 6 for day in days):
            raise ValidationError({name: "Dni tygodnia to 0–6 (poniedziałek–niedziela)."})
        setattr(rule, name, sorted(set(days)))


def _check_closure(organization: Organization, closure: BookingClosure) -> None:
    if closure.location_id is not None:
        _own(Location, organization, [closure.location_id], "location_id")
    _check_dates(closure.starts_on, closure.ends_on)


def _check_dates(starts_on: date, ends_on: date) -> None:
    if ends_on < starts_on:
        raise ValidationError(
            {"ends_on": "Ostatni dzień nie może być przed pierwszym."}, code="end_before_start"
        )


def _write[T: (BookingRule, BookingClosure, PriceRule, ParticipantCategory, Extra)](
    context: TenantContext,
    organization: Organization,
    model: type[T],
    item_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
    fields: Sequence[str],
    check: Any,
    action: str,
    *,
    unnamed: Collection[str] = (),
) -> Saved[T]:
    """`unnamed` fields go to the history as changed, without their values —
    a list of ids says nothing to a person."""
    if item_id is None:
        item = model(organization=organization, **data)
        before: dict[str, Any] = {}
    else:
        found = (
            model.all_objects.select_for_update()
            .filter(organization=organization, pk=item_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiej pozycji.")
        check_version(found.version, expected_version)
        item = found
        before = audit_snapshot(item, fields)
        for name, value in data.items():
            setattr(item, name, value)
    check(organization, item)
    changes = field_changes(before, audit_snapshot(item, fields), private=unnamed) if before else {}
    if changes:
        item.version += 1
    item.save()
    if changes:
        _audit(organization, context, action, item.id, {"changes": changes})
    elif not before:
        _audit(organization, context, action, item.id, {"created": True})
    return Saved(item, item.id, item.version, not before, changes)


def _replay[T: (BookingRule, BookingClosure, PriceRule, ParticipantCategory, Extra)](
    model: type[T], organization: Organization, item_id: UUID, created: bool
) -> Saved[T]:
    item = model.all_objects.filter(organization=organization, pk=item_id).first()
    if item is None:
        # The key's first answer was about an item deleted since.
        raise NotFound("Tej pozycji już nie ma.")
    return Saved(item, item.id, item.version, created, {}, replayed=True)


def _delete(
    model: type[BookingRule] | type[BookingClosure] | type[PriceRule],
    action: str,
    item_id: UUID,
    expected_version: int,
    idempotency_key: str,
    audit_action: str,
    *,
    going: Callable[[TenantContext, Any], object] | None = None,
) -> None:
    """`going`: called with the row before it is deleted, in the same
    transaction — for what must outlive it (a price's line in its record)."""
    context, organization = _manage()

    def write() -> Saved[None]:
        item = (
            model.all_objects.select_for_update()
            .filter(organization=organization, pk=item_id)
            .first()
        )
        if item is None:
            raise NotFound("Nie ma takiej pozycji.")
        check_version(item.version, expected_version)
        if going is not None:
            going(context, item)
        item.delete()
        _audit(organization, context, audit_action, item_id, {"deleted": True})
        return Saved(None, item_id, expected_version, False)

    setup_write(
        context=context,
        action=action,
        target_id=item_id,
        request={"expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=lambda _id: Saved(None, item_id, expected_version, False, replayed=True),
    )


def _copy[T: (BookingRule, BookingClosure, PriceRule)](
    context: TenantContext,
    organization: Organization,
    model: type[T],
    year: int,
    action: str,
) -> Saved[list[T]]:
    copies: list[T] = []
    for item in model.all_objects.filter(organization=organization, starts_on__year=year):
        item.pk = None
        item.id = model._meta.pk.get_default()
        item._state.adding = True
        # The filter took only dated ones; a price may have no dates.
        assert item.starts_on is not None and item.ends_on is not None
        item.starts_on, item.ends_on = next_year(item.starts_on), next_year(item.ends_on)
        item.version = 1
        item.save()
        copies.append(item)
    _audit(organization, context, action, None, {"copied_year": year, "count": len(copies)})
    return Saved(copies, organization.id, 1, True, {"count": {"from": 0, "to": len(copies)}})


def _audit(
    organization: Organization,
    context: TenantContext,
    action: str,
    target_id: UUID | None,
    metadata: dict[str, Any],
) -> None:
    record_audit(
        organization=organization,
        action=action,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type=_TARGETS[action],
        target_id=target_id,
        metadata=metadata,
    )
