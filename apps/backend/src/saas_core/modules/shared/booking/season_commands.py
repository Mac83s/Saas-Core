"""The assistant's commands for an offer's seasons (ADR-076 §1; ADR-072 §5 and §11).

Thin adapters over the setup services the panel's „Sezony” calls: a read of
every season with its id and version, and the save of one — its dates and the
rules for bookings in them (the shortest and the longest stay, the days a stay
may begin and end on, how far ahead, closed).

A season follows the price list's rule for the click (`pricing_commands`): one
of an offer that is still switched off changes nothing anybody can book, so it
is a draft; the same save for an offer that is switched on — or for a group or
a unit such an offer books — changes what customers can book from that moment,
and the preview raises it to `apply`. The words the person agrees to are
written here from the previewed save: whose season, its dates and every rule
it carries.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.api import CommandSpec, Preview

from .command_declarations import _effect, _given, _id, _nullable
from .models import BookingRule, RangeUnit
from .pricing_commands import _DAYS, _PUBLIC, _bounded, _live_scope, _plain, _raised, _scope
from .rules import list_rules, save_rule
from .serializers import BookingRuleInputSerializer, BookingRuleUpdateSerializer
from .services import BOOKING_ENABLED, BOOKING_MANAGE
from .views import _rule_payload

_SEASON_FIELDS = (
    "service_id",
    "group_id",
    "resource_id",
    "name",
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
_WEEKDAYS = {
    "type": ["array", "null"],
    "items": {"type": "integer", "minimum": 0, "maximum": 6},
}
#: A length in the offer's own time unit, as the panel's „Sezony” words it:
#: Polish (one, more), English (one, more).
_LENGTH: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    RangeUnit.NIGHT.value: (("nocy", "nocy"), ("night", "nights")),
    RangeUnit.DAY.value: (("dnia", "dni"), ("day", "days")),
    RangeUnit.HOUR.value: (("godziny", "godzin"), ("hour", "hours")),
    "": (("jednostki czasu", "jednostek czasu"), ("time unit", "time units")),
}


# --- booking.seasons.read@1 ----------------------------------------------------------


def _read_seasons(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return cast(
        dict[str, Any], _plain({"seasons": [_rule_payload(item) for item in list_rules()]})
    )


SEASONS_READ = CommandSpec(
    name="booking.seasons.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj sezony", "en": "Read the seasons"},
    summary={
        "pl": "Sezony usług, grup i jednostek z zasadami rezerwacji, z wersjami do zmian.",
        "en": "The seasons of services, groups and units with their booking rules and versions.",
    },
    model_description=(
        "Returns every season of the company — of a service, a group of units or a unit — "
        "switched-off ones included, each with its id, its version, its first and last local "
        "day and its rules: the shortest and the longest booking in the offer's time units "
        "(nights, days), whole multiples, the weekdays a booking may begin and end on "
        "(0 is Monday; an empty list is any day), how long before its start and how far "
        "ahead it can be made, closed, the break after. Use it before changing a season, to "
        "know its id. For a day the unit's season wins over its group's, and that over the "
        "service's. A season's price is not here: booking.prices.read has the price list."
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
        "properties": {"seasons": {"type": "array"}},
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_seasons,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- booking.season.save@1 -----------------------------------------------------------


def _season_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _SEASON_FIELDS)
    if version is None:
        serializer: Any = BookingRuleInputSerializer(data=given)
    else:
        serializer = BookingRuleUpdateSerializer(data={**given, "expected_version": version})
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _current_season(arguments: Mapping[str, Any], call: Any) -> BookingRule | None:
    if arguments["season_id"] is None:
        return None
    found = BookingRule.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "season_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiego sezonu.")
    return found


def _length(count: int, unit: str, at: int) -> str:
    words = _LENGTH.get(unit, _LENGTH[""])[at]
    return f"{count} {words[0] if count == 1 else words[1]}"


def _weekdays(days: list[int], at: int) -> str:
    return ", ".join(_DAYS[at][day] for day in days)


def _season_words(rule: BookingRule, unit: str, at: int) -> str:
    """The season as the person agrees to it: its dates, then every rule it
    carries, in the words of the panel's „Sezony”."""
    dates = f"{rule.starts_on.isoformat()} – {rule.ends_on.isoformat()}"
    if rule.name:
        dates = f"„{rule.name}” {dates}" if at == 0 else f"“{rule.name}” {dates}"
    rules: list[str] = []
    if rule.closed:
        rules.append(("zamknięte — bez rezerwacji", "closed — no bookings")[at])
    if rule.min_length is not None:
        rules.append(f"{('od', 'at least')[at]} {_length(rule.min_length, unit, at)}")
    if rule.max_length is not None:
        rules.append(f"{('do', 'at most')[at]} {_length(rule.max_length, unit, at)}")
    if rule.length_multiple is not None:
        rules.append(
            (
                f"tylko wielokrotności {rule.length_multiple}",
                f"multiples of {rule.length_multiple} only",
            )[at]
        )
    if rule.start_weekdays:
        rules.append(f"{('przyjazd', 'arrival')[at]}: {_weekdays(rule.start_weekdays, at)}")
    if rule.end_weekdays:
        rules.append(f"{('wyjazd', 'departure')[at]}: {_weekdays(rule.end_weekdays, at)}")
    if rule.notice_hours is not None:
        rules.append(
            (
                f"najpóźniej {rule.notice_hours} h przed przyjazdem",
                f"at least {rule.notice_hours} h before arrival",
            )[at]
        )
    if rule.window_days is not None:
        rules.append(
            (
                f"najwcześniej {rule.window_days} dni przed",
                f"at most {rule.window_days} days ahead",
            )[at]
        )
    if rule.buffer_after_minutes is not None:
        rules.append(
            (
                f"przerwa po pobycie: {rule.buffer_after_minutes} min",
                f"break after a stay: {rule.buffer_after_minutes} min",
            )[at]
        )
    if not rules:
        rules.append(("bez dodatkowych zasad", "no extra rules")[at])
    if not rule.active:
        rules.append(("wyłączony", "switched off")[at])
    return f"{dates}: {', '.join(rules)}"


