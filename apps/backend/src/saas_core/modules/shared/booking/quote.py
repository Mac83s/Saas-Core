"""One quote, frozen in the booking (ADR-072 §7, phase 3b).

`quote_stay` and `quote_visit` work a booking's price out from the price list
(`prices.py`) and write nothing: the panel, the public form and the assistant
show what they return, and a booking works it out again inside its transaction
and keeps it (`Appointment.quote`). A caller that shows a price sends the
digest of what it showed; another price by then is 409 `quote_changed` with the
new quote.

Amounts are whole minor units. The tax is worked out on each line and rounded
to a minor unit, halves up, because the lines go one to one into an order and
an invoice. A price list read gross takes the tax out of the amount; read net,
adds it on top (`pricing.entry.amounts`). The total a customer sees is gross.

Who pays what, under one price:
- the price's amount covers `included_people` — the people who count towards
  capacity and would pay the most, so a guest never pays more for the order
  they were listed in; empty covers everybody;
- each further person adds `extra_person_amount_minor`, a participant of a
  category its own amount when the price has one;
- a category that does not count towards capacity (a dog) is never one of the
  included and pays its amount, or nothing when the price names none;
- a price per person charges each person: its amount, or the category's.

A stay is priced by the rule of each night or day; the rule of the arrival day
decides the basis, whether further people pay per time unit or once, and the
discount for length — as the arrival day's season decides the booking rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.db.models import Q
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.organizations.canonical import canonical_json_hash
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .availability import _zone
from .item_translations import localized_texts, source_locale, translatable
from .models import (
    Extra,
    ExtraBasis,
    ExtraKind,
    ParticipantCategory,
    PriceBasis,
    PriceRule,
    Resource,
    Service,
    TimeModel,
    VatCode,
)
from .periods import plan_stay, stay_quote
from .prices import GROSS, NET, amounts_are_gross, price_for
from .services import BOOKING_ENABLED, BOOKING_MANAGE

PRICE = "price"
EXTRA_PERSON = "extra_person"
CATEGORY = "category"
DISCOUNT = "discount"
EXTRA = "extra"

#: The percent each tax code adds; exempt and outside VAT add nothing.
_RATES = {
    VatCode.STANDARD: 23,
    VatCode.REDUCED: 8,
    VatCode.SUPER_REDUCED: 5,
    VatCode.ZERO: 0,
    VatCode.EXEMPT: 0,
    VatCode.OUTSIDE: 0,
}
#: The lines the price list has no name for; another language reads English.
_WORDS = {
    EXTRA_PERSON: {"pl": "Dodatkowa osoba", "en": "Extra person"},
    DISCOUNT: {"pl": "Rabat za długość pobytu", "en": "Discount for the length of stay"},
}


class QuoteRefused(ValidationError):
    """What cannot be priced as asked — a 400 with the field and a code."""


class QuoteChanged(APIException):
    """The price is no longer the one the caller showed (ADR-072 §7)."""

    status_code = 409
    default_code = "quote_changed"
    default_detail = "Cena zmieniła się od chwili, gdy ją pokazaliśmy. Sprawdź nową."
    #: The detail below is data, not messages: the handler reads the code here.
    problem_code = "quote_changed"

    def __init__(self, quote: Quote) -> None:
        super().__init__()
        # Set after: DRF turns every leaf of a detail into text, and a quote's
        # amounts are numbers.
        body: Any = {"message": self.default_detail, "quote": quote.snapshot()}
        self.detail = body
        self.quote = quote


@dataclass(frozen=True, slots=True)
class QuoteLine:
    kind: str
    #: In the offer's own language, and in the customer's.
    name: str
    customer_name: str
    #: How many times the amount is charged: nights, people, people × nights.
    quantity: int
    #: As the price list has it — gross or net by the quote's `amounts`.
    unit_amount_minor: int
    net_minor: int
    vat_minor: int
    gross_minor: int
    vat_code: str
    #: Nights or days the line covers; empty for a line charged once.
    time_units: int | None = None
    people: int | None = None
    category_id: UUID | None = None
    price_rule_id: UUID | None = None
    #: A discount's percent.
    percent: int | None = None
    extra_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    currency: str
    #: How `unit_amount_minor` is read: `gross` or `net`.
    amounts: str
    lines: tuple[QuoteLine, ...]
    #: Who comes: `[{"category_id", "count"}]`, a standard person without one.
    participants: tuple[dict[str, Any], ...]
    #: The optional extras picked: `[{"extra_id", "quantity"}]`.
    extras: tuple[dict[str, Any], ...]
    #: Held and given back, so no part of the totals (ADR-072 §6).
    security_deposit_minor: int
    net_minor: int
    vat_minor: int
    gross_minor: int
    #: Of the price, not of its words: the same in every language.
    digest: str

    @property
    def priced(self) -> bool:
        """The offer has a price list; without one a booking is made as before."""
        return bool(self.lines) or bool(self.security_deposit_minor)

    def snapshot(self) -> dict[str, Any]:
        """The quote as a booking keeps it and an answer gives it."""
        return {
            "currency": self.currency,
            "amounts": self.amounts,
            "lines": [_line_json(line) for line in self.lines],
            "participants": list(self.participants),
            "extras": list(self.extras),
            "security_deposit_minor": self.security_deposit_minor,
            "net_minor": self.net_minor,
            "vat_minor": self.vat_minor,
            "gross_minor": self.gross_minor,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class _Party:
    category: ParticipantCategory | None
    count: int

    @property
    def counts(self) -> bool:
        return self.category is None or self.category.counts_towards_capacity


@dataclass(frozen=True, slots=True)
class _Names:
    """The words of a quote in the offer's language and the customer's."""

    source: str
    customer: str
    service: tuple[str, str]
    categories: dict[UUID, str]
    extras: dict[UUID, str]

    def word(self, kind: str) -> tuple[str, str]:
        words = _WORDS[kind]
        return words.get(self.source, words["en"]), words.get(self.customer, words["en"])

    def category(self, item: ParticipantCategory) -> tuple[str, str]:
        return item.name, self.categories.get(item.id, item.name)

    def extra(self, item: Extra) -> tuple[str, str]:
        return item.name, self.extras.get(item.id, item.name)


def quote_stay(
    *,
    service: Service,
    unit: Resource,
    days: Sequence[date],
    participants: Sequence[Mapping[str, Any]] | None = None,
    extras: Sequence[Mapping[str, Any]] | None = None,
    locale: str | None = None,
    kept: bool = False,
) -> Quote:
    """What a stay on `days` in `unit` costs (the nights or days it takes, from
    `Stay.days`). Refuses more people than the unit takes and a day the price
    list has no price for. `extras` — the optional ones picked
    (`[{"extra_id", "quantity"}]`); `kept` — a booking made earlier is priced
    again, so an extra switched off since stays on it."""
    organization = Organization.objects.get(pk=service.organization_id)
    party = _party(organization, participants)
    people = sum(group.count for group in party if group.counts)
    if unit.capacity is not None and people > unit.capacity:
        raise _refused(
            "participants",
            f"Ta jednostka przyjmuje najwyżej {unit.capacity} os.",
            "unit_capacity_exceeded",
        )
    picked = _picked(organization, service, extras, kept)
    names = _names(organization, service, party, picked, locale)
    lines = _stay_lines(organization, service, unit, days, party, names)
    lines += _extra_lines(picked, people, names, len(days))
    return _total(organization, party, picked, lines)


def _stay_lines(
    organization: Organization,
    service: Service,
    unit: Resource,
    days: Sequence[date],
    party: Sequence[_Party],
    names: _Names,
) -> list[QuoteLine]:
    """The stay's own price, without extras; nothing without a price list."""
    scope = Q(service=service) | Q(resource=unit)
    if unit.group_id is not None:
        scope |= Q(group_id=unit.group_id)
    rules = list(PriceRule.all_objects.filter(scope, organization=organization, active=True))
    if not rules:
        return []

    def on(day: date, among: Sequence[PriceRule]) -> PriceRule:
        rule = price_for(
            among, day=day, service_id=service.id, group_id=unit.group_id, resource_id=unit.id
        )
        if rule is None:
            raise _refused(
                "start_date", f"Cennik nie ma ceny na {day.isoformat()}.", "price_missing"
            )
        return rule

    first = on(days[0], rules)
    if first.basis != PriceBasis.PER_TIME_UNIT:
        return _once(first, party, names)

    timed = [rule for rule in rules if rule.basis == PriceBasis.PER_TIME_UNIT]
    segments: list[tuple[PriceRule, int]] = []
    for day in days:
        rule = on(day, timed)
        if segments and segments[-1][0].id == rule.id:
            segments[-1] = (rule, segments[-1][1] + 1)
        else:
            segments.append((rule, 1))
    lines: list[QuoteLine] = []
    for index, (rule, units) in enumerate(segments):
        lines.append(_line(PRICE, names.service, units, rule.amount_minor, rule, time_units=units))
        if first.extra_person_per_time_unit:
            lines += _people(rule, party, names, units)
        elif index == 0:
            lines += _people(rule, party, names, None)
    # What is charged per time unit gets cheaper with the length of the stay.
    percent = max(
        (line["percent"] for line in first.length_discounts if line["min_length"] <= len(days)),
        default=0,
    )
    if percent:
        by_code: dict[str, int] = {}
        for line in lines:
            if line.time_units is not None:
                by_code[line.vat_code] = (
                    by_code.get(line.vat_code, 0) + line.quantity * line.unit_amount_minor
                )
        source, customer = names.word(DISCOUNT)
        for code, amount in sorted(by_code.items()):
            lines.append(
                QuoteLine(
                    kind=DISCOUNT,
                    name=f"{source} ({percent}%)",
                    customer_name=f"{customer} ({percent}%)",
                    quantity=1,
                    unit_amount_minor=-_half_up(amount * percent, 100),
                    net_minor=0,
                    vat_minor=0,
                    gross_minor=0,
                    vat_code=code,
                    price_rule_id=first.id,
                    percent=percent,
                )
            )
    return lines


