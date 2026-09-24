"""The customer's reminder is the organization's, not a person's (ADR-058 §7)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.core.organizations.tasks import (
    issue_tenant_task_contract,
    tenant_task_context,
)
from saas_core.modules.shared.booking.availability import available_slots
from saas_core.modules.shared.booking.models import Appointment, ReminderRoute
from saas_core.modules.shared.booking.services import (
    cancel_appointment,
    complete_appointment,
    reschedule_appointment,
)
from saas_core.modules.shared.booking.tasks import dispatch_booking_reminders
from saas_core.modules.shared.notifications.models import NotificationMessage
from saas_core.modules.shared.notifications.security import encrypt_secret
from test_booking import _no_delivery, catalog, create, mails, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)


def reminders(appointment_id: Any) -> list[NotificationMessage]:
    return mails(appointment_id, "booking.reminder")


def due_now(appointment_id: UUID) -> None:
    """Brings the reminder's time forward to now, as the clock eventually would."""
    past = timezone.now() - timedelta(minutes=1)
    ReminderRoute.objects.filter(appointment_id=appointment_id).update(due_at=past)
    Appointment.all_objects.filter(pk=appointment_id).update(reminder_due_at=past)


def slot_after(member: Membership, configured: dict[str, Any], weeks: int) -> datetime:
    """The first slot on the same weekday `weeks` later: the catalogue's rule covers it."""
    day = configured["date"] + timedelta(weeks=weeks)
    with tenant(member):
        return available_slots(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            from_date=day,
            to_date=day,
        )[0].starts_at


def move(member: Membership, appointment_id: UUID, starts_at: datetime, key: str) -> None:
    reschedule_appointment(
        appointment_id=appointment_id,
        starts_at=starts_at,
        idempotency_key=key,
        principal_ref=str(member.user_id),
    )


def revoke(member: Membership) -> None:
    Membership.objects.filter(pk=member.pk).update(
        status=MembershipStatus.REVOKED, revoked_at=timezone.now()
    )


def test_a_reminder_outlives_the_membership_of_whoever_booked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("reminder-leaver")
    appointment = create(member, catalog(member)).appointment
    revoke(member)
    due_now(appointment.id)

    dispatch_booking_reminders()

    [sent] = reminders(appointment.id)
    assert ReminderRoute.objects.get(appointment_id=appointment.id).dispatched_at is not None
    # The mail is signed by the same service, so its delivery survives too.
    with tenant_task_context(
        sent.signed_tenant_context, expected_causation_id=f"email:{sent.id}"
    ) as context:
        assert context.role_key == "booking_reminder"


def test_a_visit_booked_further_ahead_than_the_task_ttl_is_still_reminded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("reminder-far")
    appointment = create(member, catalog(member)).appointment
    due_now(appointment.id)
    # Signed at booking; for a visit eight weeks out the contract is older
    # than the TTL by the time its reminder comes due.
    later = time.time() + settings.TENANT_TASK_CONTEXT_TTL_SECONDS + 86400

    with patch("django.core.signing.time.time", return_value=later):
        dispatch_booking_reminders()

    assert len(reminders(appointment.id)) == 1


