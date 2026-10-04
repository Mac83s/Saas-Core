"""Automatic jobs from due demand, and their billing (TL21b, translation-sources.md §8.3).

The pages, the model, credits and the worker are the TL6b test doubles: an
in-memory source behind the real registry and the port's scripted fake.
Demand rows are written directly — recording them is TL21a's test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.shared.billing.models import (
    CreditLedgerEntry,
    CreditLedgerKind,
    EntitlementSnapshot,
)
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from saas_core.modules.shared.translation import automation
from saas_core.modules.shared.translation.automation import (
    CONSENT_LOST,
    CREDITS_EXHAUSTED,
    MONTHLY_LIMIT,
    _next_month,
    automatic_credits_this_month,
    start_due_demand,
)
from saas_core.modules.shared.translation.demand import reconcile_demand
from saas_core.modules.shared.translation.models import (
    JobState,
    TranslationDemand,
    TranslationJob,
    TranslationSettings,
)
from saas_core.modules.shared.translation.notify import AUTOMATION_PAUSED
from saas_core.modules.shared.translation.services import change_settings
from saas_core.modules.shared.translation.settings_spec import demand_wait
from saas_core.testing.clock import never_backwards
from saas_core.testing.translation_sources import FAKE_SCOPE, FakeSourceDriver
from test_booking import tenant
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_tenant_context import authenticated_client
from test_translation_jobs import (
    SOURCE,
    JobSource,
    company,
    german,
    installed_source,
    order,
    page,
    run,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    with installed_source(monkeypatch) as pages:
        yield pages


AUTO = "translation.settings.auto_changes"
LIMIT = "translation.settings.auto_monthly_limit"


def automated(slug: str, *, credits: int = 100, limit: int | None = None) -> Membership:
    owner = company(slug, credits=credits)
    changes: dict[str, object] = {AUTO: True}
    if limit is not None:
        changes[LIMIT] = limit
    with tenant(owner):
        change_settings(changes=changes, expected_version=1, idempotency_key=f"auto-{slug}")
    return owner


def due(owner: Membership, *object_ids: UUID) -> list[TranslationDemand]:
    now = timezone.now()
    return [
        TranslationDemand.all_objects.create(
            organization=owner.organization,
            source_key=SOURCE,
            object_id=object_id,
            cause=f"user:{owner.user_id}",
            first_at=now - timedelta(minutes=10),
            due_at=now - timedelta(minutes=1),
        )
        for object_id in object_ids
    ]


def demand(owner: Membership) -> list[TranslationDemand]:
    return list(TranslationDemand.all_objects.filter(organization=owner.organization))


def test_due_demand_becomes_one_automatic_job_that_publishes_without_a_click(
    source: JobSource,
) -> None:
    owner = automated("tl21-job")
    source.live_locales.add("de")
    first, second = page(source, "Alfa beta"), page(source, "Gamma")
    (opened, _) = due(owner, first, second)
    job_id = start_due_demand(owner.organization_id)
    assert job_id is not None and demand(owner) == []
    job = TranslationJob.all_objects.get(pk=job_id)
    assert (job.trigger, job.cause, job.membership_id) == (
        "automatic",
        f"schedule:{opened.id}",
        owner.id,
    )
    assert run(job).state == JobState.SUCCEEDED
    driver = FakeSourceDriver(source)
    assert driver.public_texts(first, "de") == [german("Alfa beta")]
    assert driver.public_texts(second, "de") == [german("Gamma")]
    created = OrganizationAuditEntry.objects.get(
        organization=owner.organization, action="translation.job_created"
    )
    assert created.metadata["trigger"] == "automatic"


def test_demand_not_yet_due_or_into_no_live_language_starts_nothing(source: JobSource) -> None:
    owner = automated("tl21-idle")
    object_id = page(source, "Alfa")
    (row,) = due(owner, object_id)
    TranslationDemand.all_objects.filter(pk=row.pk).update(
        due_at=timezone.now() + timedelta(minutes=3)
    )
    assert start_due_demand(owner.organization_id) is None
    assert len(demand(owner)) == 1
    # Due, but the company publishes no other language yet: a person adds one.
    TranslationDemand.all_objects.filter(pk=row.pk).update(due_at=timezone.now())
    assert start_due_demand(owner.organization_id) is None
    assert demand(owner) == [] and not TranslationJob.all_objects.exists()


def test_the_automation_pays_whole_thousands_and_carries_the_rest(source: JobSource) -> None:
    owner = automated("tl21-carry")
    source.live_locales.add("de")
    object_id = page(source, "Strzyżenie psów " * 50)  # 799 visible characters
    due(owner, object_id)
    run(TranslationJob.all_objects.get(pk=start_due_demand(owner.organization_id)))
    consumed = CreditLedgerEntry.all_objects.filter(
        organization=owner.organization, kind=CreditLedgerKind.CONSUMED
    )
    assert not consumed.exists()
    settings_row = TranslationSettings.all_objects.get(organization=owner.organization)
    assert settings_row.auto_carry_characters == 799
    # The next change sends 399 more: 1,198 together — a thousand billed, 198 carried.
    driver = FakeSourceDriver(source)
    driver.edit(object_id, 0, "Kąpiel i strzyżenie " * 20)
    driver.publish(object_id)
    due(owner, object_id)
    run(TranslationJob.all_objects.get(pk=start_due_demand(owner.organization_id)))
    (entry,) = consumed
    assert (entry.amount, entry.operation_quantity) == (-2, 1)
    settings_row.refresh_from_db()
    assert settings_row.auto_carry_characters == 1_198 - 1_000


def test_the_settings_say_what_the_automation_spent_this_month(source: JobSource) -> None:
    """TL16e: the panel's „zużyto n z limitu” is the count the limit is held to."""
    owner = automated("tl16e-usage", limit=50)
    source.live_locales.add("de")
    client = authenticated_client(owner)

    def read() -> dict[str, Any]:
        answer = client.get("/api/v1/translation/settings/").json()["automation"]
        return dict(answer)

    assert (read()["month_credits"], read()["consent_name"]) == (0, owner.user.email)
    # 1,599 characters without a click: one thousand billed, the rest carried.
    due(owner, page(source, "Strzyżenie psów " * 100))
    job = run(TranslationJob.all_objects.get(pk=start_due_demand(owner.organization_id)))
    # The part held two thousands and paid for one: its credits are what it
    # paid, not what it held.
    (part,) = job.parts.all()
    assert (part.units, part.settled_units, part.settled_credits) == (2, 1, 2)
    # A clicked order is not the automation's month.
    run(order(owner, [page(source, "Beta")]))
    now = timezone.now()
    answer = read()
    assert answer["month_credits"] == automatic_credits_this_month(owner.organization_id, now) == 2
    assert datetime.fromisoformat(answer["month_resets_at"]) == _next_month(now)
    # The change's own answer carries it too: the panel redraws from it.
    saved = client.patch(
        "/api/v1/translation/settings/",
        {"auto_monthly_limit": 10, "expected_version": 2},
        format="json",
        HTTP_IDEMPOTENCY_KEY="tl16e-usage-limit",
    )
    assert saved.status_code == 200 and saved.json()["automation"]["month_credits"] == 2


