"""People in the assistant's conversation (ADR-076, uzupełnienie 2026-10-04
„karty osób”): the model works with a handle, the person at the screen reads
a card.

The first test is the one the rest stands on: it takes every request the port
handed to its adapter, turns it into the exact JSON OpenRouter would receive,
and looks for each customer's name, e-mail and phone in it. Only what the
person typed in the same conversation may be there.

The model is the port's scripted fake; the registry, the customers, the
orders and the visits are the real ones.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import uuid7
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.models import Membership, Organization, Role
from saas_core.modules.shared.assistant.models import AssistantMessage
from saas_core.modules.shared.assistant.services import WORKER_SEEN
from saas_core.modules.shared.billing.models import EntitlementSnapshot, Feature
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentStaffAllocation,
    Location,
    Service,
    StaffMember,
)
from saas_core.modules.shared.commerce.models import Order, OrderLine
from saas_core.modules.shared.commerce.names import COMMERCE_ENABLED
from saas_core.modules.shared.customers.models import Customer
from saas_core.modules.shared.customers.services import strip_customer
from saas_core.modules.shared.model_port.adapters.fake import FAKE, FakeReply
from saas_core.modules.shared.model_port.adapters.openrouter import request_body
from saas_core.modules.shared.model_port.matrix import MODELS, ModelProfile, register_model
from saas_core.modules.shared.notifications.security import encrypt_secret
from test_assistant_chat import MODEL, sent_tool_results, talk, tool
from test_booking import tenant
from test_sites_api import PASSWORD, sites_client

pytestmark = pytest.mark.django_db

__all__ = ["talk"]

WARSAW = ZoneInfo("Europe/Warsaw")
HANDLE = re.compile(r"klient:[a-z2-7]{5,}")

#: Three customers nobody types the whole of: two share a surname.
KSAWERY = ("Ksawery Kowalski", "ksawery.kowalski@poczta.test", "+48 601 234 567")
BONIFACY = ("Bonifacy Kowalski", "bonifacy@inna-poczta.test", "512 345 678")
ZENOBIA = ("Zenobia Brzęczyszczykiewicz", "zenobia.b@skrzynka.test", "+48 22 765 43 21")
PEOPLE = (KSAWERY, BONIFACY, ZENOBIA)


@dataclass
class Company:
    client: APIClient
    organization: Organization
    owner: Membership
    customers: dict[str, Customer]
    orders: dict[str, Order]
    visit: Appointment
    request: Appointment
    staff: StaffMember


@pytest.fixture(autouse=True)
def people_chat(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A model for the task and a worker seen; the registry is the real one."""
    register_model(
        ModelProfile(
            adapter="fake",
            model=MODEL,
            capabilities=frozenset({"tools", "zdr", "continuation", "prompt_cache"}),
            forbidden_parameters=frozenset(),
            input_usd_per_mtok=1.0,
            output_usd_per_mtok=5.0,
            context_window=100_000,
            max_output_tokens=16_000,
            probed="2026-10-03",
        )
    )
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_ADAPTER", "fake")
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL", MODEL)
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ("public", "public_personal", "personal")
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    cache.clear()
    cache.set(WORKER_SEEN, 1, 300)
    FAKE.reset()
    yield
    FAKE.reset()
    MODELS.pop(("fake", MODEL), None)


def tomorrow_at(hour: int) -> datetime:
    day = timezone.localdate(timezone=WARSAW) + timedelta(days=1)
    return datetime.combine(day, time(hour), tzinfo=WARSAW)


def _visit(
    organization: Organization,
    customer: Customer,
    service: Service,
    staff: StaffMember,
    location: Location,
    starts: datetime,
    status: str,
) -> Appointment:
    ends = starts + timedelta(minutes=30)
    appointment = Appointment.all_objects.create(
        organization=organization,
        customer=customer,
        service=service,
        staff=staff,
        location=location,
        starts_at=starts,
        ends_at=ends,
        occupied_from=starts,
        occupied_until=ends,
        timezone="Europe/Warsaw",
        service_name=service.name,
        status=status,
        hold_expires_at=(
            timezone.now() + timedelta(hours=12) if status == "pending_request" else None
        ),
        self_service_token_ciphertext=encrypt_secret(uuid7().hex),
        self_service_expires_at=starts,
    )
    AppointmentStaffAllocation.all_objects.create(
        organization=organization,
        appointment=appointment,
        staff=staff,
        occupied_range=(starts, ends),
    )
    return appointment


