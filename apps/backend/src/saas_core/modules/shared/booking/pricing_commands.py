"""The assistant's commands for an offer's units and its price list, and the
undo of a draft (ADR-076 §1; ADR-072 §3, §6, §7 and §11).

Thin adapters over the setup services the panel calls: the pool of units a
stay or a rental is booked in, a price, a participant category, an extra or a
deposit, a read of the price list, a quote that writes nothing, and the
removal of an offer nobody ever switched on.

**A price a customer will see is not a draft.** A price, an extra or a unit of
an offer that is still switched off changes nothing anybody can book, so it
takes the click of a draft. The same write on an offer that is switched on —
or on a group or a unit such an offer books — changes what customers pay or
get from that moment: the preview raises it to `apply`. Either way the words
the person agrees to carry the amount, how it is read (gross or net), the tax
and what it is charged for, written by the server from the previewed write —
never the model's account of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, cast
from uuid import UUID

from django.db.models import Q
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.api import CommandSpec, Preview
from saas_core.modules.core.organizations.models import Organization

from .command_declarations import _effect, _given, _id, _jsonable, _nullable
from .models import (
    BookingRule,
    Extra,
    ExtraBasis,
    ExtraKind,
    ParticipantCategory,
    PriceBasis,
    PriceRule,
    RangeUnit,
    Resource,
    ResourceGroup,
    Service,
    ServiceGroup,
    ServiceResource,
    VatCode,
)
from .price_views import (
    MAX_AMOUNT_MINOR,
    ExtraInputSerializer,
    ExtraUpdateSerializer,
    ParticipantCategoryInputSerializer,
    ParticipantCategoryUpdateSerializer,
    PriceRuleInputSerializer,
    PriceRuleUpdateSerializer,
    _category_payload,
    _extra_payload,
    _price_payload,
)
from .prices import (
    GROSS,
    NET,
    amounts_are_gross,
    list_categories,
    list_extras,
    list_prices,
    save_category,
    save_extra,
    save_price,
)
from .quote import quote_offer
from .serializers import BookingQuoteInputSerializer
from .services import BOOKING_ENABLED, BOOKING_MANAGE
from .setup import MAX_OFFER_UNITS, MAX_UNIT_CAPACITY, discard_draft, set_offer_units

_PUBLIC = "public"


def _choice(values: list[str], description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None], "description": description}


def _bounded(kind: str, description: str, **bounds: Any) -> dict[str, Any]:
    return {**_nullable(kind, description), **bounds}


def _plain(value: Any) -> Any:
    """As JSON carries it: ids and hours as the other commands write them, and
    dates as `YYYY-MM-DD`."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return _jsonable(value)


# --- What a customer can book now ---------------------------------------------------


def _service(organization_id: UUID, service_id: UUID | None) -> Service:
    found = (
        Service.all_objects.filter(organization_id=organization_id, pk=service_id).first()
        if service_id is not None
        else None
    )
    if found is None:
        raise NotFound("Nie ma takiej usługi.")
    return found


