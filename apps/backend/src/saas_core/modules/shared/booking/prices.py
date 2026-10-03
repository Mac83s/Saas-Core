"""The price list (ADR-072 §6, phase 3a).

A `PriceRule` prices an offer, a group of units or one unit: the base price
without dates, a season's with them, a weekend's or a peak's with weekdays and
hours. For a day and an hour one rule applies — `price_for`. A
`ParticipantCategory` is who comes when it changes the price.

Amounts are whole minor units of the company's currency, read gross or net as
the company set it (`pricing.entry.amounts`); a customer always sees gross.
Nothing here works a price out: `quote` does (§7), from these rules.

Both are setup items (§11): every write has a key with a receipt, a change
names the version it was made on, and runs as a preview. A category is never
deleted — a booking's frozen quote names it — only switched off.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, time
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.modules.core.organizations.api import setting
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .models import (
    ParticipantCategory,
    PriceBasis,
    PriceRule,
    Resource,
    ResourceGroup,
    Service,
    TimeModel,
)
from .rules import (
    CATEGORY_CHANGED,
    PRICE_CHANGED,
    _check_dates,
    _copy,
    _delete,
    _replay,
    _write,
)
from .setup import Saved, _manage, _own, setup_write

AMOUNTS = "pricing.entry.amounts"
GROSS, NET = "gross", "net"

_PRICE_FIELDS = (
    "name",
    "service_id",
    "group_id",
    "resource_id",
    "starts_on",
    "ends_on",
    "weekdays",
    "local_from",
    "local_to",
    "basis",
    "amount_minor",
    "currency",
    "vat_code",
    "included_people",
    "extra_person_amount_minor",
    "extra_person_per_time_unit",
    "category_prices",
    "length_discounts",
    "active",
)
_CATEGORY_FIELDS = ("name", "counts_towards_capacity", "active")
_SCOPES = (("service_id", Service), ("group_id", ResourceGroup), ("resource_id", Resource))


def amounts_are_gross() -> bool:
    """How the company's price list is read: gross unless it chose net."""
    return bool(setting(AMOUNTS) == GROSS)


def has_prices(organization_id: UUID) -> bool:
    """Whether the company holds amounts in its currency here (`currency_in_use`)."""
    return PriceRule.all_objects.filter(organization_id=organization_id).exists()


def list_prices() -> list[PriceRule]:
    _, organization = _manage(FeatureOperation.READ)
    return list(PriceRule.all_objects.filter(organization=organization))


def list_categories() -> list[ParticipantCategory]:
    _, organization = _manage(FeatureOperation.READ)
    return list(ParticipantCategory.all_objects.filter(organization=organization))


@transaction.atomic
def save_price(
    *,
    price_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[PriceRule]:
    """A price of an offer, a group or a unit — exactly one of `service_id`,
    `group_id`, `resource_id`. Its currency is the company's."""
    context, organization = _manage()
    created = price_id is None
    return setup_write(
        context=context,
        action="price.create" if created else "price.update",
        target_id=price_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write(
            context,
            organization,
            PriceRule,
            price_id,
            data,
            expected_version,
            _PRICE_FIELDS,
            _check_price,
            PRICE_CHANGED,
            unnamed=("category_prices", "length_discounts"),
        ),
        replay=lambda item_id: _replay(PriceRule, organization, item_id, created),
    )


@transaction.atomic
def delete_price(*, price_id: UUID, expected_version: int, idempotency_key: str) -> None:
    """Bookings keep their frozen quote, so a price can go."""
    _delete(PriceRule, "price.delete", price_id, expected_version, idempotency_key, PRICE_CHANGED)


@transaction.atomic
def copy_prices_to_next_year(
    *, year: int, idempotency_key: str = "", preview: bool = False
) -> Saved[list[PriceRule]]:
    """Every season's price that starts in `year`, again a year later."""
    context, organization = _manage()
    return setup_write(
        context=context,
        action="price.copy_year",
        target_id=None,
        request={"year": year},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _copy(context, organization, PriceRule, year, PRICE_CHANGED),
        replay=lambda _id: Saved([], organization.id, 0, True, replayed=True),
    )


@transaction.atomic
def save_category(
    *,
    category_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[ParticipantCategory]:
    context, organization = _manage()
    created = category_id is None
    return setup_write(
        context=context,
        action="participant_category.create" if created else "participant_category.update",
        target_id=category_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_category(context, organization, category_id, data, expected_version),
        replay=lambda item_id: _replay(ParticipantCategory, organization, item_id, created),
    )


def _write_category(
    context: TenantContext,
    organization: Organization,
    category_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
) -> Saved[ParticipantCategory]:
    saved = _write(
        context,
        organization,
        ParticipantCategory,
        category_id,
        data,
        expected_version,
        _CATEGORY_FIELDS,
        _check_category,
        CATEGORY_CHANGED,
    )
    if saved.created or set(saved.changes) & {"name", "active"}:
        # The catalogue's text, or what it offers, changed (TL12c).
        from .translation_source import notify_catalog_changed  # noqa: PLC0415

        notify_catalog_changed(context=context)
    return saved


def price_for(
    rules: Iterable[PriceRule],
    *,
    day: date,
    at: time | None = None,
    service_id: UUID,
    group_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> PriceRule | None:
    """The price that applies on `day` — and at `at`, for a booking that starts
    at an hour. The unit's over its group's over the offer's; then a season's
    over the base price; then the narrower one (weekdays and hours over
    weekdays or hours over neither); then the later start, then the later made.
    """
    covering = [
        rule
        for rule in rules
        if rule.active
        and (rule.starts_on is None or rule.starts_on <= day <= _end(rule))
        and (not rule.weekdays or day.weekday() in rule.weekdays)
        and (rule.local_from is None or (at is not None and rule.local_from <= at < _until(rule)))
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
            rule.starts_on is not None,
            bool(rule.weekdays) + (rule.local_from is not None),
            rule.starts_on or date.min,
            rule.created_at,
        ),
    )


def _end(rule: PriceRule) -> date:
    assert rule.ends_on is not None  # booking_price_dates_ck: both or neither
    return rule.ends_on


def _until(rule: PriceRule) -> time:
    assert rule.local_to is not None  # booking_price_hours_ck: both or neither
    return rule.local_to


def _refuse(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(message, code=code)]})


