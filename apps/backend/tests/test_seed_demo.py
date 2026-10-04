"""seed_demo: demo data for a staging stack, and the locks around it."""

from __future__ import annotations

import io
from collections import Counter
from datetime import datetime, time, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations import demo
from saas_core.modules.core.organizations.demo import DemoRun, run_demo
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationSetting,
)
from saas_core.modules.core.organizations.role_catalog import system_role
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.demo import Catalogue, Plan
from saas_core.modules.shared.booking.demo_data import lodging_stories, studio_stories
from saas_core.modules.shared.booking.models import (
    Appointment,
    BookingClosure,
    BookingRule,
    Extra,
    PresetInterest,
    PriceRule,
    Resource,
    ResourceTranslation,
    Service,
    StaffMember,
)
from saas_core.modules.shared.commerce.demo import demo_iban
from saas_core.modules.shared.commerce.ledger import refund_owed
from saas_core.modules.shared.commerce.models import LedgerEntry, Order, Payment, Refund
from saas_core.modules.shared.commerce.transfer_account import valid
from saas_core.modules.shared.customers.models import (
    ConsentRecord,
    Customer,
    CustomerDocument,
    DocumentText,
)
from saas_core.modules.shared.inventory.models import (
    InventoryBalance,
    InventoryItem,
    StockDocument,
    StockLocation,
)
from saas_core.modules.shared.notifications.models import NotificationMessage
from saas_core.modules.shared.sites.models import (
    Domain,
    Page,
    PageLocaleVersion,
    PageVersion,
    Publication,
    Site,
)
from test_sites_api import CleanTemplateMediaScanner, TemplateMediaStorage

pytestmark = pytest.mark.django_db

PASSWORD = "Demo-Test-Haslo-2026"
ZONE = ZoneInfo("Europe/Warsaw")
#: The core's own three companies are Business's: a product tells its own
#: stories (its vertical module registers them) and tests them itself.
CORE_PROFILE = not any(module.startswith("vertical.") for module in settings.ACTIVE_MODULES)
core_scenario = pytest.mark.skipif(
    not CORE_PROFILE, reason="scenariusz rdzenia (Business) opowiada profil rdzenia"
)


@pytest.fixture(autouse=True)
def media_runtime(monkeypatch: pytest.MonkeyPatch) -> TemplateMediaStorage:
    """The units' pictures go through the media library: its storage and its
    scanner, in memory."""
    storage, scanner = TemplateMediaStorage(), CleanTemplateMediaScanner()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    return storage


@pytest.fixture(autouse=True)
def business_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core's scenario, whatever a product's vertical module registered."""
    monkeypatch.setattr(demo, "_scenario", demo.default_scenario)


def noon_tomorrow() -> datetime:
    """A run „at noon tomorrow”: every reading of the clock in the run is then
    the run's own, whatever the hour the suite is run at."""
    day = timezone.now().astimezone(ZONE).date() + timedelta(days=1)
    return datetime.combine(day, time(12, 0), tzinfo=ZONE)


def seeded(only: list[str] | None = None, lines: list[str] | None = None) -> DemoRun:
    return run_demo(
        password=PASSWORD,
        log=(lines if lines is not None else []).append,
        now=noon_tomorrow(),
        only=only,
    )


#: Every table a run writes to, counted per company: a second run right after
#: the first must leave each count as it was.
COUNTED: tuple[Any, ...] = (
    Membership,
    StaffMember,
    Service,
    Resource,
    PriceRule,
    Extra,
    BookingRule,
    BookingClosure,
    PresetInterest,
    Appointment,
    Customer,
    ConsentRecord,
    CustomerDocument,
    DocumentText,
    Order,
    Payment,
    Refund,
    LedgerEntry,
    NotificationMessage,
    Site,
    Page,
    PageVersion,
    PageLocaleVersion,
    Publication,
    InventoryItem,
    StockDocument,
    OrganizationAuditEntry,
)


