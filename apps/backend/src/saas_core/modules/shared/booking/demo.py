"""Booking's part of the demo (core/organizations/demo.py): what a company
books, set up as its owner would set it up, and its bookings over time.

For every organization whose scenario data has `booking` (the core's own
companies take theirs from `demo_data.py`):

- the catalogue — a place, the people in the calendar with hours, who comes
  (participant categories), units and their groups with what a guest sees of
  them (pictures from the templates the repository ships, amenities, the town,
  a point), offers (plain, or started from a preset the way „Wzorce ofert”
  starts them) with their price list, extras, seasons and payment terms, and
  the days the company is closed;
- the bookings — `stories`, a function that plans them on a `Plan`: each
  booking is made at the moment it was made (the team in the panel, or a
  customer on the public form with the documents accepted), and what happened
  to it afterwards follows as steps: accepted, paid, called off, completed.
  The 30.09 shape — `visits` with a day offset, booked now — still works.

What exists stays: a place, a unit, an offer, an extra or a season of the same
name is reused and left as the company has it; a price list is added only
where the offer, group or unit has no price yet. A booking carries an
idempotency key made from its story's key, so a second run finds it, and each
later step finds what it already did. A taken time is skipped, not forced.

Data shape (every key but `location` optional):

    {"location": {"name", "address"},
     "staff": [email], "hours": {"weekdays", "local_start", "local_end"},
     "categories": [{"name", "counts": bool, "words"}],
     "groups": [{"name", "description", "prices": [price]}],
     "units": [{"name", "capacity", "group", "description", "amenities",
                "town", "point": (lat, lng), "show_point", "photos": [id],
                "prices": [price]}],
     "services": [{"name", "preset", "settings": {…}, "staff": [email],
                   "groups": [name], "units": [name], "prices": [price],
                   "extras": [extra], "seasons": [rule]}],
     "closures": [{"day": (month, day), "note"}],
     "interests": [{"preset", "note"}],
     "stories": callable(Plan), "visits": [the 30.09 shape]}

`words` — on an offer, a group, a unit, a category or an extra — is its name
(and description) in other languages, `{locale: {"name", "description"}}`,
written marked as imported.

A price, an extra and a season are what `prices.save_price`, `save_extra` and
`rules.save_rule` take, without the id of what they are for; a category in
`category_prices` is named (`category`), and `season: ((m, d), (m, d))` stands
for `starts_on`/`ends_on` of the next such period.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.demo import (
    DemoStep,
    DemoStory,
    register_demo_step,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tasks import tenant_task_context
from saas_core.modules.shared.notifications.security import decrypt_secret

from . import consents as booking_consents
from .item_translations import list_item_translations, save_item_translation
from .models import (
    Appointment,
    AppointmentStatus,
    BookingClosure,
    BookingMutation,
    BookingRule,
    Extra,
    Location,
    ParticipantCategory,
    PaymentPolicy,
    PriceRule,
    PublicBookingRoute,
    RequestRoute,
    Resource,
    ResourceGroup,
    SelfServiceRoute,
    Service,
    StaffMember,
    TimeModel,
)
from .orders import LINE_SOURCE
from .periods import StayPlan, book_stay
from .prices import save_category, save_extra, save_price
from .quote import quote_visit
from .rules import save_closure, save_rule
from .security import public_booking_context
from .services import (
    SlotUnavailable,
    anonymize_customer,
    answer_request,
    cancel_appointment,
    complete_appointment,
    create_appointment,
    expire_request,
    mark_no_show,
)
from .setup import save_group, save_location, save_resource, save_service
from .staff import add_person, list_people, set_person_hours, set_person_services

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import (
        DemoOrganization,
        DemoRun,
        DemoScenario,
    )

NOTICE = timedelta(minutes=15)
#: The customers' pictures of a unit come from the page templates' approved
#: photos — the only pictures the repository ships.
_PHOTO_SOURCE = "shared.sites"


def _clock(value: str) -> time:
    hours, minutes = (int(part) for part in value.split(":"))
    return time(hours, minutes)


def _mailbox(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    local = re.sub(r"[^a-z0-9]+", ".", plain.encode("ascii", "ignore").decode().lower())
    return f"{local.strip('.')}@klienci.test"


def _key() -> str:
    return str(uuid.uuid4())


def _data(run: DemoRun, spec: DemoOrganization) -> dict[str, Any] | None:
    from .demo_data import DEFAULTS  # noqa: PLC0415 — the core scenario's own companies

    data = spec.data.get("booking")
    if data is None and run.scenario.default:
        data = DEFAULTS.get(spec.key)
    return data


# --- the catalogue ---------------------------------------------------------------


@dataclass
class Catalogue:
    """What the company's stories book: its place, people, offers and units."""

    location: Location
    staff: dict[str, StaffMember] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    units: dict[str, Resource] = field(default_factory=dict)
    groups: dict[str, ResourceGroup] = field(default_factory=dict)
    categories: dict[str, ParticipantCategory] = field(default_factory=dict)
    #: The days the whole company is closed: nothing is planned on them.
    closed: set[date] = field(default_factory=set)


