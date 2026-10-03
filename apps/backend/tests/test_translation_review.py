"""What waits for a person, the person's decisions, taking a job back and
stopping one (TL6c, ADR-069 pkt 19, 21, 22, 24; translation-sources.md §6.6)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from rest_framework.exceptions import PermissionDenied

from saas_core.content_protocol.sources import ContentContext, WriteBatch, WriteOutcome
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.billing.models import CreditReservation
from saas_core.modules.shared.translation.models import (
    ItemState,
    JobState,
    ReviewState,
    TranslationJobItem,
    TranslationReviewItem,
)
from saas_core.modules.shared.translation.review import (
    ReviewChanged,
    ReviewChoice,
    cancel_job,
    decide_review,
    revert_job,
)
from saas_core.modules.shared.translation.services import change_settings
from saas_core.testing.translation_sources import (
    FAKE_SCOPE,
    FakeLiveRecordSource,
    FakeSourceDriver,
    registered_translation_source,
)
from test_booking import tenant
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_tenant_context import authenticated_client
from test_translation_jobs import (
    JobSource,
    company,
    german,
    installed_source,
    order,
    page,
    run,
)

pytestmark = pytest.mark.django_db


class LiveCards(FakeLiveRecordSource):
    """A record public on every save, letting the company's people in."""

    def __init__(self) -> None:
        super().__init__("testing.cards")

    def authorize(self, *, context: ContentContext, action: str, object_ids: Any) -> None:
        return None

    def facts(self, context: ContentContext, obj: Any, locale: str) -> Any:
        return JobSource.facts(self, context, obj, locale)  # type: ignore[arg-type]

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        return super().write(context=context, batch=batch)


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    with installed_source(monkeypatch) as installed:
        yield installed


@pytest.fixture
def cards(pages: JobSource) -> Iterator[LiveCards]:
    live = LiveCards()
    with registered_translation_source(live):
        yield live


def review_mode(owner: Any) -> None:
    with tenant(owner):
        change_settings(
            changes={"translation.settings.mode": "review"},
            expected_version=1,
            idempotency_key=f"mode-{owner.id}",
        )


def open_reviews(owner: Any) -> list[TranslationReviewItem]:
    return list(
        TranslationReviewItem.all_objects.filter(
            organization=owner.organization, state=ReviewState.OPEN
        ).order_by("created_at")
    )


def choices(rows: list[TranslationReviewItem]) -> list[ReviewChoice]:
    return [ReviewChoice(id=row.id, version=row.version) for row in rows]


