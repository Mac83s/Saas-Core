"""Removal of personal data after a time (settings plan D1–D2, answer 37a) —
the mechanism without the removal: the settings are off by default, the
preview says how many people a choice reaches, and the dry run counts company
by company, inside each one's tenant. Nothing here may change a record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.core.organizations.retention import cutoff_for, dry_run, months_of
from saas_core.modules.core.organizations.settings_service import (
    change_settings,
    read_group,
    setting,
)
from saas_core.modules.shared.booking.models import Appointment, Customer
from saas_core.modules.shared.booking.retention import customers_due
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.sites.models import SiteInquiry
from test_booking import catalog, create, membership, tenant
from test_site_inquiries import published_form, submit  # noqa: F401 — a fixture

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    cache.clear()
    yield
    cache.clear()


def change(member: Membership, group: str, *, preview: bool = False, **changes: Any) -> Any:
    with tenant(member):
        return change_settings(
            group,
            changes=changes,
            expected_version=read_group(group).version,
            idempotency_key="" if preview else str(uuid4()),
            preview=preview,
        )


def customer(member: Membership, configured: dict[str, Any], name: str, *, ended: int) -> Any:
    """A customer whose only visit ended `ended` months ago (negative: ahead)."""
    booked = create(
        member,
        {key: value for key, value in configured.items() if key != "starts_at"},
        key=f"visit-{name}",
    ).appointment
    end = timezone.now() - timedelta(days=30 * ended)
    with tenant(member):
        Appointment.all_objects.filter(pk=booked.id).update(
            starts_at=end - timedelta(minutes=30), ends_at=end
        )
        person = Customer.all_objects.create(
            organization_id=member.organization_id,
            display_name=name,
            email=f"{name}@example.test",
            contact_hash=name.ljust(64, "0"),
        )
        Appointment.all_objects.filter(pk=booked.id).update(customer=person)
        # The booking helper's own customer: the test database reads past RLS,
        # so another company booking with the same e-mail would find this one.
        Customer.all_objects.filter(pk=booked.customer_id).delete()
    return person


def test_a_cutoff_is_whole_calendar_months_back() -> None:
    assert cutoff_for(12, datetime(2026, 10, 3, 9, tzinfo=UTC)) == datetime(
        2025, 10, 3, 9, tzinfo=UTC
    )
    # The earlier month has no such day: its last one.
    assert cutoff_for(12, datetime(2028, 2, 29, tzinfo=UTC)) == datetime(2027, 2, 28, tzinfo=UTC)
    assert cutoff_for(36, datetime(2026, 1, 31, tzinfo=UTC)) == datetime(2023, 1, 31, tzinfo=UTC)
    assert [months_of(value) for value in ("off", "24", "6", 24, None, "")] == [
        None,
        24,
        None,
        None,
        None,
        None,
    ]


def test_nothing_is_due_until_a_company_turns_it_on() -> None:
    owner = membership("retencja-wyl")
    customer(owner, catalog(owner), "dawny", ended=40)

    with tenant(owner):
        assert setting("booking.retention.customers") == "off"
        assert setting("sites.retention.inquiries") == "off"
    assert dry_run() == []


def test_who_is_due_is_the_customer_without_a_visit_for_longer_and_none_ahead() -> None:
    owner = membership("retencja")
    configured = catalog(owner)
    old = customer(owner, configured, "dawny", ended=25)
    recent = customer(owner, configured, "niedawny", ended=5)
    ahead = customer(owner, configured, "umowiony", ended=-1)
    gone = customer(owner, configured, "zanonimizowany", ended=30)
    with tenant(owner):
        anonymize_customer(gone.id)
        never = Customer.all_objects.create(
            organization_id=owner.organization_id,
            display_name="bez wizyty",
            email="bez@example.test",
            contact_hash="b" * 64,
        )
        Customer.all_objects.filter(pk=never.id).update(
            created_at=timezone.now() - timedelta(days=30 * 26)
        )
        due = set(customers_due(owner.organization_id, cutoff_for(24)).values_list("id", flat=True))

    assert due == {old.id, never.id}
    assert recent.id not in due and ahead.id not in due

    preview = change(owner, "booking.retention", preview=True, customers="24")
    (effect,) = preview.effects
    assert (effect.kind, effect.resource) == ("erasure_scheduled", "booking.customer")
    assert "dotyczy teraz: 2." in effect.summary["pl"]
    assert "affected now: 2." in effect.summary["en"]
    # A preview saves nothing, and off again says nothing.
    with tenant(owner):
        assert setting("booking.retention.customers") == "off"
    change(owner, "booking.retention", customers="24")
    assert change(owner, "booking.retention", preview=True, customers="off").effects == ()


def test_the_dry_run_counts_inside_each_company_and_changes_nothing() -> None:
    owner, other = membership("retencja-a"), membership("retencja-b")
    old = customer(owner, catalog(owner), "dawny", ended=25)
    customer(other, catalog(other), "cudzy", ended=40)
    change(owner, "booking.retention", customers="24")

    with CaptureQueriesContext(connection) as queries:
        found = dry_run()

    assert [(item.organization_id, item.sweep, item.months, item.count) for item in found] == [
        (owner.organization_id, "booking.customers", 24, 1)
    ]
    # The other company never turned it on: its customers are not even read.
    statements = [query["sql"] for query in queries.captured_queries]
    reads = [index for index, sql in enumerate(statements) if "booking_customer" in sql]
    tenants = [index for index, sql in enumerate(statements) if "app.organization_id" in sql]
    assert len(reads) == 1 and tenants and min(tenants) < reads[0]
    assert not any(
        sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT")) for sql in statements
    )
    with tenant(owner):
        kept = Customer.all_objects.get(pk=old.id)
    assert (kept.display_name, kept.email, kept.anonymized_at) == (
        "dawny",
        "dawny@example.test",
        None,
    )


def test_a_company_that_turned_it_off_again_is_not_counted() -> None:
    """The run reads the setting inside the company's own transaction: what a
    preview promised a moment ago binds nobody once the company said off."""
    owner = membership("retencja-off")
    customer(owner, catalog(owner), "dawny", ended=25)
    change(owner, "booking.retention", customers="12")
    assert [item.count for item in dry_run()] == [1]

    change(owner, "booking.retention", customers="off")

    assert dry_run() == []


def test_enquiries_older_than_the_period_are_due(published_form: Any) -> None:  # noqa: F811
    client, organization, owner, site, host = published_form
    assert submit(site, host, key="stare").status_code == 201
    assert submit(site, host, key="nowe", email="nowy@example.test").status_code == 201
    member = Membership.objects.get(organization=organization, user=owner)
    with tenant(member):
        first = SiteInquiry.all_objects.filter(organization=organization).order_by("id").first()
        assert first is not None
        SiteInquiry.all_objects.filter(pk=first.pk).update(
            created_at=timezone.now() - timedelta(days=30 * 13)
        )

    preview = change(member, "sites.retention", preview=True, inquiries="12")
    change(member, "sites.retention", inquiries="12")
    found = dry_run()

    assert "dotyczy teraz: 1." in preview.effects[0].summary["pl"]
    assert "zostają tam" in preview.effects[0].summary["pl"]
    assert [(item.sweep, item.months, item.count) for item in found] == [("sites.inquiries", 12, 1)]
    with tenant(member):
        assert SiteInquiry.all_objects.filter(organization=organization).count() == 2


def test_the_command_only_counts() -> None:
    owner = membership("retencja-cmd")
    customer(owner, catalog(owner), "dawny", ended=25)
    change(owner, "booking.retention", customers="24")

    with pytest.raises(CommandError, match="tylko liczy"):
        call_command("privacy_retention")
    out = StringIO()
    call_command("privacy_retention", "--dry-run", stdout=out)

    lines = out.getvalue().strip().splitlines()
    assert lines[0].startswith(f"{owner.organization_id}\tbooking.customers\t24 mies.\t")
    assert lines[0].endswith("\t1")
    assert "Niczego nie usunięto." in lines[-1]
