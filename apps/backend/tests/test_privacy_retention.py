"""Removal of personal data after a time (settings plan D1–D2, answer 37a):
off by default and the company's own decision; a preview that says how many
and from which day; a grace period and a mail to the owners; a run that works
company by company inside each one's tenant, takes the person out of every
stored copy and leaves the visits and the statistics; and nothing for a
company that said off."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from celery import current_app
from celery.schedules import crontab
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.core.organizations import retention, settings_registry
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    OrganizationSetting,
)
from saas_core.modules.core.organizations.retention import (
    GRACE_DAYS,
    cutoff_for,
    dry_run,
    months_of,
    register_retention_exclusion,
    run,
)
from saas_core.modules.core.organizations.settings_service import (
    change_settings,
    read_group,
    setting,
)
from saas_core.modules.core.organizations.tasks import run_privacy_retention
from saas_core.modules.shared.booking import retention as booking_retention
from saas_core.modules.shared.booking.models import Appointment, Customer, SelfServiceRoute
from saas_core.modules.shared.booking.retention import customers_due, erase_customers
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.notifications.models import NotificationMessage
from saas_core.modules.shared.notifications.services import queue_email
from saas_core.modules.shared.sites.models import SiteInquiry
from test_booking import catalog, create, membership, tenant
from test_site_inquiries import published_form, submit  # noqa: F401 — a fixture

pytestmark = pytest.mark.django_db

CUSTOMERS = "booking.retention.customers"
INQUIRIES = "sites.retention.inquiries"
NOTICE = "system.retention_scheduled"


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


def past_grace(member: Membership, key: str) -> None:
    """As if the company had made its choice before the grace period."""
    with tenant(member):
        OrganizationSetting.objects.filter(organization_id=member.organization_id, key=key).update(
            updated_at=timezone.now() - timedelta(days=GRACE_DAYS + 1)
        )


def switch_on(member: Membership, months: str = "24") -> None:
    change(member, "booking.retention", customers=months)
    past_grace(member, CUSTOMERS)


def customer(member: Membership, configured: dict[str, Any], name: str, *, ended: int) -> Any:
    """A customer whose only visit ended `ended` months ago (negative: ahead),
    with their notes, the street of the visit and a confirmation mail."""
    booked = create(
        member,
        {key: value for key, value in configured.items() if key != "starts_at"},
        key=f"visit-{name}",
    ).appointment
    end = timezone.now() - timedelta(days=30 * ended)
    with tenant(member):
        person = Customer.all_objects.create(
            organization_id=member.organization_id,
            display_name=name,
            email=f"{name}@example.test",
            phone="+48500100200",
            contact_hash=name.ljust(64, "0"),
        )
        first = booked.customer_id
        Appointment.all_objects.filter(pk=booked.id).update(
            starts_at=end - timedelta(minutes=30),
            ends_at=end,
            customer=person,
            customer_notes="Boli mnie kolano",
            place_address="ul. Polna 3",
            place_town="Olsztyn",
        )
        Customer.all_objects.filter(pk=first).delete()
        queue_email(
            recipient_email=person.email,
            template_key="booking.confirmation",
            template_version=1,
            locale="pl",
            template_context={"organization_name": "Studio", "starts_at": "12.10 10:00"},
            idempotency_key=f"confirm-{name}",
            causation_id=f"booking:{booked.id}",
        )
    person.visit_id = booked.id
    return person


def read_customer(member: Membership, person: Any) -> Customer:
    with tenant(member):
        return Customer.all_objects.get(pk=person.id)


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


def test_nothing_is_due_until_the_company_itself_turns_it_on(settings: Any) -> None:
    owner = membership("retencja-wyl")
    old = customer(owner, catalog(owner), "dawny", ended=40)

    with tenant(owner):
        assert setting(CUSTOMERS) == "off"
        assert setting(INQUIRIES) == "off"
    assert dry_run() == []
    # A value from anywhere but the company's own row never starts a removal.
    settings.SETTINGS_DEFAULTS = {CUSTOMERS: "12"}
    assert dry_run() == [] and run().removed == ()
    assert read_customer(owner, old).email == "dawny@example.test"
    spec = settings_registry.setting_spec(CUSTOMERS)
    assert (spec.product_default, spec.scopes) == (False, ("organization",))


def test_who_is_due_and_the_preview_names_the_count_and_the_day() -> None:
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
    day = (timezone.now() + timedelta(days=GRACE_DAYS)).date()
    assert (effect.kind, effect.resource) == ("erasure_scheduled", "booking.customer")
    assert "dotyczy teraz: 2." in effect.summary["pl"]
    assert "affected now: 2." in effect.summary["en"]
    # The first day anything could go: a week ahead, in the company's calendar.
    assert any(str(day + timedelta(days=shift)) in effect.summary["pl"] for shift in (0, 1)), (
        effect.summary["pl"]
    )
    # A preview saves nothing and mails nobody.
    with tenant(owner):
        assert setting(CUSTOMERS) == "off"
        assert not NotificationMessage.all_objects.filter(template_key=NOTICE).exists()
    change(owner, "booking.retention", customers="24")
    assert change(owner, "booking.retention", preview=True, customers="off").effects == ()


def test_the_owners_are_told_and_nothing_goes_for_a_week() -> None:
    owner = membership("retencja-laska")
    old = customer(owner, catalog(owner), "dawny", ended=25)

    change(owner, "booking.retention", customers="24")

    with tenant(owner):
        (notice,) = NotificationMessage.all_objects.filter(template_key=NOTICE)
    assert notice.recipient_user_id == owner.user_id
    assert (notice.context["months"], notice.context["count"]) == ("24", "1")
    assert notice.context["settings_url"].endswith("/panel/settings/privacy")
    # Inside the grace period the dry run says what waits, and a run takes nothing.
    (waiting,) = dry_run()
    assert (waiting.count, waiting.waits_until is not None) == (1, True)
    assert run().removed == ()
    assert read_customer(owner, old).email == "dawny@example.test"

    # Making it later tells nobody; making it sooner does, and waits again.
    change(owner, "booking.retention", customers="36")
    change(owner, "booking.retention", customers="12")
    with tenant(owner):
        assert NotificationMessage.all_objects.filter(template_key=NOTICE).count() == 2
    assert run().removed == ()

    past_grace(owner, CUSTOMERS)
    (done,) = run().removed
    assert (done.sweep, done.period, done.count) == ("booking.customers", "12 mies.", 1)
    assert read_customer(owner, old).anonymized_at is not None


def test_a_run_takes_the_person_out_of_every_stored_copy_and_leaves_the_visit() -> None:
    owner = membership("retencja-run")
    configured = catalog(owner)
    old = customer(owner, configured, "dawny", ended=25)
    recent = customer(owner, configured, "niedawny", ended=5)
    with tenant(owner):
        # A mail to one of the company's own people about the same visit.
        queue_email(
            recipient_email=owner.user.email,
            recipient_user=owner.user,
            template_key="system.activity",
            template_version=1,
            locale="pl",
            template_context={"display_name": "Anna", "message": "Nowa wizyta"},
            idempotency_key="staff-dawny",
            causation_id=f"booking:{old.visit_id}",
        )
        assert SelfServiceRoute.objects.filter(
            appointment_id=old.visit_id, revoked_at__isnull=True
        ).exists()
    switch_on(owner)

    result = run()

    assert [(item.sweep, item.count) for item in result.removed] == [("booking.customers", 1)]
    assert result.failed == ()
    stripped = read_customer(owner, old)
    assert (stripped.display_name, stripped.email, stripped.phone) == (
        "Zanonimizowany klient",
        "",
        "",
    )
    assert stripped.anonymized_at is not None
    with tenant(owner):
        visit = Appointment.all_objects.get(pk=old.visit_id)
        # The visit stays, with its town; the person's words and street go.
        assert (visit.customer_notes, visit.place_address, visit.place_town) == ("", "", "Olsztyn")
        to_customer = NotificationMessage.all_objects.get(idempotency_key="confirm-dawny")
        to_staff = NotificationMessage.all_objects.get(idempotency_key="staff-dawny")
        assert to_customer.recipient_email.endswith("@invalid.local")
        assert (to_customer.context, to_customer.signed_tenant_context) == ({}, "")
        assert to_staff.recipient_email == owner.user.email
        assert not SelfServiceRoute.objects.filter(
            appointment_id=old.visit_id, revoked_at__isnull=True
        ).exists()
        # One history row for the run: counts, never a person.
        (entry,) = OrganizationAuditEntry.objects.filter(
            organization_id=owner.organization_id, action=retention.RUN_ACTION
        )
        assert entry.metadata == {"sweep": "booking.customers", "period": "24 mies.", "removed": 1}
        assert entry.actor_user_id is None
        kept_mail = NotificationMessage.all_objects.get(idempotency_key="confirm-niedawny")
    kept = read_customer(owner, recent)
    assert (kept.display_name, kept.email) == ("niedawny", "niedawny@example.test")
    assert kept_mail.recipient_email == "niedawny@example.test"
    # Again does nothing, and writes no second history row.
    assert run().removed == ()
    with tenant(owner):
        assert (
            OrganizationAuditEntry.objects.filter(
                organization_id=owner.organization_id, action=retention.RUN_ACTION
            ).count()
            == 1
        )


def test_only_the_company_that_said_so_loses_anything() -> None:
    """Two companies, both with customers long gone; one switched it on."""
    first, second = membership("retencja-a"), membership("retencja-b")
    mine = customer(first, catalog(first), "moj", ended=40)
    theirs = customer(second, catalog(second), "cudzy", ended=40)
    switch_on(first)

    with CaptureQueriesContext(connection) as queries:
        result = run()

    assert [item.organization_id for item in result.removed] == [first.organization_id]
    assert read_customer(first, mine).anonymized_at is not None
    untouched = read_customer(second, theirs)
    assert (untouched.display_name, untouched.email, untouched.phone, untouched.anonymized_at) == (
        "cudzy",
        "cudzy@example.test",
        "+48500100200",
        None,
    )
    with tenant(second):
        visit = Appointment.all_objects.get(pk=theirs.visit_id)
        mail = NotificationMessage.all_objects.get(idempotency_key="confirm-cudzy")
    assert (visit.customer_notes, visit.place_address) == ("Boli mnie kolano", "ul. Polna 3")
    assert mail.recipient_email == "cudzy@example.test"
    # Every statement that writes names its company, and the tenant is set
    # before anything is read.
    statements = [query["sql"] for query in queries.captured_queries]
    writes = [
        sql
        for sql in statements
        if sql.lstrip().upper().startswith("UPDATE")
        and ("booking_customer" in sql or "booking_appointment" in sql)
    ]
    company = first.organization_id
    assert writes and all(
        f"\"organization_id\" = '{company.hex}'" in sql.split(" WHERE ", 1)[1] for sql in writes
    )
    tenants = [i for i, sql in enumerate(statements) if "app.organization_id" in sql]
    reads = [i for i, sql in enumerate(statements) if "booking_customer" in sql]
    assert min(tenants) < min(reads)


def test_a_company_that_switched_it_off_after_the_preview_loses_nothing() -> None:
    owner = membership("retencja-off")
    old = customer(owner, catalog(owner), "dawny", ended=25)
    switch_on(owner, "12")
    assert [item.count for item in dry_run()] == [1]

    change(owner, "booking.retention", customers="off")

    assert dry_run() == [] and run().removed == ()
    assert read_customer(owner, old).email == "dawny@example.test"


def test_one_companys_failure_stops_nobody_and_the_run_takes_a_capped_bite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = membership("retencja-pada"), membership("retencja-dziala")
    configured = catalog(second)
    customer(first, catalog(first), "pechowy", ended=40)
    people = [customer(second, configured, f"dawny{n}", ended=30 + n) for n in range(3)]
    switch_on(first)
    switch_on(second)
    real = booking_retention.erase_customers

    def failing(organization_id: Any, cutoff: Any, limit: int) -> int:
        if organization_id == first.organization_id:
            raise RuntimeError("boom")
        return real(organization_id, cutoff, limit)

    sweep = retention._sweeps["booking.customers"]
    monkeypatch.setitem(
        retention._sweeps,
        "booking.customers",
        retention.RetentionSweep(key=sweep.key, rule=sweep.rule, due=sweep.due, erase=failing),
    )

    result = run(limit=2)

    assert result.failed == (first.organization_id,)
    assert [(item.organization_id, item.count) for item in result.removed] == [
        (second.organization_id, 2)
    ]
    # The rest the next time.
    assert [item.count for item in run(limit=2).removed] == [1]
    assert all(read_customer(second, person).anonymized_at for person in people)
    out = StringIO()
    with pytest.raises(CommandError, match=str(first.organization_id)):
        call_command("privacy_retention", "--run", stdout=out)


def test_a_company_whose_commit_fails_is_failed_and_never_also_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = membership("retencja-commit"), membership("retencja-commit-ok")
    customer(first, catalog(first), "pechowy", ended=40)
    customer(second, catalog(second), "dawny", ended=40)
    switch_on(first)
    switch_on(second)
    entered: list[Any] = []
    set_tenant = retention.set_local_organization_id
    monkeypatch.setattr(
        retention,
        "set_local_organization_id",
        lambda organization_id: (entered.append(organization_id), set_tenant(organization_id)),
    )

    @contextmanager
    def atomic() -> Iterator[None]:
        with transaction.atomic():
            yield
        # The block's work went through; the commit is what fails.
        if entered[-1] == first.organization_id:
            raise OperationalError("could not commit")

    # Only the run's own block: the services inside keep the real one.
    monkeypatch.setattr(retention, "transaction", SimpleNamespace(atomic=atomic))

    result = run()

    assert result.failed == (first.organization_id,)
    assert [item.organization_id for item in result.removed] == [second.organization_id]


def test_a_visit_booked_while_the_run_was_looking_keeps_the_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the first statement found is asked again under the lock."""
    owner = membership("retencja-wyscig")
    configured = catalog(owner)
    old = customer(owner, configured, "dawny", ended=25)
    booked = customer(owner, configured, "wrocil", ended=25)
    with tenant(owner):
        # Committed after the run chose its candidates: a visit ahead.
        Appointment.all_objects.filter(pk=booked.visit_id).update(
            starts_at=timezone.now() + timedelta(days=3),
            ends_at=timezone.now() + timedelta(days=3, minutes=30),
        )
        monkeypatch.setattr(
            booking_retention,
            "customers_due",
            lambda organization_id, cutoff: Customer.all_objects.filter(
                organization_id=organization_id, id__in=[old.id, booked.id]
            ),
        )
        assert erase_customers(owner.organization_id, cutoff_for(24), 10) == 1
    assert read_customer(owner, old).anonymized_at is not None
    assert read_customer(owner, booked).email == "wrocil@example.test"