def counts() -> dict[str, int]:
    found: dict[str, int] = {"users": User.objects.count()}
    for organization in Organization.objects.order_by("slug"):
        for model in COUNTED:
            manager = getattr(model, "all_objects", model.objects)
            found[f"{organization.slug}:{model.__name__}"] = manager.filter(
                organization=organization
            ).count()
    return found


def statuses(model: Any, organization: Organization) -> Counter[str]:
    return Counter(
        model.all_objects.filter(organization=organization).values_list("status", flat=True)
    )


@core_scenario
def test_three_companies_tell_their_stories_and_a_second_run_changes_nothing() -> None:
    lines: list[str] = []
    run = seeded(lines=lines)
    assert not [line for line in lines if line.startswith("!")], lines
    first = counts()
    now = run.now
    studio, lodging, rental = (
        Organization.objects.get(slug=slug)
        for slug in ("studio-testowe", "domki-nad-jeziorem", "kajaki-krutynia")
    )

    # --- the accounts and what every company has
    owner = User.objects.get(email="wlasciciel@saas.test")
    assert owner.status == UserStatus.ACTIVE and owner.check_password(PASSWORD)
    assert Membership.objects.filter(organization=studio).count() == 3
    for organization in (studio, lodging, rental):
        snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
        assert snapshot.features.get("booking.enabled") is True
        assert snapshot.subscription_state == "active"
        assert organization.public_locales[:2] == ["pl", "en"]
        # Founded long before the run, so its past has somewhere to happen.
        assert organization.created_at < now - timedelta(days=800)
        terms = CustomerDocument.all_objects.get(organization=organization, kind="booking_terms")
        texts = DocumentText.all_objects.filter(organization=organization, version__document=terms)
        assert {text.locale for text in texts} == {"pl", "en"}
        assert all(
            text.text.startswith(("To przykładowy tekst", "This is a demo")) for text in texts
        )
        site = Site.all_objects.get(organization=organization)
        published = site.current_publication.snapshot
        assert {entry["locale"] for page in published["pages"] for entry in page["locales"]} == {
            "pl",
            "en",
        }

    # --- Studio: visits with a price list, a request and a transfer ahead
    visits = Appointment.all_objects.filter(organization=studio)
    assert visits.filter(ends_at__lt=now).count() >= 15
    assert visits.filter(starts_at__gt=now).count() >= 10
    assert set(statuses(Appointment, studio)) >= {
        "confirmed",
        "canceled",
        "pending_request",
        "pending_payment",
    }
    assert visits.filter(needs_assignment=True, starts_at__gt=now).exists()
    assert set(statuses(Order, studio)) >= {
        "awaiting_payment",
        "paid",
        "canceled",
        "refunded",
        "draft",
    }
    consultation = Service.all_objects.get(organization=studio, name="Konsultacja")
    assert consultation.payment_policy == "on_site"
    assert sorted(
        PriceRule.all_objects.filter(service=consultation).values_list("amount_minor", "weekdays")
    ) == [(15000, []), (18000, [5])]
    assert Extra.all_objects.filter(service=consultation, name="Materiały szkoleniowe").exists()
    assert Service.all_objects.get(
        organization=studio, name="Warsztat indywidualny"
    ).confirmation == ("on_request")
    assert Service.all_objects.get(organization=studio, name="Pakiet startowy").payment_policy == (
        "transfer"
    )
    assert PresetInterest.all_objects.filter(
        organization=studio, preset_id="core.group_class"
    ).exists()
    assert BookingClosure.all_objects.filter(
        organization=studio, note__contains="Niepodległości"
    ).exists()
    # One customer anonymised; three whose last visit was over a year ago —
    # what the removal after a time would take, switched off as it is.
    customers = Customer.all_objects.filter(organization=studio)
    assert customers.filter(anonymized_at__isnull=False).count() == 1
    long_ago = [
        customer
        for customer in customers.filter(anonymized_at__isnull=True)
        if max(visit.ends_at for visit in customer.appointments.all()) < now - timedelta(days=366)
    ]
    assert len(long_ago) == 3
    journal = Counter(
        ConsentRecord.all_objects.filter(organization=studio).values_list("kind", flat=True)
    )
    assert journal["document"] > 0 and journal["marketing"] > 0
    assert customers.filter(email="").exists() and customers.exclude(email="").exists()
    # The warehouse of the 30.09 seed is still there.
    staff_stock = StockLocation.all_objects.get(
        organization=studio, holder=User.objects.get(email="pracownik@saas.test")
    )
    held = {
        row.item.name: row.quantity
        for row in InventoryBalance.all_objects.filter(location=staff_stock).select_related("item")
    }
    assert held["Rękawiczki nitrylowe M (100 szt.)"] == 1

    # --- Domki: stays from the preset, with every state of an order
    stay = Service.all_objects.get(organization=lodging, name="Pobyt nad jeziorem")
    assert (stay.preset_id, stay.active, stay.payment_policy) == ("core.lodging", True, "deposit")
    assert stay.deposit_percent == 30 and len(stay.cancellation_refunds) >= 2
    units = Resource.all_objects.filter(organization=lodging)
    assert units.count() == 4
    assert all(unit.public and unit.photos and unit.amenities and unit.city_slug for unit in units)
    assert units.filter(show_exact_location=True, latitude__isnull=False).count() == 1
    assert BookingRule.all_objects.filter(organization=lodging).count() == 2
    assert PriceRule.all_objects.filter(organization=lodging, starts_on__isnull=False).exists()
    assert PriceRule.all_objects.filter(organization=lodging, included_people=4).exists()
    assert PriceRule.all_objects.filter(organization=lodging).exclude(length_discounts=[]).exists()
    assert Extra.all_objects.filter(organization=lodging, kind="security_deposit").exists()
    stays = Appointment.all_objects.filter(organization=lodging)
    assert stays.filter(ends_at__lt=now).exists() and stays.filter(starts_at__gt=now).exists()
    # Somebody is there today: arriving, staying or leaving.
    midnight = now.replace(hour=0, minute=0)
    assert stays.filter(
        starts_at__lt=midnight + timedelta(days=1), ends_at__gt=midnight, status="confirmed"
    ).exists()
    assert set(statuses(Order, lodging)) == {
        "awaiting_payment",
        "partially_paid",
        "paid",
        "refunded",
        "canceled",
    }
    assert Refund.all_objects.filter(organization=lodging).exists()
    # Called off with a settlement: something was paid, part of it is owed back.
    assert any(
        refund_owed(order) > 0
        for order in Order.all_objects.filter(organization=lodging, status="canceled")
    )
    # What a guest reads in another language says where it came from.
    words = ResourceTranslation.all_objects.filter(organization=lodging, locale="en").first()
    assert words is not None and words.provenance["name"]["origin"] == "import"
    body = PageLocaleVersion.all_objects.filter(organization=lodging, locale="en").latest("number")
    assert {unit["provenance"]["origin"] for unit in body.units.values()} == {"import"}
    home = PageVersion.all_objects.filter(organization=lodging).order_by("number")
    assert [version.origin for version in home] == ["template", "save"]

    # --- Kajaki: a rental by the day, from its preset
    rent = Service.all_objects.get(organization=rental, name="Wypożyczenie kajaka")
    assert (rent.preset_id, rent.range_unit, rent.active) == ("core.rental", "day", True)
    assert Resource.all_objects.filter(organization=rental).count() == 4
    assert set(statuses(Order, rental)) >= {"paid", "awaiting_payment", "canceled"}

    # --- the bank accounts are made up: valid numbers of a bank nobody has
    for organization in (studio, lodging, rental):
        number = demo_iban(organization.slug)
        assert valid(number) and number[4:20] == "0" * 16
        assert OrganizationSetting.objects.filter(
            organization=organization, key="commerce.transfer.account_number", value=number
        ).exists()

    # --- few mails, none on the second run, and nothing else changes
    queued = NotificationMessage.all_objects.count()
    assert 0 < queued < 100
    assert all(
        address.endswith(".test")
        for address in NotificationMessage.all_objects.values_list("recipient_email", flat=True)
    )
    again: list[str] = []
    seeded(lines=again)
    assert counts() == first
    assert any("e-maile w tym uruchomieniu: 0" in line for line in again)
    assert not [line for line in again if line.startswith(("!", "+"))], again