def quote_visit(
    *,
    service: Service,
    starts_at: datetime,
    participants: Sequence[Mapping[str, Any]] | None = None,
    extras: Sequence[Mapping[str, Any]] | None = None,
    locale: str | None = None,
    kept: bool = False,
) -> Quote:
    """What a visit that starts at `starts_at` costs: the price of that local
    day and hour, and the extras."""
    organization = Organization.objects.get(pk=service.organization_id)
    party = _party(organization, participants)
    picked = _picked(organization, service, extras, kept)
    names = _names(organization, service, party, picked, locale)
    rules = list(
        PriceRule.all_objects.filter(organization=organization, service=service, active=True)
    )
    lines: list[QuoteLine] = []
    if rules:
        local = starts_at.astimezone(_zone())
        rule = price_for(rules, day=local.date(), at=local.time(), service_id=service.id)
        if rule is None:
            raise _refused("starts_at", "Cennik nie ma ceny na ten termin.", "price_missing")
        lines = _once(rule, party, names)
    lines += _extra_lines(picked, sum(group.count for group in party if group.counts), names, None)
    return _total(organization, party, picked, lines)


def quote_offer(
    *,
    service_id: UUID,
    starts_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    resource_id: UUID | None = None,
    group_id: UUID | None = None,
    participants: Sequence[Mapping[str, Any]] | None = None,
    extras: Sequence[Mapping[str, Any]] | None = None,
    locale: str | None = None,
) -> Quote:
    """What a booking would cost, for whoever books in the panel: a visit at
    `starts_at`, or a stay from `start_date` to `end_date` on the unit a
    booking would take. Nothing is written."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    if starts_at is not None:
        service = Service.all_objects.filter(
            organization_id=context.organization_id,
            pk=service_id,
            active=True,
            time_model=TimeModel.SLOT,
        ).first()
        if service is None:
            raise NotFound("Nie ma takiej usługi.")
        return quote_visit(
            service=service,
            starts_at=starts_at,
            participants=participants,
            extras=extras,
            locale=locale,
        )
    if start_date is None or end_date is None:
        raise _refused("starts_at", "Podaj termin wizyty albo daty pobytu.", "required")
    plan = plan_stay(
        service_id=service_id,
        start_date=start_date,
        end_date=end_date,
        resource_id=resource_id,
        group_id=group_id,
    )
    return stay_quote(plan, participants=participants, extras=extras, locale=locale)


def assert_shown(quote: Quote, digest: str) -> None:
    """The price is still the one the caller showed, or 409 `quote_changed`."""
    if digest and digest != quote.digest:
        raise QuoteChanged(quote)


def _once(rule: PriceRule, party: Sequence[_Party], names: _Names) -> list[QuoteLine]:
    """A price charged once: per booking, per group or per person."""
    if rule.basis != PriceBasis.PER_PERSON:
        return [
            _line(PRICE, names.service, 1, rule.amount_minor, rule),
            *_people(rule, party, names, None),
        ]
    own = _own_amounts(rule)
    lines = []
    standard = sum(
        group.count
        for group in party
        if group.category is None or (group.category.id not in own and group.counts)
    )
    if standard:
        lines.append(
            _line(PRICE, names.service, standard, rule.amount_minor, rule, people=standard)
        )
    for group in party:
        if group.category is not None and group.category.id in own:
            lines.append(
                _line(
                    CATEGORY,
                    names.category(group.category),
                    group.count,
                    own[group.category.id],
                    rule,
                    people=group.count,
                    category_id=group.category.id,
                )
            )
    return lines


def _people(
    rule: PriceRule, party: Sequence[_Party], names: _Names, units: int | None
) -> list[QuoteLine]:
    """What the people add to the rule's amount — per `units` time units when
    given, otherwise once."""
    own = _own_amounts(rule)
    extra = rule.extra_person_amount_minor or 0
    # Who counts, with what each would pay when not included, dearest first.
    payers = sorted(
        (
            (
                own.get(group.category.id, extra) if group.category is not None else extra,
                group,
            )
            for group in party
            if group.counts
        ),
        key=lambda payer: -payer[0],
    )
    charged: list[tuple[int, _Party, int]] = []
    left = rule.included_people
    for amount, group in payers:
        if left is None:
            continue
        paying = max(0, group.count - left)
        left = max(0, left - group.count)
        if paying and amount:
            charged.append((amount, group, paying))
    for group in party:
        if not group.counts and group.category is not None and own.get(group.category.id):
            charged.append((own[group.category.id], group, group.count))
    times = units or 1
    return [
        _line(
            CATEGORY if group.category is not None else EXTRA_PERSON,
            names.category(group.category)
            if group.category is not None
            else names.word(EXTRA_PERSON),
            count * times,
            amount,
            rule,
            time_units=units,
            people=count,
            category_id=group.category.id if group.category is not None else None,
        )
        for amount, group, count in charged
    ]


@dataclass(frozen=True, slots=True)
class _Picked:
    """The offer's extras on this booking."""

    #: What is charged, with how many: the mandatory ones and the picked.
    charged: tuple[tuple[Extra, int], ...]
    #: The optional ones as picked: `[{"extra_id", "quantity"}]`.
    chosen: tuple[dict[str, Any], ...]
    deposit: int