def _live_scope(
    organization_id: UUID,
    *,
    service_id: UUID | None = None,
    group_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> bool:
    """Whether a customer can book what the price is for: the offer is switched
    on, or a switched-on offer books the group or the unit."""
    if service_id is not None:
        return Service.all_objects.filter(
            organization_id=organization_id, pk=service_id, active=True
        ).exists()
    if resource_id is not None:
        unit = Resource.all_objects.filter(organization_id=organization_id, pk=resource_id).first()
        if unit is None:
            return False
        if ServiceResource.all_objects.filter(
            organization_id=organization_id, resource=unit, service__active=True
        ).exists():
            return True
        group_id = unit.group_id
    return (
        group_id is not None
        and ServiceGroup.all_objects.filter(
            organization_id=organization_id, group_id=group_id, service__active=True
        ).exists()
    )


def _raised(live: bool) -> str | None:
    return "apply" if live else None


# --- Words the person agrees to ------------------------------------------------------

_VAT_WORDS: dict[str, tuple[str, str]] = {
    VatCode.EXEMPT.value: ("zwolnione z VAT", "VAT exempt"),
    VatCode.OUTSIDE.value: ("nie podlega VAT", "outside VAT"),
}
_TIME_UNIT: dict[str, tuple[str, str]] = {
    RangeUnit.NIGHT.value: ("za noc", "per night"),
    RangeUnit.DAY.value: ("za dzień", "per day"),
    "": ("za jednostkę czasu", "per time unit"),
}
_BASIS: dict[str, tuple[str, str]] = {
    PriceBasis.PER_BOOKING.value: ("za rezerwację", "per booking"),
    PriceBasis.PER_PERSON.value: ("za osobę", "per person"),
    PriceBasis.PER_GROUP.value: ("za grupę", "per group"),
    ExtraBasis.PER_PERSON_PER_TIME_UNIT.value: ("za osobę", "per person"),
}
_DAYS = (
    ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."),
    ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
)


def _money(amount_minor: int, currency: str, at: int) -> str:
    whole, part = divmod(amount_minor, 100)
    # Thousands grouped the way each language writes them: a no-break space, a comma.
    grouped = f"{whole:,}".replace(",", chr(0xA0) if at == 0 else ",")
    return f"{grouped}{',' if at == 0 else '.'}{part:02d} {currency}"


def _vat(code: str, at: int) -> str:
    return _VAT_WORDS[code][at] if code in _VAT_WORDS else f"VAT {code}%"


def _read_as(at: int) -> str:
    return (("brutto", "gross") if amounts_are_gross() else ("netto", "net"))[at]


def _per(basis: str, unit: str, at: int) -> str:
    """What an amount is charged for; a time unit by the offer's own."""
    if basis == PriceBasis.PER_TIME_UNIT:
        return _TIME_UNIT.get(unit, _TIME_UNIT[""])[at]
    if basis == ExtraBasis.PER_PERSON_PER_TIME_UNIT:
        return f"{_BASIS[basis][at]} {_TIME_UNIT.get(unit, _TIME_UNIT[''])[at]}"
    return _BASIS[basis][at]


def _scope(rule: PriceRule | BookingRule) -> tuple[tuple[str, str], str]:
    """Whose price or season it is, in words, and the time unit its offer counts."""
    if rule.service_id is not None:
        service = Service.all_objects.get(pk=rule.service_id)
        return (f"usługi „{service.name}”", f"of the service “{service.name}”"), service.range_unit
    if rule.group_id is not None:
        name = ResourceGroup.all_objects.get(pk=rule.group_id).name
        return (f"grupy jednostek „{name}”", f"of the group of units “{name}”"), ""
    assert rule.resource_id is not None  # one scope, checked by the write
    name = Resource.all_objects.get(pk=rule.resource_id).name
    return (f"jednostki „{name}”", f"of the unit “{name}”"), ""


def _price_words(rule: PriceRule, unit: str, at: int) -> str:
    """The price as the person agrees to it: the amount, what for, how it is
    read, the tax, and what narrows it."""
    parts = [
        f"{_money(rule.amount_minor, rule.currency, at)} {_per(rule.basis, unit, at)}",
        _read_as(at),
        _vat(rule.vat_code, at),
    ]
    if rule.starts_on is not None and rule.ends_on is not None:
        dates = f"{rule.starts_on.isoformat()} – {rule.ends_on.isoformat()}"
        parts.append(f"{('w sezonie', 'in the season')[at]} {dates}")
    else:
        parts.append(("cena podstawowa", "the base price")[at])
    if rule.weekdays:
        parts.append(", ".join(_DAYS[at][day] for day in rule.weekdays))
    if rule.local_from is not None and rule.local_to is not None:
        parts.append(f"{rule.local_from.isoformat('minutes')}–{rule.local_to.isoformat('minutes')}")
    if rule.included_people is not None and rule.extra_person_amount_minor is not None:
        more = _money(rule.extra_person_amount_minor, rule.currency, at)
        each = _TIME_UNIT.get(unit, _TIME_UNIT[""])[at] if rule.extra_person_per_time_unit else ""
        parts.append(
            (
                f"w cenie {rule.included_people} os., każda kolejna {more} {each}".strip(),
                f"{rule.included_people} people included, each further {more} {each}".strip(),
            )[at]
        )
    if rule.category_prices:
        count = len(rule.category_prices)
        parts.append((f"ceny kategorii: {count}", f"category prices: {count}")[at])
    if rule.length_discounts:
        best = max(line["percent"] for line in rule.length_discounts)
        parts.append((f"rabat za długość do {best}%", f"a discount for length up to {best}%")[at])
    if not rule.active:
        parts.append(("wyłączona", "switched off")[at])
    return ", ".join(parts)


def _units_pl(count: int) -> str:
    if count == 1:
        return "1 jednostka"
    few = count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14)
    return f"{count} {'jednostki' if few else 'jednostek'}"


def _listed(names: list[str], at: int) -> str:
    shown = ", ".join(f"„{name}”" if at == 0 else f"“{name}”" for name in names[:3])
    rest = len(names) - 3
    if rest > 0:
        shown += (f" i {rest} kolejnych", f" and {rest} more")[at]
    return shown


# --- booking.offer.units.set@1 -------------------------------------------------------

_UNITS_FIELDS = ("count", "capacity", "location_id")


def _units_data(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "service_id": _id(arguments, "service_id"),
        "count": arguments["count"],
        "capacity": arguments["capacity"],
        "location_id": (
            _id(arguments, "location_id") if arguments["location_id"] is not None else None
        ),
    }


