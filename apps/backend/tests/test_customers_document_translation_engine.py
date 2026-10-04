"""A document for customers through the translation engine (ADR-073 §9 and
„Rozstrzygnięcia plastra 4d-2”) on the real `customers.document` source: a
person's order is translated and billed, its result waits in the review queue
in every translation mode, and accepting it there takes a fresh second factor
— the queue says so to the panel (403 `step_up_required`) and to the
assistant before its consent click. Needs shared.translation: on conftest's
list for profiles without it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.step_up import StepUpRequired, activate_step_up
from saas_core.modules.shared.billing.models import CreditOperation, EntitlementSnapshot
from saas_core.modules.shared.customers.documents import read_document
from saas_core.modules.shared.customers.models import DocumentText
from saas_core.modules.shared.customers.translation_source import SOURCE_KEY, UNIT_KEY
from saas_core.modules.shared.model_port.adapters.fake import FAKE
from saas_core.modules.shared.translation import worker
from saas_core.modules.shared.translation.command_declarations import REVIEW_ACCEPT
from saas_core.modules.shared.translation.jobs import (
    TargetRequest,
    order_translation,
    quote_translation,
)
from saas_core.modules.shared.translation.models import (
    JobState,
    ReviewState,
    TranslationJob,
    TranslationJobItem,
    TranslationReviewItem,
)
from saas_core.modules.shared.translation.review import (
    ReviewChoice,
    decide_review,
    review_detail,
)
from saas_core.modules.shared.translation.services import change_settings
from saas_core.modules.shared.translation.tasks import WORKER_SEEN
from test_customers_document_source import DocumentsDriver, _as
from test_customers_documents import stepped_up
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_tenant_context import authenticated_client
from test_translation_jobs import translator

pytestmark = pytest.mark.django_db

SOURCE_TEXT = "Regulamin wizyt.\n\nWizytę odwołasz najpóźniej dzień wcześniej."


def english(text: str) -> str:
    return f"[en] {text}"


def _company(monkeypatch: pytest.MonkeyPatch, mode: str = "automatic") -> tuple[Any, UUID]:
    """A company with an approved document, the engine around it (the port's
    fake model, a worker seen, a price, credits, the acknowledgement) and the
    company's translation mode."""
    with stepped_up():
        driver = DocumentsDriver()
        object_id = driver.create([SOURCE_TEXT])
        driver.publish(object_id)
    monkeypatch.setattr(FAKE, "complete", translator(english))
    cache.set(WORKER_SEEN, 1, 300)
    CreditOperation.objects.filter(key="translation.characters").update(is_active=True, cost=2)
    EntitlementSnapshot.all_objects.filter(organization=driver.organization).update(
        quotas={"credits.monthly": 100}, sources={"credits.monthly": {"kind": "plan"}}
    )
    with _as(driver.publisher):
        change_settings(
            changes={
                "translation.settings.processing_acknowledged": True,
                "translation.settings.mode": mode,
            },
            expected_version=0,
            idempotency_key=f"ack-{driver.organization.id}",
        )
    return driver, object_id


def _ordered(driver: DocumentsDriver, object_id: UUID) -> TranslationJob:
    targets = [TargetRequest(source_key=SOURCE_KEY, object_id=object_id, locale="en")]
    with _as(driver.publisher):
        quoted = quote_translation(targets=targets)
        assert quoted.available, quoted.reasons
        # The quote already says the result will wait, and why.
        assert quoted.quote.waiting == {"legal_document": 1}
        job = order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key=f"order-{object_id}",
        ).value
    worker.run_job(job.organization_id, job.id)
    job.refresh_from_db()
    return job


def _waiting(driver: DocumentsDriver) -> TranslationReviewItem:
    return TranslationReviewItem.all_objects.get(
        organization=driver.organization, state=ReviewState.OPEN
    )


