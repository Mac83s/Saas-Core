"""A message past `NOTIFICATIONS_RETENTION_DAYS` loses its recipient's data,
whoever queued it and whatever became of them — a system sweep in each
company's tenant (found 03.10: the scrub was bound to the sender's 45-day
contract, raised on a message with provider events, and had no test)."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.shared.notifications.models import (
    DataExport,
    ExportStatus,
    NotificationAttempt,
    NotificationMessage,
    PendingTaskRoute,
    ProviderEventInbox,
    ProviderMessageRoute,
)
from saas_core.modules.shared.notifications.security import recipient_digest
from saas_core.modules.shared.notifications.services import (
    Conflict,
    queue_email,
    scrub_notification_message,
)
from saas_core.modules.shared.notifications.tasks import recover_pending, scrub_expired
from test_notifications import membership, tenant

pytestmark = pytest.mark.django_db

CUSTOMER = "klient@example.test"


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )


def mail(member: Membership, key: str, *, age_days: int) -> NotificationMessage:
    """A message to a customer, queued `age_days` ago."""
    with tenant(member):
        message, _ = queue_email(
            recipient_email=CUSTOMER,
            template_key="system.activity",
            template_version=1,
            locale="pl",
            template_context={"display_name": "Jan Kowalski", "message": "Wizyta 12.10"},
            idempotency_key=key,
            causation_id=f"booking:{key}",
        )
        queued = timezone.now() - timedelta(days=age_days)
        NotificationMessage.all_objects.filter(pk=message.pk).update(
            created_at=queued, retention_expires_at=queued + timedelta(days=30)
        )
        message.refresh_from_db()
    return message


def read(member: Membership, message: NotificationMessage) -> NotificationMessage:
    with tenant(member):
        return NotificationMessage.all_objects.get(pk=message.pk)


def test_the_sweep_scrubs_what_is_past_retention_and_only_that() -> None:
    owner = membership(slug="retencja-poczty")
    old = mail(owner, "stara", age_days=31)
    fresh = mail(owner, "nowa", age_days=3)
    with tenant(owner):
        NotificationAttempt.all_objects.create(
            organization_id=owner.organization_id, message=old, number=1, outcome="sent"
        )

    assert scrub_expired() == 1

    scrubbed, kept = read(owner, old), read(owner, fresh)
    assert scrubbed.recipient_email.endswith("@invalid.local")
    assert CUSTOMER not in scrubbed.recipient_email
    # The digest of the address goes with it: nothing leads back to the person.
    assert scrubbed.recipient_hash != recipient_digest(CUSTOMER)
    assert (scrubbed.context, scrubbed.signed_tenant_context) == ({}, "")
    # The delivery log stays: the row, its ids and its attempts.
    assert (scrubbed.idempotency_key, scrubbed.causation_id) == ("stara", "booking:stara")
    with tenant(owner):
        assert NotificationAttempt.all_objects.filter(message=old).count() == 1
    assert (kept.recipient_email, kept.recipient_hash) == (CUSTOMER, recipient_digest(CUSTOMER))
    assert kept.context["display_name"] == "Jan Kowalski"
    # Nothing left to do: a second run finds none.
    assert scrub_expired() == 0


def test_a_message_whose_sender_has_left_the_company_is_scrubbed_too() -> None:
    """The contract the message was queued with is its sender's; the sweep
    does not need it."""
    owner = membership(slug="odszedl")
    old = mail(owner, "po-odejsciu", age_days=40)
    Membership.objects.filter(pk=owner.pk).update(
        status=MembershipStatus.LEFT, revoked_at=timezone.now()
    )

    assert scrub_expired() == 1
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT recipient_email, context FROM notifications_notificationmessage WHERE id = %s",
            [old.pk],
        )
        email, context = cursor.fetchone()
    assert email.endswith("@invalid.local") and context in ({}, "{}")


def test_a_message_with_provider_events_is_scrubbed_with_its_routing() -> None:
    owner = membership(slug="zdarzenia")
    old = mail(owner, "ze-zdarzeniem", age_days=35)
    route = ProviderMessageRoute.objects.create(
        provider_message_id="prov-1",
        organization_id=owner.organization_id,
        message_id=old.pk,
        tenant_context_ciphertext="x",
    )
    ProviderEventInbox.objects.create(
        event_id="evt-1", route=route, status="delivered", payload_digest="d" * 64
    )

    assert scrub_expired() == 1

    assert read(owner, old).context == {}
    assert not ProviderMessageRoute.objects.filter(message_id=old.pk).exists()
    assert not ProviderEventInbox.objects.filter(event_id="evt-1").exists()


def test_each_company_is_read_inside_its_own_tenant_and_one_failure_stops_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = membership(slug="pierwsza"), membership(slug="druga")
    mail(first, "a", age_days=31)
    other = mail(second, "b", age_days=31)

    with CaptureQueriesContext(connection) as queries:
        assert scrub_expired() == 2
    statements = [query["sql"] for query in queries.captured_queries]
    reads = [i for i, sql in enumerate(statements) if "notifications_notificationmessage" in sql]
    tenants = [i for i, sql in enumerate(statements) if "app.organization_id" in sql]
    assert tenants and min(tenants) < min(reads)

    from saas_core.modules.shared.notifications import tasks  # noqa: PLC0415

    again = mail(first, "c", age_days=31)
    later = mail(second, "d", age_days=31)
    real = tasks.scrub_expired_messages

    def failing(organization_id: Any, **kwargs: Any) -> int:
        if organization_id == first.organization_id:
            raise RuntimeError("boom")
        return real(organization_id, **kwargs)

    monkeypatch.setattr(tasks, "scrub_expired_messages", failing)
    assert scrub_expired() == 1
    assert read(first, again).recipient_email == CUSTOMER
    assert read(second, later).context == {} and read(second, other).context == {}


def test_a_leftover_cleanup_route_is_closed_not_retried_and_new_mail_makes_none() -> None:
    owner = membership(slug="trasy")
    message = mail(owner, "trasa", age_days=31)
    assert not PendingTaskRoute.objects.filter(kind="email_cleanup").exists()
    # A route from before the sweep, bound to its sender's contract.
    PendingTaskRoute.objects.create(
        kind="email_cleanup",
        object_key=str(message.pk),
        tenant_context_ciphertext="",
        next_dispatch_at=timezone.now() - timedelta(minutes=1),
    )
    PendingTaskRoute.objects.filter(kind="email").update(completed_at=timezone.now())

    recover_pending()

    route = PendingTaskRoute.objects.get(kind="email_cleanup")
    assert route.completed_at is not None
    assert read(owner, message).recipient_email == CUSTOMER
    assert scrub_expired() == 1


def test_an_export_past_its_expiry_is_emptied_by_the_same_sweep() -> None:
    owner = membership(slug="eksport")
    with tenant(owner):
        export = DataExport.all_objects.create(
            organization_id=owner.organization_id,
            kind="notifications",
            status=ExportStatus.READY,
            content="id,status\n1,sent\n",
            row_count=1,
            idempotency_key="e1",
            signed_tenant_context="x",
            created_by=owner.user,
            expires_at=timezone.now() - timedelta(hours=1),
        )

    assert scrub_expired() == 1
    with tenant(owner):
        emptied = DataExport.all_objects.get(pk=export.pk)
    assert (emptied.content, emptied.status) == ("", ExportStatus.EXPIRED)


def test_a_message_inside_its_retention_cannot_be_scrubbed_by_the_dated_call() -> None:
    owner = membership(slug="za-wczesnie")
    fresh = mail(owner, "swieza", age_days=1)
    with tenant(owner), pytest.raises(Conflict):
        scrub_notification_message(fresh.pk)


def test_the_report_counts_and_changes_nothing() -> None:
    owner = membership(slug="raport")
    old = mail(owner, "do-raportu", age_days=45)
    out = StringIO()

    call_command("notification_retention_report", stdout=out)

    line = out.getvalue().strip()
    assert "wiadomości 1, eksporty 0, firmy 1" in line and "Niczego nie zmieniono." in line
    assert CUSTOMER not in line
    assert read(owner, old).recipient_email == CUSTOMER