def _preview_units(arguments: Mapping[str, Any], call: Any) -> Preview:
    data = _units_data(arguments)
    service = _service(call.context.organization_id, data["service_id"])
    saved = set_offer_units(**data, expected_version=service.version, preview=True)
    pool = saved.value
    added = pool.added
    # A pool another switched-on offer books changes what customers get too.
    live = service.active or _live_scope(call.context.organization_id, group_id=pool.group.id)
    if added:
        pl = (
            f"Usługa „{service.name}”: {_units_pl(len(pool.units))} w grupie "
            f"„{pool.group.name}” — nowe: {_listed(added, 0)}"
        )
        en = (
            f"Service “{service.name}”: {len(pool.units)} unit(s) in the group "
            f"“{pool.group.name}” — new: {_listed(added, 1)}"
        )
    elif saved.changes:
        pl = (
            f"Usługa „{service.name}” będzie rezerwowana w grupie „{pool.group.name}” "
            f"({_units_pl(len(pool.units))}); nowych jednostek nie dodaję"
        )
        en = (
            f"Service “{service.name}” will be booked in the group “{pool.group.name}” "
            f"({len(pool.units)} unit(s)); no unit is added"
        )
    else:
        pl = f"Usługa „{service.name}” ma już {_units_pl(len(pool.units))} — bez zmian"
        en = f"Service “{service.name}” already has {len(pool.units)} unit(s) — no change"
    return Preview(
        effects=(_effect("updated", "booking.service", str(service.id), pl, en),),
        observed_versions={f"booking.service:{service.id}": service.version},
        escalate_to=_raised(live),
    )