def test_the_run_locks_the_customers_visits_before_it_decides() -> None:
    """Moving a visit locks the visit, not its customer. So that a visit moved
    ahead while the run works is either waited for and seen, or waits for the
    run: every visit of the locked customers is locked — with no date in the
    filter, a row that does not match yet would not be waited for — after the
    customers and before the first write. One connection cannot hold the
    other side of the race; the order of the statements is the proof here."""
    owner = membership("retencja-przeniesienie")
    customer(owner, catalog(owner), "dawny", ended=25)

    with tenant(owner), CaptureQueriesContext(connection) as queries:
        assert erase_customers(owner.organization_id, cutoff_for(24), 10) == 1

    statements = [query["sql"] for query in queries.captured_queries]

    def locked(model: Any) -> int:
        return next(
            index
            for index, sql in enumerate(statements)
            if f'FROM "{model._meta.db_table}"' in sql and sql.endswith("FOR NO KEY UPDATE")
        )

    first_write = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE"))
    assert locked(Customer) < locked(Appointment) < first_write
    condition = statements[locked(Appointment)].split(" WHERE ")[1].split(" ORDER BY ")[0]
    assert "customer_id" in condition and "ends_at" not in condition


def test_a_booking_after_the_strip_gets_a_new_customer_and_companies_never_share_one() -> None:
    first, second = membership("retencja-nowy"), membership("retencja-inna")
    old = customer(first, catalog(first), "dawny", ended=25)
    switch_on(first)
    assert run().removed

    # The same person books again: a new record, the stripped one stays empty.
    again = create(first, catalog_again(first), key="wraca").appointment
    # Another company's customer with the same e-mail is never this one.
    elsewhere = create(second, catalog(second), key="gdzie-indziej").appointment

    with tenant(first):
        new = Customer.all_objects.get(pk=again.customer_id)
    with tenant(second):
        other = Customer.all_objects.get(pk=elsewhere.customer_id)
    assert new.id != old.id and new.email == "jan@example.test"
    assert (other.organization_id, other.id != new.id) == (second.organization_id, True)
    assert read_customer(first, old).email == ""


