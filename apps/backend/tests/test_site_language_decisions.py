"""A person's decisions about a language version (ADR-070 pkt 12–13, plan TL9c):
accept, reject, publish, withdraw and accept several at once — each that changes
the site a derived publication of the published state, never anybody's drafts —
and rollback carrying the language versions of the state it restores."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.sites.language_decisions import publish_locale_version
from saas_core.modules.shared.sites.language_versions import save_locale_body
from saas_core.modules.shared.sites.models import (
    PageLocaleVersion,
    PageTranslation,
    Publication,
    Site,
)
from saas_core.modules.shared.sites.services import PersonRequired
from test_site_language_publication import _translate_all
from test_site_language_versions_api import _draft, _hero, _page, _send, _url
from test_sites_api import (
    create_site,
    publish_site_request,
    rollback_site_request,
    sites_client,
)
from test_sites_collections import _verified_platform_domain

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _get(host: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)


def _published_site(slug: str) -> tuple[Any, Any, str, str, str, str]:
    """A site live in Polish and English on its home page; the offer page has
    an English address and body, not yet published."""
    client, organization, _ = sites_client(slug=slug, role_key="owner")
    site_id = create_site(client).data["id"]
    home = str(_page(client, site_id, "start", [_hero("Witaj", "Studio projektowe")]))
    offer = str(_page(client, site_id, "oferta", [_hero("Oferta", "Projekt od 120 zł")]))
    _translate_all(client, home, "home-en")
    published = publish_site_request(client, site_id, idempotency_key="first")
    assert published.status_code == 201, published.data
    _translate_all(client, offer, "offer-en")
    host = _verified_platform_domain(site_id).hostname
    return client, organization, site_id, home, offer, host


def _waiting(page_id: str) -> PageTranslation:
    """The current English body made to wait for review, as a job in review
    mode leaves it."""
    row = PageTranslation.all_objects.get(page_id=page_id, locale="en")
    PageTranslation.all_objects.filter(pk=row.pk).update(
        body_pending=row.body_current, body_current=None, pending_reason="review_mode"
    )
    return PageTranslation.all_objects.get(pk=row.pk)


def _snapshot(site_id: str) -> dict[str, Any]:
    return Site.all_objects.get(pk=site_id).current_publication.snapshot


def _page_of(snapshot: dict[str, Any], page_id: str) -> dict[str, Any]:
    return next(page for page in snapshot["pages"] if page["page_id"] == page_id)


def _post(client: Any, url: str, payload: dict[str, Any] | None = None, key: str = "") -> Any:
    return _send(client, "post", url, payload or {}, key=key)


def test_accepting_changes_only_that_language_entry_and_never_drafts():
    client, _, site_id, home, offer, host = _published_site("decide-accept")
    before = _snapshot(site_id)
    row = _waiting(offer)
    # Unpublished work elsewhere: a Polish draft on the home page.
    _draft(client, home, 1, [_hero("Szkic, którego nie widać", "Studio projektowe")], "home-v2")

    accepted = _post(
        client, _url(offer, tail="accept/"), {"expected_body_version": row.body_version}, "accept"
    )

    assert accepted.status_code == 200, accepted.data
    assert (accepted.data["published"], accepted.data["skipped"]) == (True, None)
    after = _snapshot(site_id)
    assert Publication.all_objects.get(pk=accepted.data["publication_id"]).reason == "locale_accept"
    assert _page_of(after, home) == _page_of(before, home)
    assert after["navigation"] == before["navigation"]
    offer_page = _page_of(after, offer)
    assert {entry["locale"] for entry in offer_page["locales"]} == {"pl", "en"}
    assert offer_page["hreflang"] == {"pl": "/oferta/", "en": "/en/oferta-en/"}
    assert _get(host, "/en/oferta-en/").status_code == 200
    row.refresh_from_db()
    assert (row.body_pending_id, row.body_current_id is not None) == (None, True)
    assert row.slug_locked_at is not None


def test_the_body_says_what_waits_for_a_decision_and_what_was_taken_off():
    """What the editor's banner reads (TL15): the version waiting and why,
    and whether a person took the language off the site."""
    client, _, site_id, _home, offer, _host = _published_site("decide-body-state")
    row = _waiting(offer)

    waiting = client.get(_url(offer))
    assert waiting.status_code == 200, waiting.data
    assert waiting.json()["pending"] == {
        "version_id": str(row.body_pending_id),
        "number": row.body_pending.number,
        "reason": "review_mode",
    }
    assert (waiting.json()["version_id"], waiting.json()["withdrawn"]) == (None, False)
    # The editor names a unit's section from its key's position.
    assert waiting.json()["block_types"] == ["core.hero"]
    assert {unit["key"].split("/")[0] for unit in waiting.json()["units"]} == {"0"}

    _post(client, _url(offer, tail="accept/"), {"expected_body_version": row.body_version}, "ok")
    accepted = client.get(_url(offer)).json()
    assert accepted["pending"] is None
    assert accepted["version_id"] == str(row.body_pending_id)
    _post(client, _url(offer, tail="withdraw/"), key="off")
    assert client.get(_url(offer)).json()["withdrawn"] is True


def test_rejecting_drops_the_waiting_version_and_publishes_nothing():
    client, _, site_id, _home, offer, host = _published_site("decide-reject")
    row = _waiting(offer)
    sequence = Site.all_objects.get(pk=site_id).current_publication.sequence

    rejected = _post(
        client, _url(offer, tail="reject/"), {"expected_body_version": row.body_version}, "reject"
    )

    assert rejected.status_code == 200, rejected.data
    assert rejected.data["publication_id"] is None
    row.refresh_from_db()
    assert row.body_pending_id is None
    assert Site.all_objects.get(pk=site_id).current_publication.sequence == sequence
    assert _get(host, "/en/oferta-en/").status_code == 404


def test_a_version_of_an_unpublished_draft_waits_for_the_person_s_publication():
    client, _, site_id, _home, offer, host = _published_site("decide-unpublished")
    publish_site_request(client, site_id, idempotency_key="second")
    assert _get(host, "/en/oferta-en/").status_code == 200
    # The Polish offer changes in a draft and English follows that draft.
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 120 zł, nowy opis")], "offer-v2")
    body = client.get(_url(offer)).data
    moved = _post(
        client,
        _url(offer, tail="rebase/"),
        {"expected_body_version": body["body_version"]},
        "rebase",
    )
    assert moved.status_code == 201, moved.data
    _translate_all(client, offer, "offer-en-v2", prefix="EN2 ")

    waiting = _post(client, _url(offer, tail="publish/"), key="publish-en")

    assert waiting.status_code == 200, waiting.data
    assert (waiting.data["published"], waiting.data["skipped"]) == (False, "source_unpublished")
    assert _get(host, "/en/oferta-en/").data["blocks"][0]["data"]["text"] == (
        "EN Projekt od 120 zł"
    )
    # The person's publication of the draft takes English with it.
    publish_site_request(client, site_id, idempotency_key="third")
    assert _get(host, "/en/oferta-en/").data["blocks"][0]["data"]["text"] == (
        "EN2 Projekt od 120 zł, nowy opis"
    )


def test_a_withdrawn_version_answers_308_until_it_is_published_again():
    client, _, site_id, _home, offer, host = _published_site("decide-withdraw")
    publish_site_request(client, site_id, idempotency_key="second")

    withdrawn = _post(client, _url(offer, tail="withdraw/"), key="withdraw")

    assert withdrawn.status_code == 200, withdrawn.data
    gone = _get(host, "/en/oferta-en/")
    assert gone.status_code == 308
    assert gone["Location"] == "/oferta/"
    # The next publication of the whole site keeps it off.
    publish_site_request(client, site_id, idempotency_key="third")
    assert _get(host, "/en/oferta-en/").status_code == 308
    back = _post(client, _url(offer, tail="publish/"), key="back")
    assert back.data["published"] is True
    assert _get(host, "/en/oferta-en/").status_code == 200
    reasons = list(
        Publication.all_objects.filter(site_id=site_id)
        .order_by("sequence")
        .values_list("reason", flat=True)
    )
    assert reasons[-3:] == ["locale_withdraw", "publish", "locale_publish"]


def test_several_versions_are_accepted_in_one_publication_against_the_previewed_list():
    client, _, site_id, _home, offer, _host = _published_site("decide-batch")
    contact = str(_page(client, site_id, "kontakt", [_hero("Kontakt", "Napisz do nas")]))
    rows = [_waiting(offer)]
    publish_site_request(client, site_id, idempotency_key="with-contact")
    _translate_all(client, contact, "contact-en")
    rows.append(_waiting(contact))
    items = [
        {"page_id": str(row.page_id), "locale": "en", "expected_body_version": row.body_version}
        for row in rows
    ]
    url = f"/api/v1/sites/{site_id}/translations/accept/"

    other = create_site(client, slug="other-site", idempotency_key="other-site").data["id"]
    elsewhere = _post(
        client, f"/api/v1/sites/{other}/translations/accept/preview/", {"items": items}
    )
    twice = _post(client, url + "preview/", {"items": [items[0], items[0]]})
    preview = _post(client, url + "preview/", {"items": items})
    stale = _post(client, url, {"items": items, "digest": "0" * 64}, "batch-stale")
    accepted = _post(client, url, {"items": items, "digest": preview.data["digest"]}, "batch")

    assert elsewhere.status_code == 404
    assert twice.status_code == 400
    assert preview.status_code == 200, preview.data
    assert {item["skipped"] for item in preview.data["items"]} == {None}
    assert stale.status_code == 409
    assert stale.data["code"] == "locale_batch_stale"
    assert accepted.status_code == 200, accepted.data
    (publication,) = {item["publication_id"] for item in accepted.data["items"]}
    assert publication is not None
    snapshot = _snapshot(site_id)
    for page_id in (offer, contact):
        assert "en" in _page_of(snapshot, page_id)["hreflang"]


def test_rollback_restores_the_language_versions_and_releases_nothing_newer():
    client, _, site_id, _home, offer, host = _published_site("decide-rollback")
    first = Site.all_objects.get(pk=site_id).current_publication
    publish_site_request(client, site_id, idempotency_key="second")
    assert _get(host, "/en/oferta-en/").status_code == 200

    restored = rollback_site_request(client, site_id, str(first.id), idempotency_key="back")

    assert restored.status_code == 201, restored.data
    assert _get(host, "/en/oferta-en/").status_code == 404
    assert _get(host, "/en/").status_code == 200
    # The English offer stays current, only off the restored state.
    assert PageTranslation.all_objects.get(page_id=offer, locale="en").body_current_id


def test_decisions_are_a_person_s_and_assistant_text_is_marked_as_ai():
    client, organization, _site_id, _home, offer, _host = _published_site("decide-acting")
    membership = Membership.objects.get(organization=organization)
    conversation = f"conversation:{uuid7()}"
    acting = acting_context(context_from_membership(membership), via="assistant", ref=conversation)
    body = client.get(_url(offer)).data

    with activate_tenant_context(acting):
        result = save_locale_body(
            page_id=UUID(offer),
            locale="en",
            source_version_id=body["source_version_id"],
            expected_body_version=body["body_version"],
            units={"0/title": "Offer from the assistant"},
            idempotency_key="assistant-save",
            provenance_model="test/model",
        )
        with pytest.raises(PersonRequired):
            publish_locale_version(
                page_id=UUID(offer), locale="en", idempotency_key="assistant-publish"
            )

    version = PageLocaleVersion.all_objects.get(pk=result.value.version.id)
    assert version.origin_ref == conversation
    title = version.units["0/title"]["provenance"]
    assert (title["origin"], title["model"]) == ("ai", "test/model")