def answered(client: APIClient, path: str, **query: str) -> Any:
    response = client.get(path, query)
    assert response.status_code == 200, (path, response.status_code, response.data)
    return response.data


@core_scenario
def test_each_companys_screens_answer_with_its_own_data_only() -> None:
    run = seeded()
    now = run.now
    window = {
        "from": (now - timedelta(days=10)).isoformat(),
        "to": (now + timedelta(days=10)).isoformat(),
    }
    days = {
        "from": (now - timedelta(days=10)).date().isoformat(),
        "to": (now + timedelta(days=20)).date().isoformat(),
    }
    seen: dict[str, set[str]] = {}
    for key, email in (
        ("studio", "wlasciciel@saas.test"),
        ("domki", "domki@saas.test"),
        ("kajaki", "kajaki@saas.test"),
    ):
        organization = run.organizations[key]
        client = APIClient()
        assert (
            client.post(
                "/api/v1/auth/login/", {"email": email, "password": PASSWORD}, format="json"
            ).status_code
            == 200
        )
        client.put(
            "/api/v1/session/active-organization/",
            {"organization_id": str(organization.id)},
            format="json",
        )

        read = partial(answered, client)

        visits = read("/api/v1/booking/appointments/", **window)["items"]
        assert visits, key
        assert {str(row["id"]) for row in visits} <= {
            str(pk)
            for pk in Appointment.all_objects.filter(organization=organization).values_list(
                "id", flat=True
            )
        }
        rows = read("/api/v1/commerce/orders/")["items"]
        assert rows, key
        seen[key] = {str(row["id"]) for row in rows}
        own = {
            str(pk)
            for pk in Order.all_objects.filter(organization=organization).values_list(
                "id", flat=True
            )
        }
        assert seen[key] <= own
        assert read(f"/api/v1/commerce/orders/{next(iter(seen[key]))}/")["lines"]
        setup = read("/api/v1/booking/setup/")
        assert setup["services"] and all(
            str(item["id"])
            in {
                str(pk)
                for pk in Service.all_objects.filter(organization=organization).values_list(
                    "id", flat=True
                )
            }
            for item in setup["services"]
        )
        documents = read("/api/v1/customers/documents/")
        assert any(row["in_force"] for row in documents["documents"]), key
        assert read("/api/v1/booking/presets/")
        assert read("/api/v1/sites/")
        read("/api/v1/booking/requests/")
        read("/api/v1/booking/queue/")
        if key != "studio":
            assert read("/api/v1/booking/occupancy/", **days), key

        # What a visitor gets without an account: the site and the form.
        host = Domain.all_objects.get(organization=organization).hostname
        page = APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host)
        assert page.status_code == 200 and page.data, (key, page.status_code)
        assert (
            APIClient().get("/api/v1/public/site/", {"path": "/en/"}, HTTP_HOST=host).status_code
            == 200
        )
        form = run.links[key]["form"].rsplit("/", 1)[-1]
        catalogue = APIClient().get(f"/api/v1/booking/public/{form}/")
        assert catalogue.status_code == 200, (key, catalogue.status_code)
        if key == "domki":
            assert catalogue.data["stays"]
            unit = Resource.all_objects.filter(organization=organization).first()
            assert unit is not None
            assert (
                APIClient()
                .get("/api/v1/public/site/", {"path": f"/stay/{unit.public_slug}/"}, HTTP_HOST=host)
                .status_code
                == 200
            )
            assert (
                APIClient()
                .get("/api/v1/public/site/", {"path": "/documents/booking-terms/"}, HTTP_HOST=host)
                .status_code
                == 200
            )

    # No company's list names another's order, and another's order is not found.
    assert not seen["studio"] & seen["domki"] and not seen["domki"] & seen["kajaki"]
    client = APIClient()
    client.post(
        "/api/v1/auth/login/", {"email": "kajaki@saas.test", "password": PASSWORD}, format="json"
    )
    client.put(
        "/api/v1/session/active-organization/",
        {"organization_id": str(run.organizations["kajaki"].id)},
        format="json",
    )
    foreign = next(iter(seen["domki"]))
    assert client.get(f"/api/v1/commerce/orders/{foreign}/").status_code == 404


