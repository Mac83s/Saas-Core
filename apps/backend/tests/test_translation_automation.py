"""Automatic jobs from due demand, and their billing (TL21b, translation-sources.md §8.3).

The pages, the model, credits and the worker are the TL6b test doubles: an
in-memory source behind the real registry and the port's scripted fake.
Demand rows are written directly — recording them is TL21a's test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID

import pytest
from django.utils import timezone

from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.shared.billing.models import CreditLedgerEntry, CreditLedgerKind
from saas_core.modules.shared.translation.automation import (
    CONSENT_LOST,
    CREDITS_EXHAUSTED,
    MONTHLY_LIMIT,
    _next_month,
    start_due_demand,
)
from saas_core.modules.shared.translation.demand import DEMAND_WAIT
from saas_core.modules.shared.translation.models import (
    JobState,
    TranslationDemand,
    TranslationJob,
    TranslationSettings,
)
from saas_core.modules.shared.translation.services import change_settings
from saas_core.testing.translation_sources import FakeSourceDriver
from test_booking import tenant
from test_model_port import fake_models  # noqa: F401 — the port's fake models
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
    assert row.state == "waiting" and row.due_at >= before + DEMAND_WAIT
    assert TranslationJob.all_objects.filter(trigger="automatic").count() == 0
