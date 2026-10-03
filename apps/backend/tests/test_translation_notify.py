"""What the company hears and what the operator decides (TL6c-3, ADR-069 pkt 20, 22, 26)."""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO

import pytest
from django.core.management import call_command

from saas_core.modules.core.organizations.models import OrganizationAuditEntry, WorkspaceKind
from saas_core.modules.shared.model_port.adapters.fake import FAKE
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from saas_core.modules.shared.translation import jobs
from saas_core.modules.shared.translation.models import (
    JobState,
    TranslationJob,
    TranslationReviewItem,
)
from saas_core.modules.shared.translation.notify import (
    JOB_PROBLEM,
    REVIEW_WAITING,
    notify_waiting_reviews,
)
from test_booking import tenant
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_sites_ai_badge import operator
from test_translation_jobs import (
    JobSource,
    company,
    german,
    installed_source,
    order,
    page,
    run,
    translator,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    with installed_source(monkeypatch) as installed:
        yield installed


def delivered(mail: NotificationMessage) -> str:
    """The delivery task opens the contract the mail was signed with and sends
    it; a contract it refuses leaves the mail queued for ever, with only a line
    in the security log."""
    from saas_core.modules.shared.notifications.tasks import deliver_email_task  # noqa: PLC0415

    deliver_email_task.run(str(mail.id), mail.signed_tenant_context)
    return str(NotificationMessage.all_objects.get(pk=mail.id).status)


def test_a_job_with_gaps_tells_the_person_who_ordered_it(
    pages: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl6c3-gaps")
    monkeypatch.setattr(
        FAKE, "complete", translator(lambda text: "Call now" if "⟦m:1⟧" in text else german(text))
    )
    job = run(order(owner, [page(pages, "Alfa"), page(pages, "Zadzwoń: +48 600 100 200")]))
    assert job.state == JobState.PARTIAL
    notice = AppNotification.all_objects.get(organization=owner.organization, kind=JOB_PROBLEM)
    assert notice.user_id == owner.user_id
    assert notice.payload == {"job_id": str(job.id), "state": "partial", "count": 2, "written": 1}
    mail = NotificationMessage.all_objects.get(
        organization=owner.organization, template_key=JOB_PROBLEM
    )
    assert mail.recipient_email == owner.user.email
    assert delivered(mail) == "sent"


def test_a_job_that_ends_while_its_holds_are_settled_still_sends_its_mail(
    pages: JobSource,
) -> None:
    """A part that cannot start closes the job inside the settlement's context,
    which no task contract opens: the notice is the organization's own."""
    from saas_core.modules.core.organizations.context import (  # noqa: PLC0415
        activate_tenant_context,
    )
    from saas_core.modules.shared.translation.notify import notify_job_problem  # noqa: PLC0415
    from saas_core.modules.shared.translation.worker import _settlement_context  # noqa: PLC0415

    owner = company("tl6c3-settling")
    job = run(order(owner, [page(pages, "Alfa")]))
    job.state = JobState.FAILED
    with tenant(owner), activate_tenant_context(_settlement_context(job)):
        notify_job_problem(job, written=0, total=1)
    mail = NotificationMessage.all_objects.get(
        organization=owner.organization, template_key=JOB_PROBLEM
    )
    assert delivered(mail) == "sent"


def test_a_clean_job_says_nothing(pages: JobSource) -> None:
    owner = company("tl6c3-clean")
    run(order(owner, [page(pages, "Alfa")]))
    assert not AppNotification.all_objects.filter(organization=owner.organization).exists()


def test_once_a_day_the_managers_hear_what_waits(pages: JobSource) -> None:
    owner = company("tl6c3-digest")
    with tenant(owner):
        for reason in ("review_mode", "review_mode", "legal_document"):
            TranslationReviewItem.all_objects.create(
                organization=owner.organization,
                source_key="testing.pages",
                object_id=owner.id,
                locale="de",
                basis="published",
                basis_version="published:1",
                reason=reason,
            )
    assert notify_waiting_reviews() >= 1
    assert notify_waiting_reviews() == 0
    notice = AppNotification.all_objects.get(organization=owner.organization, kind=REVIEW_WAITING)
    assert notice.payload == {"count": 3, "reasons": {"review_mode": 2, "legal_document": 1}}
    # The sweep has no person behind it: the mail goes as the organization's
    # own job, which delivery has to open.
    mail = NotificationMessage.all_objects.get(
        organization=owner.organization, template_key=REVIEW_WAITING
    )
    assert delivered(mail) == "sent"


def test_the_platforms_content_above_the_threshold_waits_for_the_operator(
    pages: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl6c3-platform")
    organization = owner.organization
    organization.workspace_kind = WorkspaceKind.PLATFORM
    organization.save(update_fields=["workspace_kind"])
    monkeypatch.setattr(jobs, "platform_confirm_usd_micros", lambda: 0)
    job = order(owner, [page(pages, "Alfa")])
    assert (job.billing, job.confirmation_required) == ("platform_budget", True)
    assert job.estimated_usd_micros and job.estimated_usd_micros > 0
    waiting = run(job)
    assert waiting.state == JobState.RUNNING
    staff = operator("tl6c3-platform-op@example.test")
    call_command(
        "translation_confirm_job",
        "--organization",
        str(organization.id),
        "--job",
        str(job.id),
        "--operator",
        staff.email,
        "--reason",
        "Migracja treści Puppily",
        stdout=StringIO(),
    )
    done = run(TranslationJob.all_objects.get(pk=job.id))
    assert done.state == JobState.SUCCEEDED
    assert OrganizationAuditEntry.objects.filter(
        organization=organization, action="translation.job_confirmed"
    ).exists()


def test_the_operator_takes_a_job_back_with_a_reason(pages: JobSource) -> None:
    from saas_core.testing.translation_sources import FakeSourceDriver

    owner = company("tl6c3-revert")
    object_id = page(pages, "Alfa")
    job = run(order(owner, [object_id]))
    assert FakeSourceDriver(pages).public_texts(object_id, "de") == [german("Alfa")]
    staff = operator("tl6c3-revert-op@example.test")
    call_command(
        "translation_revert_job",
        "--organization",
        str(owner.organization_id),
        "--job",
        str(job.id),
        "--operator",
        staff.email,
        "--reason",
        "Skarga klienta",
        stdout=StringIO(),
    )
    assert FakeSourceDriver(pages).public_texts(object_id, "de") is None
    entry = OrganizationAuditEntry.objects.get(
        organization=owner.organization, action="translation.job_reverted"
    )
    assert (entry.actor_user_id, entry.metadata["reason"]) == (staff.id, "Skarga klienta")
