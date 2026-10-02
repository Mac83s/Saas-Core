"""Booking's part of the demo (core/organizations/demo.py): a day board to click.

For every organization whose scenario data has `booking`: a place, services
(one of them needing two people), the people in the calendar with hours, and
visits today and on the next two days. A visit of a two-person service with one
named person leaves a vacancy, so it waits in „Do przydzielenia”.

What exists stays: a place or service of the same name is reused, a person who
already has hours keeps them, and a visit is booked with an idempotency key made
from its day and position, so a second run returns it. A time already past (or
closer than 15 minutes) is skipped rather than booked into the past.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import time, timedelta
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException

from .models import Location, Service, StaffMember
from .services import create_appointment
from .setup import save_location, save_service
from .staff import add_person, list_people, set_person_hours, set_person_services

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRun

#: The core Business scenario's calendar (the default scenario leaves it to us).
BUSINESS: dict[str, Any] = {
    "location": {"name": "Studio — sala 1", "address": "ul. Testowa 1, Warszawa"},
    "services": [
        {"name": "Konsultacja", "duration_minutes": 60, "staff_count": 1},
        {"name": "Sesja we dwoje", "duration_minutes": 60, "staff_count": 2},
    ],
    "staff": ["wlasciciel@saas.test", "kierownik@saas.test", "pracownik@saas.test"],
    "hours": {"weekdays": [0, 1, 2, 3, 4, 5, 6], "local_start": "07:00", "local_end": "21:00"},
    "visits": [
        {
            "day": 0,
            "time": "10:00",
            "service": "Konsultacja",
            "staff": ["pracownik@saas.test"],
            "customer": "Joanna Nowak",
        },  # noqa: E501
        {
            "day": 0,
            "time": "12:00",
            "service": "Konsultacja",
            "staff": ["kierownik@saas.test"],
            "customer": "Piotr Zieliński",
        },  # noqa: E501
        {
            "day": 0,
            "time": "15:00",
            "service": "Sesja we dwoje",
            "staff": ["wlasciciel@saas.test"],
            "customer": "Katarzyna Wiśniewska",
        },  # noqa: E501
        {
            "day": 0,
            "time": "18:30",
            "service": "Konsultacja",
            "staff": ["kierownik@saas.test"],
            "customer": "Tomasz Lewandowski",
        },  # noqa: E501
        {
            "day": 1,
            "time": "09:00",
            "service": "Konsultacja",
            "staff": ["pracownik@saas.test"],
            "customer": "Agnieszka Kamińska",
        },  # noqa: E501
        {
            "day": 1,
            "time": "11:00",
            "service": "Sesja we dwoje",
            "staff": ["wlasciciel@saas.test"],
            "customer": "Ewa Kowalczyk",
        },  # noqa: E501
        {
            "day": 1,
            "time": "14:00",
            "service": "Konsultacja",
            "staff": ["kierownik@saas.test"],
            "customer": "Marcin Szymański",
        },  # noqa: E501
        {
            "day": 2,
            "time": "10:00",
            "service": "Konsultacja",
            "staff": ["wlasciciel@saas.test"],
            "customer": "Barbara Woźniak",
        },  # noqa: E501
        {
            "day": 2,
            "time": "13:00",
            "service": "Konsultacja",
            "staff": ["pracownik@saas.test"],
            "customer": "Michał Wójcik",
        },  # noqa: E501
    ],
}

NOTICE = timedelta(minutes=15)


def _clock(value: str) -> time:
    hours, minutes = (int(part) for part in value.split(":"))
    return time(hours, minutes)


def _mailbox(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    local = re.sub(r"[^a-z0-9]+", ".", plain.encode("ascii", "ignore").decode().lower())
    return f"{local.strip('.')}@klienci.test"


def seed_calendar(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = run.data(spec.key, "booking")
        if data is None and run.scenario.default and spec.key == "firma":
            data = BUSINESS
        if data is not None:
            _seed_organization(run, spec.key, data)


def _seed_organization(run: DemoRun, key: str, data: dict[str, Any]) -> None:
    organization = run.organizations[key]
    with run.acting(key) as request:
        # The company's own place when it has one: a demo fits the hours its
        # people already work.
        places = Location.all_objects.filter(organization=organization, active=True)
        location = places.filter(name=data["location"]["name"]).first() or places.first()
        if location is None:
            location = save_location(
                location_id=None, data=dict(data["location"]), idempotency_key=str(uuid.uuid4())
            ).value
            run.log(f"+ miejsce {location.name}")

        people = {person.staff.membership_id: person for person in list_people()}
        staff: dict[str, StaffMember] = {}
        for email in data["staff"]:
            user = run.user(email)
            membership = user.memberships.get(organization=organization)
            person = people.get(membership.id)
            if person is None:
                entry = add_person(
                    request=request,
                    name=f"{user.first_name} {user.last_name}".strip(),
                    membership_id=membership.id,
                )
                run.log(f"+ osoba w kalendarzu {entry.display_name}")
                people = {item.staff.membership_id: item for item in list_people()}
                person = people[membership.id]
            staff[email] = person.staff

        services: dict[str, Service] = {}
        for wanted in data["services"]:
            service = Service.all_objects.filter(
                organization=organization, name=wanted["name"]
            ).first()
            if service is None:
                save_service(
                    service_id=None,
                    data={
                        "minimum_notice_minutes": 0,
                        **wanted,
                        "location_ids": [location.id],
                        "staff_ids": [entry.id for entry in staff.values()],
                    },
                    idempotency_key=str(uuid.uuid4()),
                )
                service = Service.all_objects.get(organization=organization, name=wanted["name"])
                run.log(f"+ usługa {service.name}")
            services[service.name] = service

        for entry in staff.values():
            person = next(item for item in list_people() if item.staff.id == entry.id)
            wanted_ids = {service.id for service in services.values()}
            if not wanted_ids <= set(person.service_ids):
                set_person_services(
                    staff_id=entry.id,
                    service_ids=[*person.service_ids, *wanted_ids - set(person.service_ids)],
                )
            if not person.has_hours:
                hours = data["hours"]
                set_person_hours(
                    staff_id=entry.id,
                    rules=[
                        {
                            "weekday": weekday,
                            "local_start": _clock(hours["local_start"]),
                            "local_end": _clock(hours["local_end"]),
                            "location_id": location.id,
                        }
                        for weekday in hours["weekdays"]
                    ],
                    expected_version=person.staff.hours_version,
                    idempotency_key=str(uuid.uuid4()),
                )
                run.log(f"+ godziny pracy {entry.display_name}")

    booked = skipped = 0
    for index, visit in enumerate(data["visits"]):
        starts_at = run.at(key, visit["day"], visit["time"])
        if starts_at < run.now + NOTICE:
            continue
        day = run.day(key, visit["day"]).isoformat()
        try:
            # Its own transaction: one taken slot does not undo the others.
            with run.acting(key) as request:
                result = create_appointment(
                    service_id=services[visit["service"]].id,
                    staff_ids=[staff[email].id for email in visit["staff"]],
                    location_id=location.id,
                    starts_at=starts_at,
                    customer_data={
                        "display_name": visit["customer"],
                        "email": _mailbox(visit["customer"]),
                        "locale": "pl",
                    },
                    idempotency_key=f"seed-demo:{organization.slug}:{day}:{index}",
                    principal_ref=str(request.user.pk),
                )
            booked += int(result.created)
        except (APIException, DjangoValidationError) as error:
            skipped += 1
            detail = getattr(error, "detail", None) or getattr(error, "messages", error)
            run.log(f"! wizyta {visit['customer']} {starts_at:%d.%m %H:%M}: {detail}")
    run.log(f"{'+' if booked else '='} wizyty: nowe {booked}, pominięte {skipped}")