def _picked(
    organization: Organization,
    service: Service,
    extras: Sequence[Mapping[str, Any]] | None,
    kept: bool,
) -> _Picked:
    wanted: dict[UUID, int] = {}
    for line in extras or ():
        key = UUID(str(line["extra_id"]))
        wanted[key] = wanted.get(key, 0) + int(line.get("quantity") or 1)
    offered = list(Extra.all_objects.filter(organization=organization, service=service))
    if set(wanted) - {extra.id for extra in offered}:
        raise _refused("extras", "Ta usługa nie ma takiej dopłaty.", "invalid")
    charged: list[tuple[Extra, int]] = []
    chosen: list[dict[str, Any]] = []
    deposit = 0
    for extra in offered:
        if extra.kind == ExtraKind.SECURITY_DEPOSIT:
            deposit += extra.amount_minor if extra.active else 0
        elif extra.mandatory:
            if extra.active:
                charged.append((extra, 1))
        elif quantity := wanted.get(extra.id, 0):
            # A booking priced again keeps an extra the company has since
            # switched off; a new one cannot take it.
            if not extra.active and not kept:
                raise _refused("extras", f"„{extra.name}” nie jest już w ofercie.", "invalid")
            if quantity > extra.max_quantity:
                raise _refused(
                    "extras",
                    f"„{extra.name}” można wziąć najwyżej {extra.max_quantity} razy.",
                    "extra_quantity_exceeded",
                )
            charged.append((extra, quantity))
            chosen.append({"extra_id": str(extra.id), "quantity": quantity})
    return _Picked(tuple(charged), tuple(chosen), deposit)