def _set_units(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    data = _units_data(arguments)
    saved = set_offer_units(
        **data,
        expected_version=call.preview.observed_versions[f"booking.service:{data['service_id']}"],
        idempotency_key=call.idempotency_key,
    )
    pool = saved.value
    return {
        "service_id": str(pool.service.id),
        "group_id": str(pool.group.id),
        "group_name": pool.group.name,
        "units": [{"id": str(unit.id), "name": unit.name} for unit in pool.units],
        "added": list(pool.added),
        "version": saved.version,
    }


OFFER_UNITS_SET = CommandSpec(
    name="booking.offer.units.set",
    version=1,
    module="shared.booking",
    title={"pl": "Ustaw jednostki usługi", "en": "Set a service's units"},
    summary={
        "pl": "Ile identycznych jednostek ma pobyt albo wynajem; brakujące są dodawane.",
        "en": "How many identical units a stay or a rental has; the missing ones are added.",
    },
    model_description=(
        "Brings a stay or a rental (a service with time model `range`) up to `count` "
        "identical units — cottages, rooms, kayaks — in one step: the service's group of "
        "units is made under the service's name when it has none, and the units it lacks "
        "are added, named after the group and numbered. `count` is how many units the "
        "service has in all, not how many to add. It only ever adds: a count below what "
        "is there is refused with `units_cannot_be_removed` on `count` — tell the person "
        "to switch the spare unit off in the panel. `capacity` (people one unit takes) and "
        "`location_id` describe the units added; null leaves them unset. A visit by the "
        "clock has no units (`units_need_range_offer`); a group that is switched off is "
        "refused (`unit_group_switched_off`). Take the count from the person; "
        "use booking.setup.read first for the service id."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["service_id", *_UNITS_FIELDS],
        "properties": {
            "service_id": {"type": "string", "description": "The stay or rental."},
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_OFFER_UNITS,
                "description": "How many units the service has in all.",
            },
            "capacity": _bounded(
                "integer",
                "How many people one new unit takes; null leaves it unset.",
                minimum=1,
                maximum=MAX_UNIT_CAPACITY,
            ),
            "location_id": _nullable(
                "string", "The company's place the new units are at; null leaves it unset."
            ),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "service_id": {"type": "string"},
            "group_id": {"type": "string"},
            "group_name": {"type": "string"},
            "units": {"type": "array"},
            "added": {"type": "array"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_set_units,
    undo="none:a unit is never deleted, it may hold bookings; a spare one is switched off",
    preview=_preview_units,
    version_field="expected_version",
)


# --- booking.prices.read@1 -----------------------------------------------------------


def _read_prices(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    organization = Organization.objects.get(pk=call.context.organization_id)
    return cast(
        dict[str, Any],
        _plain({
            "currency": organization.currency,
            "amounts": GROSS if amounts_are_gross() else NET,
            "prices": [_price_payload(item) for item in list_prices()],
            "extras": [_extra_payload(item) for item in list_extras()],
            "categories": [_category_payload(item) for item in list_categories()],
        }),
    )


PRICES_READ = CommandSpec(
    name="booking.prices.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj cennik", "en": "Read the price list"},
    summary={
        "pl": "Ceny, dopłaty, kaucje i kategorie uczestników, z wersjami do zmian.",
        "en": "Prices, extras, deposits and participant categories, with their versions.",
    },
    model_description=(
        "Returns the company's price list as it was entered: every price (of a service, a "
        "group of units or a unit — the base price without dates, a season's with them), "
        "every extra and deposit, every participant category, switched-off ones included, "
        "each with its id and version; `currency` and whether amounts are read `gross` or "
        "`net`. Amounts are whole minor units (grosze). Use it before changing a price, to "
        "know the ids. It is the list, not what a booking costs: never add amounts up "
        "yourself — ask booking.quote.read."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "currency": {"type": "string"},
            "amounts": {"type": "string"},
            "prices": {"type": "array"},
            "extras": {"type": "array"},
            "categories": {"type": "array"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_prices,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- booking.price.save@1 ------------------------------------------------------------

_PRICE_FIELDS = (
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
)
_AMOUNT = {"minimum": 0, "maximum": MAX_AMOUNT_MINOR}
_VAT_DESCRIPTION = (
    "The tax rate as a code: 23, 8, 5, 0, `zw` (exempt), `np` (outside VAT). The person "
    "says it; never pick one for them."
)


def _price_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _PRICE_FIELDS)
    if version is None:
        serializer: Any = PriceRuleInputSerializer(data=given)
    else:
        serializer = PriceRuleUpdateSerializer(data={**given, "expected_version": version})
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _current_price(arguments: Mapping[str, Any], call: Any) -> PriceRule | None:
    if arguments["price_id"] is None:
        return None
    found = PriceRule.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "price_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiej ceny.")
    return found


def _preview_price(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = _current_price(arguments, call)
    version = current.version if current is not None else None
    saved = save_price(
        price_id=current.id if current is not None else None,
        data=_price_data(arguments, version),
        expected_version=version,
        preview=True,
    )
    rule = saved.value
    whose, unit = _scope(rule)
    live = _live_scope(
        call.context.organization_id,
        service_id=rule.service_id,
        group_id=rule.group_id,
        resource_id=rule.resource_id,
    )
    if current is None:
        pl = f"Nowa cena {whose[0]}: {_price_words(rule, unit, 0)}"
        en = f"New price {whose[1]}: {_price_words(rule, unit, 1)}"
    else:
        pl = f"Cena {whose[0]} po zmianie: {_price_words(rule, unit, 0)}"
        en = f"The price {whose[1]} after the change: {_price_words(rule, unit, 1)}"
    if live:
        pl += " — obowiązuje od razu, dla nowych rezerwacji"
        en += " — in force at once, for new bookings"
    return Preview(
        effects=(
            _effect(
                "created" if current is None else "updated",
                "booking.price",
                str(current.id) if current is not None else "",
                pl,
                en,
            ),
        ),
        observed_versions=(
            {f"booking.price:{current.id}": current.version} if current is not None else {}
        ),
        escalate_to=_raised(live),
    )


def _save_price(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    price_id = _id(arguments, "price_id") if arguments["price_id"] is not None else None
    version = (
        call.preview.observed_versions[f"booking.price:{price_id}"]
        if price_id is not None
        else None
    )
    saved = save_price(
        price_id=price_id,
        data=_price_data(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    rule = saved.value
    return {
        "price_id": str(rule.id),
        "amount_minor": rule.amount_minor,
        "currency": rule.currency,
        "basis": rule.basis,
        "vat_code": rule.vat_code,
        "active": rule.active,
        "version": rule.version,
    }


PRICE_SAVE = CommandSpec(
    name="booking.price.save",
    version=1,
    module="shared.booking",
    title={"pl": "Zapisz cenę", "en": "Save a price"},
    summary={
        "pl": "Cena usługi, grupy jednostek albo jednostki: podstawowa albo sezonu.",
        "en": "A price of a service, a group of units or a unit: the base one or a season's.",
    },
    model_description=(
        "Adds a price (price_id null) or changes one (its price_id from booking.prices.read). "
        "A price belongs to exactly one of a service, a group of units or a unit. Without "
        "dates it is the base price; with starts_on and ends_on a season's; weekdays and "
        "hours narrow it to a weekend or a peak. `amount_minor` is whole minor units "
        "(45000 is 450.00) in the company's currency, read gross or net as the company's "
        "price list is (booking.prices.read says which). `basis`: per_booking; "
        "per_time_unit — a night or a day of a stay, never for a visit by the clock; "
        "per_person; per_group. With included_people give extra_person_amount_minor too "
        "(0 says further people come free). Money is never guessed: the amount and the tax "
        "code are the person's own words — when either was not said, ask, do not call. "
        "Pass null for every field that stays as it is (a new price takes its defaults); "
        "a list given replaces the list; a field cannot be cleared here — the person "
        "clears a season's dates in the panel. A price of a switched-on service is in "
        "force at once for new bookings; bookings already made keep theirs."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["price_id", *_PRICE_FIELDS],
        "properties": {
            "price_id": _nullable("string", "The price to change; null adds a new one."),
            "service_id": _nullable("string", "The service it prices."),
            "group_id": _nullable("string", "The group of units it prices."),
            "resource_id": _nullable("string", "The unit it prices."),
            "name": _nullable("string", "A name for the company: „Sezon wysoki”, „Weekend”."),
            "starts_on": _nullable("string", "First local day of the season, YYYY-MM-DD."),
            "ends_on": _nullable("string", "Last local day of the season, included."),
            "weekdays": {
                "type": ["array", "null"],
                "items": {"type": "integer", "minimum": 0, "maximum": 6},
                "description": "The weekdays it prices, 0 is Monday; null — every day.",
            },
            "local_from": _nullable("string", "With local_to: the local hours it prices, HH:MM."),
            "local_to": _nullable("string", "The end of those hours, HH:MM."),
            "basis": _choice(list(PriceBasis.values), "What the amount is charged for."),
            "amount_minor": _bounded(
                "integer", "The amount in minor units of the company's currency.", **_AMOUNT
            ),
            "vat_code": _choice(list(VatCode.values), _VAT_DESCRIPTION),
            "included_people": _nullable(
                "integer", "How many people the amount covers; null — everybody who comes."
            ),
            "extra_person_amount_minor": _bounded(
                "integer",
                "What each person beyond included_people adds, in minor units.",
                **_AMOUNT,
            ),
            "extra_person_per_time_unit": _nullable(
                "boolean", "Further people pay per night or day, not once."
            ),
            "category_prices": {
                "type": ["array", "null"],
                "description": "A participant category's own amount instead of a person's.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category_id", "amount_minor"],
                    "properties": {
                        "category_id": {"type": "string", "description": "The category."},
                        "amount_minor": {
                            "type": "integer",
                            "description": "What one participant of it pays, in minor units.",
                            **_AMOUNT,
                        },
                    },
                },
            },
            "length_discounts": {
                "type": ["array", "null"],
                "description": "For per_time_unit: the percent off from so many nights or days.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["min_length", "percent"],
                    "properties": {
                        "min_length": {"type": "integer", "description": "From this many."},
                        "percent": {"type": "integer", "description": "The percent off, 1–100."},
                    },
                },
            },
            "active": _nullable("boolean", "False switches the price off."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "price_id": {"type": "string"},
            "amount_minor": {"type": "integer"},
            "currency": {"type": "string"},
            "basis": {"type": "string"},
            "vat_code": {"type": "string"},
            "active": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_save_price,
    undo="command:booking.price.save@1",
    preview=_preview_price,
    version_field="expected_version",
)


# --- booking.participant_category.save@1 ---------------------------------------------

_CATEGORY_FIELDS = ("name", "counts_towards_capacity", "active")


def _category_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _CATEGORY_FIELDS)
    if version is None:
        serializer: Any = ParticipantCategoryInputSerializer(data=given)
    else:
        serializer = ParticipantCategoryUpdateSerializer(
            data={**given, "expected_version": version}
        )
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _current_category(arguments: Mapping[str, Any], call: Any) -> ParticipantCategory | None:
    if arguments["category_id"] is None:
        return None
    found = ParticipantCategory.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "category_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiej kategorii.")
    return found


def _preview_category(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = _current_category(arguments, call)
    version = current.version if current is not None else None
    saved = save_category(
        category_id=current.id if current is not None else None,
        data=_category_data(arguments, version),
        expected_version=version,
        preview=True,
    )
    item = saved.value
    counted = (
        ("liczy się do pojemności jednostki", "counts towards a unit's capacity")
        if item.counts_towards_capacity
        else ("nie liczy się do pojemności jednostki", "does not count towards a unit's capacity")
    )
    state = ("", "") if item.active else (", wyłączona", ", switched off")
    if current is None:
        pl = f"Nowa kategoria uczestników „{item.name}” — {counted[0]}{state[0]}"
        en = f"New participant category “{item.name}” — {counted[1]}{state[1]}"
    else:
        pl = f"Kategoria uczestników „{item.name}” po zmianie: {counted[0]}{state[0]}"
        en = f"Participant category “{item.name}” after the change: {counted[1]}{state[1]}"
    return Preview(
        effects=(
            _effect(
                "created" if current is None else "updated",
                "booking.participant_category",
                str(current.id) if current is not None else "",
                pl,
                en,
            ),
        ),
        observed_versions=(
            {f"booking.participant_category:{current.id}": current.version}
            if current is not None
            else {}
        ),
    )


def _save_category(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    category_id = _id(arguments, "category_id") if arguments["category_id"] is not None else None
    version = (
        call.preview.observed_versions[f"booking.participant_category:{category_id}"]
        if category_id is not None
        else None
    )
    saved = save_category(
        category_id=category_id,
        data=_category_data(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    item = saved.value
    return {
        "category_id": str(item.id),
        "name": item.name,
        "counts_towards_capacity": item.counts_towards_capacity,
        "active": item.active,
        "version": item.version,
    }


CATEGORY_SAVE = CommandSpec(
    name="booking.participant_category.save",
    version=1,
    module="shared.booking",
    title={"pl": "Zapisz kategorię uczestników", "en": "Save a participant category"},
    summary={
        "pl": "Kto przyjeżdża, gdy zmienia to cenę: „Dziecko”, „Senior”, „Pies”.",
        "en": "Who comes, when it changes the price: “Child”, “Senior”, “Dog”.",
    },
    model_description=(
        "Adds a participant category (category_id null) or changes one (its id from "
        "booking.prices.read). A category is who comes when that changes the price — a "
        "child, a senior, a dog; a price then names its amount in category_prices. "
        "counts_towards_capacity says whether such a participant takes a place in a unit "
        "(a child does, a dog does not). A category is never deleted — bookings name it — "
        "only switched off with active false. Pass null for every field that stays as it "
        "is; a new category needs a name. It belongs to the whole company, so it shows in "
        "every booking form that asks who comes."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["category_id", *_CATEGORY_FIELDS],
        "properties": {
            "category_id": _nullable("string", "The category to change; null adds a new one."),
            "name": _nullable("string", "Its name as customers see it, up to 160 characters."),
            "counts_towards_capacity": _nullable(
                "boolean", "Whether such a participant takes a place in a unit."
            ),
            "active": _nullable("boolean", "False switches the category off."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "category_id": {"type": "string"},
            "name": {"type": "string"},
            "counts_towards_capacity": {"type": "boolean"},
            "active": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    # The company's own list, used by every form that asks who comes: there is
    # no draft of it.
    risk="apply",
    run=_save_category,
    undo="command:booking.participant_category.save@1",
    preview=_preview_category,
    version_field="expected_version",
)


# --- booking.extra.save@1 ------------------------------------------------------------

_EXTRA_FIELDS = (
    "service_id",
    "name",
    "kind",
    "basis",
    "amount_minor",
    "vat_code",
    "mandatory",
    "max_quantity",
    "active",
)


def _extra_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _EXTRA_FIELDS)
    if version is None:
        serializer: Any = ExtraInputSerializer(data=given)
    else:
        # An extra stays with its offer: the service is not a field of a change.
        given.pop("service_id", None)
        serializer = ExtraUpdateSerializer(data={**given, "expected_version": version})
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _current_extra(arguments: Mapping[str, Any], call: Any) -> Extra | None:
    if arguments["extra_id"] is None:
        return None
    found = Extra.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "extra_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiej dopłaty.")
    return found


def _extra_words(extra: Extra, unit: str, at: int) -> str:
    amount = _money(extra.amount_minor, extra.currency, at)
    if extra.kind == ExtraKind.SECURITY_DEPOSIT:
        words = (
            f"{amount} — pobierana przy rezerwacji i zwracana, bez podatku, poza ceną",
            f"{amount} — held for the booking and given back, no tax, outside the price",
        )[at]
    else:
        picked = (
            ("na każdej rezerwacji", "on every booking")
            if extra.mandatory
            else (
                f"do wyboru, najwyżej {extra.max_quantity}",
                f"picked by the customer, at most {extra.max_quantity}",
            )
        )[at]
        words = ", ".join((
            f"{amount} {_per(extra.basis, unit, at)}",
            _read_as(at),
            _vat(extra.vat_code, at),
            picked,
        ))
    return words if extra.active else f"{words}, {('wyłączona', 'switched off')[at]}"


def _preview_extra(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = _current_extra(arguments, call)
    version = current.version if current is not None else None
    saved = save_extra(
        extra_id=current.id if current is not None else None,
        data=_extra_data(arguments, version),
        expected_version=version,
        preview=True,
    )
    extra = saved.value
    service = _service(call.context.organization_id, extra.service_id)
    deposit = extra.kind == ExtraKind.SECURITY_DEPOSIT
    what = ("Kaucja", "Deposit") if deposit else ("Dopłata", "Extra")
    new = ("Nowa ", "New ") if current is None else ("", "")
    pl = (
        f"{new[0]}{what[0].lower() if new[0] else what[0]} „{extra.name}” usługi "
        f"„{service.name}”: {_extra_words(extra, service.range_unit, 0)}"
    )
    en = (
        f"{new[1]}{what[1].lower() if new[1] else what[1]} “{extra.name}” of the service "
        f"“{service.name}”: {_extra_words(extra, service.range_unit, 1)}"
    )
    if service.active:
        pl += " — obowiązuje od razu, dla nowych rezerwacji"
        en += " — in force at once, for new bookings"
    return Preview(
        effects=(
            _effect(
                "created" if current is None else "updated",
                "booking.extra",
                str(current.id) if current is not None else "",
                pl,
                en,
            ),
        ),
        observed_versions=(
            {f"booking.extra:{current.id}": current.version} if current is not None else {}
        ),
        escalate_to=_raised(service.active),
    )


def _save_extra(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    extra_id = _id(arguments, "extra_id") if arguments["extra_id"] is not None else None
    version = (
        call.preview.observed_versions[f"booking.extra:{extra_id}"]
        if extra_id is not None
        else None
    )
    saved = save_extra(
        extra_id=extra_id,
        data=_extra_data(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    extra = saved.value
    return {
        "extra_id": str(extra.id),
        "service_id": str(extra.service_id),
        "name": extra.name,
        "kind": extra.kind,
        "amount_minor": extra.amount_minor,
        "currency": extra.currency,
        "active": extra.active,
        "version": extra.version,
    }


EXTRA_SAVE = CommandSpec(
    name="booking.extra.save",
    version=1,
    module="shared.booking",
    title={"pl": "Zapisz dopłatę albo kaucję", "en": "Save an extra or a deposit"},
    summary={
        "pl": "Co usługa dolicza do ceny albo jaką kaucję pobiera.",
        "en": "What a service adds to its price, or the deposit it holds.",
    },
    model_description=(
        "Adds an extra to one service (extra_id null, with service_id) or changes one (its "
        "extra_id from booking.prices.read). `kind` `charge` is something the customer "
        "pays — final cleaning, bed linen, a local tax: mandatory on every booking, or "
        "picked by the customer up to max_quantity; `basis` per_booking, per_person, and "
        "for a stay per_time_unit or per_person_per_time_unit. `kind` `security_deposit` "
        "is money held and given back: one amount per booking, no tax, never part of the "
        "total — give only its name and amount. `amount_minor` is whole minor units "
        "(15000 is 150.00), read gross or net like the price list. Money is never guessed: "
        "the amount and the tax code are the person's own words — when either was not "
        "said, ask, do not call. An extra is never deleted — bookings name it — only "
        "switched off with active false. Pass null for every field that stays as it is."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["extra_id", *_EXTRA_FIELDS],
        "properties": {
            "extra_id": _nullable("string", "The extra to change; null adds a new one."),
            "service_id": _nullable("string", "The service a new extra belongs to."),
            "name": _nullable("string", "Its name as customers see it, up to 160 characters."),
            "kind": _choice(list(ExtraKind.values), "A charge, or a deposit held and given back."),
            "basis": _choice(list(ExtraBasis.values), "What the amount is charged for."),
            "amount_minor": _bounded(
                "integer", "The amount in minor units of the company's currency.", **_AMOUNT
            ),
            "vat_code": _choice(list(VatCode.values), _VAT_DESCRIPTION),
            "mandatory": _nullable(
                "boolean", "On every booking of the service; otherwise the customer picks."
            ),
            "max_quantity": _nullable(
                "integer", "How many of an optional one a booking may take, 1–100."
            ),
            "active": _nullable("boolean", "False switches the extra off."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "extra_id": {"type": "string"},
            "service_id": {"type": "string"},
            "name": {"type": "string"},
            "kind": {"type": "string"},
            "amount_minor": {"type": "integer"},
            "currency": {"type": "string"},
            "active": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_save_extra,
    undo="command:booking.extra.save@1",
    preview=_preview_extra,
    version_field="expected_version",
)


# --- booking.quote.read@1 ------------------------------------------------------------

_QUOTE_FIELDS = (
    "service_id",
    "starts_at",
    "start_date",
    "end_date",
    "resource_id",
    "group_id",
    "participants",
    "extras",
    "price_only",
)


def _read_quote(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    given = _given(arguments, _QUOTE_FIELDS)
    for name in ("participants", "extras"):
        if name in given:
            given[name] = [
                {key: value for key, value in line.items() if value is not None}
                for line in given[name]
            ]
    serializer = BookingQuoteInputSerializer(data=given)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("locale", None)
    return cast(dict[str, Any], _plain(quote_offer(**data).snapshot()))


QUOTE_READ = CommandSpec(
    name="booking.quote.read",
    version=1,
    module="shared.booking",
    title={"pl": "Wyceń rezerwację", "en": "Quote a booking"},
    summary={
        "pl": "Ile kosztowałaby rezerwacja — bez zapisywania czegokolwiek.",
        "en": "What a booking would cost — nothing is written.",
    },
    model_description=(
        "Works out what a booking would cost and writes nothing: a visit at `starts_at` "
        "(ISO date and time), or a stay from `start_date` to `end_date` (YYYY-MM-DD) in "
        "the unit or the group named, or the least busy free unit when neither is. "
        "Returns the lines with which price applied (price_rule_id), the net, tax and "
        "gross totals in minor units, and the security deposit beside them — never in "
        "them. `price_only` true answers what the price list says for that time whether "
        "or not it could be booked (the service still switched off, the unit taken, a "
        "season's rule broken) — use it to check a price just saved. A time the price "
        "list has no price for is `price_missing`; a service with no price list at all "
        "answers no lines. This is the only place a price is worked out: never add "
        "amounts up yourself."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_QUOTE_FIELDS),
        "properties": {
            "service_id": {"type": "string", "description": "The service to price."},
            "starts_at": _nullable("string", "A visit's start, ISO date and time with offset."),
            "start_date": _nullable("string", "A stay's first day, YYYY-MM-DD."),
            "end_date": _nullable("string", "A stay's last day (the day of leaving), YYYY-MM-DD."),
            "resource_id": _nullable("string", "The unit of the stay."),
            "group_id": _nullable("string", "The group of units of the stay."),
            "participants": {
                "type": ["array", "null"],
                "description": "Who comes; null — one standard person.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category_id", "count"],
                    "properties": {
                        "category_id": _nullable(
                            "string", "A participant category; null — standard people."
                        ),
                        "count": {"type": "integer", "description": "How many of them."},
                    },
                },
            },
            "extras": {
                "type": ["array", "null"],
                "description": "The optional extras picked; mandatory ones are always charged.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["extra_id", "quantity"],
                    "properties": {
                        "extra_id": {"type": "string", "description": "The extra."},
                        "quantity": _nullable("integer", "How many; null — one."),
                    },
                },
            },
            "price_only": _nullable("boolean", "True: what the price list says, bookable or not."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "currency": {"type": "string"},
            "amounts": {"type": "string"},
            "lines": {"type": "array"},
            "participants": {"type": "array"},
            "extras": {"type": "array"},
            "security_deposit_minor": {"type": "integer"},
            "payment_policy": {"type": "string"},
            "net_minor": {"type": "integer"},
            "vat_minor": {"type": "integer"},
            "gross_minor": {"type": "integer"},
            "digest": {"type": "string"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_quote,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- booking.offer.discard@1 ---------------------------------------------------------


def _preview_discard(arguments: Mapping[str, Any], call: Any) -> Preview:
    service_id = _id(arguments, "service_id")
    service = _service(call.context.organization_id, service_id)
    own = Q(organization_id=call.context.organization_id, service=service)
    prices = PriceRule.all_objects.filter(own).count()
    extras = Extra.all_objects.filter(own).count()
    seasons = BookingRule.all_objects.filter(own).count()
    discard_draft(service_id=service_id, preview=True)
    return Preview(
        effects=(
            _effect(
                "deleted",
                "booking.service",
                str(service.id),
                f"Usunięcie wersji roboczej usługi „{service.name}” razem z jej cenami "
                f"({prices}), dopłatami i kaucjami ({extras}) oraz zasadami sezonów "
                f"({seasons}). Jednostki i ich grupa zostają.",
                f"Removal of the draft service “{service.name}” with its prices ({prices}), "
                f"extras and deposits ({extras}) and season rules ({seasons}). The units "
                "and their group stay.",
            ),
        ),
        observed_versions={f"booking.service:{service.id}": service.version},
    )


def _discard(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    saved = discard_draft(
        service_id=_id(arguments, "service_id"), idempotency_key=call.idempotency_key
    )
    return {"service_id": str(saved.value), "discarded": True}


OFFER_DISCARD = CommandSpec(
    name="booking.offer.discard",
    version=1,
    module="shared.booking",
    title={"pl": "Usuń wersję roboczą usługi", "en": "Remove a draft service"},
    summary={
        "pl": "Usuwa usługę, której nikt jeszcze nie włączył, z jej cenami i dopłatami.",
        "en": "Removes a service nobody has switched on yet, with its prices and extras.",
    },
    model_description=(
        "Removes a service that was never switched on and has no bookings — a draft — "
        "together with its links, its own prices, extras, deposits and season rules. It "
        "is the undo of booking.preset.apply and booking.offer.create. A service that "
        "was ever switched on is refused with `not_a_draft` on service_id and one with "
        "bookings with `service_has_bookings`: such a service is only switched off, "
        "which the person does in the panel. Units and their group are not removed. "
        "This cannot be undone; use it only when the person asks to remove the draft."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["service_id"],
        "properties": {
            "service_id": {"type": "string", "description": "The draft service to remove."}
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {"service_id": {"type": "string"}, "discarded": {"type": "boolean"}},
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    # The draft's prices are the owner's typed numbers: gone, they are typed again.
    risk="irreversible",
    run=_discard,
    undo="none:a removed draft is set up again from its preset",
    preview=_preview_discard,
    no_version_reason="A draft is removed whole; the consent still binds the version it saw.",
)

PRICING_COMMANDS = (
    OFFER_UNITS_SET,
    PRICES_READ,
    PRICE_SAVE,
    CATEGORY_SAVE,
    EXTRA_SAVE,
    QUOTE_READ,
    OFFER_DISCARD,
)