@override_settings(MODEL_PORT_PROCESSOR_LISTED=True)
@pytest.mark.parametrize("mode", ["automatic", "review"])
def test_an_ordered_translation_waits_in_the_queue_whatever_the_companys_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    driver, object_id = _company(monkeypatch, mode)
    job = _ordered(driver, object_id)

    assert job.state == JobState.SUCCEEDED
    item = TranslationJobItem.all_objects.get(job=job)
    # Delivered and waiting is billed like any delivered result (ADR-069 pkt 24).
    assert item.outcomes == [{"state": "pending", "reason": "legal_document", "keys": 1}]
    assert item.delivered_characters > 0
    row = _waiting(driver)
    assert (row.source_key, row.object_id, row.locale) == (SOURCE_KEY, object_id, "en")
    assert (row.reason, list(row.texts)) == ("legal_document", [UNIT_KEY])
    # Nothing was written: customers who read English get no document yet.
    assert driver.public_texts(object_id, "en") is None
    with _as(driver.publisher):
        detail = review_detail(row.id)
        translation = read_document(driver.document(object_id).kind)["document"]["translation"]
    assert (detail["comparable"], detail["fits"], detail["acceptable"]) == (True, True, True)
    assert detail["label"] == "Regulamin rezerwacji"
    assert detail["scope"] == "booking_terms"
    [unit] = detail["units"]
    assert (unit["source_text"], unit["current_text"]) == (SOURCE_TEXT, "")
    assert unit["proposed_text"] == english(SOURCE_TEXT)
    # The document's own screen says a translation waits for a person.
    assert translation == {"object_id": object_id, "version": 1, "waiting": ["en"]}


@override_settings(MODEL_PORT_PROCESSOR_LISTED=True)
def test_accepting_in_the_queue_takes_a_fresh_second_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, object_id = _company(monkeypatch)
    _ordered(driver, object_id)
    row = _waiting(driver)
    choice = [ReviewChoice(id=row.id, version=row.version)]

    with _as(driver.publisher), activate_step_up(None), pytest.raises(StepUpRequired):
        decide_review(action="accept", choices=choice, idempotency_key="accept-1")
    row.refresh_from_db()
    # Refused whole: the item still waits with its text, and the same click
    # (the same key) goes through once the person has given the code.
    assert row.state == ReviewState.OPEN and list(row.texts) == [UNIT_KEY]
    assert driver.public_texts(object_id, "en") is None

    with _as(driver.publisher), stepped_up():
        [decided] = decide_review(action="accept", choices=choice, idempotency_key="accept-1").value
    assert decided["outcomes"] == [{"state": "live", "reason": None, "keys": 1}]
    row.refresh_from_db()
    assert (row.state, row.texts) == (ReviewState.ACCEPTED, {})
    assert driver.public_texts(object_id, "en") == [english(SOURCE_TEXT)]
    text = DocumentText.all_objects.get(
        organization=driver.organization, locale="en", version__document_id=object_id
    )
    assert text.accepted_by == driver.publisher.actor_id
    assert (text.provenance["origin"], text.provenance["model"]) == (
        "ai",
        "fake/translator-20261001",
    )
    with _as(driver.publisher):
        translation = read_document(driver.document(object_id).kind)["document"]["translation"]
    assert translation["waiting"] == []
    # A second order finds nothing to translate.
    with _as(driver.publisher):
        again = quote_translation(
            targets=[TargetRequest(source_key=SOURCE_KEY, object_id=object_id, locale="en")]
        )
    assert again.quote.units == 0


@override_settings(MODEL_PORT_PROCESSOR_LISTED=True)
def test_the_panel_is_asked_for_the_code_over_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    driver, object_id = _company(monkeypatch)
    _ordered(driver, object_id)
    row = _waiting(driver)
    client = authenticated_client(driver.membership)

    refused = client.post(
        "/api/v1/translation/review/accept/",
        {"items": [{"id": str(row.id), "version": row.version}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="accept-api-1",
    )

    assert refused.status_code == 403
    assert refused.json()["code"] == "step_up_required"
    row.refresh_from_db()
    assert row.state == ReviewState.OPEN
    assert driver.public_texts(object_id, "en") is None


@override_settings(MODEL_PORT_PROCESSOR_LISTED=True)
def test_the_assistant_says_before_the_click_that_the_person_accepts_in_the_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, object_id = _company(monkeypatch)
    _ordered(driver, object_id)
    row = _waiting(driver)

    class Call:
        context = driver.publisher

    with _as(driver.publisher), pytest.raises(ValidationError) as refused:
        REVIEW_ACCEPT.preview({"item_ids": [str(row.id)]}, Call())

    assert refused.value.detail["item_ids"][0].code == "person_required"