def planned(stories: Any, now: datetime, key: str) -> Plan:
    """The stories as a run at `now` would plan them — nothing is written."""
    run = DemoRun(demo.default_scenario(), password=PASSWORD, log=lambda line: None, now=now)
    run.organizations = {key: SimpleNamespace(timezone="Europe/Warsaw")}  # type: ignore[dict-item]
    plan = Plan(run, key, Catalogue(location=None))  # type: ignore[arg-type]
    stories(plan)
    return plan


def waiting(plan: Plan, now: datetime, first: str, later: set[str]) -> int:
    """How many stories began with `first` by `now` and have none of `later` yet."""
    return sum(
        1
        for story in plan.stories
        if story.steps[0].do in {"booking.visit", "booking.stay"}
        and story.key.startswith(first)
        and story.steps[0].at <= now
        and not any(step.do in later and step.at <= now for step in story.steps[1:])
    )


def test_whenever_the_seed_runs_something_waits_for_an_answer_and_for_a_transfer() -> None:
    monday = datetime(2026, 10, 5, 0, 0, tzinfo=ZONE)
    for hour in range(0, 7 * 24, 3):
        now = monday + timedelta(hours=hour, minutes=20)
        studio = planned(studio_stories, now, "studio")
        answered = {"booking.accept", "booking.decline", "booking.expire"}
        assert waiting(studio, now, "prosba:", answered) >= 1, now
        assert waiting(studio, now, "przelew:", {"commerce.pay", "commerce.lapse"}) >= 1, now
        lodging = planned(lodging_stories, now, "domki")
        paid = {"commerce.pay", "commerce.lapse"}
        assert (
            sum(
                waiting(lodging, now, name, paid)
                for name in ("apartament-pon:", "apartament-sr:", "brzozowy-weekend:")
            )
            >= 1
        ), now