def _preview_season(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = _current_season(arguments, call)
    version = current.version if current is not None else None
    saved = save_rule(
        rule_id=current.id if current is not None else None,
        data=_season_data(arguments, version),
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
        pl = f"Nowy sezon {whose[0]} — {_season_words(rule, unit, 0)}"
        en = f"New season {whose[1]} — {_season_words(rule, unit, 1)}"
    else:
        pl = f"Sezon {whose[0]} po zmianie — {_season_words(rule, unit, 0)}"
        en = f"The season {whose[1]} after the change — {_season_words(rule, unit, 1)}"
    if live:
        pl += " — obowiązuje od razu, dla nowych rezerwacji"
        en += " — in force at once, for new bookings"
    return Preview(
        effects=(
            _effect(
                "created" if current is None else "updated",
                "booking.season",
                str(current.id) if current is not None else "",
                pl,
                en,
            ),
        ),
        observed_versions=(
            {f"booking.season:{current.id}": current.version} if current is not None else {}
        ),
        escalate_to=_raised(live),
    )


def _save_season(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    season_id = _id(arguments, "season_id") if arguments["season_id"] is not None else None
    version = (
        call.preview.observed_versions[f"booking.season:{season_id}"]
        if season_id is not None
        else None
    )
    saved = save_rule(
        rule_id=season_id,
        data=_season_data(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    rule = saved.value
    return {
        "season_id": str(rule.id),
        "starts_on": rule.starts_on.isoformat(),
        "ends_on": rule.ends_on.isoformat(),
        "active": rule.active,
        "version": rule.version,
    }


SEASON_SAVE = CommandSpec(
    name="booking.season.save",
    version=1,
    module="shared.booking",
    title={"pl": "Zapisz sezon", "en": "Save a season"},
    summary={
        "pl": "Sezon usługi, grupy jednostek albo jednostki: daty i zasady rezerwacji.",
        "en": "A season of a service, a group of units or a unit: its dates and booking rules.",
    },
    model_description=(
        "Adds a season (season_id null) or changes one (its season_id from "
        "booking.seasons.read). A season belongs to exactly one of a service, a group of "
        "units or a unit, and holds the rules for bookings between starts_on and ends_on, "
        "both days included: min_length and max_length in the offer's time units (nights "
        "of a stay, days of a rental), length_multiple (7 — whole weeks only), "
        "start_weekdays and end_weekdays — the days a booking may begin and end on, 0 is "
        "Monday — notice_hours, window_days, closed (no bookings in these dates at all) "
        "and the break after a booking. The dates and every rule are the person's own "
        "words: when the dates were not said, ask, do not call; give a year only as the "
        "person meant it. Pass null for every field that stays as it is (a new season "
        "takes no rule it was not given); a list given replaces the list; a rule cannot "
        "be cleared here — the person clears it in the panel, in „Sezony i zasady”. A season "
        "prices nothing: a season's price is booking.price.save with the same dates. A "
        "season of a switched-on service is in force at once for new bookings; bookings "
        "already made stay."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["season_id", *_SEASON_FIELDS],
        "properties": {
            "season_id": _nullable("string", "The season to change; null adds a new one."),
            "service_id": _nullable("string", "The service it is a season of."),
            "group_id": _nullable("string", "The group of units it is a season of."),
            "resource_id": _nullable("string", "The unit it is a season of."),
            "name": _nullable("string", "A name for the company: „Sezon wysoki”, „Majówka”."),
            "starts_on": _nullable("string", "First local day of the season, YYYY-MM-DD."),
            "ends_on": _nullable("string", "Last local day of the season, included."),
            "min_length": _bounded(
                "integer",
                "The shortest booking, in the offer's time units (nights, days).",
                minimum=1,
                maximum=1000,
            ),
            "max_length": _bounded(
                "integer", "The longest booking, in the same units.", minimum=1, maximum=1000
            ),
            "length_multiple": _bounded(
                "integer",
                "Only multiples of this length; 7 is whole weeks.",
                minimum=1,
                maximum=365,
            ),
            "start_weekdays": {
                **_WEEKDAYS,
                "description": "The weekdays a booking may begin on, 0 is Monday; null keeps "
                "them, and a new season then allows every day.",
            },
            "end_weekdays": {
                **_WEEKDAYS,
                "description": "The weekdays a booking may end on, 0 is Monday.",
            },
            "notice_hours": _bounded(
                "integer",
                "At least this many hours before its start a booking can be made.",
                minimum=0,
                maximum=24 * 365,
            ),
            "window_days": _bounded(
                "integer",
                "At most this many days ahead a booking can be made.",
                minimum=1,
                maximum=730,
            ),
            "closed": _nullable("boolean", "True takes no bookings in these dates at all."),
            "buffer_after_minutes": _bounded(
                "integer",
                "The break after a booking (cleaning), in minutes.",
                minimum=0,
                maximum=60 * 24 * 7,
            ),
            "active": _nullable("boolean", "False switches the season off."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "season_id": {"type": "string"},
            "starts_on": {"type": "string"},
            "ends_on": {"type": "string"},
            "active": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_save_season,
    undo="command:booking.season.save@1",
    preview=_preview_season,
    version_field="expected_version",
)

SEASON_COMMANDS = (SEASONS_READ, SEASON_SAVE)