def catalog_again(member: Membership) -> dict[str, Any]:
    """The company's catalogue as `catalog()` made it, for another booking."""
    from saas_core.modules.shared.booking.models import (  # noqa: PLC0415
        Location,
        Resource,
        Service,
        StaffMember,
    )

    with tenant(member):
        organization_id = member.organization_id
        return {
            "location": Location.all_objects.get(organization_id=organization_id),
            "staff": StaffMember.all_objects.get(organization_id=organization_id),
            "resource": Resource.all_objects.get(organization_id=organization_id),
            "service": Service.all_objects.get(organization_id=organization_id),
            "date": timezone.localdate() + timedelta(days=7),
        }


def test_a_customer_another_module_still_needs_is_not_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = membership("retencja-wyjatek")
    configured = catalog(owner)
    held = customer(owner, configured, "z-faktura", ended=40)
    free = customer(owner, configured, "bez-faktury", ended=40)
    monkeypatch.setattr(retention, "_exclusions", {})
    register_retention_exclusion("booking.customers", lambda _organization_id: [held.id])
    switch_on(owner)

    assert [item.count for item in run().removed] == [1]
    assert read_customer(owner, held).email == "z-faktura@example.test"
    assert read_customer(owner, free).anonymized_at is not None


def test_the_customers_group_is_offered_only_where_the_profile_says_so(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where a visit hangs on a farm's card the customer stays named there:
    the profile does not offer the setting (`features.customerRetention`)."""
    monkeypatch.setattr(settings_registry, "_groups", {})
    monkeypatch.setattr(settings_registry, "_keys", {})
    monkeypatch.setattr(retention, "_sweeps", {})
    settings.CUSTOMER_RETENTION_OFFERED = False

    booking_retention.register_retention()

    assert settings_registry._groups == {} and retention._sweeps == {}


def test_enquiries_lose_the_person_and_stay_in_the_statistics(published_form: Any) -> None:  # noqa: F811
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
        carried = NotificationMessage.all_objects.filter(causation_id=f"site-inquiry:{first.pk}")
        assert carried and all(m.context["name"] == "Jane Visitor" for m in carried)

    preview = change(member, "sites.retention", preview=True, inquiries="12")
    change(member, "sites.retention", inquiries="12")
    assert "dotyczy teraz: 1." in preview.effects[0].summary["pl"]
    assert "zostają tam" in preview.effects[0].summary["pl"]
    assert run().removed == ()  # the grace period
    past_grace(member, INQUIRIES)

    (done,) = run().removed

    assert (done.sweep, done.count) == ("sites.inquiries", 1)
    with tenant(member):
        erased = SiteInquiry.all_objects.get(pk=first.pk)
        other = SiteInquiry.all_objects.exclude(pk=first.pk).get(organization=organization)
        assert (erased.name, erased.email, erased.phone, erased.message) == ("", "", "", "")
        assert erased.erased_at is not None and erased.page_path == "/"
        assert erased.idempotency_key == f"erased:{erased.pk}"
        # The row stays: the site's statistics still count two enquiries.
        assert SiteInquiry.all_objects.filter(organization=organization).count() == 2
        assert all(
            m.context == {}
            for m in NotificationMessage.all_objects.filter(causation_id=f"site-inquiry:{first.pk}")
        )
        assert other.name == "Jane Visitor" and other.erased_at is None
    # An erased enquiry is not due again, and the panel says what it is.
    assert run().removed == ()
    listed = client.get(f"/api/v1/sites/{site.id}/inquiries/")
    assert listed.status_code == 200, listed.data
    by_id = {str(item["id"]): item for item in listed.data["items"]}
    assert by_id[str(first.pk)]["erased_at"] is not None
    assert by_id[str(first.pk)]["name"] == ""


def test_the_command_counts_or_removes_and_says_which() -> None:
    owner = membership("retencja-cmd")
    old = customer(owner, catalog(owner), "dawny", ended=25)
    switch_on(owner)

    with pytest.raises(CommandError):
        call_command("privacy_retention")
    out = StringIO()
    call_command("privacy_retention", "--dry-run", stdout=out)
    lines = out.getvalue().strip().splitlines()
    assert lines[0].startswith(f"{owner.organization_id}\tbooking.customers\t24 mies.\t")
    assert lines[0].endswith("\t1")
    assert "Niczego nie usunięto." in lines[-1]
    assert read_customer(owner, old).email == "dawny@example.test"

    out = StringIO()
    call_command("privacy_retention", "--run", stdout=out)
    assert f"{owner.organization_id}\tbooking.customers\t24 mies.\tusunięto 1" in out.getvalue()
    assert "dawny" not in out.getvalue().replace("usunięto", "")
    assert read_customer(owner, old).anonymized_at is not None


def test_a_rule_the_platform_sets_runs_through_the_same_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A module whose retention is a platform setting in days — the
    assistant's conversations — registers the same way and needs no job of
    its own; such a rule has no grace period."""
    owner = membership("retencja-platforma")
    monkeypatch.setattr(retention, "_sweeps", {})
    removed: list[tuple[Any, Any, int]] = []
    monkeypatch.setattr(
        "saas_core.modules.core.organizations.platform_settings.platform_setting",
        lambda key: 90,
    )
    retention.register_retention_sweep(
        retention.RetentionSweep(
            key="probe.conversations",
            rule=retention.platform_days("assistant.retention.conversation_days"),
            due=lambda organization_id, cutoff: 3,
            erase=lambda organization_id, cutoff, limit: (
                removed.append((organization_id, cutoff, limit)) or 3
            ),
        )
    )
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)

    found = [item for item in dry_run(now) if item.organization_id == owner.organization_id]
    done = [item for item in run(now).removed if item.organization_id == owner.organization_id]

    assert [(item.period, item.count, item.waits_until) for item in found] == [("90 dni", 3, None)]
    assert [(item.sweep, item.period, item.count) for item in done] == [
        ("probe.conversations", "90 dni", 3)
    ]
    assert (owner.organization_id, now - timedelta(days=90), retention.RUN_LIMIT) in removed


