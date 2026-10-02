"""seed_demo: demo data for a staging stack, and the locks around it."""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.demo import run_demo
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.models import Appointment, Service, StaffMember
from saas_core.modules.shared.inventory.models import (
    InventoryBalance,
    InventoryItem,
    StockDocument,
    StockLocation,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Demo-Test-Haslo-2026"
ZONE = ZoneInfo("Europe/Warsaw")


def tomorrow_morning() -> datetime:
    """A run "at 6:00 tomorrow": every demo visit lies ahead of the real clock."""
    day = timezone.now().astimezone(ZONE).date() + timedelta(days=1)
    return datetime.combine(day, time(6, 0), tzinfo=ZONE)


def counts() -> dict[str, int]:
    organization = Organization.objects.get(slug="studio-testowe")
    return {
        "memberships": Membership.objects.filter(organization=organization).count(),
        "people": StaffMember.all_objects.filter(organization=organization).count(),
        "services": Service.all_objects.filter(organization=organization).count(),
        "visits": Appointment.all_objects.filter(organization=organization).count(),
        "vacancies": Appointment.all_objects.filter(
            organization=organization, needs_assignment=True
        ).count(),
        "items": InventoryItem.all_objects.filter(
            organization=organization, sku__startswith="DEMO-"
        ).count(),  # noqa: E501
        "documents": StockDocument.all_objects.filter(
            organization=organization, status="posted"
        ).count(),
        "personal_stock": StockLocation.all_objects.filter(
            organization=organization, kind="person"
        ).count(),
    }


def test_the_seed_builds_a_business_demo_and_a_second_run_adds_nothing() -> None:
    lines: list[str] = []
    run_demo(password=PASSWORD, log=lines.append, now=tomorrow_morning())
    first = counts()

    assert first == {
        "memberships": 3,
        "people": 3,
        "services": 2,
        "visits": 9,
        "vacancies": 2,
        "items": 4,
        "documents": 5,
        "personal_stock": 2,
    }
    owner = User.objects.get(email="wlasciciel@saas.test")
    assert owner.status == UserStatus.ACTIVE
    assert owner.check_password(PASSWORD)
    organization = Organization.objects.get(slug="studio-testowe")
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert snapshot.features.get("booking.enabled") is True
    assert snapshot.subscription_state == "active"
    # What the staff member was given, less what they used, is on their shelf.
    staff_stock = StockLocation.all_objects.get(
        organization=organization, holder=User.objects.get(email="pracownik@saas.test")
    )
    held = {
        row.item.name: row.quantity
        for row in InventoryBalance.all_objects.filter(location=staff_stock).select_related("item")
    }
    assert held["Rękawiczki nitrylowe M (100 szt.)"] == 1
    assert held["Płyn do dezynfekcji 1 l"] == 1

    run_demo(password=PASSWORD, log=lines.append, now=tomorrow_morning())
    assert counts() == first


def test_an_item_whose_category_the_profile_lacks_goes_without_one(monkeypatch) -> None:
    # A product's organization type has its own categories (HoofCare: blocks,
    # dressings): the Business demo's "material" must not stop the seed there.
    from saas_core.modules.shared.inventory import demo as warehouse  # noqa: PLC0415

    data = {**warehouse.BUSINESS, "items": [dict(item) for item in warehouse.BUSINESS["items"]]}
    data["items"][3]["category"] = "nie-ma-takiej"
    monkeypatch.setattr(warehouse, "BUSINESS", data)
    run_demo(password=PASSWORD, log=lambda line: None, now=tomorrow_morning())
    gloves = InventoryItem.all_objects.get(sku="DEMO-GLV")
    assert gloves.category is None


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
    assert not Organization.objects.filter(slug="studio-testowe").exists()


def test_the_password_comes_from_stdin_and_is_never_short(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_SEED_ENABLED", "1")
    monkeypatch.delenv("DEMO_SEED_PASSWORD", raising=False)
    monkeypatch.delenv("DEMO_SEED_PASSWORD_FILE", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("krotkie\n"))
    with pytest.raises(CommandError, match="co najmniej 12"):
        call_command("seed_demo", "--password-stdin")

    monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\n"))
    output = io.StringIO()
    call_command("seed_demo", "--password-stdin", stdout=output)
    assert "Dane demo gotowe." in output.getvalue()
    assert User.objects.get(email="kierownik@saas.test").check_password(PASSWORD)


@pytest.mark.skipif(
    "shared.farms" not in settings.ACTIVE_MODULES,
    reason="rejestr gospodarstw istnieje tylko w profilu, który go składa",
)
def test_a_product_scenario_links_a_farm_to_the_company(monkeypatch) -> None:
    from saas_core.modules.core.organizations import demo
    from saas_core.modules.shared.farms.models import Farm, FarmShare

    scenario = demo.DemoScenario(
        organizations=(
            demo.DemoOrganization(
                key="firma",
                name="Firma Demo",
                slug="firma-demo",
                owner=demo.DemoPerson("szef@firma.test", "Szef", "Firmy"),
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
    run_demo(password=PASSWORD, log=lines.append, now=tomorrow_morning())
    run_demo(password=PASSWORD, log=lines.append, now=tomorrow_morning())

    company = Organization.objects.get(slug="firma-demo")
    card = Farm.all_objects.get(organization=company, name="Gospodarstwo Demo")
    assert FarmShare.objects.filter(company_farm_id=card.id, status="active").count() == 1
    assert any("połączone z kontem rolnika" in line for line in lines)


def test_a_demo_account_outside_the_test_domain_is_refused(monkeypatch) -> None:
    from saas_core.modules.core.organizations import demo

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