def test_a_route_that_no_longer_opens_is_set_aside_instead_of_blocking_the_queue(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _no_delivery(monkeypatch)
    member = membership("reminder-queue")
    appointment = create(member, catalog(member)).appointment
    due_now(appointment.id)
    # Routes from before ADR-058 carry their creator's membership; more of them
    # than one run takes, all due earlier than the live one.
    leaver = membership("reminder-queue-leaver")
    stale = [uuid7() for _ in range(101)]
    with activate_tenant_context(context_from_membership(leaver)):
        signed = {key: issue_tenant_task_contract(causation_id=f"booking:{key}") for key in stale}
    revoke(leaver)
    earlier = timezone.now() - timedelta(hours=1)
    ReminderRoute.objects.bulk_create(
        ReminderRoute(
            appointment_id=key,
            organization_id=leaver.organization_id,
            signed_tenant_context=encrypt_secret(signed[key]),
            due_at=earlier,
        )
        for key in stale
    )
    # Encrypted under a key since rotated: no run will ever decrypt it.
    rotated = ReminderRoute.objects.create(
        appointment_id=uuid7(),
        organization_id=leaver.organization_id,
        signed_tenant_context=Fernet(Fernet.generate_key()).encrypt(b"contract").decode(),
        due_at=earlier,
    )

    with caplog.at_level("WARNING", logger="saas_core.security"):
        dispatch_booking_reminders()
        dispatch_booking_reminders()

    assert len(reminders(appointment.id)) == 1
    assert not ReminderRoute.objects.filter(dispatched_at__isnull=True).exists()
    rejected = [r for r in caplog.records if r.getMessage() == "booking_reminder_route_rejected"]
    assert {r.route_id for r in rejected} == {str(key) for key in [*stale, rotated.pk]}


def test_a_moved_visit_is_reminded_at_its_new_time_and_again_after_every_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("reminder-move")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    next_week, week_after = slot_after(member, configured, 1), slot_after(member, configured, 2)
    due_now(appointment.id)

    with tenant(member):
        move(member, appointment.id, next_week, "move-1")
    dispatch_booking_reminders()

    # The old reminder time has come and gone without a mail.
    assert reminders(appointment.id) == []
    route = ReminderRoute.objects.get(appointment_id=appointment.id)
    lead = timedelta(hours=settings.BOOKING_REMINDER_LEAD_HOURS)
    assert route.due_at == next_week - lead and route.dispatched_at is None

    due_now(appointment.id)
    dispatch_booking_reminders()
    assert len(reminders(appointment.id)) == 1

    # Reminded already, then moved again: the new time gets its own reminder.
    with tenant(member):
        move(member, appointment.id, week_after, "move-2")
    due_now(appointment.id)
    dispatch_booking_reminders()
    first, second = reminders(appointment.id)
    assert first.context["starts_at"] != second.context["starts_at"]

    # Back to a time reminded before: that reminder was for another arming.
    with tenant(member):
        move(member, appointment.id, next_week, "move-3")
    due_now(appointment.id)
    dispatch_booking_reminders()
    assert len(reminders(appointment.id)) == 3


@pytest.mark.parametrize("close", [cancel_appointment, complete_appointment])
def test_a_visit_called_off_or_done_is_not_reminded(
    monkeypatch: pytest.MonkeyPatch, close: Any
) -> None:
    _no_delivery(monkeypatch)
    member = membership(f"reminder-{close.__name__.split('_')[0]}")
    appointment = create(member, catalog(member)).appointment
    due_now(appointment.id)
    with tenant(member):
        close(
            appointment_id=appointment.id,
            idempotency_key="close-1",
            principal_ref=str(member.user_id),
        )

    dispatch_booking_reminders()

    assert reminders(appointment.id) == []
    assert ReminderRoute.objects.get(appointment_id=appointment.id).dispatched_at is not None


def _wait_until_somebody_waits_for_me(seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT count(*) FROM pg_locks "
                "WHERE NOT granted AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
            if cursor.fetchone()[0]:
                return
            time.sleep(0.05)
    pytest.fail("the dispatch never waited on the move's lock")


def test_a_move_committing_during_the_dispatch_keeps_its_new_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run has read the old, due route; the move re-arms it meanwhile.

    Without the lock the run mailed the old time and stamped the moved visit
    as reminded, so its new time was never reminded at all.
    """
    _no_delivery(monkeypatch)
    member = membership("reminder-race")
    configured = catalog(member)
    appointment = create(member, configured).appointment
    next_week = slot_after(member, configured, 1)
    due_now(appointment.id)
    moved = threading.Event()

    def moving() -> None:
        close_old_connections()
        try:
            with tenant(member):
                move(member, appointment.id, next_week, "race-move")
                moved.set()
                _wait_until_somebody_waits_for_me()
        finally:
            moved.set()
            connections.close_all()

    def dispatching() -> int:
        close_old_connections()
        try:
            moved.wait(60)
            return dispatch_booking_reminders()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(moving), executor.submit(dispatching)]
        for outcome in outcomes:
            outcome.result()

    assert reminders(appointment.id) == []
    route = ReminderRoute.objects.get(appointment_id=appointment.id)
    assert route.dispatched_at is None and route.due_at > timezone.now()
    appointment.refresh_from_db()
    assert appointment.reminder_sent_at is None