def seed_calendar(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = _data(run, spec)
        if data is None:
            continue
        catalogue = _catalogue(run, spec.key, data)
        plan = Plan(run, spec.key, catalogue)
        _legacy_visits(plan, data.get("visits") or ())
        if stories := data.get("stories"):
            stories(plan)
        run.play(spec.key, plan.stories)
        plan.report()
        _form_link(run, spec.key)


def describe(scenario: DemoScenario, spec: DemoOrganization) -> Sequence[str]:
    from .demo_data import DEFAULTS  # noqa: PLC0415

    data = spec.data.get("booking") or (DEFAULTS.get(spec.key) if scenario.default else None)
    if data is None:
        return ()
    offers = ", ".join(
        f"{item['name']}" + (f" (wzorzec {item['preset']})" if item.get("preset") else "")
        for item in data.get("services", ())
    )
    lines = [f"miejsce „{data['location']['name']}”; oferty: {offers}"]
    if data.get("units"):
        lines.append("jednostki: " + ", ".join(unit["name"] for unit in data["units"]))
    if data.get("stories") or data.get("visits"):
        lines.append(
            "rezerwacje z ostatnich tygodni, dzisiejsze i przyszłe — przez zespół i przez "
            "formularz publiczny — z tym, co się z nimi działo (wpłaty, odwołania, prośby)"
        )
    return lines


def _catalogue(run: DemoRun, key: str, data: dict[str, Any]) -> Catalogue:
    organization = run.organizations[key]
    today = run.day(key, 0)
    # The pictures first, at the real time: the media library reserves its
    # storage against the wall clock, whenever the unit was set up.
    with run.acting(key):
        missing = Resource.all_objects.filter(organization=organization).values_list(
            "name", flat=True
        )
        photos = {
            photo: _photo(run, photo)
            for wanted in data.get("units", ())
            if wanted["name"] not in set(missing)
            for photo in wanted.get("photos", ())
        }
    with run.setting_up(key), run.acting(key):
        # The company's own place when it has one: a demo fits the hours its
        # people already work.
        places = Location.all_objects.filter(organization=organization, active=True)
        location = places.filter(name=data["location"]["name"]).first() or places.first()
        if location is None:
            location = save_location(
                location_id=None, data=dict(data["location"]), idempotency_key=_key()
            ).value
            run.log(f"+ miejsce {location.name}")
        catalogue = Catalogue(location=location)
        _people(run, key, data, catalogue)
        for wanted in data.get("categories", ()):
            category = ParticipantCategory.all_objects.filter(
                organization=organization, name=wanted["name"]
            ).first()
            if category is None:
                category = save_category(
                    category_id=None,
                    data={
                        "name": wanted["name"],
                        "counts_towards_capacity": wanted.get("counts", True),
                    },
                    idempotency_key=_key(),
                ).value
            catalogue.categories[category.name] = category
            _words("participant_category", category, wanted.get("words"))
        for wanted in data.get("groups", ()):
            group = ResourceGroup.all_objects.filter(
                organization=organization, name=wanted["name"]
            ).first()
            if group is None:
                group = save_group(
                    group_id=None,
                    data={"name": wanted["name"], "description": wanted.get("description", "")},
                    idempotency_key=_key(),
                ).value
                run.log(f"+ pula jednostek {group.name}")
            catalogue.groups[group.name] = group
            _words("group", group, wanted.get("words"))
        for wanted in data.get("units", ()):
            unit = _unit(run, organization, catalogue, wanted, photos)
            catalogue.units[wanted["name"]] = unit
            _words("resource", unit, wanted.get("words"))
        # An offer first, then what it costs, then how it is paid for and — for
        # one started from a preset — the switch: the order a company sets it
        # up in, and the one the services ask for.
        fresh = {
            wanted["name"]: _service(run, organization, catalogue, wanted)
            for wanted in data.get("services", ())
        }
        for wanted in data.get("services", ()):
            service = catalogue.services[wanted["name"]]
            _words("service", service, wanted.get("words"))
            _prices(run, organization, catalogue, wanted, today, service=service)
            for extra in wanted.get("extras", ()):
                item = Extra.all_objects.filter(
                    organization=organization, service=service, name=extra["name"]
                ).first()
                if item is None:
                    item = save_extra(
                        extra_id=None,
                        data={
                            **{name: value for name, value in extra.items() if name != "words"},
                            "service_id": service.id,
                        },
                        idempotency_key=_key(),
                    ).value
                _words("extra", item, extra.get("words"))
            for season in wanted.get("seasons", ()):
                _season(run, organization, service, season, today)
        for wanted in data.get("groups", ()):
            _prices(
                run, organization, catalogue, wanted, today, group=catalogue.groups[wanted["name"]]
            )
        for wanted in data.get("units", ()):
            _prices(
                run, organization, catalogue, wanted, today, unit=catalogue.units[wanted["name"]]
            )
        for wanted in data.get("services", ()):
            _terms(run, catalogue, wanted, created=fresh[wanted["name"]])
        _hours(run, data, catalogue)
        for wanted in data.get("closures", ()):
            _closure(run, organization, wanted, today)
        for closure in BookingClosure.all_objects.filter(
            organization=organization, location__isnull=True
        ):
            span = (closure.ends_on - closure.starts_on).days
            catalogue.closed.update(closure.starts_on + timedelta(days=n) for n in range(span + 1))
        for wanted in data.get("interests", ()):
            _interest(run, wanted)
    return catalogue


def _interest(run: DemoRun, wanted: Mapping[str, Any]) -> None:
    """A sign-up for a preset that is announced („wkrótce”), with what the
    company says it lacks — as „Wzorce ofert” takes it. One the company made
    itself keeps its own note; a preset ready by now is applied, not waited
    for, so the sign-up is left out."""
    from .presets import preset_interests, save_interest  # noqa: PLC0415

    if wanted["preset"] in preset_interests():
        return
    try:
        with transaction.atomic():
            save_interest(
                preset_id=wanted["preset"], note=wanted.get("note", ""), idempotency_key=_key()
            )
    except APIException as error:
        run.log(f"= zapis na wzorzec {wanted['preset']} pominięty: {error.detail}")
        return
    run.log(f"+ zapis na wzorzec „wkrótce” {wanted['preset']}")


def _people(run: DemoRun, key: str, data: dict[str, Any], catalogue: Catalogue) -> None:
    organization = run.organizations[key]
    people = {person.staff.membership_id: person for person in list_people()}
    for email in data.get("staff", ()):
        user = run.user(email)
        membership = user.memberships.get(organization=organization)
        person = people.get(membership.id)
        if person is None:
            entry = add_person(
                name=f"{user.first_name} {user.last_name}".strip(),
                membership_id=membership.id,
                idempotency_key=_key(),
            ).value
            run.log(f"+ osoba w kalendarzu {entry.display_name}")
            people = {item.staff.membership_id: item for item in list_people()}
            person = people[membership.id]
        catalogue.staff[email] = person.staff


def _hours(run: DemoRun, data: dict[str, Any], catalogue: Catalogue) -> None:
    """Each person does the offers the scenario names them for and has a week
    to be booked in; a person who has hours already keeps them."""
    for email, entry in catalogue.staff.items():
        person = next(item for item in list_people() if item.staff.id == entry.id)
        does = {
            catalogue.services[wanted["name"]].id
            for wanted in data.get("services", ())
            if email in wanted.get("staff", catalogue.staff)
            and catalogue.services[wanted["name"]].time_model == TimeModel.SLOT
        }
        if not does <= set(person.service_ids):
            set_person_services(
                staff_id=entry.id,
                service_ids=[*person.service_ids, *does - set(person.service_ids)],
            )
        if not person.has_hours and (hours := data.get("hours")):
            set_person_hours(
                staff_id=entry.id,
                rules=[
                    {
                        "weekday": weekday,
                        "local_start": _clock(hours["local_start"]),
                        "local_end": _clock(hours["local_end"]),
                        "location_id": catalogue.location.id,
                    }
                    for weekday in hours["weekdays"]
                ],
                expected_version=person.staff.hours_version,
                idempotency_key=_key(),
            )
            run.log(f"+ godziny pracy {entry.display_name}")


def _words(kind: str, item: Any, words: Mapping[str, Mapping[str, str]] | None) -> None:
    """The item's name (and description) in the company's other languages,
    from the scenario: written through the catalogue's own translation door,
    marked as imported — not a person's translation, not a model's. A language
    the item already has words in is left as it is."""
    if not words:
        return
    _entry, _item, _own, rows = list_item_translations(kind, item.id)
    for locale, row in rows:
        if row is None and locale in words:
            save_item_translation(
                kind=kind,
                item_id=item.id,
                locale=locale,
                texts=dict(words[locale]),
                expected_version=0,
                idempotency_key=_key(),
                imported=True,
            )


def _unit(
    run: DemoRun,
    organization: Organization,
    catalogue: Catalogue,
    wanted: Mapping[str, Any],
    pictures: Mapping[str, uuid.UUID | None],
) -> Resource:
    unit = Resource.all_objects.filter(organization=organization, name=wanted["name"]).first()
    if unit is not None:
        return unit
    point = wanted.get("point")
    content: dict[str, Any] = {
        "public": True,
        "amenities": list(wanted.get("amenities", ())),
        "city_slug": wanted.get("town", ""),
        **(
            {
                "latitude": point[0],
                "longitude": point[1],
                "show_exact_location": bool(wanted.get("show_point")),
            }
            if point
            else {}
        ),
    }
    photos = [
        asset
        for asset in (pictures.get(photo) for photo in wanted.get("photos", ()))
        if asset is not None
    ]
    group = catalogue.groups.get(wanted.get("group") or "")
    unit = save_resource(
        resource_id=None,
        data={
            "name": wanted["name"],
            "capacity": wanted.get("capacity", 1),
            "description": wanted.get("description", ""),
            "location_id": catalogue.location.id,
            **({"group_id": group.id} if group else {}),
            **content,
            **({"photo_ids": photos} if photos else {}),
        },
        idempotency_key=_key(),
    ).value
    run.log(f"+ jednostka {unit.name}" + (f" ({len(photos)} zdj.)" if photos else ""))
    return unit


def _photo(run: DemoRun, photo_id: str) -> uuid.UUID | None:
    """A template photo in the company's media library — through the same
    import, scan and variants as a template's own pictures — or None where
    the profile has no sites, the plan no storage, or the import fails: a unit
    without a picture is still a unit."""
    if _PHOTO_SOURCE not in settings.ACTIVE_MODULES:
        return None
    from saas_core.modules.shared.sites.template_media import (  # noqa: PLC0415
        materialize_template_photo,
    )

    try:
        with transaction.atomic():
            return materialize_template_photo(
                photo_id=photo_id, idempotency_key=f"seed-demo:{photo_id}"
            )
    except (APIException, DjangoValidationError, OSError, RuntimeError) as error:
        run.log(f"! zdjęcie {photo_id}: {getattr(error, 'detail', error)}")
        return None


def _service(
    run: DemoRun, organization: Organization, catalogue: Catalogue, wanted: Mapping[str, Any]
) -> bool:
    """The offer of that name, made when the company has none — plain, or
    started from a preset the way „Wzorce ofert” starts it: a switched-off
    copy the company then gives its place and units. Says whether it made it."""
    from .presets import apply_preset  # noqa: PLC0415 — reads the presets' contract

    service = Service.all_objects.filter(organization=organization, name=wanted["name"]).first()
    created = service is None
    if service is None:
        staff_ids = [catalogue.staff[email].id for email in wanted.get("staff", catalogue.staff)]
        links = {
            "location_ids": [catalogue.location.id],
            **({"staff_ids": staff_ids} if staff_ids else {}),
            **(
                {"group_ids": [catalogue.groups[name].id for name in wanted["groups"]]}
                if wanted.get("groups")
                else {}
            ),
            **(
                {"resource_ids": [catalogue.units[name].id for name in wanted["units"]]}
                if wanted.get("units")
                else {}
            ),
        }
        if preset := wanted.get("preset"):
            draft = apply_preset(
                preset_id=preset, name=wanted["name"], idempotency_key=_key()
            ).value.service
            service = save_service(
                service_id=draft.id,
                data=links,
                expected_version=draft.version,
                idempotency_key=_key(),
            ).value.service
            run.log(f"+ oferta {service.name} z wzorca {preset} v{service.preset_version}")
        else:
            plain = {
                name: value
                for name, value in wanted.get("settings", {}).items()
                if name not in _PAYMENT_TERMS
            }
            service = save_service(
                service_id=None,
                data={"minimum_notice_minutes": 0, **plain, "name": wanted["name"], **links},
                idempotency_key=_key(),
            ).value.service
            run.log(f"+ oferta {service.name}")
    catalogue.services[wanted["name"]] = service
    return created


def _terms(run: DemoRun, catalogue: Catalogue, wanted: Mapping[str, Any], *, created: bool) -> None:
    """How the offer is paid for, once it has a price to take a part of — and
    the switch of one started from a preset. An offer the company had before
    keeps its terms; only a way of paying nobody chose yet is filled in."""
    service = catalogue.services[wanted["name"]]
    service.refresh_from_db()
    settings_ = wanted.get("settings", {})
    terms = (
        {name: settings_[name] for name in _PAYMENT_TERMS if name in settings_}
        if created or service.payment_policy == PaymentPolicy.NONE
        else {}
    )
    if created and wanted.get("preset"):
        terms = {
            **{name: value for name, value in settings_.items() if name not in terms},
            **terms,
            "active": True,
        }
    if terms:
        try:
            with transaction.atomic():
                service = save_service(
                    service_id=service.id,
                    data=terms,
                    expected_version=service.version,
                    idempotency_key=_key(),
                ).value.service
        except (APIException, DjangoValidationError) as error:
            # No orders in the plan, no bank account: the offer stays as it is.
            run.log(f"! warunki oferty {service.name}: {getattr(error, 'detail', error)}")
            service.refresh_from_db()
    catalogue.services[wanted["name"]] = service


#: How an offer is paid for and what giving it up gives back.
_PAYMENT_TERMS = (
    "payment_policy",
    "deposit_percent",
    "transfer_due_days",
    "balance_due_days_before",
    "cancellation_refunds",
    "cancellation_applies_to",
)


def _prices(
    run: DemoRun,
    organization: Organization,
    catalogue: Catalogue,
    wanted: Mapping[str, Any],
    today: date,
    *,
    service: Service | None = None,
    group: ResourceGroup | None = None,
    unit: Resource | None = None,
) -> None:
    """The price list of an offer, a group or a unit — only where it has no
    price yet: a company's own prices are never added to."""
    prices = wanted.get("prices")
    if not prices:
        return
    scope = (
        {"service_id": service.id}
        if service
        else {"group_id": group.id}
        if group
        else {"resource_id": unit.id if unit else None}
    )
    if PriceRule.all_objects.filter(organization=organization, **scope).exists():
        return
    for price in prices:
        data = {**price, **scope}
        if season := data.pop("season", None):
            data["starts_on"], data["ends_on"] = _next_period(today, *season)
        if "category_prices" in data:
            data["category_prices"] = [
                {
                    "category_id": catalogue.categories[line["category"]].id,
                    "amount_minor": line["amount_minor"],
                }
                for line in data["category_prices"]
            ]
        save_price(price_id=None, data=data, idempotency_key=_key())
    run.log(f"+ cennik {wanted['name']}: {len(prices)} poz.")


def _season(
    run: DemoRun,
    organization: Organization,
    service: Service,
    season: Mapping[str, Any],
    today: date,
) -> None:
    if BookingRule.all_objects.filter(
        organization=organization, service=service, name=season["name"]
    ).exists():
        return
    data = {**season, "service_id": service.id}
    if period := data.pop("season", None):
        data["starts_on"], data["ends_on"] = _next_period(today, *period)
    else:
        # A rule for every day: the years around today.
        data.setdefault("starts_on", date(today.year - 1, 1, 1))
        data.setdefault("ends_on", date(today.year + 2, 12, 31))
    save_rule(rule_id=None, data=data, idempotency_key=_key())
    run.log(f"+ sezon {season['name']} ({service.name})")


def _closure(
    run: DemoRun, organization: Organization, wanted: Mapping[str, Any], today: date
) -> None:
    month, day = wanted["day"]
    closed = date(today.year, month, day)
    if closed < today:
        closed = date(today.year + 1, month, day)
    if BookingClosure.all_objects.filter(
        organization=organization, starts_on=closed, ends_on=closed
    ).exists():
        return
    save_closure(
        closure_id=None,
        data={"starts_on": closed, "ends_on": closed, "note": wanted["note"]},
        idempotency_key=_key(),
    )
    run.log(f"+ dzień zamknięty {closed:%d.%m.%Y}: {wanted['note']}")


def _next_period(today: date, start: tuple[int, int], end: tuple[int, int]) -> tuple[date, date]:
    """The next period from `start` to `end` (month, day) that has not ended."""
    for year in (today.year - 1, today.year, today.year + 1):
        first = date(year, *start)
        last = date(year + (1 if end < start else 0), *end)
        if last >= today:
            return first, last
    raise ValueError("No such period.")  # pragma: no cover — one of three years always fits


def _form_link(run: DemoRun, key: str) -> None:
    """Where the company's public booking form is, for the guide."""
    organization = run.organizations[key]
    route = PublicBookingRoute.objects.filter(organization_id=organization.id).first()
    if route is not None and settings.PUBLIC_BOOKING_ENABLED:
        run.links[key]["form"] = f"{run.links[key]['panel']}/book/{route.public_slug}"


# --- planning stories ------------------------------------------------------------


class Story:
    """One booking being planned: `then` adds what happened to it afterwards."""

    def __init__(self, told: DemoStory) -> None:
        self._told = told

    def then(self, do: str, at: datetime, **data: Any) -> Story:
        self._told.steps.append(DemoStep(at=at, do=do, data=data))
        return self


class Plan:
    """A company's bookings, planned as stories (the scenario's `stories`
    function gets one). Dates are the company's own; a customer is a mapping
    with `display_name` and a `phone`, an `email` or both."""

    def __init__(self, run: DemoRun, key: str, catalogue: Catalogue) -> None:
        self.run = run
        self.key = key
        self.catalogue = catalogue
        self.today = run.day(key, 0)
        self.stories: list[DemoStory] = []
        self.booked = 0
        self.taken = 0

    def at(self, day: date, clock: str) -> datetime:
        return self.run.on(self.key, day, clock)

    def days(self, back: int, ahead: int) -> list[date]:
        """Every day from `back` days ago to `ahead` days from today."""
        return [self.today + timedelta(days=n) for n in range(-back, ahead + 1)]

    def weeks(self, back: int, ahead: int) -> list[date]:
        """The Mondays from `back` weeks ago to `ahead` weeks from this one."""
        monday = self.today - timedelta(days=self.today.weekday())
        return [monday + timedelta(weeks=n) for n in range(-back, ahead + 1)]

    def visit(
        self,
        key: str,
        day: date,
        clock: str,
        *,
        offer: str,
        booked: datetime,
        customer: Mapping[str, str],
        by: str = "",
        staff: Sequence[str] = (),
        extras: Sequence[str] = (),
        agreed: bool = False,
        marketing: bool = False,
        notes: str = "",
    ) -> Story:
        """A visit at `clock` of `day`, booked at `booked` — by the person
        `by` in the panel, or by the customer on the public form when nobody
        is named (the server then picks who takes it unless `staff` asks for
        one). `agreed`: the team showed the company's documents; a customer
        booking for themselves always accepts them. `marketing`: they ticked
        the offers' consent."""
        return self._plan(
            key,
            booked,
            "booking.visit",
            offer=offer,
            starts_at=self.at(day, clock),
            customer=dict(customer),
            by=by,
            staff=tuple(staff),
            extras=tuple(extras),
            agreed=agreed,
            marketing=marketing,
            notes=notes,
        )

    def stay(
        self,
        key: str,
        first: date,
        last: date,
        *,
        offer: str,
        booked: datetime,
        customer: Mapping[str, str],
        by: str = "",
        unit: str = "",
        group: str = "",
        people: Mapping[str, int] | None = None,
        extras: Sequence[str] = (),
        agreed: bool = False,
        marketing: bool = False,
        notes: str = "",
    ) -> Story:
        """A stay or a rental from `first` to `last` on the unit named, or on
        any free unit of the group. `people`: how many of each category come,
        `""` being a standard person."""
        return self._plan(
            key,
            booked,
            "booking.stay",
            offer=offer,
            first=first,
            last=last,
            customer=dict(customer),
            by=by,
            unit=unit,
            group=group,
            people=dict(people or {}),
            extras=tuple(extras),
            agreed=agreed,
            marketing=marketing,
            notes=notes,
        )

    def _plan(self, key: str, booked: datetime, do: str, **data: Any) -> Story:
        told = DemoStory(
            key=key, steps=[DemoStep(at=booked, do=do, data=data)], memo={"plan": self}
        )
        self.stories.append(told)
        return Story(told)

    def report(self) -> None:
        self.run.log(
            f"{'+' if self.booked else '='} rezerwacje: nowe {self.booked}"
            + (f", pominięte {self.taken} (termin zajęty)" if self.taken else "")
        )


def _legacy_visits(plan: Plan, visits: Sequence[Mapping[str, Any]]) -> None:
    """The 30.09 shape: `{"day", "time", "service", "staff", "customer"}`,
    booked now by the owner; a time already past or too near is left out."""
    run, key = plan.run, plan.key
    owner = run.spec(key).owner.email
    for index, visit in enumerate(visits):
        starts_at = run.at(key, visit["day"], visit["time"])
        if starts_at < run.now + NOTICE:
            continue
        day = run.day(key, visit["day"])
        plan.visit(
            f"{day.isoformat()}:{index}",
            day,
            visit["time"],
            offer=visit["service"],
            booked=run.now,
            by=owner,
            staff=visit["staff"],
            customer={
                "display_name": visit["customer"],
                "email": _mailbox(visit["customer"]),
                "locale": "pl",
            },
        )


# --- the steps -------------------------------------------------------------------


def _found(run: DemoRun, key: str, story: DemoStory) -> Appointment | None:
    """The booking this story made on an earlier run, whoever made it."""
    organization = run.organizations[key]
    mutation = (
        BookingMutation.all_objects.filter(
            organization_id=organization.id,
            action="create",
            idempotency_key=_idempotency_key(run, key, story),
        )
        .select_related("appointment")
        .first()
    )
    return mutation.appointment if mutation else None


def _idempotency_key(run: DemoRun, key: str, story: DemoStory) -> str:
    return f"seed-demo:{run.organizations[key].slug}:{story.key}"


def _remember(story: DemoStory, appointment: Appointment) -> None:
    story.memo["appointment_id"] = appointment.id
    story.memo["customer_id"] = appointment.customer_id
    # What an order of this booking is found by (`commerce.api.order_for`).
    story.memo["order"] = (LINE_SOURCE, str(appointment.id))


def _appointment(story: DemoStory) -> Appointment | None:
    found = story.memo.get("appointment_id")
    return Appointment.all_objects.filter(pk=found).first() if found else None


def _accepted(locale: str, *, marketing: bool) -> booking_consents.BookingConsents:
    """What the form showed and the customer ticked: every document in force
    in the booking's language."""
    shown = booking_consents.shown(locale)
    return booking_consents.BookingConsents(
        documents=tuple(uuid.UUID(row["text_id"]) for row in shown["documents"]),
        marketing=marketing and shown["marketing"] is not None,
    )


def _book(
    run: DemoRun,
    key: str,
    story: DemoStory,
    step: DemoStep,
    booking: Callable[[str, booking_consents.BookingConsents | None, bool], Appointment],
) -> None:
    plan: Plan = story.memo["plan"]
    existing = _found(run, key, story)
    if existing is not None:
        _remember(story, existing)
        return
    data = step.data
    locale = data["customer"].get("locale") or "pl"
    try:
        if data["by"]:
            with run.acting(key, data["by"]) as request:
                agreed = _accepted(locale, marketing=data["marketing"]) if data["agreed"] else None
                appointment = booking(str(request.user.pk), agreed, False)
        else:
            with public_booking_context(run.organizations[key].id):
                agreed = _accepted(locale, marketing=data["marketing"])
                appointment = booking("public", agreed, True)
    except SlotUnavailable:
        plan.taken += 1
        story.stopped = "termin zajęty"
        return
    plan.booked += 1
    _remember(story, appointment)


def _visit(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    plan: Plan = story.memo["plan"]
    catalogue, data = plan.catalogue, step.data
    service = catalogue.services[data["offer"]]
    extras = [
        {"extra_id": extra.id, "quantity": 1}
        for extra in Extra.all_objects.filter(service=service, name__in=data["extras"])
    ]

    def booking(
        principal: str, agreed: booking_consents.BookingConsents | None, public: bool
    ) -> Appointment:
        digest = ""
        if public:
            # The price the form showed, sent back with the booking.
            digest = quote_visit(
                service=service,
                starts_at=data["starts_at"],
                extras=extras,
                locale=data["customer"].get("locale") or None,
            ).digest
        staff_ids = [catalogue.staff[email].id for email in data["staff"]]
        return create_appointment(
            service_id=service.id,
            location_id=catalogue.location.id,
            starts_at=data["starts_at"],
            customer_data=data["customer"],
            idempotency_key=_idempotency_key(run, key, story),
            principal_ref=principal,
            extras=extras,
            quote_digest=digest,
            consents=agreed,
            customer_notes=data["notes"],
            **(
                {"requested_staff_id": staff_ids[0]}
                if public and staff_ids
                else {"staff_ids": staff_ids}
                if staff_ids
                else {}
            ),
        ).appointment

    _book(run, key, story, step, booking)


def _stay(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    plan: Plan = story.memo["plan"]
    catalogue, data = plan.catalogue, step.data
    service = catalogue.services[data["offer"]]
    wanted: dict[str, Any] = {
        "service_id": service.id,
        "start_date": data["first"],
        "end_date": data["last"],
        **({"resource_id": catalogue.units[data["unit"]].id} if data["unit"] else {}),
        **({"group_id": catalogue.groups[data["group"]].id} if data["group"] else {}),
        "participants": [
            {
                "category_id": catalogue.categories[name].id if name else None,
                "count": count,
            }
            for name, count in data["people"].items()
        ]
        or None,
        "extras": [
            {"extra_id": extra.id, "quantity": 1}
            for extra in Extra.all_objects.filter(service=service, name__in=data["extras"])
        ],
    }

    def booking(
        principal: str, agreed: booking_consents.BookingConsents | None, public: bool
    ) -> Appointment:
        digest = ""
        if public:
            shown = book_stay(
                **wanted,
                customer_data={"locale": data["customer"].get("locale", "")},
                idempotency_key="",
                principal_ref="",
                preview=True,
            )
            assert isinstance(shown, StayPlan)
            digest = shown.quote.digest if shown.quote is not None else ""
        booked = book_stay(
            **wanted,
            customer_data=data["customer"],
            idempotency_key=_idempotency_key(run, key, story),
            principal_ref=principal,
            quote_digest=digest,
            consents=agreed,
            customer_notes=data["notes"],
        )
        assert not isinstance(booked, StayPlan)
        return booked.appointment

    _book(run, key, story, step, booking)


def _answer(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    appointment = _appointment(story)
    if appointment is None or appointment.status != AppointmentStatus.PENDING_REQUEST:
        return
    with run.acting(key, step.data.get("by")) as request:
        answer_request(
            appointment_id=appointment.id,
            accept=step.do == "booking.accept",
            reason=step.data.get("reason", ""),
            idempotency_key=f"{_idempotency_key(run, key, story)}:answer",
            principal_ref=str(request.user.pk),
        )


def _expire(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    """Nobody answered in the offer's time: what booking's own task does when
    the date comes, for this one request and under the request's own contract."""
    appointment = _appointment(story)
    if appointment is None or appointment.status != AppointmentStatus.PENDING_REQUEST:
        return
    route = RequestRoute.objects.filter(
        appointment_id=appointment.id, dispatched_at__isnull=True
    ).first()
    if route is None:
        return
    with tenant_task_context(
        decrypt_secret(route.signed_tenant_context),
        expected_causation_id=f"booking:{appointment.id}",
        expires=False,
    ):
        expire_request(appointment.id)
    RequestRoute.objects.filter(pk=route.pk, dispatched_at__isnull=True).update(
        dispatched_at=timezone.now()
    )


def _cancel(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    appointment = _appointment(story)
    if appointment is None or appointment.status == AppointmentStatus.CANCELED:
        return
    idempotency_key = f"{_idempotency_key(run, key, story)}:cancel"
    if by := step.data.get("by"):
        # The company calls it off: everything its customer paid goes back.
        with run.acting(key, by) as request:
            cancel_appointment(
                appointment_id=appointment.id,
                idempotency_key=idempotency_key,
                principal_ref=str(request.user.pk),
            )
        return
    # The customer gives it up through their own link: settled by the terms
    # frozen in the booking.
    route = SelfServiceRoute.objects.get(appointment_id=appointment.id)
    with public_booking_context(appointment.organization_id):
        cancel_appointment(
            appointment_id=appointment.id,
            idempotency_key=idempotency_key,
            principal_ref=route.token_digest,
        )


def _complete(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    appointment = _appointment(story)
    if appointment is None or appointment.status != AppointmentStatus.CONFIRMED:
        return
    with run.acting(key, step.data.get("by")) as request:
        close = mark_no_show if step.do == "booking.no_show" else complete_appointment
        close(
            appointment_id=appointment.id,
            idempotency_key=f"{_idempotency_key(run, key, story)}:{step.do}",
            principal_ref=str(request.user.pk),
        )


def _anonymize(run: DemoRun, key: str, story: DemoStory, step: DemoStep) -> None:
    appointment = _appointment(story)
    if appointment is None or appointment.customer.anonymized_at is not None:
        return
    with run.acting(key, step.data.get("by")):
        anonymize_customer(appointment.customer_id)
    run.log(f"+ klient zanonimizowany ({story.key})")


def register_steps() -> None:
    """From `BookingConfig.ready`: what a story's booking steps do."""
    register_demo_step("booking.visit", _visit)
    register_demo_step("booking.stay", _stay)
    register_demo_step("booking.accept", _answer)
    register_demo_step("booking.decline", _answer)
    register_demo_step("booking.expire", _expire)
    register_demo_step("booking.cancel", _cancel)
    register_demo_step("booking.complete", _complete)
    register_demo_step("booking.no_show", _complete)
    register_demo_step("booking.anonymize", _anonymize)
