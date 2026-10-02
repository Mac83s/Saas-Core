"""Quotes, orders and the worker (TL6b, ADR-069 pkt 13, 18–21, 23, 24).

The model is the port's scripted fake, answering each segment of the call;
the content is an in-memory source behind the real registry. Credits, the
ledger, leases, the person's membership and the history are real.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from saas_core.content_protocol.sources import ContentContext, WriteBatch, WriteOutcome
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.shared.billing.models import (
    CreditLedgerEntry,
    CreditLedgerKind,
    CreditOperation,
    CreditReservation,
    EntitlementSnapshot,
)
from saas_core.modules.shared.model_port.adapters.base import AdapterCall, AdapterResult
from saas_core.modules.shared.model_port.adapters.fake import FAKE
from saas_core.modules.shared.model_port.api import ModelError, Usage
from saas_core.modules.shared.translation import worker
from saas_core.modules.shared.translation.jobs import (
    TargetRequest,
    TranslationQuoteChanged,
    TranslationUnavailable,
    order_translation,
    quote_translation,
)
from saas_core.modules.shared.translation.models import (
    ItemState,
    JobState,
    TranslationJob,
    TranslationJobItem,
)
from saas_core.modules.shared.translation.services import (
    TranslationIdempotencyConflict,
    change_settings,
)
from saas_core.modules.shared.translation.tasks import WORKER_SEEN
from saas_core.testing.translation_sources import (
    FakeDraftSource,
    FakeSourceDriver,
    registered_translation_source,
)
from test_billing_credits import assert_ledger_matches_balance
from test_booking import membership, tenant
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

SOURCE = "testing.pages"


class JobSource(FakeDraftSource):
    """The in-memory pages, as a module that lets the company's people in."""

    def __init__(self) -> None:
        super().__init__(SOURCE)
        self.writes: list[ContentContext] = []
        self.publications: list[str] = []

    def authorize(self, *, context: ContentContext, action: str, object_ids: Any) -> None:
        return None

    def facts(self, context: ContentContext, obj: Any, locale: str) -> Any:
        from saas_core.content_protocol.policy import PublicationFacts

        return PublicationFacts(
            legal_document=obj.legal,
            locale_live=locale in self.live_locales,
            actor_may_publish=True,
        )

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        self.writes.append(context)
        return super().write(context=context, batch=batch)

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        self.publications.append(idempotency_key)
        return super().publish(
            context=context, scope=scope, job_ref=job_ref, idempotency_key=idempotency_key
        )


def german(text: str) -> str:
    """A stand-in translation: every word changed, tokens kept."""
    return " ".join(
        word if word.startswith("⟦") or not word else f"de{word}" for word in text.split(" ")
    )


def translator(
    answer: Callable[[str], str | None] = german,
) -> Callable[[AdapterCall], AdapterResult]:
    """A model answering every segment it is sent; None leaves one out."""

    def complete(call: AdapterCall) -> AdapterResult:
        FAKE.calls.append(call)
        payload = json.loads(call.request.messages[-1].content or "{}")
        rows = []
        for segment in payload["segments"]:
            text = answer(segment["text"])
            if text is not None:
                rows.append({"id": segment["id"], "text": text})
        return AdapterResult(
            text=json.dumps({"translations": rows}, ensure_ascii=False),
            tool_calls=(),
            finish_reason="stop",
            usage=Usage(input_tokens=100, output_tokens=50),
            cost_usd_micros=1_000,
            resolved_model="fake/translator-20261001",
            resolved_provider="fake",
            provider_request_id="fake",
        )

    return complete


@contextmanager
def installed_source(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    """The pages registered, the model answering, a worker seen, a price set."""
    pages = JobSource()
    monkeypatch.setattr(FAKE, "complete", translator())
    cache.set(WORKER_SEEN, 1, 300)
    CreditOperation.objects.filter(key="translation.characters").update(is_active=True, cost=2)
    try:
        with registered_translation_source(pages):
            yield pages
    finally:
        cache.delete(WORKER_SEEN)


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    with installed_source(monkeypatch) as pages:
        yield pages


def company(slug: str, *, credits: int = 100) -> Membership:
    owner = membership(slug)
    organization = owner.organization
    organization.public_locales = ["pl", "de"]
    organization.save(update_fields=["public_locales"])
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        quotas={"credits.monthly": credits}, sources={"credits.monthly": {"kind": "plan"}}
    )
    with tenant(owner):
        change_settings(
            changes={"translation.settings.processing_acknowledged": True},
            expected_version=0,
            idempotency_key=f"ack-{slug}",
        )
    return owner


def page(source: JobSource, *texts: str) -> UUID:
    driver = FakeSourceDriver(source)
    object_id = driver.create(list(texts))
    driver.publish(object_id)
    return object_id