def _extra_lines(picked: _Picked, people: int, names: _Names, units: int | None) -> list[QuoteLine]:
    """The extras' lines: once, per time unit, per person, or per both. A
    discount for length never reaches them."""
    lines = []
    for extra, quantity in picked.charged:
        timed = extra.basis in (ExtraBasis.PER_TIME_UNIT, ExtraBasis.PER_PERSON_PER_TIME_UNIT)
        personal = extra.basis in (ExtraBasis.PER_PERSON, ExtraBasis.PER_PERSON_PER_TIME_UNIT)
        name, customer_name = names.extra(extra)
        lines.append(
            QuoteLine(
                kind=EXTRA,
                name=name,
                customer_name=customer_name,
                quantity=quantity * (units or 1 if timed else 1) * (people if personal else 1),
                unit_amount_minor=extra.amount_minor,
                net_minor=0,
                vat_minor=0,
                gross_minor=0,
                vat_code=extra.vat_code,
                time_units=units if timed else None,
                people=people if personal else None,
                extra_id=extra.id,
            )
        )
    return lines


def _own_amounts(rule: PriceRule) -> dict[UUID, int]:
    return {UUID(line["category_id"]): int(line["amount_minor"]) for line in rule.category_prices}


def _line(
    kind: str,
    name: tuple[str, str],
    quantity: int,
    amount: int,
    rule: PriceRule,
    **detail: Any,
) -> QuoteLine:
    return QuoteLine(
        kind=kind,
        name=name[0],
        customer_name=name[1],
        quantity=quantity,
        unit_amount_minor=amount,
        net_minor=0,
        vat_minor=0,
        gross_minor=0,
        vat_code=rule.vat_code,
        price_rule_id=rule.id,
        **detail,
    )


