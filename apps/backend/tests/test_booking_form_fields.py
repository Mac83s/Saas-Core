"""An offer's own form fields (ADR-072 §8, „Rozstrzygnięcia plastra 5j”): what
a company asks its customer beyond a name and a contact, how the public form
gets it, how a booking keeps the answers, who reads them, and how they leave
with the customer."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditEntry
from saas_core.modules.shared.booking.form_fields import FIELD_LIMITS, list_fields, save_field
from saas_core.modules.shared.booking.item_translations import save_item_translation
from saas_core.modules.shared.booking.models import (
    Appointment,
    BookingSetupMutation,
    FormField,
    FormFieldTranslation,
    Service,
)
from saas_core.modules.shared.booking.presets import apply_preset
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.booking.setup import discard_draft
from saas_core.modules.shared.customers.models import ConsentRecord
from saas_core.modules.shared.media.models import AiOrigin, MediaAsset
from saas_core.modules.shared.notifications.models import NotificationMessage
from test_booking import _no_delivery, catalog, membership, tenant
from test_booking_contacts import worker
from test_booking_prices import key
from test_booking_public_choice import book, setup
from test_booking_public_stays import booked, form
from test_booking_stays import stay
from test_booking_unit_content import change, picture
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

LICENCE = "ABC 123456"


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def field(service_id: Any, name: str, **given: Any) -> FormField:
    return save_field(
        field_id=None,
        data={"service_id": service_id, "name": name, **given},
        idempotency_key=key(),
    ).value


def refused(**data: Any) -> list[tuple[Any, Any]]:
    with pytest.raises(ValidationError) as error:
        save_field(field_id=None, data=data, idempotency_key=key())
    return [(found["field"], found["code"]) for found in problem_errors(error.value)]


def answers(*given: tuple[FormField, str]) -> list[dict[str, str]]:
    return [{"field_id": str(asked.id), "value": value} for asked, value in given]


def errors(response: Any) -> list[tuple[str, str]]:
    assert response.status_code == 400, response.content
    return sorted((found["field"], found["code"]) for found in response.json()["errors"])


def asked_of(configured: dict[str, Any]) -> dict[str, FormField]:
    """A rental's form: a licence number it must have, how tall the rider is,
    the day of birth, a frame to choose and two boxes to tick."""
    offer = configured["service"].id
    with tenant(configured["owner"]):
        return {
            "licence": field(offer, "Numer prawa jazdy", mandatory=True),
            "height": field(offer, "Wzrost w cm", kind="number"),
            "born": field(offer, "Data urodzenia", kind="date"),
            "frame": field(offer, "Rama", kind="choice", options=["Damska", "Męska"]),
            "rules": field(
                offer, "Zapoznałem się z regulaminem obiektu", kind="consent", mandatory=True
            ),
            "photos": field(offer, "Zgadzam się na zdjęcia z pobytu", kind="consent"),
        }


def test_a_field_is_a_setup_item_of_its_offer() -> None:
    owner = membership("pola-zapis")
    visit = catalog(owner)["service"].id
    with tenant(owner):
        first = field(visit, " Imię pupila ", mandatory=True)
        choice = field(visit, "Rozmiar", kind="choice", options=[" S ", "M", "", "L"])
        # Options are a choice's alone, and a new field goes last.
        plain = field(visit, "Uwagi do dojazdu", options=["a", "b"])
        assert (first.name, first.kind, first.mandatory, first.position) == (
            "Imię pupila",
            "text",
            True,
            1,
        )
        assert (choice.option_list, choice.position) == (["S", "M", "L"], 2)
        assert (plain.option_list, plain.position) == ([], 3)

        assert refused(service_id=visit, name="imię pupila") == [("name", "name_taken")]
        assert refused(service_id=visit, name="Kolor", kind="choice", options=["Jeden"]) == [
            ("options", "options_required")
        ]
        assert refused(service_id=visit, name="Kolor", kind="choice", options=["a", "A"]) == [
            ("options", "options_repeated")
        ]
        assert refused(service_id=visit, name="  ") == [("name", "required")]

        # A preview refuses what the write would and stores nothing.
        before = FormField.all_objects.count()
        seen = save_field(
            field_id=first.id, data={"mandatory": False}, expected_version=1, preview=True
        )
        assert seen.changes == {"mandatory": {"from": True, "to": False}}
        assert FormField.all_objects.get(pk=first.id).mandatory is True
        assert FormField.all_objects.count() == before

        # A change names the version it was made on; the same key answers again.
        again = key()
        off = save_field(
            field_id=first.id,
            data={"active": False, "name": "Imię zwierzaka"},
            expected_version=1,
            idempotency_key=again,
        )
        assert off.changes == {
            "name": {"from": "Imię pupila", "to": "Imię zwierzaka"},
            "active": {"from": True, "to": False},
        }
        replay = save_field(
            field_id=first.id,
            data={"active": False, "name": "Imię zwierzaka"},
            expected_version=1,
            idempotency_key=again,
        )
        assert (replay.replayed, replay.version) == (True, 2)
        with pytest.raises(Exception) as stale:
            save_field(
                field_id=first.id, data={"active": True}, expected_version=1, idempotency_key=key()
            )
        assert getattr(stale.value, "default_code", "") == "booking_version_conflict"

        # A form longer than the bound is not filled: the next one is refused.
        for number in range(FIELD_LIMITS["max_fields"] - 2):
            field(visit, f"Pytanie {number}")
        assert refused(service_id=visit, name="O jedno za dużo") == [
            ("service_id", "fields_too_many")
        ]
        assert len(list_fields()) == FIELD_LIMITS["max_fields"] + 1
    entry = OrganizationAuditEntry.objects.filter(
        organization=owner.organization, action="booking.field.changed", target_id=first.id
    ).latest("occurred_at")
    assert (entry.target_type, set(entry.metadata["changes"])) == (
        "booking_field",
        {"name", "active"},
    )


def test_the_api_lists_and_changes_fields_for_whoever_sets_services_up() -> None:
    owner = membership("pola-api")
    visit = catalog(owner)["service"]
    client = authenticated_client(owner)
    made = client.post(
        "/api/v1/booking/setup/fields/",
        {"service_id": str(visit.id), "name": "Rama", "kind": "choice", "options": ["A", "B"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert made.status_code == 201, made.content
    created = made.json()
    assert (created["options"], created["mandatory"], created["version"]) == (["A", "B"], False, 1)
    preview = client.post(
        f"/api/v1/booking/setup/fields/{created['id']}/preview/",
        {"mandatory": True, "expected_version": 1},
        format="json",
    )
    assert preview.json()["changes"] == {"mandatory": {"from": False, "to": True}}
    listed = client.get("/api/v1/booking/setup/fields/").json()
    assert [item["name"] for item in listed["items"]] == ["Rama"]
    assert listed["limits"]["max_fields"] == FIELD_LIMITS["max_fields"]
    assert [kind["value"] for kind in listed["limits"]["kinds"]] == [
        "text",
        "number",
        "date",
        "choice",
        "consent",
    ]
    # Somebody who does not set services up reads and writes nothing of it.
    staff = authenticated_client(worker(owner, "pola-pracownik@example.test"))
    assert staff.get("/api/v1/booking/setup/fields/").status_code == 403
    denied = staff.post(
        "/api/v1/booking/setup/fields/",
        {"service_id": str(visit.id), "name": "Cudze"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert denied.status_code == 403
    # Another company's offer is not there to be given a field.
    other = authenticated_client(membership("pola-api-obcy"))
    foreign = other.post(
        "/api/v1/booking/setup/fields/",
        {"service_id": str(visit.id), "name": "Cudze"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert foreign.status_code == 400, foreign.content
    assert other.get("/api/v1/booking/setup/fields/").json()["items"] == []


def test_the_form_reads_what_it_asks_in_the_visitors_language() -> None:
    configured = form("pola-katalog", priced=False)
    owner = configured["owner"]
    visit = catalog(owner)["service"]
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["pl", "en"])
    asked = asked_of(configured)
    with tenant(owner):
        field(visit.id, "Skąd o nas wiesz?")
        switched_off = field(configured["service"].id, "Stare pytanie")
        save_field(
            field_id=switched_off.id,
            data={"active": False},
            expected_version=1,
            idempotency_key=key(),
        )
        save_item_translation(
            kind="field",
            item_id=asked["frame"].id,
            locale="en",
            texts={"name": "Frame", "options": "Step-through\nDiamond"},
            expected_version=0,
            idempotency_key=key(),
        )
        # A list said in another number of lines is no translation of this one.
        with pytest.raises(ValidationError) as uneven:
            save_item_translation(
                kind="field",
                item_id=asked["frame"].id,
                locale="en",
                texts={"options": "Only one"},
                expected_version=1,
                idempotency_key=key(),
            )
    assert [(e["field"], e["code"]) for e in problem_errors(uneven.value)] == [
        ("texts.options", "lines_mismatch")
    ]

    client = APIClient()
    own = client.get(f"{configured['url']}/").json()["form_fields"]
    stay_fields = [item for item in own if item["service_id"] == str(configured["service"].id)]
    assert [(item["name"], item["kind"], item["mandatory"]) for item in stay_fields] == [
        ("Numer prawa jazdy", "text", True),
        ("Wzrost w cm", "number", False),
        ("Data urodzenia", "date", False),
        ("Rama", "choice", False),
        ("Zapoznałem się z regulaminem obiektu", "consent", True),
        ("Zgadzam się na zdjęcia z pobytu", "consent", False),
    ]
    assert stay_fields[3]["options"] == [
        {"value": "Damska", "label": "Damska"},
        {"value": "Męska", "label": "Męska"},
    ]
    assert [item["name"] for item in own if item["service_id"] == str(visit.id)] == [
        "Skąd o nas wiesz?"
    ]

    english = client.get(f"{configured['url']}/", {"locale": "en"}).json()["form_fields"]
    frame = next(item for item in english if item["id"] == str(asked["frame"].id))
    # The label is the visitor's; what an answer sends back stays the company's word.
    assert (frame["name"], frame["options"]) == (
        "Frame",
        [{"value": "Damska", "label": "Step-through"}, {"value": "Męska", "label": "Diamond"}],
    )
    # Options the engine wrote in another number of lines: the company's own are shown.
    with tenant(owner):
        row = FormFieldTranslation.all_objects.get(field=asked["frame"], locale="en")
        row.texts = {**row.texts, "options": "One"}
        row.save(update_fields=["texts"])
    english = client.get(f"{configured['url']}/", {"locale": "en"}).json()["form_fields"]
    frame = next(item for item in english if item["id"] == str(asked["frame"].id))
    assert [option["label"] for option in frame["options"]] == ["Damska", "Męska"]


def test_a_stay_booked_on_the_form_keeps_its_answers_and_journals_the_consents() -> None:
    configured = form("pola-pobyt", priced=False)
    owner = configured["owner"]
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["pl", "en"])
    asked = asked_of(configured)
    with tenant(owner):
        save_item_translation(
            kind="field",
            item_id=asked["photos"].id,
            locale="en",
            texts={"name": "I agree to photos of my stay"},
            expected_version=0,
            idempotency_key=key(),
        )
    client = APIClient()
    guest = {"display_name": "Jan Gość", "email": "jan-pola@example.test", "locale": "en"}

    # Nothing answered: each mandatory field is named, and nothing is written.
    assert errors(booked(client, configured, customer=guest)) == sorted([
        (f"answers.{asked['licence'].id}", "field_required"),
        (f"answers.{asked['rules'].id}", "field_required"),
    ])
    wrong = booked(
        client,
        configured,
        customer=guest,
        answers=answers(
            (asked["licence"], LICENCE),
            (asked["rules"], "true"),
            (asked["height"], "wysoki"),
            (asked["born"], "12.05.1990"),
            (asked["frame"], "Step-through"),
        ),
    )
    assert errors(wrong) == sorted([
        (f"answers.{asked['height'].id}", "field_invalid"),
        (f"answers.{asked['born'].id}", "field_invalid"),
        (f"answers.{asked['frame'].id}", "field_invalid"),
    ])
    with tenant(owner):
        other = field(catalog(owner)["service"].id, "Pytanie innej usługi")
    unknown = booked(
        client,
        configured,
        customer=guest,
        answers=answers((asked["licence"], LICENCE), (asked["rules"], "true"), (other, "x")),
    )
    assert errors(unknown) == [("answers", "field_unknown")]
    with tenant(owner):
        assert not Appointment.all_objects.filter(organization=owner.organization).exists()
        assert not ConsentRecord.all_objects.filter(organization=owner.organization).exists()

    given = answers(
        (asked["licence"], f"  {LICENCE} "),
        (asked["height"], "182,50"),
        (asked["born"], "1990-05-12"),
        (asked["frame"], "Męska"),
        (asked["rules"], "true"),
        (asked["photos"], "true"),
    )
    again = key()
    made = booked(client, configured, idem=again, customer=guest, answers=given)
    assert made.status_code == 201, made.content
    # The guest's answer is not sent back to the page.
    assert LICENCE not in made.content.decode()
    assert booked(client, configured, idem=again, customer=guest, answers=given).status_code == 200
    changed = answers((asked["licence"], "INNY 1"), (asked["rules"], "true"))
    assert (
        booked(client, configured, idem=again, customer=guest, answers=changed).status_code == 409
    )

    with tenant(owner):
        booking = Appointment.all_objects.get(pk=made.json()["id"])
        assert [(line["name"], line["kind"], line["value"]) for line in booking.form_answers] == [
            ("Numer prawa jazdy", "text", LICENCE),
            ("Wzrost w cm", "number", "182.5"),
            ("Data urodzenia", "date", "1990-05-12"),
            ("Rama", "choice", "Męska"),
            # A consent is no value: the journal has its words.
            ("Zapoznałem się z regulaminem obiektu", "consent", ""),
            ("Zgadzam się na zdjęcia z pobytu", "consent", ""),
        ]
        journal = ConsentRecord.all_objects.filter(
            organization=owner.organization, source_reference=str(booking.id), kind="field"
        ).order_by("created_at", "id")
        # Word for word as the guest read it: the company's translation where it has one.
        assert [(line.wording, line.locale, line.granted) for line in journal] == [
            ("Zapoznałem się z regulaminem obiektu", "en", True),
            ("I agree to photos of my stay", "en", True),
        ]
        assert all(line.customer_id == booking.customer_id for line in journal)
        # A field changed or switched off later rewrites nothing.
        save_field(
            field_id=asked["licence"].id,
            data={"name": "Nr dokumentu", "active": False},
            expected_version=1,
            idempotency_key=key(),
        )
        assert Appointment.all_objects.get(pk=booking.id).form_answers[0]["name"] == (
            "Numer prawa jazdy"
        )
        # Neither a message nor the history of changes carries what was answered.
        written = json.dumps(
            [
                list(
                    NotificationMessage.all_objects.filter(
                        organization=owner.organization
                    ).values_list("context", flat=True)
                ),
                list(
                    OrganizationAuditEntry.objects.filter(
                        organization=owner.organization
                    ).values_list("metadata", flat=True)
                ),
                list(
                    BookingSetupMutation.all_objects.filter(
                        organization=owner.organization
                    ).values_list("request_hash", flat=True)
                ),
            ],
            default=str,
        )
        assert LICENCE not in written and "182.5" not in written


def test_a_visit_booked_on_the_form_asks_its_own_fields() -> None:
    configured = setup("pola-wizyta", people=1, need=1, choice="none")
    with tenant(configured["owner"]):
        pet = field(configured["service"].id, "Imię pupila", mandatory=True)
    client = APIClient()
    assert errors(book(client, configured, "pola-w1")) == [(f"answers.{pet.id}", "field_required")]
    made = book(client, configured, "pola-w2", answers=answers((pet, "Reksio")))
    assert made.status_code == 201, made.content
    with tenant(configured["owner"]):
        visit = Appointment.all_objects.get(pk=made.json()["id"])
        assert [(line["name"], line["value"]) for line in visit.form_answers] == [
            ("Imię pupila", "Reksio")
        ]
        too_long = "x" * 201
    refused_long = book(client, configured, "pola-w3", answers=answers((pet, too_long)))
    assert errors(refused_long) == [(f"answers.{pet.id}", "field_too_long")]


def test_the_office_answers_what_the_form_asks_and_answers_are_read_like_the_phone() -> None:
    configured = form("pola-zespol", priced=False, units=2)
    owner = configured["owner"]
    asked = asked_of(configured)
    with tenant(owner):
        # Whoever books without the panel's dialog — a product through
        # `booking.api`, a seed — shows no form and is asked for nothing.
        bare = stay(
            configured, configured["first"], configured["first"] + timedelta(days=2)
        ).appointment
        assert bare.form_answers == []

    client = authenticated_client(owner)

    def office(**body: Any) -> Any:
        return client.post(
            "/api/v1/booking/stays/",
            {
                **configured["target"],
                "start_date": _later(configured, 7),
                "end_date": _later(configured, 9),
                "customer": {"display_name": "Jan Telefoniczny", "phone": "+48 600 000 111"},
                **body,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=key(),
        )

    # The panel's dialog shows the offer's fields: the office answers the
    # mandatory ones for the caller — but never ticks a consent for them.
    assert errors(office()) == [(f"answers.{asked['licence'].id}", "field_required")]
    ticked = office(answers=answers((asked["licence"], LICENCE), (asked["rules"], "true")))
    assert errors(ticked) == [("answers", "field_unknown")]
    made = office(answers=answers((asked["licence"], LICENCE), (asked["frame"], "Damska")))
    assert made.status_code == 201, made.content
    booking_id = made.json()["id"]
    assert [(line["name"], line["value"]) for line in made.json()["form_answers"]] == [
        ("Numer prawa jazdy", LICENCE),
        ("Rama", "Damska"),
    ]
    with tenant(owner):
        assert not ConsentRecord.all_objects.filter(organization=owner.organization).exists()

    def read(member: Any) -> list[dict[str, Any]]:
        response = authenticated_client(member).get(
            "/api/v1/booking/appointments/",
            {"from": _later(configured, 0), "to": _later(configured, 30)},
        )
        assert response.status_code == 200, response.content
        (found,) = [item for item in response.json()["items"] if item["id"] == booking_id]
        return list(found["form_answers"])

    assert [(line["name"], line["value"]) for line in read(owner)] == [
        ("Numer prawa jazdy", LICENCE),
        ("Rama", "Damska"),
    ]
    # Somebody of the company who does not see the customer's phone does not
    # see what the customer answered either.
    assert read(worker(owner, "pola-nie-widzi@example.test")) == []


def test_the_office_answers_a_visits_fields_too() -> None:
    configured = setup("pola-wizyta-biuro", people=1, need=1, choice="none")
    owner = configured["owner"]
    with tenant(owner):
        pet = field(configured["service"].id, "Imię pupila", mandatory=True)
        field(configured["service"].id, "Znam regulamin", kind="consent", mandatory=True)
    client = authenticated_client(owner)
    times = (
        APIClient()
        .get(
            f"{configured['url']}/times/",
            {**configured["query"], "date": configured["day"].isoformat()},
        )
        .json()["items"]
    )

    def office(**body: Any) -> Any:
        return client.post(
            "/api/v1/booking/appointments/",
            {
                **configured["query"],
                "starts_at": times[0]["starts_at"],
                "customer": {"display_name": "Anna Telefoniczna", "phone": "+48 600 000 222"},
                **body,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=key(),
        )

    # The mandatory question is the office's to ask; the consent is not.
    assert errors(office()) == [(f"answers.{pet.id}", "field_required")]
    made = office(answers=answers((pet, "Reksio")))
    assert made.status_code == 201, made.content
    assert [(line["name"], line["value"]) for line in made.json()["form_answers"]] == [
        ("Imię pupila", "Reksio")
    ]


def _later(configured: dict[str, Any], days: int) -> str:
    return str((configured["first"] + timedelta(days=days)).isoformat())


def test_answers_leave_with_the_customer_and_the_journal_stays() -> None:
    configured = form("pola-anonim", priced=False)
    owner = configured["owner"]
    asked = asked_of(configured)
    made = booked(
        APIClient(),
        configured,
        answers=answers((asked["licence"], LICENCE), (asked["rules"], "true")),
    )
    assert made.status_code == 201, made.content
    with tenant(owner):
        booking = Appointment.all_objects.get(pk=made.json()["id"])
        assert booking.form_answers
        anonymize_customer(booking.customer_id)
        booking.refresh_from_db()
        assert booking.form_answers == []
        # The journal names nobody and keeps the evidence of what was agreed to.
        assert ConsentRecord.all_objects.filter(
            source_reference=str(booking.id), kind="field"
        ).exists()


@pytest.mark.parametrize(
    ("preset_id", "locales", "name", "mandatory", "other"),
    [
        ("core.lodging", ["pl", "en"], "Przybliżona godzina przyjazdu", False, "en"),
        ("core.care_stay", ["en", "pl"], "Who or what we look after", True, "pl"),
        ("core.care_stay", ["pl"], "Kogo lub co przyjmujemy", True, None),
    ],
)
def test_a_preset_brings_what_its_form_asks_and_a_draft_takes_it_back(
    preset_id: str, locales: list[str], name: str, mandatory: bool, other: str | None
) -> None:
    owner = membership(f"pola-wzorzec-{preset_id.rpartition('.')[2].replace('_', '-')}")
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=locales)
    with tenant(owner):
        # A preview makes nothing, fields included.
        apply_preset(preset_id=preset_id, name="Oferta", preview=True)
        assert not FormField.all_objects.filter(organization=owner.organization).exists()
        draft = apply_preset(preset_id=preset_id, name="Oferta", idempotency_key=key())
        (asked,) = FormField.all_objects.filter(service_id=draft.item_id)
        assert asked.name.startswith(name)
        assert (asked.kind, asked.mandatory, asked.active) == ("text", mandatory, True)
        rows = {row.locale: row for row in FormFieldTranslation.all_objects.filter(field=asked)}
        assert list(rows) == ([other] if other else [])
        if other:
            # Said by the template: a person or the engine may replace it.
            assert rows[other].provenance["name"]["origin"] == "template"
        discard_draft(service_id=draft.item_id, idempotency_key=key())
        assert not Service.all_objects.filter(pk=draft.item_id).exists()
        assert not FormField.all_objects.filter(organization=owner.organization).exists()
        assert not FormFieldTranslation.all_objects.filter(organization=owner.organization).exists()


def test_a_rental_from_the_preset_asks_nothing_by_itself() -> None:
    """A licence number is a car rental's own question (the owner's decision
    of 2026-10-07, data minimisation): the preset in use brings no field, and
    the version that did stays what it was for whoever names it."""
    owner = membership("pola-wzorzec-wypozyczalnia")
    with tenant(owner):
        latest = apply_preset(preset_id="core.rental", name="Rowery", idempotency_key=key())
        assert latest.value.service.preset_version == 5
        assert not FormField.all_objects.filter(service_id=latest.item_id).exists()
        # A published version is never changed: version 4 still asks.
        earlier = apply_preset(
            preset_id="core.rental", version=4, name="Auta", idempotency_key=key()
        )
        (asked,) = FormField.all_objects.filter(service_id=earlier.item_id)
        assert (asked.name, asked.mandatory) == ("Numer prawa jazdy", False)


def test_the_form_marks_a_picture_a_model_made() -> None:
    configured = form("pola-zdjecia-ai", priced=False, units=1)
    owner = configured["owner"]
    (unit,) = configured["units"]
    generated, taken = picture(owner, name="ai"), picture(owner, name="foto")
    MediaAsset.all_objects.filter(pk=generated.id).update(
        ai_origin=AiOrigin.GENERATED, width=1600, height=1200
    )
    change(owner, unit, public=True, photo_ids=[generated.id, taken.id])
    (offer,) = APIClient().get(f"{configured['url']}/").json()["stays"]
    (group,) = offer["groups"]
    assert [
        (photo["id"], photo["ai_generated"], photo["width"], photo["height"])
        for photo in group["photos"]
    ] == [
        (str(generated.id), True, 1600, 1200),
        (str(taken.id), False, taken.width or 0, taken.height or 0),
    ]