def order(owner: Membership, objects: list[UUID], key: str = "job-1") -> TranslationJob:
    targets = [TargetRequest(source_key=SOURCE, object_id=o, locale="de") for o in objects]
    with tenant(owner):
        quoted = quote_translation(targets=targets)
        assert quoted.available, quoted.reasons
        saved = order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key=key,
        )
    return saved.value


def run(job: TranslationJob) -> TranslationJob:
    worker.run_job(job.organization_id, job.id)
    return TranslationJob.all_objects.get(pk=job.id)


def test_an_order_holds_credits_runs_as_the_person_and_settles_what_was_delivered(
    source: JobSource,
) -> None:
    owner = company("tl6b-run")
    first = page(source, "Strzyżenie psów " * 50, "Kąpiel")
    job = order(owner, [first])
    # 805 visible characters (trailing space trimmed): one unit, 2 credits held.
    reservation = CreditReservation.all_objects.get(organization=owner.organization)
    assert (reservation.quantity, reservation.cost) == (1, 2)
    done = run(job)
    assert done.state == JobState.SUCCEEDED
    item = TranslationJobItem.all_objects.get(job=job)
    assert item.state == ItemState.WRITTEN and item.delivered_characters == 805
    assert FakeSourceDriver(source).public_texts(first, "de") == [
        german("Strzyżenie psów " * 50),
        german("Kąpiel"),
    ]
    # The source saw the person's membership acting through the job.
    context = source.writes[0]
    assert (context.acting_via, context.acting_ref) == (
        "ai_translation",
        f"translation_job:{job.id}",
    )
    assert context.membership_id == owner.id
    assert source.publications == [f"{job.id}:0:{SOURCE}:testing-scope"]
    consumed = CreditLedgerEntry.all_objects.get(
        organization=owner.organization, kind=CreditLedgerKind.CONSUMED
    )
    assert (consumed.amount, consumed.operation_quantity) == (-2, 1)
    assert_ledger_matches_balance(owner.organization)
    actions = set(
        OrganizationAuditEntry.objects.filter(organization=owner.organization).values_list(
            "action", flat=True
        )
    )
    assert {"translation.job_created", "translation.job_succeeded"} <= actions


def test_a_stale_digest_answers_the_new_quote_and_a_key_answers_once(source: JobSource) -> None:
    owner = company("tl6b-digest")
    object_id = page(source, "Alfa", "Beta")
    targets = [TargetRequest(source_key=SOURCE, object_id=object_id, locale="de")]
    with tenant(owner):
        quoted = quote_translation(targets=targets)
        again = quote_translation(targets=targets)
        assert again.quote.digest == quoted.quote.digest
    driver = FakeSourceDriver(source)
    driver.edit(object_id, 0, "Alfa nowa")
    driver.publish(object_id)
    with tenant(owner), pytest.raises(TranslationQuoteChanged) as changed:
        order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key="k",
        )
    assert changed.value.quote.digest != quoted.quote.digest
    fresh = changed.value.quote
    with tenant(owner):
        first = order_translation(
            targets=targets,
            digest=fresh.digest,
            expected_credits=fresh.credits,
            idempotency_key="k2",
        )
        repeat = order_translation(
            targets=targets,
            digest=fresh.digest,
            expected_credits=fresh.credits,
            idempotency_key="k2",
        )
        assert repeat.replayed and repeat.item_id == first.item_id
        with pytest.raises(TranslationIdempotencyConflict):
            order_translation(
                targets=targets,
                digest=fresh.digest,
                expected_credits=fresh.credits + 1,
                idempotency_key="k2",
            )