def test_review_mode_results_wait_are_billed_and_go_out_when_accepted(pages: JobSource) -> None:
    owner = company("tl6c-accept")
    review_mode(owner)
    object_id = page(pages, "Alfa", "Beta")
    job = run(order(owner, [object_id]))
    assert job.state == JobState.SUCCEEDED
    item = TranslationJobItem.all_objects.get(job=job)
    # Waiting in review mode is billed like a delivered result (ADR-069 pkt 24).
    assert item.delivered_characters == len("Alfa") + len("Beta")
    [row] = open_reviews(owner)
    assert (row.reason, row.keys, row.texts) == ("review_mode", 2, {})
    driver = FakeSourceDriver(pages)
    assert driver.public_texts(object_id, "de") is None
    client = authenticated_client(owner)
    listed = client.get("/api/v1/translation/review/")
    assert listed.status_code == 200 and listed.json()["items"][0]["reason"] == "review_mode"
    accepted = client.post(
        "/api/v1/translation/review/accept/",
        {"items": [{"id": str(row.id), "version": row.version}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="accept-1",
    )
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["items"][0]["state"] == "accepted"
    assert driver.public_texts(object_id, "de") == [german("Alfa"), german("Beta")]
    stale = client.post(
        "/api/v1/translation/review/accept/",
        {"items": [{"id": str(row.id), "version": row.version}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="accept-2",
    )
    assert stale.status_code == 409 and stale.json()["code"] == "translation_review_changed"


def test_the_list_names_what_waits_as_its_source_lists_it(
    pages: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl16-labels")
    review_mode(owner)
    object_id = page(pages, "Alfa")
    run(order(owner, [object_id]))
    client = authenticated_client(owner)
    listed = client.get("/api/v1/translation/review/").json()
    assert listed["count"] == 1
    assert client.get("/api/v1/translation/review/?reason=qa_flagged").json()["count"] == 0
    [item] = listed["items"]
    assert (item["object_id"], item["label"], item["scope"]) == (
        str(object_id),
        "Studio Testowe",
        FAKE_SCOPE,
    )

    # A source the person may not read: the row stays, without a name.
    def refuse(**_kwargs: Any) -> Any:
        raise PermissionDenied

    monkeypatch.setattr(pages, "list_objects", refuse)
    [item] = client.get("/api/v1/translation/review/").json()["items"]
    assert (item["reason"], item["label"], item["scope"]) == ("review_mode", "", "")


def test_a_live_records_waiting_text_is_kept_here_and_written_on_acceptance(
    pages: JobSource, cards: LiveCards
) -> None:
    owner = company("tl6c-live")
    review_mode(owner)
    driver = FakeSourceDriver(cards)
    card = driver.create(["Salon fryzjerski dla psów"])
    job = run(_order_card(owner, card))
    assert job.state == JobState.SUCCEEDED
    [row] = open_reviews(owner)
    assert row.reason == "review_mode" and list(row.texts) == ["u0"]
    assert driver.public_texts(card, "de") is None
    with tenant(owner):
        decide_review(action="accept", choices=choices([row]), idempotency_key="live-1")
    assert driver.public_texts(card, "de") == [german("Salon fryzjerski dla psów")]
    row.refresh_from_db()
    assert row.state == ReviewState.ACCEPTED and row.texts == {}


def test_a_live_records_waiting_text_is_read_beside_its_source(
    pages: JobSource, cards: LiveCards, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = company("tl16c-detail")
    review_mode(owner)
    driver = FakeSourceDriver(cards)
    card = driver.create(["Salon fryzjerski dla psów", "Kąpiel"])
    run(_order_card(owner, card))
    page_id = page(pages, "Alfa")
    run(order(owner, [page_id]))
    client = authenticated_client(owner)
    waiting = client.get("/api/v1/translation/review/").json()["items"]
    listed = {item["source_key"]: item for item in waiting}
    assert listed["testing.cards"]["comparable"] is True
    # A versioned source keeps the waiting text itself: nothing to compare here.
    versioned = listed[next(key for key in listed if key != "testing.cards")]
    assert versioned["comparable"] is False
    answer = client.get(f"/api/v1/translation/review/{versioned['id']}/").json()
    assert (answer["comparable"], answer["fits"], answer["units"]) == (False, True, [])

    detail = client.get(f"/api/v1/translation/review/{listed['testing.cards']['id']}/").json()
    assert (detail["comparable"], detail["fits"], detail["source_locale"]) == (True, True, "pl")
    assert detail["units"] == [
        {
            "key": "u0",
            "source_text": "Salon fryzjerski dla psów",
            "current_text": "",
            "proposed_text": german("Salon fryzjerski dla psów"),
        },
        {
            "key": "u1",
            "source_text": "Kąpiel",
            "current_text": "",
            "proposed_text": german("Kąpiel"),
        },
    ]

    # The source moved since: the text is still shown, and an acceptance would not be taken.
    driver.edit(card, 1, "Kąpiel z suszeniem")
    moved = client.get(f"/api/v1/translation/review/{detail['id']}/").json()
    assert moved["fits"] is False
    assert moved["units"][1]["source_text"] == "Kąpiel z suszeniem"
    [row] = [row for row in open_reviews(owner) if row.source_key == "testing.cards"]
    with tenant(owner), pytest.raises(ReviewChanged):
        decide_review(action="accept", choices=choices([row]), idempotency_key="moved-1")

    # Another company does not see it; a source the person may not read answers 403.
    stranger = authenticated_client(company("tl16c-stranger"))
    assert stranger.get(f"/api/v1/translation/review/{detail['id']}/").status_code == 404

    def refuse(**_kwargs: Any) -> Any:
        raise PermissionDenied

    monkeypatch.setattr(cards, "authorize", refuse)
    assert client.get(f"/api/v1/translation/review/{detail['id']}/").status_code == 403

    # Once decided the text is gone, and so is the item.
    monkeypatch.undo()
    with tenant(owner):
        decide_review(action="discard", choices=choices([row]), idempotency_key="gone-1")
    assert client.get(f"/api/v1/translation/review/{detail['id']}/").status_code == 404


def _order_card(owner: Any, card: Any) -> Any:
    from saas_core.modules.shared.translation.jobs import (
        TargetRequest,
        order_translation,
        quote_translation,
    )

    targets = [TargetRequest(source_key="testing.cards", object_id=card, locale="de")]
    with tenant(owner):
        quoted = quote_translation(targets=targets)
        return order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key=f"card-{card}",
        ).value


def test_a_job_or_the_assistant_alone_cannot_decide(pages: JobSource) -> None:
    owner = company("tl6c-person")
    review_mode(owner)
    run(order(owner, [page(pages, "Alfa")]))
    rows = open_reviews(owner)
    with tenant(owner) as context:
        acting = replace(
            context, acting_via="ai_translation", acting_ref=f"translation_job:{uuid4()}"
        )
        with activate_tenant_context(acting), pytest.raises(PersonRequired):
            decide_review(action="accept", choices=choices(rows), idempotency_key="x")


def test_what_the_checks_refused_waits_but_cannot_be_accepted(
    pages: JobSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saas_core.modules.shared.model_port.adapters.fake import FAKE
    from test_translation_jobs import translator

    owner = company("tl6c-refused")
    monkeypatch.setattr(FAKE, "complete", translator(lambda text: "Call now"))
    run(order(owner, [page(pages, "Zadzwoń: +48 600 100 200")]))
    [row] = open_reviews(owner)
    assert (row.reason, row.keys) == ("qa_failed", 1)
    with tenant(owner), pytest.raises(Exception) as refused:
        decide_review(action="accept", choices=choices([row]), idempotency_key="qa")
    assert refused.value.get_codes() == {"items.0": ["not_acceptable"]}  # type: ignore[attr-defined]
    with tenant(owner):
        decide_review(action="discard", choices=choices([row]), idempotency_key="qa-d")
    row.refresh_from_db()
    assert row.state == ReviewState.DISCARDED


def test_a_newer_result_supersedes_the_waiting_one(pages: JobSource) -> None:
    owner = company("tl6c-supersede")
    review_mode(owner)
    object_id = page(pages, "Alfa")
    run(order(owner, [object_id], key="first"))
    [first] = open_reviews(owner)
    driver = FakeSourceDriver(pages)
    driver.edit(object_id, 0, "Alfa nowa")
    driver.publish(object_id)
    run(order(owner, [object_id], key="second"))
    first.refresh_from_db()
    assert first.state == ReviewState.SUPERSEDED
    [second] = open_reviews(owner)
    assert second.id != first.id
    with tenant(owner), pytest.raises(ReviewChanged):
        decide_review(action="accept", choices=choices([first]), idempotency_key="old")


def test_taking_a_job_back_restores_the_texts_from_before_it(pages: JobSource) -> None:
    owner = company("tl6c-revert")
    object_id = page(pages, "Alfa")
    job = run(order(owner, [object_id]))
    driver = FakeSourceDriver(pages)
    assert driver.public_texts(object_id, "de") == [german("Alfa")]
    with tenant(owner):
        reverted = revert_job(job_id=job.id, idempotency_key="revert-1")
        assert reverted.value.reverted_at is not None
        assert revert_job(job_id=job.id, idempotency_key="revert-1").replayed
        with pytest.raises(Exception) as twice:
            revert_job(job_id=job.id, idempotency_key="revert-2")
    assert twice.value.get_codes() == {"job_id": ["already_reverted"]}  # type: ignore[attr-defined]
    assert driver.public_texts(object_id, "de") is None


def test_stopping_a_job_cancels_what_has_not_started_and_releases_the_hold(
    pages: JobSource,
) -> None:
    owner = company("tl6c-cancel")
    job = order(owner, [page(pages, "Alfa"), page(pages, "Beta")])
    with tenant(owner):
        saved = cancel_job(job_id=job.id, idempotency_key="stop")
    assert saved.value.state == JobState.CANCELED
    assert set(
        TranslationJobItem.all_objects.filter(job=job).values_list("state", "error_code")
    ) == {(ItemState.CANCELED, "canceled")}
    reservation = CreditReservation.all_objects.get(organization=owner.organization)
    assert reservation.state == "released"