def _check_price(organization: Organization, rule: PriceRule) -> None:
    scopes = [name for name, _model in _SCOPES if getattr(rule, name) is not None]
    if len(scopes) != 1:
        raise _refuse(
            "service_id",
            "Cena dotyczy jednej usługi, jednej grupy albo jednej jednostki.",
            "one_scope",
        )
    for name, model in _SCOPES:
        if getattr(rule, name) is not None:
            _own(model, organization, [getattr(rule, name)], name)
    # The amount carries the company's currency; a company with prices keeps
    # its currency (`currency_in_use`), so every rule has the same one.
    rule.currency = organization.currency
    if (rule.starts_on is None) != (rule.ends_on is None):
        raise _refuse(
            "ends_on" if rule.ends_on is None else "starts_on",
            "Podaj oba dni sezonu albo żadnego.",
            "required",
        )
    if rule.starts_on is not None and rule.ends_on is not None:
        _check_dates(rule.starts_on, rule.ends_on)
    if (rule.local_from is None) != (rule.local_to is None):
        raise _refuse(
            "local_to" if rule.local_to is None else "local_from",
            "Podaj obie godziny albo żadnej.",
            "required",
        )
    if (
        rule.local_from is not None
        and rule.local_to is not None
        and rule.local_to <= rule.local_from
    ):
        raise _refuse("local_to", "Koniec musi być po początku.", "end_before_start")
    if any(not 0 <= day <= 6 for day in rule.weekdays):
        raise _refuse("weekdays", "Dni tygodnia to 0–6 (poniedziałek–niedziela).", "invalid")
    rule.weekdays = sorted(set(rule.weekdays))
    timed = rule.basis == PriceBasis.PER_TIME_UNIT
    if timed and rule.service_id is not None:
        # A visit has a set length and no time unit to multiply by.
        slot = Service.all_objects.filter(
            organization=organization, pk=rule.service_id, time_model=TimeModel.SLOT
        ).exists()
        if slot:
            raise _refuse(
                "basis",
                "Wizyta nie ma jednostki czasu: wybierz cenę za rezerwację.",
                "basis_needs_time_unit",
            )
    if rule.basis == PriceBasis.PER_PERSON and (
        rule.included_people is not None or rule.extra_person_amount_minor is not None
    ):
        raise _refuse(
            "included_people",
            "Cena za osobę liczy każdą osobę: nie ma osób w cenie ani dopłaty.",
            "not_for_this_basis",
        )
    if rule.extra_person_amount_minor is not None and rule.included_people is None:
        raise _refuse(
            "included_people", "Podaj, ile osób jest w cenie.", "included_people_required"
        )
    if rule.extra_person_amount_minor is None or not timed:
        rule.extra_person_per_time_unit = False
    rule.category_prices = _category_prices(organization, rule.category_prices)
    if rule.length_discounts and not timed:
        raise _refuse(
            "length_discounts",
            "Rabat za długość dotyczy ceny za jednostkę czasu.",
            "not_for_this_basis",
        )
    rule.length_discounts = _length_discounts(rule.length_discounts)


def _category_prices(organization: Organization, given: Any) -> list[dict[str, Any]]:
    ids = [UUID(str(line["category_id"])) for line in given]
    if len(set(ids)) != len(ids):
        raise _refuse("category_prices", "Każda kategoria ma jedną cenę.", "duplicate")
    _own(ParticipantCategory, organization, ids, "category_prices")
    return [
        {"category_id": str(category_id), "amount_minor": int(line["amount_minor"])}
        for category_id, line in zip(ids, given, strict=True)
    ]


def _length_discounts(given: Any) -> list[dict[str, int]]:
    lines = sorted(
        (
            {"min_length": int(line["min_length"]), "percent": int(line["percent"])}
            for line in given
        ),
        key=lambda line: line["min_length"],
    )
    if len({line["min_length"] for line in lines}) != len(lines):
        raise _refuse("length_discounts", "Każdy próg długości ma jeden rabat.", "duplicate")
    return lines


def _check_category(organization: Organization, category: ParticipantCategory) -> None:
    category.name = category.name.strip()
    taken = ParticipantCategory.all_objects.filter(
        organization=organization, name__iexact=category.name
    ).exclude(pk=category.pk)
    if taken.exists():
        raise _refuse("name", "Taka kategoria już jest.", "name_taken")