@core_scenario
def test_one_company_is_seeded_when_one_is_asked_for() -> None:
    lines: list[str] = []
    seeded(only=["kajaki"], lines=lines)
    assert list(Organization.objects.values_list("slug", flat=True)) == ["kajaki-krutynia"]
    with pytest.raises(ValueError, match="Nie ma scenariusza nikt; są: studio, domki, kajaki"):
        seeded(only=["nikt"])


@core_scenario
def test_the_list_says_what_a_run_would_make_and_writes_nothing() -> None:
    output = io.StringIO()
    call_command("seed_demo", "--list", stdout=output)
    said = output.getvalue()
    for expected in (
        "studio: Studio Testowe (slug studio-testowe",
        "konto domki@saas.test",
        "wzorzec core.lodging",
        "szablon core.lodging",
        "regulamin rezerwacji — w mocy w językach: pl, en, de",
        "rachunek do przelewów (zmyślony",
    ):
        assert expected in said, expected
    assert not Organization.objects.exists() and not User.objects.exists()
    only = io.StringIO()
    call_command("seed_demo", "--list", "--scenario", "kajaki", stdout=only)
    assert "kajaki: Kajaki Krutynia" in only.getvalue() and "Studio Testowe" not in only.getvalue()


@core_scenario
def test_the_command_ends_with_the_accounts_and_the_click_paths(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_SEED_ENABLED", "1")
    monkeypatch.setenv("DEMO_SEED_PASSWORD", PASSWORD)
    output = io.StringIO()
    call_command("seed_demo", "--scenario", "kajaki", stdout=output)
    said = output.getvalue()
    assert "Dane demo gotowe." in said
    assert "Kajaki Krutynia: kajaki@saas.test (owner)" in said
    # Five paths, each with this stack's own address; the password is not said.
    assert [
        line.strip()[:2]
        for line in said.splitlines()
        if line.strip()[:2] in {"1.", "2.", "3.", "4.", "5."}
    ] == ["1.", "2.", "3.", "4.", "5."]
    assert f"{settings.PUBLIC_SITE_SCHEME}://kajaki-krutynia." in said
    assert "/book/" in said and "/panel/orders" in said
    assert PASSWORD not in said


@core_scenario
@pytest.mark.skipif(
    "shared.translation" not in settings.ACTIVE_MODULES,
    reason="silnik tłumaczeń istnieje tylko w profilu, który go składa",
)
def test_a_company_whose_automation_would_call_a_real_model_is_left_out(monkeypatch) -> None:
    from saas_core.modules.shared.translation import demo as translation_demo

    seeded(only=["kajaki"])
    rental = Organization.objects.get(slug="kajaki-krutynia")
    before = Appointment.all_objects.filter(organization=rental).count()
    monkeypatch.setattr(
        translation_demo,
        "automation_on",
        lambda organization_id, source: organization_id == rental.id,
    )
    lines: list[str] = []
    run_demo(
        password=PASSWORD,
        log=lines.append,
        now=noon_tomorrow() + timedelta(days=3),
        only=["kajaki"],
    )
    assert any("automatyczne tłumaczenia" in line and line.startswith("!") for line in lines)
    assert Appointment.all_objects.filter(organization=rental).count() == before


@core_scenario
@pytest.mark.skipif(
    "shared.translation" not in settings.ACTIVE_MODULES,
    reason="silnik tłumaczeń istnieje tylko w profilu, który go składa",
)
def test_without_the_models_stand_in_no_translation_is_ordered_and_the_run_says_so() -> None:
    from saas_core.modules.shared.translation.models import TranslationJob

    lines: list[str] = []
    seeded(only=["kajaki"], lines=lines)
    assert any("atrapa modelu" in line and "pominięte (1)" in line for line in lines), lines
    assert not TranslationJob.all_objects.exists()


@core_scenario
@pytest.mark.skipif(
    "shared.translation" not in settings.ACTIVE_MODULES,
    reason="silnik tłumaczeń istnieje tylko w profilu, który go składa",
)
def test_where_the_models_stand_in_answers_a_document_waits_for_a_person(
    settings, monkeypatch
) -> None:
    from saas_core.modules.shared.model_port.matrix import MODELS, register_model
    from saas_core.modules.shared.model_port.models import TestDoubleCompany
    from saas_core.modules.shared.model_port.test_double import ECHO_MODEL, echo_profile
    from saas_core.modules.shared.translation.models import TranslationJob

    # A company somebody else made, with the scenario's owner: the seed adds
    # to it, but does not decide for it which model translates.
    owner = User.objects.create_user("wlasciciel@saas.test", PASSWORD, status=UserStatus.ACTIVE)
    studio = Organization.objects.create(name="Studio Testowe", slug="studio-testowe")
    Membership.objects.create(organization=studio, user=owner, role=system_role("", "owner"))

    settings.MODEL_PORT_TEST_DOUBLE = True
    settings.PUBLIC_SITE_SCHEME = "http"
    # The suite runs no AI worker; a stack that translates has one.
    monkeypatch.setattr("saas_core.modules.shared.translation.jobs._availability", lambda: ())
    register_model(echo_profile())
    lines: list[str] = []
    try:
        seeded(only=["kajaki", "studio"], lines=lines)
    finally:
        MODELS.pop(("fake", ECHO_MODEL), None)
    rental = Organization.objects.get(slug="kajaki-krutynia")
    assert TestDoubleCompany.objects.filter(
        organization_id=rental.id, added_by="seed_demo"
    ).exists()
    said = [line for line in lines if "tłumacz" in line]
    assert TranslationJob.all_objects.filter(organization=rental).count() == 1, said
    assert any("Kajaki Krutynia: zlecone atrapie modelu" in line for line in lines), lines
    assert not TestDoubleCompany.objects.filter(organization_id=studio.id).exists()
    assert not TranslationJob.all_objects.filter(organization=studio).exists()
    assert any("Studio Testowe pominięte: firmy, której nie założyły" in line for line in lines)


def test_a_document_of_the_seed_gets_a_language_the_company_added_since() -> None:
    from saas_core.modules.core.organizations.context import set_local_organization_id

    seeded(only=["kajaki"])
    rental = Organization.objects.get(slug="kajaki-krutynia")
    terms = DocumentText.all_objects.filter(
        organization=rental, version__document__kind="booking_terms"
    )
    assert {text.locale for text in terms} == {"pl", "en"}
    if "de" not in settings.SITES_SUPPORTED_LOCALES:
        return
    set_local_organization_id(rental.id)
    Organization.objects.filter(pk=rental.id).update(public_locales=["pl", "en", "de"])
    lines: list[str] = []
    seeded(only=["kajaki"], lines=lines)
    assert {text.locale for text in terms.all()} == {"pl", "en", "de"}
    assert any("dopisane języki de" in line for line in lines)


def test_an_item_whose_category_the_profile_lacks_goes_without_one(monkeypatch) -> None:
    # A product's organization type has its own categories (HoofCare: blocks,
    # dressings): the Business demo's "material" must not stop the seed there.
    from saas_core.modules.shared.inventory import demo as warehouse  # noqa: PLC0415

    data = {**warehouse.BUSINESS, "items": [dict(item) for item in warehouse.BUSINESS["items"]]}
    data["items"][3]["category"] = "nie-ma-takiej"
    monkeypatch.setattr(warehouse, "BUSINESS", data)
    seeded(only=["studio"])
    gloves = InventoryItem.all_objects.get(sku="DEMO-GLV")
    assert gloves.category is None


def test_the_seed_takes_over_neither_somebody_elses_company_nor_an_operator() -> None:
    owner = User.objects.create_user("ktos@inny.test", "Haslo-Inne-2026", status=UserStatus.ACTIVE)
    stranger = Organization.objects.create(name="Cudza", slug="studio-testowe")
    Membership.objects.create(organization=stranger, user=owner, role=system_role("", "owner"))
    with pytest.raises(ValueError, match="należy do kogoś innego"):
        seeded(only=["studio"])
    stranger.slug = "cudza"
    stranger.save(update_fields=["slug"])

    # The first run made the demo owner's account before it stopped; an
    # operator with that address is not reset either.
    operator = User.objects.get(email="wlasciciel@saas.test")
    operator.is_staff = True
    operator.set_password("Haslo-Operatora-2026")
    operator.save()
    with pytest.raises(ValueError, match="nie jest kontem demo"):
        seeded(only=["studio"])
    operator.refresh_from_db()
    assert operator.check_password("Haslo-Operatora-2026")


def test_the_command_refuses_without_the_flag_and_on_production(monkeypatch, settings) -> None:
    monkeypatch.delenv("DEMO_SEED_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_SEED_PASSWORD", PASSWORD)
    with pytest.raises(CommandError, match="DEMO_SEED_ENABLED"):
        call_command("seed_demo")

    monkeypatch.setenv("DEMO_SEED_ENABLED", "1")
    settings.APP_ENV = "production"
    with pytest.raises(CommandError, match="produkcję"):
        call_command("seed_demo")
    settings.APP_ENV = "staging"
    settings.STRIPE_LIVEMODE = True
    with pytest.raises(CommandError, match="produkcję"):
        call_command("seed_demo")
    assert not Organization.objects.exists()


def test_the_password_comes_from_stdin_and_is_never_short(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_SEED_ENABLED", "1")
    monkeypatch.delenv("DEMO_SEED_PASSWORD", raising=False)
    monkeypatch.delenv("DEMO_SEED_PASSWORD_FILE", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("krotkie\n"))
    with pytest.raises(CommandError, match="co najmniej 12"):
        call_command("seed_demo", "--password-stdin")

    monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\n"))
    output = io.StringIO()
    call_command("seed_demo", "--password-stdin", "--scenario", "studio", stdout=output)
    assert "Dane demo gotowe." in output.getvalue()
    assert User.objects.get(email="kierownik@saas.test").check_password(PASSWORD)


@pytest.mark.skipif(
    "shared.farms" not in settings.ACTIVE_MODULES,
    reason="rejestr gospodarstw istnieje tylko w profilu, który go składa",
)
def test_a_product_scenario_links_a_farm_to_the_company(monkeypatch) -> None:
    from saas_core.modules.shared.farms.models import Farm, FarmShare

    scenario = demo.DemoScenario(
        organizations=(
            demo.DemoOrganization(
                key="firma",
                name="Firma Demo",
                slug="firma-demo",
                owner=demo.DemoPerson("szef@firma.test", "Szef", "Firmy"),
                # The farm comes with the company whenever the company is chosen.
                needs=("farma",),
            ),
            demo.DemoOrganization(
                key="farma",
                name="Farma Demo",
                slug="farma-demo",
                owner=demo.DemoPerson("rolnik@farma.test", "Jan", "Rolnik"),
            ),
        ),
        data={
            "farms": {
                "links": [
                    {
                        "company": "firma",
                        "farm": "farma",
                        "card": {
                            "name": "Gospodarstwo Demo",
                            "keeper_name": "Jan Rolnik",
                            "email": "rolnik@farma.test",
                            "village": "Testowo",
                        },
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(demo, "_scenario", lambda: scenario)
    lines: list[str] = []
    seeded(only=["firma"], lines=lines)
    seeded(only=["firma"], lines=lines)

    company = Organization.objects.get(slug="firma-demo")
    card = Farm.all_objects.get(organization=company, name="Gospodarstwo Demo")
    assert FarmShare.objects.filter(company_farm_id=card.id, status="active").count() == 1
    assert any("połączone z kontem rolnika" in line for line in lines)


def test_a_demo_account_outside_the_test_domain_is_refused(monkeypatch) -> None:
    scenario = demo.DemoScenario(
        organizations=(
            demo.DemoOrganization(
                key="firma",
                name="Prawdziwa",
                slug="prawdziwa",
                owner=demo.DemoPerson("ktos@example.com", "Ktoś", "Prawdziwy"),
            ),
        )
    )
    monkeypatch.setattr(demo, "_scenario", lambda: scenario)
    with pytest.raises(ValueError, match=".test"):
        run_demo(password=PASSWORD, log=print)
    assert not Organization.objects.filter(slug="prawdziwa").exists()


def test_a_product_tells_a_story_with_its_own_step(monkeypatch) -> None:
    """What package Y2 builds on: a scenario of its own, a part that plays
    stories, and a step the product registers for what only it knows."""
    told: list[tuple[str, datetime]] = []

    def trim(run: DemoRun, key: str, story: demo.DemoStory, step: demo.DemoStep) -> None:
        told.append((f"{story.key}:{step.data['cows']}", timezone.now()))
        story.memo["trimmed"] = True

    def part(run: DemoRun) -> None:
        now = run.now
        run.play(
            "firma",
            [
                demo.DemoStory(
                    key="wizyta-1",
                    steps=[
                        demo.DemoStep(
                            at=now - timedelta(days=3), do="product.trim", data={"cows": 12}
                        ),
                        demo.DemoStep(
                            at=now + timedelta(days=1), do="product.trim", data={"cows": 5}
                        ),
                        demo.DemoStep(at=now - timedelta(days=1), do="product.unknown"),
                    ],
                )
            ],
        )

    scenario = demo.DemoScenario(
        organizations=(
            demo.DemoOrganization(
                key="firma",
                name="Firma Produktu",
                slug="firma-produktu",
                owner=demo.DemoPerson("szef@produkt.test", "Szef", "Produktu"),
                story="Opowieść produktu.",
                paths=(demo.DemoPath("Kalendarz", "{panel}/panel/calendar"),),
            ),
        )
    )
    monkeypatch.setattr(demo, "_scenario", lambda: scenario)
    monkeypatch.setitem(demo._steps, "product.trim", trim)
    monkeypatch.setitem(demo._parts, "product.part", (500, part, None))
    run = seeded()
    # Only the step whose moment has come is played, at that moment; one of a
    # module that is not composed is passed over.
    assert [name for name, _at in told] == ["wizyta-1:12"]
    assert abs(told[0][1] - (run.now - timedelta(days=3))) < timedelta(seconds=5)
    assert "  1. Kalendarz" in run.guide()