@pytest.mark.parametrize("value", [0, -30, True, "soon"])
def test_a_platform_rule_below_one_day_is_no_rule(
    monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    """Such a rule has no grace period, so zero or less would make everything
    due at once: it is read as no rule, never as a reason to remove."""
    membership("retencja-zero")
    monkeypatch.setattr(retention, "_sweeps", {})
    monkeypatch.setattr(
        "saas_core.modules.core.organizations.platform_settings.platform_setting",
        lambda key: value,
    )
    asked: list[str] = []
    retention.register_retention_sweep(
        retention.RetentionSweep(
            key="probe.conversations",
            rule=retention.platform_days("assistant.retention.conversation_days"),
            due=lambda organization_id, cutoff: asked.append("due") or 5,
            erase=lambda organization_id, cutoff, limit: asked.append("erase") or 5,
        )
    )

    assert dry_run() == []
    assert run() == retention.RunResult(removed=(), failed=())
    assert asked == []


def test_the_run_is_scheduled_once_a_night(settings: Any) -> None:
    entry = settings.CELERY_BEAT_SCHEDULE["privacy-retention-run"]

    assert entry["task"] == run_privacy_retention.name
    assert entry["task"] in current_app.tasks
    # By the clock: an interval would start over with every release.
    assert entry["schedule"] == crontab(hour=2, minute=30)


def test_the_operators_switch_stops_the_scheduled_run_and_not_the_command(settings: Any) -> None:
    owner = membership("retencja-noc")
    old = customer(owner, catalog(owner), "dawny", ended=25)
    switch_on(owner)

    settings.PRIVACY_RETENTION_SCHEDULE_ENABLED = False
    assert run_privacy_retention() == 0
    assert read_customer(owner, old).anonymized_at is None
    out = StringIO()
    call_command("privacy_retention", "--dry-run", stdout=out)
    assert out.getvalue().splitlines()[0].endswith("\t1")

    settings.PRIVACY_RETENTION_SCHEDULE_ENABLED = True
    assert run_privacy_retention() == 1
    assert read_customer(owner, old).anonymized_at is not None