def _total(
    organization: Organization, party: Sequence[_Party], picked: _Picked, lines: list[QuoteLine]
) -> Quote:
    gross = amounts_are_gross()
    taxed = [_taxed(line, gross) for line in lines]
    participants = tuple(
        {
            "category_id": str(group.category.id) if group.category is not None else None,
            "count": group.count,
        }
        for group in party
    )
    sums = {
        "net_minor": sum(line.net_minor for line in taxed),
        "vat_minor": sum(line.vat_minor for line in taxed),
        "gross_minor": sum(line.gross_minor for line in taxed),
    }
    essence = {
        "currency": organization.currency,
        "amounts": GROSS if gross else NET,
        "lines": [
            {key: value for key, value in _line_json(line).items() if "name" not in key}
            for line in taxed
        ],
        "participants": list(participants),
        "extras": list(picked.chosen),
        "security_deposit_minor": picked.deposit,
        **sums,
    }
    return Quote(
        currency=organization.currency,
        amounts=GROSS if gross else NET,
        lines=tuple(taxed),
        participants=participants,
        extras=picked.chosen,
        security_deposit_minor=picked.deposit,
        digest=canonical_json_hash(essence),
        **sums,
    )


def _taxed(line: QuoteLine, gross: bool) -> QuoteLine:
    amount = line.quantity * line.unit_amount_minor
    sign, value = (-1, -amount) if amount < 0 else (1, amount)
    rate = _RATES[VatCode(line.vat_code)]
    if gross:
        net = _half_up(value * 100, 100 + rate)
        vat, total = value - net, value
    else:
        vat = _half_up(value * rate, 100)
        net, total = value, value + vat
    return replace(line, net_minor=sign * net, vat_minor=sign * vat, gross_minor=sign * total)


def _half_up(numerator: int, denominator: int) -> int:
    """`numerator / denominator` to a whole minor unit, halves up."""
    return (2 * numerator + denominator) // (2 * denominator)


def _line_json(line: QuoteLine) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, UUID) else value for key, value in asdict(line).items()
    }


def _party(
    organization: Organization, participants: Sequence[Mapping[str, Any]] | None
) -> list[_Party]:
    """Who comes, each category once; nobody named is one standard person."""
    counts: dict[UUID | None, int] = {}
    for line in participants or [{"category_id": None, "count": 1}]:
        raw = line.get("category_id")
        key = UUID(str(raw)) if raw else None
        counts[key] = counts.get(key, 0) + int(line["count"])
    wanted = [key for key in counts if key is not None]
    found = {
        item.id: item
        for item in ParticipantCategory.all_objects.filter(
            organization=organization, pk__in=wanted, active=True
        )
    }
    if len(found) != len(wanted):
        raise _refused("participants", "Nie ma takiej kategorii uczestników.", "invalid")
    party = sorted(
        (
            _Party(found[key] if key is not None else None, count)
            for key, count in counts.items()
            if count > 0
        ),
        key=lambda group: (
            group.category is not None,
            group.category.name if group.category else "",
        ),
    )
    if not any(group.counts for group in party):
        raise _refused("participants", "Podaj, ile osób przyjdzie.", "participants_required")
    return party


def _names(
    organization: Organization,
    service: Service,
    party: Sequence[_Party],
    picked: _Picked,
    locale: str | None,
) -> _Names:
    source = source_locale(organization)
    customer = locale or source
    categories = [group.category for group in party if group.category is not None]
    extras = [extra for extra, _quantity in picked.charged]
    translated = customer != source
    own = (
        localized_texts(translatable("service"), [service], customer).get(service.id, {})
        if translated
        else {}
    )
    return _Names(
        source=source,
        customer=customer,
        service=(service.name, own.get("name", service.name)),
        categories={
            item_id: texts["name"]
            for item_id, texts in (
                localized_texts(translatable("participant_category"), categories, customer)
                if translated and categories
                else {}
            ).items()
            if "name" in texts
        },
        extras={
            item_id: texts["name"]
            for item_id, texts in (
                localized_texts(translatable("extra"), extras, customer)
                if translated and extras
                else {}
            ).items()
            if "name" in texts
        },
    )


def _refused(field: str, message: str, code: str) -> QuoteRefused:
    return QuoteRefused({field: [ErrorDetail(message, code=code)]})
