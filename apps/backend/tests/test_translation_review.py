"""What waits for a person, the person's decisions, taking a job back and
stopping one (TL6c, ADR-069 pkt 19, 21, 22, 24; translation-sources.md §6.6)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

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
from test_sites_api import csrf_value
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


def test_a_jobs_detail_names_its_items_and_says_whether_it_can_be_taken_back(
    pages: JobSource,
) -> None:
    owner = company("tl16d-detail")
    first = run(order(owner, [page(pages, "Alfa")], key="job-a"))
    client = authenticated_client(owner)

    def detail(job: Any, query: str = "") -> Any:
        return client.get(f"/api/v1/translation/jobs/{job.id}/{query}").json()

    plain = detail(first)
    assert plain["revertable"] is True
    # Following a job reads no source: the items go without their names.
    assert [(item["label"], item["scope"]) for item in plain["items"]] == [("", FAKE_SCOPE)]
    assert detail(first, "?labels=true")["items"][0]["label"] == "Studio Testowe"
    [part] = plain["parts"]
    assert (part["state"], part["reserved_credits"], part["settled_credits"]) == ("settled", 2, 2)

    # A later job wrote too: it is the one to take back now, and only once.
    second = run(order(owner, [page(pages, "Beta")], key="job-b"))
    assert (detail(first)["revertable"], detail(second)["revertable"]) == (False, True)
    # The server holds the same line as the screen: an older job stays the
    # operator's to take back (`translation_revert_job`).
    older = client.post(
        f"/api/v1/translation/jobs/{first.id}/revert/", HTTP_IDEMPOTENCY_KEY="take-back-older"
    )
    assert older.status_code == 400
    assert [(e["field"], e["code"], e["message"]) for e in older.json()["errors"]] == [
        ("job_id", "not_latest_job", "Cofnąć można tylko ostatnie zadanie, które coś zapisało.")
    ]
    with tenant(owner):
        revert_job(job_id=second.id, idempotency_key="take-back")
    assert detail(second)["revertable"] is False

    # The list keeps the jobs still running apart from those that ended.
    waiting = order(owner, [page(pages, "Gamma")], key="job-c")
    assert detail(waiting)["revertable"] is False
    with tenant(owner), pytest.raises(Exception) as running:
        revert_job(job_id=waiting.id, idempotency_key="take-back-running")
    assert running.value.get_codes() == {"job_id": ["job_running"]}  # type: ignore[attr-defined]

    def listed(query: str) -> list[str]:
        answer = client.get(f"/api/v1/translation/jobs/{query}").json()
        return [job["id"] for job in answer["items"]]

    assert listed("?active=true") == [str(waiting.id)]
    assert listed("?active=false") == [str(second.id), str(first.id)]
    assert len(listed("")) == 3
    assert client.get("/api/v1/translation/jobs/?active=perhaps").status_code == 400

    # Another company sees none of it.
    stranger = authenticated_client(company("tl16d-stranger"))
    assert stranger.get(f"/api/v1/translation/jobs/{first.id}/").status_code == 404
    assert stranger.get("/api/v1/translation/jobs/").json()["items"] == []


def test_the_translations_overview_names_what_can_be_accepted_in_a_cell() -> None:
    """„Zaakceptuj” in a cell of „Strona internetowa → Tłumaczenia” (TL16g):
    the overview is the site module's, the queue is the engine's — the cell
    learns what waits through the registry, never by importing the engine."""
    from saas_core.modules.core.organizations.context import context_from_membership
    from saas_core.modules.core.organizations.models import Membership
    from saas_core.modules.shared.sites.models import PageTranslation
    from saas_core.modules.shared.translation.review import waiting_reviews
    from test_site_language_decisions import _published_site, _waiting
    from test_site_translation_overview_sources import _other, _site_with_footer

    PAGE_KEY = "sites.page"  # noqa: N806
    client, site = _site_with_footer("tl16g-cell-texts")

    def waits(source_key: str, object_id: Any, reason: str = "review_mode") -> Any:
        return TranslationReviewItem.all_objects.create(
            organization_id=site.organization_id,
            source_key=source_key,
            object_id=object_id,
            locale="en",
            basis="published",
            basis_version="v1",
            reason=reason,
            keys=2,
        )

    def texts_cell() -> dict[str, Any]:
        [row] = [
            item
            for item in _other(client, site.id, locale="en")["items"]
            if item["source_key"] == "sites.site_texts"
        ]
        return row["cells"][0]

    # A result with no text to accept, and the question whether to take a
    # translation down, are the queue's own: the cell stays as it reads.
    waits("sites.site_texts", site.id, reason="qa_failed")
    waits("sites.site_texts", site.id, reason="source_withdrawn")
    assert (texts_cell()["state"], texts_cell()["review_id"]) == ("missing", None)

    item = waits("sites.site_texts", site.id)
    cell = texts_cell()
    assert (
        cell["state"],
        cell["review_id"],
        cell["review_version"],
        cell["review_comparable"],
    ) == ("pending", str(item.id), item.version, False)
    # A live record's text waits in the queue alone: the cell says to read it there.
    TranslationReviewItem.all_objects.filter(pk=item.pk).update(
        texts={"footer/text": ["Welcome", {}]}
    )
    assert texts_cell()["review_comparable"] is True
    waiting_rows = _other(client, site.id, locale="en", state="pending")["items"]
    assert [row["source_key"] for row in waiting_rows] == ["sites.site_texts"]

    # Decided: nothing waits in the cell any more.
    TranslationReviewItem.all_objects.filter(pk=item.pk).update(state=ReviewState.ACCEPTED)
    assert texts_cell()["review_id"] is None

    # A page's waiting version names its item only while it still waits.
    pages_client, organization, site_id, _home, offer, _host = _published_site("tl16g-cell-page")
    review = TranslationReviewItem.all_objects.create(
        organization_id=organization.id,
        source_key=PAGE_KEY,
        object_id=offer,
        locale="en",
        basis="published",
        basis_version="v1",
        reason="review_mode",
    )

    def offer_cell() -> dict[str, Any]:
        rows = pages_client.get(f"/api/v1/sites/{site_id}/translations/").json()["items"]
        [row] = [row for row in rows if row["id"] == offer]
        return next(cell for cell in row["cells"] if cell["locale"] == "en")

    assert (offer_cell()["state"], offer_cell()["review_id"]) == ("complete", None)
    row = _waiting(offer)
    assert (offer_cell()["state"], offer_cell()["review_id"]) == ("pending", str(review.id))
    # Decided in the page's editor: the item is still open, the cell offers nothing.
    PageTranslation.all_objects.filter(pk=row.pk).update(
        body_current=row.body_pending_id, body_pending=None, pending_reason=""
    )
    assert offer_cell()["review_id"] is None

    # A person who may not read the queue learns nothing of it from the overview.
    _waiting(offer)
    owner = context_from_membership(Membership.objects.get(organization=organization))
    assert (PAGE_KEY, UUID(offer), "en") in waiting_reviews(owner)
    assert waiting_reviews(replace(owner, permissions=frozenset())) == {}


def test_a_version_decided_in_the_pages_editor_leaves_nothing_in_the_queue() -> None:
    """Accepted or rejected in the language editor, past „Do akceptacji”: the
    queue's item for that version could no longer be accepted or discarded
    (the page has nothing pending), so it must not stay open and counted."""
    from test_site_language_decisions import _post, _published_site, _waiting
    from test_site_language_versions_api import _url

    client, organization, site_id, _home, offer, _host = _published_site("tl16g-editor-decides")

    def queued(reason: str = "review_mode") -> TranslationReviewItem:
        return TranslationReviewItem.all_objects.create(
            organization_id=organization.id,
            source_key="sites.page",
            object_id=offer,
            locale="en",
            basis="published",
            basis_version="v1",
            reason=reason,
        )

    def waiting() -> int:
        return client.get("/api/v1/translation/review/").json()["count"]

    # Accepted in the editor.
    row = _waiting(offer)
    item = queued()
    # Whether the original should come down too is another question: it stays.
    withdrawal = queued("source_withdrawn")
    assert waiting() == 2
    accepted = _post(
        client,
        _url(offer, "en", "accept/"),
        {"expected_body_version": row.body_version},
        key="editor-accept",
    )
    assert accepted.status_code == 200, accepted.data
    item.refresh_from_db()
    assert (item.state, item.version, item.texts) == (ReviewState.SUPERSEDED, 2, {})
    withdrawal.refresh_from_db()
    assert withdrawal.state == ReviewState.OPEN
    assert waiting() == 1
    # A decision still sent on the closed item is told so, not half-applied.
    stale = client.post(
        "/api/v1/translation/review/accept/",
        {"items": [{"id": str(item.id), "version": 1}]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="stale-accept",
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "translation_review_changed")

    # Rejected in the editor.
    row = _waiting(offer)
    item = queued()
    rejected = _post(
        client,
        _url(offer, "en", "reject/"),
        {"expected_body_version": row.body_version},
        key="editor-reject",
    )
    assert rejected.status_code == 200, rejected.data
    item.refresh_from_db()
    assert item.state == ReviewState.SUPERSEDED


def test_the_clean_up_closes_what_an_editors_decision_left_in_the_queue() -> None:
    """`sites_close_decided_reviews`: items whose page has nothing waiting any
    more (decided in the editor before it told the queue) are closed the way
    the editor closes them now; the dry run only says so, a repeat finds
    nothing, and what still waits — or was never a text to accept — stays."""
    from io import StringIO

    from django.core.management import call_command

    from test_site_language_decisions import _published_site, _waiting

    _client, organization, _site, home, offer, _host = _published_site("q-review-clean-up")

    def queued(page: Any, reason: str = "review_mode", locale: str = "en") -> TranslationReviewItem:
        return TranslationReviewItem.all_objects.create(
            organization_id=organization.id,
            source_key="sites.page",
            object_id=page,
            locale=locale,
            basis="published",
            basis_version="v1",
            reason=reason,
        )

    def run(*arguments: str) -> str:
        out = StringIO()
        call_command("sites_close_decided_reviews", *arguments, stdout=out)
        return out.getvalue()

    _waiting(offer)
    still_waits = queued(offer)
    orphan = queued(home)
    # Whether the original should come down too is another question.
    withdrawal = queued(home, "source_withdrawn")
    # Never a text to accept, in a language with nothing else open: not the editor's.
    refused = queued(home, "gate_failed", locale="de")
    card = TranslationReviewItem.all_objects.create(
        organization_id=organization.id,
        source_key="profiles.public_profile",
        object_id=uuid4(),
        locale="en",
        basis="published",
        basis_version="v1",
        reason="review_mode",
        texts={"headline": ["x", {}]},
    )

    def states() -> list[str]:
        rows = [still_waits, orphan, withdrawal, refused, card]
        for row in rows:
            row.refresh_from_db()
        return [row.state for row in rows]

    looked = run("--dry-run")
    assert f"{organization.id}\t{home}\ten" in looked and "Do zamknięcia: 1" in looked
    assert states() == [ReviewState.OPEN] * 5

    assert "Zamknięto: 1" in run()
    assert states() == [
        ReviewState.OPEN,
        ReviewState.SUPERSEDED,
        ReviewState.OPEN,
        ReviewState.OPEN,
        ReviewState.OPEN,
    ]
    assert "Zamknięto: 0" in run()