def test_a_job_created_just_before_the_clock_steps_back_still_runs(
    source: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What failed the test above once beside a second gate (03.10): the
    machine's clock was stepped back 100 ms between the job's creation and its
    claim, the worker read the job as not yet due and the run did nothing. The
    suite's clock only moves forward (`saas_core.testing.clock`)."""
    owner = automated("tl21-step")
    source.live_locales.add("de")
    due(owner, page(source, "Alfa"))
    step = timedelta(0)
    monkeypatch.setattr(timezone, "now", never_backwards(lambda: datetime.now(UTC) + step))
    create = automation._create_job

    def created_then_stepped_back(*args: Any, **kwargs: Any) -> TranslationJob:
        nonlocal step
        job = create(*args, **kwargs)
        step = timedelta(milliseconds=-100)
        return job

    monkeypatch.setattr(automation, "_create_job", created_then_stepped_back)
    job_id = start_due_demand(owner.organization_id)
    # The run the creation itself hands over is enough: nothing waits for a tick.
    assert TranslationJob.all_objects.get(pk=job_id).state == JobState.SUCCEEDED


def test_the_months_limit_holds_the_demand_until_next_month(source: JobSource) -> None:
    owner = automated("tl21-limit", limit=1)
    source.live_locales.add("de")
    due(owner, page(source, "Alfa"))
    now = timezone.now()
    assert start_due_demand(owner.organization_id, now) is None
    (row,) = demand(owner)
    assert (row.state, row.reason, row.check_at) == ("blocked", MONTHLY_LIMIT, _next_month(now))
    # Blocked demand is not retried before its time.
    assert start_due_demand(owner.organization_id) is None
    assert not TranslationJob.all_objects.exists()


def test_no_credits_blocks_and_a_lost_consent_blocks_or_drops(source: JobSource) -> None:
    owner = automated("tl21-credits", credits=0)
    source.live_locales.add("de")
    object_id = page(source, "Alfa")
    due(owner, object_id)
    assert start_due_demand(owner.organization_id) is None
    assert [(row.state, row.reason) for row in demand(owner)] == [("blocked", CREDITS_EXHAUSTED)]
    paused = NotificationMessage.all_objects.get(
        organization=owner.organization, template_key=AUTOMATION_PAUSED
    )
    assert paused.context["panel_url"].endswith("/panel/settings/credits")
    assert (paused.context["reason_text"], paused.context["link_label"]) == (
        "brakuje kredytów",
        "Otwórz kredyty",
    )
    TranslationDemand.all_objects.filter(organization=owner.organization).delete()
    # The consenting person no longer active: the consent is gone with them.
    Membership.objects.filter(pk=owner.pk).update(status="suspended")
    due(owner, object_id)
    assert start_due_demand(owner.organization_id) is None
    assert [row.reason for row in demand(owner)] == [CONSENT_LOST]
    # Turned off: the demand has nothing to wait for.
    Membership.objects.filter(pk=owner.pk).update(status="active")
    TranslationSettings.all_objects.filter(organization=owner.organization).update(
        auto_changes=False
    )
    TranslationDemand.all_objects.filter(organization=owner.organization).update(
        state="waiting", check_at=None
    )
    assert start_due_demand(owner.organization_id) is None
    assert demand(owner) == []


def test_a_pair_already_in_a_job_waits_for_it(source: JobSource) -> None:
    owner = automated("tl21-busy")
    source.live_locales.add("de")
    object_id = page(source, "Alfa")
    order(owner, [object_id])
    (row,) = due(owner, object_id)
    before = timezone.now()
    assert start_due_demand(owner.organization_id) is None
    row.refresh_from_db()
    assert row.state == "waiting" and row.due_at >= before + demand_wait()
    assert TranslationJob.all_objects.filter(trigger="automatic").count() == 0


def test_a_paused_automation_tells_the_managers_once_a_period(source: JobSource) -> None:
    owner = automated("tl21-paused", limit=1)
    source.live_locales.add("de")
    object_id = page(source, "Alfa")
    due(owner, object_id)
    start_due_demand(owner.organization_id)
    notice = AppNotification.all_objects.get(
        organization=owner.organization, kind=AUTOMATION_PAUSED
    )
    assert notice.user_id == owner.user_id and notice.payload == {"reason": MONTHLY_LIMIT}
    # The sweep has no person behind it: the mail goes as the organization's
    # own job, and delivery opens that contract.
    from saas_core.modules.shared.notifications.tasks import deliver_email_task  # noqa: PLC0415

    mail = NotificationMessage.all_objects.get(
        organization=owner.organization, template_key=AUTOMATION_PAUSED
    )
    # To where the limit is raised; no credits would lead to the credits page.
    # The mail says why and calls its link by where it leads.
    assert mail.context["panel_url"].endswith("/panel/settings/languages")
    assert (mail.template_version, mail.context["reason_text"], mail.context["link_label"]) == (
        2,
        "wykorzystano miesięczny limit automatu",
        "Otwórz ustawienia tłumaczeń",
    )
    deliver_email_task.run(str(mail.id), mail.signed_tenant_context)
    assert NotificationMessage.all_objects.get(pk=mail.id).status == "sent"
    # Tried again within the month: still one notice.
    TranslationDemand.all_objects.filter(organization=owner.organization).update(
        check_at=timezone.now()
    )
    start_due_demand(owner.organization_id)
    assert (
        AppNotification.all_objects.filter(
            organization=owner.organization, kind=AUTOMATION_PAUSED
        ).count()
        == 1
    )


def test_the_daily_repair_records_a_change_whose_notice_was_lost(source: JobSource) -> None:
    owner = automated("tl21-repair")
    organization = owner.organization
    organization.organization_type = settings.DEFAULT_ORGANIZATION_TYPE
    organization.save(update_fields=["organization_type"])
    source.module_id = "shared.sites"  # a module the company's type composes
    object_id = page(source, "Alfa")  # published, its notice never arrived
    assert reconcile_demand() >= 1
    (row,) = demand(owner)
    assert (row.object_id, row.cause) == (object_id, "schedule")


@override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de"))
def test_a_published_change_on_a_real_site_goes_out_in_german_without_a_click(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    """The acceptance of TL21 on the `sites.page` source: the company consents
    once; then publishing a Polish change gives one job after the wait, and the
    German page follows without anyone clicking."""
    from test_sites_page_translation_source import SitesPageDriver, TestSitesPageSource, _job

    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Witamy w studiu"])
    driver.publish(home)
    _job(contract, driver, home)  # German is live on the site
    organization_id = driver.publisher.organization_id
    EntitlementSnapshot.all_objects.filter(organization_id=organization_id).update(
        quotas={"sites.max": 1000, "credits.monthly": 100},
        sources={
            "sites.enabled": {"kind": "plan"},
            "sites.max": {"kind": "plan"},
            "credits.monthly": {"kind": "plan"},
        },
    )
    with installed_source(monkeypatch), activate_tenant_context(driver.publisher):
        change_settings(
            changes={"translation.settings.processing_acknowledged": True, AUTO: True},
            expected_version=0,
            idempotency_key="tl21-site-consent",
        )
        driver.edit(home, 0, "Zapraszamy do studia")
        with django_capture_on_commit_callbacks(execute=True):
            driver.publish(home)
        (row,) = TranslationDemand.all_objects.filter(organization_id=organization_id)
        assert row.source_key == "sites.page" and row.object_id == home
        assert start_due_demand(organization_id) is None  # still within the five minutes
        job_id = start_due_demand(organization_id, row.due_at)
        assert job_id is not None
        assert run(TranslationJob.all_objects.get(pk=job_id)).state == JobState.SUCCEEDED
    assert driver.public_texts(home, "de") == [german("Zapraszamy do studia")]


def test_what_the_automation_still_has_to_translate_is_listed_with_why_it_is_held(
    source: JobSource,
) -> None:
    """„Wstrzymane” in „Tłumaczenia → Zadania” (TL16g): the demand the
    automation could not start, with the reason and when it tries again."""
    owner = automated("tl16g-held", limit=1)
    source.live_locales.add("de")
    held, quiet = page(source, "Alfa"), page(source, "Beta")
    due(owner, held)
    now = timezone.now()
    assert start_due_demand(owner.organization_id, now) is None
    TranslationDemand.all_objects.create(
        organization=owner.organization,
        source_key=SOURCE,
        object_id=quiet,
        cause=f"user:{owner.user_id}",
        first_at=now,
        due_at=now + timedelta(minutes=5),
    )
    client = authenticated_client(owner)

    listed = client.get("/api/v1/translation/demand/")
    assert listed.status_code == 200, listed.json()
    assert listed.json()["count"] == 2
    first, second = listed.json()["items"]
    assert (first["object_id"], first["state"], first["reason"]) == (
        str(held),
        "blocked",
        MONTHLY_LIMIT,
    )
    assert datetime.fromisoformat(first["check_at"]) == _next_month(now)
    # Named as the source lists it, like the review queue's rows.
    assert (first["source_key"], first["scope"]) == (SOURCE, FAKE_SCOPE)
    assert first["label"]
    # Waiting out its quiet time: no reason, nothing to check again.
    assert (second["object_id"], second["state"], second["reason"], second["check_at"]) == (
        str(quiet),
        "waiting",
        "",
        None,
    )

    blocked = client.get("/api/v1/translation/demand/", {"state": "blocked", "limit": 1}).json()
    assert ([row["object_id"] for row in blocked["items"]], blocked["count"]) == ([str(held)], 1)
    assert blocked["next_cursor"] is None
    paged = client.get("/api/v1/translation/demand/", {"limit": 1}).json()
    assert paged["next_cursor"] == "1"
    rest = client.get("/api/v1/translation/demand/", {"limit": 1, "cursor": "1"}).json()
    assert [row["object_id"] for row in rest["items"]] == [str(quiet)]
    assert client.get("/api/v1/translation/demand/", {"state": "perhaps"}).status_code == 400

    # Another company sees none of it; a person without the right is refused.
    stranger = authenticated_client(company("tl16g-held-stranger"))
    assert stranger.get("/api/v1/translation/demand/").json() == {
        "items": [],
        "count": 0,
        "next_cursor": None,
    }
    Membership.objects.filter(pk=owner.pk).update(
        role=Role.objects.get(key="staff", organization=None, organization_type="")
    )
    assert authenticated_client(owner).get("/api/v1/translation/demand/").status_code == 403
