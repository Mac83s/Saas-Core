"""A proposed SEO change remains reviewable and cannot mutate metadata before approval."""

from __future__ import annotations

from typing import Any

import pytest
from django.utils import timezone

import test_content_base_integrity as base_tests
from saas_core.modules.shared.sites.models import (
    ContentProposal,
    Page,
    PageTranslation,
    PageVersion,
)
from test_content_base_integrity import rebase, translation_for
from test_content_preview_authorization import connector, grant_for
from test_sites_api import csrf_value, save_draft

surface = base_tests.surface
clear_cache = base_tests.clear_cache
pytestmark = pytest.mark.django_db


@pytest.fixture
def proposed(surface: Any) -> tuple[Any, Any, Any, Any, Any]:
    person, _, _, document = surface
    translation = translation_for(surface)
    Page.all_objects.filter(pk=translation.page_id).update(automation_policy="proposed")
    automation, key = connector(surface, scope="content:draft")
    grant = grant_for(surface, key)
    grant.mode = "draft_write"
    grant.save(update_fields=["mode"])
    document = rebase(surface)
    response = automation.post(
        "/api/v1/sites/changes/apply/",
        {"change_set": document},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["pending_commands"] == ["translation.update"]
    assert response.json()["applied_commands"] == []
    proposal = ContentProposal.all_objects.get(pk=response.json()["proposal_id"])
    return person, automation, translation, proposal, document


def detail(person: Any, proposal: ContentProposal) -> Any:
    response = person.get(f"/api/v1/sites/proposals/{proposal.id}/")
    assert response.status_code == 200, response.content
    return response.json()


def accept(person: Any, proposal: ContentProposal, token: str) -> Any:
    return person.post(
        f"/api/v1/sites/proposals/{proposal.id}/accept/",
        {"review_token": token},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(person),
    )


def reject(person: Any, proposal: ContentProposal) -> Any:
    return person.post(
        f"/api/v1/sites/proposals/{proposal.id}/discard/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(person),
    )


def test_proposed_metadata_waits_for_human_and_has_a_stored_localized_diff(proposed: Any) -> None:
    person, _, translation, proposal, _ = proposed
    translation.refresh_from_db()
    assert translation.description == "Original description"
    assert translation.version == 1
    body = detail(person, proposal)
    assert body["target"]["locale"] == "pl"
    assert body["metadata_before"]["description"] == "Original description"
    assert body["metadata_after"]["description"] == "Proposed copy."
    assert body["metadata_pending"] is True
    response = person.post(
        f"/api/v1/sites/{translation.site_id}/publications/",
        format="json",
        HTTP_IDEMPOTENCY_KEY="pending-meta-publication",
        HTTP_X_CSRFTOKEN=csrf_value(person),
    )
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "automation_approval_required"


def test_accept_applies_exact_metadata_once_and_retains_closed_history(proposed: Any) -> None:
    person, _, translation, proposal, _ = proposed
    token = detail(person, proposal)["review_token"]
    first = accept(person, proposal, token)
    assert first.status_code == 200, first.content
    translation.refresh_from_db()
    assert translation.description == "Proposed copy."
    assert translation.version == 2
    assert first.json()["published"] is False
    assert accept(person, proposal, token).json() == first.json()
    translation.refresh_from_db()
    assert translation.version == 2
    assert detail(person, proposal)["review_state"] == "accepted"
    assert person.get("/api/v1/sites/proposals/").json() == []
    assert reject(person, proposal).status_code == 409


def test_reject_retains_metadata_and_history_and_creates_monotonic_draft(proposed: Any) -> None:
    person, _, translation, proposal, _ = proposed
    response = reject(person, proposal)
    assert response.status_code == 200, response.content
    assert response.json()["restored_version"] == 3
    translation.refresh_from_db()
    assert translation.description == "Original description"
    assert translation.version == 1
    assert detail(person, proposal)["review_state"] == "rejected"
    assert PageVersion.all_objects.filter(page_id=translation.page_id).count() == 3
    assert reject(person, proposal).json() == response.json()
    assert PageVersion.all_objects.filter(page_id=translation.page_id).count() == 3
    saved = save_draft(
        person,
        translation.page_id,
        expected_version=3,
        idempotency_key="after-rejected-meta",
        heading="New human work",
    )
    assert saved.status_code == 201


@pytest.mark.parametrize("edited", ["metadata", "draft"])
def test_human_edits_supersede_accept_and_reject(proposed: Any, edited: str) -> None:
    person, _, translation, proposal, _ = proposed
    token = detail(person, proposal)["review_token"]
    if edited == "metadata":
        PageTranslation.all_objects.filter(pk=translation.pk).update(description="Human intervened")
    else:
        save_draft(
            person,
            translation.page_id,
            expected_version=2,
            idempotency_key="superseding-human",
            heading="Human intervened",
        )
    assert accept(person, proposal, token).status_code == 409
    assert reject(person, proposal).status_code == 409
    proposal.refresh_from_db()
    assert proposal.review_state == "pending"


def test_automation_cannot_accept_its_own_proposal_or_read_human_review_token(
    proposed: Any,
) -> None:
    person, automation, _, proposal, _ = proposed
    token = detail(person, proposal)["review_token"]
    response = automation.post(
        f"/api/v1/sites/proposals/{proposal.id}/accept/",
        {"review_token": token},
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert automation.get(f"/api/v1/sites/proposals/{proposal.id}/").status_code == 403


@pytest.mark.parametrize("tamper", ["token", "stored_metadata", "expired"])
def test_accept_refuses_tampered_or_expired_review(proposed: Any, tamper: str) -> None:
    from unittest.mock import patch

    person, _, translation, proposal, _ = proposed
    token = detail(person, proposal)["review_token"]
    if tamper == "token":
        token += "x"
    elif tamper == "stored_metadata":
        proposal.metadata_after["description"] = "Changed after review"
        proposal.save(update_fields=["metadata_after"])
    later = timezone.now().timestamp() + (86_400 if tamper == "expired" else 0)
    with patch("django.core.signing.time.time", return_value=later):
        response = accept(person, proposal, token)
    assert response.status_code == 409, response.content
    translation.refresh_from_db()
    assert translation.description == "Original description"


def test_accept_requires_csrf_in_a_human_session(proposed: Any) -> None:
    person, _, _, proposal, _ = proposed
    response = person.post(
        f"/api/v1/sites/proposals/{proposal.id}/accept/",
        {"review_token": detail(person, proposal)["review_token"]},
        format="json",
    )
    assert response.status_code == 403
