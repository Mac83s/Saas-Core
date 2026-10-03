"""What a customer agrees to while booking (phase 4c; ADR-073 §9): the public
form shows the company's documents in force in the booking's language, and a
booking appends its lines to the consent journal in its own transaction."""

from __future__ import annotations

import hashlib
from datetime import time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.booking.consents import (
    DOCUMENT_STATEMENTS,
    SOURCE,
    BookingConsents,
    DocumentsChanged,
)
from saas_core.modules.shared.booking.models import Appointment, PublicBookingRoute
from saas_core.modules.shared.booking.periods import book_stay
from saas_core.modules.shared.booking.services import create_appointment
from saas_core.modules.shared.customers.api import Customer, current_document
from saas_core.modules.shared.customers.documents import add_text, read_document
from saas_core.modules.shared.customers.models import ConsentRecord
from test_booking import company_today, tenant
from test_booking_slots import at, team
from test_booking_stays import cottages, saturday_after
from test_customers_documents import approved, company, stepped_up, with_second_factor

pytestmark = pytest.mark.django_db

TERMS = "booking_terms"
PRIVACY = "privacy_policy"
TERMS_TEXT = "Wizytę można odwołać najpóźniej dzień wcześniej."
PRIVACY_TEXT = "Administratorem danych jest Studio."


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def form(slug: str, locales: tuple[str, ...] = ("pl", "en")) -> dict[str, Any]:
    """A company with a public booking form and somebody who may approve
    its documents."""
    owner = with_second_factor(company(slug, locales))
    configured = team(owner, people=1, hours=(time(8), time(14)), duration=60)
    PublicBookingRoute.objects.create(public_slug=slug, organization_id=owner.organization_id)
    configured.update(
        owner=owner,
        url=f"/api/v1/booking/public/{slug}",
        day=company_today() + timedelta(days=7),
    )
    return configured