def test_the_api_returns_409_with_the_new_quote(source: JobSource) -> None:
    owner = company("tl6b-api")
    object_id = page(source, "Alfa")
    client = authenticated_client(owner)
    body = {"targets": [{"source_key": SOURCE, "object_id": str(object_id), "locale": "de"}]}
    quote = client.post("/api/v1/translation/quotes/", body, format="json")
    assert quote.status_code == 200, quote.json()
    stale = client.post(
        "/api/v1/translation/jobs/",
        {**body, "digest": "0" * 64, "expected_credits": quote.json()["credits"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="api-1",
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "translation_quote_changed"
    assert stale.json()["quote"]["digest"] == quote.json()["digest"]
    created = client.post(
        "/api/v1/translation/jobs/",
        {**body, "digest": quote.json()["digest"], "expected_credits": quote.json()["credits"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="api-2",
    )
    assert created.status_code == 201, created.json()
    detail = client.get(f"/api/v1/translation/jobs/{created.json()['id']}/")
    assert detail.status_code == 200 and detail.json()["items"][0]["locale"] == "de"


def test_an_item_the_checks_refuse_twice_is_not_billed(
    source: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl6b-partial")
    good = page(source, "Dobry tekst " * 100)
    bad = page(source, "Zadzwoń: +48 600 100 200")
    # The model drops the phone mask every time: a hard error, retried once.
    monkeypatch.setattr(
        FAKE, "complete", translator(lambda text: "Call now" if "⟦m:1⟧" in text else german(text))
    )
    job = run(order(owner, [good, bad]))
    assert job.state == JobState.PARTIAL
    items = {i.object_id: i for i in TranslationJobItem.all_objects.filter(job=job)}
    assert items[bad].state == ItemState.FAILED and items[bad].delivered_characters == 0
    assert items[good].delivered_characters == 1199
    part = job.parts.get()
    assert (part.settled_units, part.settled_credits) == (2, 4)
    assert_ledger_matches_balance(owner.organization)


def test_a_part_past_its_deadline_settles_what_it_has(source: JobSource) -> None:
    owner = company("tl6b-deadline")
    job = order(owner, [page(source, "Alfa " * 300)])
    part = job.parts.get()
    with tenant(owner):
        part.deadline_at = timezone.now() - timedelta(minutes=1)
        part.save()
    worker.finish_parts(owner.organization_id, job.id)
    job.refresh_from_db()
    assert job.state == JobState.FAILED
    item = TranslationJobItem.all_objects.get(job=job)
    assert (item.state, item.error_code) == (ItemState.CANCELED, "deadline_passed")
    reservation = CreditReservation.all_objects.get(organization=owner.organization)
    assert reservation.state == "released"
    assert_ledger_matches_balance(owner.organization)


def test_waiting_for_the_pool_is_an_hour_not_an_error(
    source: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl6b-budget")
    job = order(owner, [page(source, "Alfa")])
    later = timezone.now() + timedelta(hours=1)

    def exhausted(_request: Any) -> Any:
        raise ModelError("budget", "pool_exhausted", until=later)

    monkeypatch.setattr(worker, "complete", exhausted)
    done = run(job)
    assert done.state == JobState.RUNNING
    assert abs((done.next_attempt_at - later).total_seconds()) < 1
    item = TranslationJobItem.all_objects.get(job=job)
    assert item.state == ItemState.QUEUED and item.error_code == ""


def test_a_revoked_person_stops_the_job_unbilled(source: JobSource) -> None:
    owner = company("tl6b-revoked")
    job = order(owner, [page(source, "Alfa")])
    Membership.objects.filter(pk=owner.id).update(status="revoked", revoked_at=timezone.now())
    done = run(job)
    assert done.state == JobState.FAILED
    item = TranslationJobItem.all_objects.get(job=job)
    assert item.error_code == "authorization_revoked"
    assert not CreditLedgerEntry.all_objects.filter(
        organization=owner.organization, kind=CreditLedgerKind.CONSUMED
    ).exists()


def test_without_a_price_or_a_worker_nothing_is_ordered(source: JobSource) -> None:
    owner = company("tl6b-unavailable")
    object_id = page(source, "Alfa")
    targets = [TargetRequest(source_key=SOURCE, object_id=object_id, locale="de")]
    cache.delete(WORKER_SEEN)
    CreditOperation.objects.filter(key="translation.characters").update(is_active=False, cost=0)
    with tenant(owner):
        quoted = quote_translation(targets=targets)
        assert {"worker_unavailable", "operation_unpriced"} <= set(quoted.reasons)
        with pytest.raises(TranslationUnavailable):
            order_translation(
                targets=targets,
                digest=quoted.quote.digest,
                expected_credits=quoted.quote.credits,
                idempotency_key="none",
            )
    assert not TranslationJob.all_objects.filter(organization=owner.organization).exists()


def test_one_active_item_per_pair_and_a_busy_pair_is_quoted_as_in_progress(
    source: JobSource,
) -> None:
    owner = company("tl6b-busy")
    object_id = page(source, "Alfa")
    order(owner, [object_id])
    with tenant(owner):
        quoted = quote_translation(
            targets=[TargetRequest(source_key=SOURCE, object_id=object_id, locale="de")]
        )
    assert quoted.quote.lines[0].excluded == "in_progress" and quoted.quote.units == 0
    item = TranslationJobItem.all_objects.get(organization=owner.organization)
    with tenant(owner), pytest.raises(IntegrityError), transaction.atomic():
        TranslationJobItem.all_objects.create(
            organization=owner.organization,
            job=item.job,
            part=item.part,
            position=1,
            source_key=SOURCE,
            object_id=object_id,
            locale="de",
            basis="published",
            scope="",
        )


@pytest.mark.parametrize(
    "table",
    [
        "translation_translationjob",
        "translation_translationjobpart",
        "translation_translationjobitem",
    ],
)
def test_job_tables_force_rls(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [table]
        )
        assert cursor.fetchone() == (True, True)