def _order(organization: Organization, customer: Customer, number: str, gross: int) -> Order:
    order = Order.all_objects.create(
        organization=organization,
        number=number,
        source="booking",
        customer=customer,
        buyer_name=customer.display_name,
        buyer_email=customer.email,
        buyer_phone=customer.phone,
        currency="PLN",
        amounts="gross",
        net_minor=gross,
        gross_minor=gross,
        status="awaiting_payment",
        channel="office",
        version=1,
        placed_at=timezone.now(),
    )
    OrderLine.all_objects.create(
        organization=organization,
        order=order,
        revision=1,
        position=1,
        kind="booking",
        name="Konsultacja",
        customer_name="Konsultacja",
        quantity=1,
        unit_amount_minor=gross,
        net_minor=gross,
        vat_minor=0,
        gross_minor=gross,
        tax_rate="zw",
        source="booking.appointment",
        source_reference=str(uuid7()),
    )
    return order


def company(slug: str) -> Company:
    """A company with three customers: Ksawery and Bonifacy each have an order,
    Zenobia a visit tomorrow at ten, Bonifacy a request that waits."""
    client, organization, user = sites_client(slug=slug, role_key="owner")
    Feature.objects.get_or_create(
        key=COMMERCE_ENABLED, defaults={"name": "Zamówienia", "module": "shared.commerce"}
    )
    features = {"assistant.text.enabled": True, "booking.enabled": True, COMMERCE_ENABLED: True}
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features=features,
        quotas={"credits.monthly": 50},
        sources={
            **{key: {"kind": "plan"} for key in features},
            "credits.monthly": {"kind": "plan"},
        },
    )
    owner = Membership.objects.get(organization=organization, user=user)
    with tenant(owner):
        location = Location.all_objects.create(
            organization=organization, name="Centrum", public_slug="centrum"
        )
        staff = StaffMember.all_objects.create(
            organization=organization, display_name="Ola", public_slug="ola"
        )
        other = StaffMember.all_objects.create(
            organization=organization, display_name="Iga", public_slug="iga"
        )
        service = Service.all_objects.create(
            organization=organization,
            name="Konsultacja",
            public_slug="konsultacja",
            duration_minutes=30,
        )
        customers = {
            name: Customer.all_objects.create(
                organization=organization,
                display_name=name,
                email=email,
                phone=phone,
                contact_hash=uuid7().hex,
            )
            for name, email, phone in PEOPLE
        }
        visit = _visit(
            organization,
            customers[ZENOBIA[0]],
            service,
            staff,
            location,
            tomorrow_at(10),
            "confirmed",
        )
        request = _visit(
            organization,
            customers[BONIFACY[0]],
            service,
            other,
            location,
            tomorrow_at(10) + timedelta(days=9),
            "pending_request",
        )
        orders = {
            KSAWERY[0]: _order(organization, customers[KSAWERY[0]], "R/2026/0001", 15000),
            BONIFACY[0]: _order(organization, customers[BONIFACY[0]], "R/2026/0002", 9000),
        }
    return Company(client, organization, owner, customers, orders, visit, request, staff)


def colleague(
    firm: Company, role_key: str, *, on_visits_of: StaffMember | None = None
) -> APIClient:
    """Somebody else of the same company, signed in."""
    user = User.objects.create_user(
        email=f"{role_key}-{firm.organization.slug}@example.test", password=PASSWORD
    )
    user.status = UserStatus.ACTIVE
    user.save()
    membership = Membership.objects.create(
        organization=firm.organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )
    if on_visits_of is not None:
        StaffMember.all_objects.filter(pk=on_visits_of.pk).update(membership=membership)
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    signed_in = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert signed_in.status_code == 200
    return client


def wire(call_index: int) -> str:
    """The n-th request as OpenRouter would receive it: the adapter's own body,
    serialised as the adapter serialises it."""
    return json.dumps(request_body(FAKE.calls[call_index]), ensure_ascii=False)


def secrets_of(person: tuple[str, str, str]) -> set[str]:
    """Every way a customer's record could show in a request: the name and its
    words, the e-mail and its two halves, the phone as written and as digits."""
    name, email, phone = person
    digits = re.sub(r"\D", "", phone)
    return {
        name,
        *name.split(),
        email,
        *email.split("@"),
        phone,
        digits,
        digits[-9:],
    }