def book(configured: dict[str, Any], key: str, hour: int = 9, **extra: Any) -> Any:
    customer = {"display_name": "Anna", "email": f"{key}@example.test"}
    return APIClient().post(
        f"{configured['url']}/appointments/",
        {
            "service_id": str(configured["service"].id),
            "location_id": str(configured["location"].id),
            "starts_at": at(configured["day"], hour).isoformat(),
            **extra,
            "customer": {**customer, **extra.get("customer", {})},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def shown(configured: dict[str, Any], locale: str | None = None) -> dict[str, Any]:
    answer = APIClient().get(f"{configured['url']}/consents/", {"locale": locale} if locale else {})
    assert answer.status_code == 200
    return answer.json()


def in_force(owner: Membership, kind: str, locale: str = "pl") -> Any:
    with tenant(owner):
        document = current_document(kind, locale)
    assert document is not None
    return document


def in_force_version(owner: Membership, kind: str) -> int:
    """The document's lock, for the next write to it."""
    with tenant(owner):
        return int(read_document(kind)["document"]["version"])


def journal(owner: Membership) -> list[ConsentRecord]:
    return list(
        ConsentRecord.all_objects.filter(organization_id=owner.organization_id).order_by("id")
    )


def test_the_form_shows_the_documents_in_force_in_the_bookings_language() -> None:
    configured = form("zgody-formularz")
    owner: Membership = configured["owner"]
    # Nothing published: nothing to show, and nothing is asked of a booking.
    assert shown(configured) == {"locale": "pl", "documents": []}
    assert book(configured, "bez-dokumentow").status_code == 201
    assert journal(owner) == []

    approved(owner, PRIVACY_TEXT, PRIVACY)
    approved(owner, TERMS_TEXT, TERMS)
    with tenant(owner), stepped_up():
        add_text(
            PRIVACY,
            number=1,
            locale="en",
            text="The controller is Studio.",
            expected_version=in_force_version(owner, PRIVACY),
        )
    terms, privacy = in_force(owner, TERMS), in_force(owner, PRIVACY)
    english = in_force(owner, PRIVACY, "en")

    polish = shown(configured, "pl")
    # The terms first, then the privacy policy: two separate statements.
    assert polish == {
        "locale": "pl",
        "documents": [
            {
                "kind": TERMS,
                "statement": "Akceptuję regulamin",
                "text_id": str(terms.text_id),
                "version": 1,
                "effective_from": terms.effective_from.isoformat(),
                "url": terms.url,
            },
            {
                "kind": PRIVACY,
                "statement": "Zapoznałem się z polityką prywatności",
                "text_id": str(privacy.text_id),
                "version": 1,
                "effective_from": privacy.effective_from.isoformat(),
                "url": privacy.url,
            },
        ],
    }
    # The terms have no English text: an English booking is not shown the
    # Polish ones instead, and is not asked to accept them.
    assert [
        (x["kind"], x["text_id"], x["statement"]) for x in shown(configured, "en")["documents"]
    ] == [(PRIVACY, str(english.text_id), "I have read the privacy policy")]
    # A language the company does not have is booked in its first one.
    assert shown(configured, "de") == polish
    assert shown(configured) == polish
    assert APIClient().get("/api/v1/booking/public/nie-ma-takiej/consents/").status_code == 404


def test_a_customer_books_only_with_the_documents_in_force_and_the_journal_says_so() -> None:
    configured = form("zgody-rezerwacja")
    owner: Membership = configured["owner"]
    approved(owner, TERMS_TEXT, TERMS)
    approved(owner, PRIVACY_TEXT, PRIVACY)
    terms, privacy = in_force(owner, TERMS), in_force(owner, PRIVACY)
    both = {"documents": [str(terms.text_id), str(privacy.text_id)]}

    # Nothing accepted, or one of the two: no booking, and the answer says
    # what to show.
    unseen = book(configured, "nic")
    half = book(configured, "polowa", consents={"documents": [str(terms.text_id)]})
    for refused in (unseen, half):
        assert (refused.status_code, refused.json()["code"]) == (409, "documents_changed")
        assert refused.json()["detail"]["documents"] == shown(configured)["documents"]
    assert not Appointment.all_objects.filter(organization_id=owner.organization_id).exists()
    assert not Customer.all_objects.filter(organization_id=owner.organization_id).exists()
    assert journal(owner) == []

    booked = book(configured, "obie", consents=both)
    assert booked.status_code == 201
    visit = Appointment.all_objects.get(organization_id=owner.organization_id)
    lines = journal(owner)
    assert [
        (x.kind, x.document_text_id, x.text_hash, x.locale, x.granted, x.source, x.source_reference)
        for x in lines
    ] == [
        ("document", terms.text_id, terms.text_hash, "pl", True, SOURCE, str(visit.id)),
        ("document", privacy.text_id, privacy.text_hash, "pl", True, SOURCE, str(visit.id)),
    ]
    assert {x.customer_id for x in lines} == {visit.customer_id}

    # The same key answers the first booking again and writes no second line.
    again = book(configured, "obie", consents=both)
    assert (again.status_code, again.json()["id"]) == (200, booked.json()["id"])
    assert len(journal(owner)) == 2

    # The company approves new terms: what the customer ticked a minute ago
    # is no longer what is in force, and the answer carries the new text.
    approved(owner, TERMS_TEXT + "\n\nZadatek przepada.", TERMS)
    newer = in_force(owner, TERMS)
    assert (newer.version, newer.text_id != terms.text_id) == (2, True)
    stale = book(configured, "stare", hour=11, consents=both)
    assert (stale.status_code, stale.json()["code"]) == (409, "documents_changed")
    assert [x["text_id"] for x in stale.json()["detail"]["documents"]] == [
        str(newer.text_id),
        str(privacy.text_id),
    ]
    fresh = book(
        configured,
        "nowe",
        hour=11,
        consents={"documents": [str(newer.text_id), str(privacy.text_id)]},
    )
    assert fresh.status_code == 201
    assert [x.document_text_id for x in journal(owner)[2:]] == [newer.text_id, privacy.text_id]


def test_the_bookings_language_decides_and_no_other_language_stands_in() -> None:
    configured = form("zgody-jezyk")
    owner: Membership = configured["owner"]
    approved(owner, TERMS_TEXT, TERMS)
    approved(owner, PRIVACY_TEXT, PRIVACY)
    with tenant(owner), stepped_up():
        add_text(
            PRIVACY,
            number=1,
            locale="en",
            text="The controller is Studio.",
            expected_version=in_force_version(owner, PRIVACY),
        )
    polish, english = in_force(owner, PRIVACY), in_force(owner, PRIVACY, "en")

    # Booking in English: the Polish text the customer did not read is not
    # the one they accept.
    wrong = book(
        configured,
        "en-pl",
        customer={"locale": "en"},
        consents={"documents": [str(polish.text_id)]},
    )
    assert (wrong.status_code, wrong.json()["code"]) == (409, "documents_changed")
    assert wrong.json()["detail"]["locale"] == "en"
    booked = book(
        configured,
        "en-en",
        customer={"locale": "en"},
        consents={"documents": [str(english.text_id)]},
    )
    assert booked.status_code == 201
    # One line: the terms have no English text, so nothing was shown or asked.
    assert [(x.document_text_id, x.locale) for x in journal(owner)] == [(english.text_id, "en")]


def test_the_team_books_without_documents_and_a_caller_that_showed_them_is_held_to_them() -> None:
    configured = form("zgody-panel")
    owner: Membership = configured["owner"]
    approved(owner, TERMS_TEXT, TERMS)
    terms = in_force(owner, TERMS)

    def visit(key: str, hour: int, **extra: Any) -> Any:
        return create_appointment(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            starts_at=at(configured["day"], hour),
            customer_data={"display_name": "Jan", "email": "jan@example.test"},
            idempotency_key=key,
            principal_ref="test",
            **extra,
        )

    with tenant(owner):
        # The office books for a customer on the phone: nobody ticked anything.
        visit("biuro", 9)
        assert journal(owner) == []
        # A caller that says it showed the documents is held to the ones in force.
        with pytest.raises(DocumentsChanged):
            visit("produkt-bez", 10, consents=BookingConsents())
        visit("produkt", 10, consents=BookingConsents(documents=(terms.text_id,)))
    assert [x.document_text_id for x in journal(owner)] == [terms.text_id]


def test_a_stay_writes_the_same_lines_and_a_marketing_consent_is_a_line_of_its_own() -> None:
    owner = with_second_factor(company("zgody-pobyt"))
    setup = cottages(owner, units=1)
    approved(owner, TERMS_TEXT, TERMS)
    terms = in_force(owner, TERMS)
    wording = "Chcę dostawać oferty Studia na podany adres e-mail."
    first = saturday_after(30)

    with tenant(owner):
        booked = book_stay(
            service_id=setup["service"].id,
            group_id=setup["group"].id,
            start_date=first,
            end_date=first + timedelta(days=2),
            customer_data={"display_name": "Gość", "email": "gosc@example.test"},
            idempotency_key="pobyt-zgody",
            principal_ref="test",
            consents=BookingConsents(documents=(terms.text_id,), marketing=wording),
        )
    stay = booked.appointment
    assert [
        (x.kind, x.document_text_id, x.text_hash, x.locale, x.source, x.source_reference)
        for x in journal(owner)
    ] == [
        ("document", terms.text_id, terms.text_hash, "pl", SOURCE, str(stay.id)),
        (
            "marketing",
            None,
            hashlib.sha256(wording.encode()).hexdigest(),
            "pl",
            SOURCE,
            str(stay.id),
        ),
    ]


def test_every_document_of_the_form_has_its_statement_in_polish_and_english() -> None:
    assert list(DOCUMENT_STATEMENTS) == [TERMS, PRIVACY]
    for wording in DOCUMENT_STATEMENTS.values():
        assert wording["pl"] and wording["en"]