def leaked(text: str, typed: str) -> list[str]:
    """The customers' data found in `text` that the person never typed."""
    found = []
    spaceless = re.sub(r"[\s-]", "", text)
    for person in PEOPLE:
        for secret in secrets_of(person):
            if secret.casefold() in typed.casefold():
                continue
            if secret.casefold() in text.casefold() or (secret.isdigit() and secret in spaceless):
                found.append(secret)
    return sorted(found)


def people_of(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {card["name"]: card for card in item.get("people", [])}


ORDERS_ARGS = {"status": None, "q": None, "page": None, "customer": None}


def tool_outputs(chat: Any) -> list[dict[str, Any]]:
    """Every tool result of the conversation as the model reads it, oldest first."""
    rows = AssistantMessage.all_objects.filter(conversation_id=chat.id, role="tool")
    return [json.loads(row.content) for row in rows.order_by("index")]


def test_nothing_of_a_customer_reaches_the_provider_unless_the_person_typed_it(talk: Any) -> None:
    firm = company("people-wire")
    chat = talk(firm.client)
    day = tomorrow_at(10).date().isoformat()
    typed = (
        "Czy pan Kowalski zapłacił za zamówienie? Podaj mi telefon do klienta z jutrzejszej "
        "wizyty i powiedz, czyja prośba o rezerwację czeka."
    )
    FAKE.script(
        tool("customers_find_v1", {"q": "Kowalski"}, "c1"),
        tool("commerce_orders_read_v1", {**ORDERS_ARGS, "q": "Kowalski"}, "c2"),
        tool("commerce_order_read_v1", {"order_id": None, "number": "R/2026/0001"}, "c3"),
        tool("booking_appointments_read_v1", {"from": day, "to": day}, "c4"),
        tool("booking_requests_read_v1", {}, "c5"),
        FakeReply(text="Dwie osoby o tym nazwisku mają po jednym zamówieniu."),
    )

    assert chat.say(typed).status_code == 202
    assert chat.last()["state"] == "done", chat.last()

    # Six requests left for the provider. Each is checked whole: the prompt,
    # the tools' descriptions, the transcript and every tool result in it.
    assert len(FAKE.calls) == 6
    for index in range(6):
        sent = wire(index)
        assert leaked(sent, typed) == [], f"request {index}"
        # What the person typed is there — it is theirs to say.
        assert "Kowalski" in sent
    # The stored transcript is what the next request is built from, so it is
    # clean in the same way.
    for row in AssistantMessage.all_objects.exclude(role="user"):
        assert leaked(row.content + json.dumps(row.tool_calls, ensure_ascii=False), typed) == []

    # What the model did get: a handle where a person is, and the facts.
    found, listed, one, visits, requests = (result["output"] for result in sent_tool_results(5))
    assert found["total"] == 2
    handles = {person["handle"] for person in found["people"]}
    assert len(handles) == 2 and all(HANDLE.fullmatch(handle) for handle in handles)
    by_number = {order["number"]: order["buyer"] for order in listed["orders"]}
    assert set(by_number) == {"R/2026/0001", "R/2026/0002"}
    assert set(by_number.values()) == handles
    # One person, one handle — whichever tool names them.
    assert one["buyer"] == by_number["R/2026/0001"]
    (visit,) = visits["appointments"]
    assert (visit["service"], visit["starts_at"]) == ("Konsultacja", f"{day}T10:00")
    assert HANDLE.fullmatch(visit["customer"]) and visit["customer"] not in handles
    (request,) = requests["requests"]
    assert request["customer"] == by_number["R/2026/0002"]
    # Hours are the company's wall clock, with no zone beside them to convert by.
    assert "timezone" not in visit and "timezone" not in request
    assert request["starts_at"].endswith("T10:00")


def test_the_person_at_the_screen_reads_a_card_where_the_model_wrote_a_handle(talk: Any) -> None:
    firm = company("people-card")
    chat = talk(firm.client)
    day = tomorrow_at(10).date().isoformat()
    FAKE.script(
        tool("booking_appointments_read_v1", {"from": day, "to": day}),
        FakeReply(text="Jutro jest jedna wizyta."),
    )
    chat.say("Kto przychodzi na jutrzejszą wizytę?")
    handle = tool_outputs(chat)[0]["output"]["appointments"][0]["customer"]
    said = f"Jutro o 10:00 jest wizyta: {handle}. Telefon jest na karcie."
    FAKE.script(FakeReply(text=said))

    chat.say("Podaj telefon do tej osoby.", key="t2")

    answer = chat.last()["items"][-1]
    assert answer["text"] == said
    (card,) = answer["people"]
    assert card == {
        "handle": handle,
        "kind": "customer",
        "name": ZENOBIA[0],
        "email": ZENOBIA[1],
        "phone": ZENOBIA[2],
        "links": [
            {
                "title": {"pl": "Wizyta w kalendarzu", "en": "The visit in the calendar"},
                "href": f"/panel/calendar?view=day&date={day}",
            }
        ],
    }
    # The model was shown the handle and its own words, never the card.
    assert leaked(wire(len(FAKE.calls) - 1), "") == []
    # A handle nobody issued stays plain text: no card can be made up.
    FAKE.script(FakeReply(text="To klient:aaaaa albo klient:1."))
    chat.say("A inni?", key="t3")
    assert chat.last()["items"][-1].get("people", []) == []


def test_a_card_shows_what_the_reader_sees_in_the_panel(talk: Any) -> None:
    firm = company("people-rights")
    # Staff: reads the calendar, plans nothing, sees no orders. Iga is on the
    # visit Bonifacy asked for, not on Zenobia's.
    iga = StaffMember.all_objects.get(organization=firm.organization, display_name="Iga")
    chat = talk(colleague(firm, "staff", on_visits_of=iga))
    first = tomorrow_at(10).date()
    FAKE.script(
        tool(
            "booking_appointments_read_v1",
            {"from": first.isoformat(), "to": (first + timedelta(days=10)).isoformat()},
        ),
        FakeReply(text="Są dwie."),
    )
    chat.say("Jakie wizyty są w najbliższych dniach?")
    zenobia, bonifacy = (
        visit["customer"] for visit in tool_outputs(chat)[0]["output"]["appointments"]
    )
    FAKE.script(FakeReply(text=f"Są dwie: {zenobia} i {bonifacy}."))
    chat.say("Kto?", key="t2")

    cards = people_of(chat.last()["items"][-1])

    # A visit Iga is not on: the name the calendar shows her, no contact.
    assert (cards[ZENOBIA[0]]["email"], cards[ZENOBIA[0]]["phone"]) == (None, None)
    # Her own visit: the contact the calendar gives the people going there.
    assert (cards[BONIFACY[0]]["email"], cards[BONIFACY[0]]["phone"]) == BONIFACY[1:]
    # She reads no orders, so no card of hers links to one.
    assert all("/panel/orders" not in link["href"] for link in cards[BONIFACY[0]]["links"])

    # The owner's conversation about the same person: the contact and the order.
    mine = talk(firm.client)
    FAKE.script(
        tool("commerce_orders_read_v1", {**ORDERS_ARGS, "q": "Bonifacy"}),
        FakeReply(text="Jedno."),
    )
    mine.say("Jakie zamówienia ma Bonifacy?")
    buyer = tool_outputs(mine)[0]["output"]["orders"][0]["buyer"]
    # Another conversation, another handle for the same person.
    assert buyer != bonifacy
    FAKE.script(FakeReply(text=f"Jedno: {buyer}."))
    mine.say("Czyje?", key="t2")
    (card,) = mine.last()["items"][-1]["people"]
    assert (card["name"], card["email"], card["phone"]) == BONIFACY
    assert f"/panel/orders/{firm.orders[BONIFACY[0]].id}" in [
        link["href"] for link in card["links"]
    ]

    # The card is read from the record as it is now: a customer taken out of
    # the company's records is no longer named by an old conversation.
    with tenant(firm.owner):
        strip_customer(
            Customer.all_objects.select_for_update().get(pk=firm.customers[BONIFACY[0]].pk)
        )
    (card,) = mine.last()["items"][-1]["people"]
    assert (card["name"], card["email"], card["phone"]) == ("Zanonimizowany klient", None, None)


def test_a_customer_is_found_as_people_write_and_say_the_name(talk: Any) -> None:
    """Without the Polish letters, and in the case the sentence put the surname in."""
    firm = company("people-words")
    chat = talk(firm.client)
    asked = ["Kowalskiego", "kowalskim", "Brzeczyszczykiewicz", "Zenobii Brzęczyszczykiewiczowi"]
    FAKE.script(
        *(tool("customers_find_v1", {"q": q}, f"c{index}") for index, q in enumerate(asked)),
        tool("customers_find_v1", {"q": "Nowaka"}, "c8"),
        tool("customers_find_v1", {"q": "Kowalczyk"}, "c9"),
        FakeReply(text="Znalezione."),
    )

    chat.say("Znajdź kontakt do Kowalskiego i do Zenobii Brzęczyszczykiewicz")

    genitive, instrumental, plain, dative, nobody, another = (
        result["output"] for result in tool_outputs(chat)
    )
    # Both Kowalskis, whichever case the surname came in — and the same two people.
    assert (genitive["total"], instrumental["total"]) == (2, 2)
    assert {person["handle"] for person in genitive["people"]} == {
        person["handle"] for person in instrumental["people"]
    }
    # One Zenobia, typed without her letters or declined with her first name.
    assert (plain["total"], dative["total"]) == (1, 1)
    assert plain["people"][0]["handle"] == dative["people"][0]["handle"]
    assert plain["people"][0]["matched"] == ["name"]
    # A stem is not a licence: another surname finds nobody.
    assert (nobody["total"], another["total"]) == (0, 0)


def test_a_handle_works_only_in_the_conversation_that_issued_it(talk: Any) -> None:
    firm = company("people-handle")
    chat = talk(firm.client)
    FAKE.script(
        tool("customers_find_v1", {"q": "ksawery.kowalski@poczta.test"}, "c1"),
        tool("customers_find_v1", {"q": "601234567"}, "c2"),
        tool("customers_find_v1", {"q": "Nowak"}, "c3"),
        FakeReply(text="Jest jedna taka osoba."),
    )
    chat.say("Znajdź kontakt: ksawery.kowalski@poczta.test, 601234567 albo Nowak")
    by_mail, by_phone, nobody = (result["output"] for result in tool_outputs(chat))
    # Found by the e-mail and by the phone the person typed — the same person,
    # the same handle; a name nobody has finds nobody.
    (handle,) = {person["handle"] for person in (*by_mail["people"], *by_phone["people"])}
    assert (by_mail["people"][0]["matched"], by_phone["people"][0]["matched"]) == (
        ["email"],
        ["phone"],
    )
    assert (nobody["total"], nobody["people"]) == (0, [])

    # In its own conversation the handle names the person to the server.
    FAKE.script(
        tool("commerce_orders_read_v1", {**ORDERS_ARGS, "customer": handle}, "c4"),
        FakeReply(text="Jedno zamówienie."),
    )
    chat.say("Jakie ma zamówienia?", key="t2")
    own = tool_outputs(chat)[-1]
    assert [order["number"] for order in own["output"]["orders"]] == ["R/2026/0001"]

    def refused_in(conversation: Any, call_id: str) -> dict[str, Any]:
        FAKE.script(
            tool("commerce_orders_read_v1", {**ORDERS_ARGS, "customer": handle}, call_id),
            FakeReply(text="Nie znam tej osoby w tej rozmowie."),
        )
        conversation.say(f"Pokaż zamówienia osoby {handle}")
        (result,) = tool_outputs(conversation)
        return dict(result)

    # In another conversation of the same person it names nobody.
    second = talk(firm.client)
    second.id = second.post("conversations/", {"language": "pl", "kind": "operate"}, key="2").data[
        "id"
    ]
    assert second.id != chat.id
    elsewhere = refused_in(second, "x1")
    assert elsewhere["status"] == "refused"
    assert elsewhere["error"]["code"] == "person_handle_unknown"
    assert [error["field"] for error in elsewhere["error"]["errors"]] == ["customer"]
    # Nor in another company's conversation.
    abroad = refused_in(talk(company("people-other").client), "x2")
    assert (abroad["status"], abroad["error"]["code"]) == ("refused", "person_handle_unknown")
    # A handle a model makes up names nobody either, and shows no card.
    FAKE.script(
        tool("commerce_orders_read_v1", {**ORDERS_ARGS, "customer": "klient:aaaaa"}, "c9"),
        FakeReply(text="Nie ma takiej osoby: klient:aaaaa."),
    )
    chat.say("A zamówienia osoby klient:aaaaa?", key="t3")
    assert tool_outputs(chat)[-1]["error"]["code"] == "person_handle_unknown"
    assert chat.last()["items"][-1].get("people", []) == []
