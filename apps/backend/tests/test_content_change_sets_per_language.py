"""Content operations per language (ADR-070 pkt 17, plan TL13).

A page has one change-set base per language. In the site's source language it
is the page's draft, as before. In any other language it is that language
version: its own lock, the blocks it assembles into, text-only replacements
written as units, and a structure that stays the source's. The profile these
tests run under offers Polish and English, so English stands for "another
language"; the proof on a running stack uses German.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.notifications.models import ApiKey, ApiKeyCredentialRoute
from saas_core.modules.shared.sites.models import (
    ContentAutomationGrant,
    ContentProposal,
    Page,
    PageLocaleVersion,
    PageTranslation,
    PageVersion,
    Site,
    SiteOutboxEvent,
)
from test_content_operations_api import _apply, _change_set, _preview
from test_site_language_publication import _translate_all
from test_site_language_versions_api import _hero, _page, _paragraph, _translate
from test_sites_api import create_site, csrf_value, publish_site_request, sites_client
from test_sites_operations import _api_key_client

pytestmark = pytest.mark.django_db
BASE_URL = "/api/v1/sites/content-base/"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def _block(block: dict[str, Any]) -> dict[str, Any]:
    """A stored block in the contract's envelope."""
    return {
        "type": block["block_type"],
        "schema_version": block["schema_version"],
        "data": block["data"],
    }


def _site(slug: str) -> tuple[Any, Any, Any, str, str]:
    """A page in Polish with an English version: its own address and text."""
    client, organization, owner = sites_client(slug=slug, role_key="owner")
    site_id = str(create_site(client).data["id"])
    blocks = [_hero("Witaj", "Studio"), _paragraph("Akapit")]
    page_id = str(_page(client, site_id, "oferta", blocks))
    saved = _translate(
        client,
        page_id,
        {"0/title": "Welcome", "0/text": "Studio", "1/text": "Paragraph"},
        "oferta-en",
    )
    assert saved.status_code == 201, saved.data
    return client, organization, owner, site_id, page_id


def _document(
    client: Any, site_id: str, page_id: str, locale: str, commands: list[dict[str, Any]]
) -> dict[str, Any]:
    target = {"kind": "site_page", "site_id": site_id, "page_id": page_id, "locale": locale}
    base = client.get(BASE_URL, target)
    assert base.status_code == 200, base.content
    return _change_set(target=target, base=base.json()["base"], commands=commands)


def _replace(position: int, block: dict[str, Any]) -> dict[str, Any]:
    return {"command": "block.replace", "position": position, "block": _block(block)}


def _english(page_id: str) -> PageTranslation:
    return PageTranslation.all_objects.select_related("body_current", "body_pending").get(
        page_id=page_id, locale="en"
    )


def _connector(organization: Any, owner: Any, site_id: str, *, policy: str, page_id: str) -> Any:
    """A drafting key on a page whose automation policy is `policy`."""
    client = _api_key_client(organization=organization, created_by=owner, marker="t")
    key = ApiKey.all_objects.get(organization=organization)
    ApiKey.all_objects.filter(pk=key.id).update(scopes=["content:draft"])
    ApiKeyCredentialRoute.objects.filter(api_key_id=key.id).update(scopes=["content:draft"])
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=site_id,
        mode="draft_write",
        created_by=owner,
    )
    Page.all_objects.filter(pk=page_id).update(automation_policy=policy)
    return client


def _send(client: Any, path: str, document: dict[str, Any]) -> Any:
    return client.post(path, {"change_set": document}, content_type="application/json")


def test_a_text_change_in_another_language_leaves_the_source_and_its_waiting_change_alone() -> None:
    client, _, _, site_id, page_id = _site("locale-cs-text")
    page_version = Page.all_objects.get(pk=page_id).version
    # Computed before the English change, applied after it.
    polish = _document(
        client, site_id, page_id, "pl", [_replace(1, _paragraph("Lepszy akapit"))]
    )
    english = _document(
        client, site_id, page_id, "en", [_replace(1, _paragraph("A better paragraph"))]
    )
    assert english["base"]["version"] == 1 == _english(page_id).body_version

    preview = _preview(client, english)
    assert preview.status_code == 200, preview.content
    assert preview.json()["base_version"] == 1
    assert [block["data"] for block in preview.json()["blocks_before"]] == [
        {"title": "Welcome", "text": "Studio"},
        {"text": "Paragraph"},
    ]
    assert preview.json()["blocks_after"][1]["data"] == {"text": "A better paragraph"}

    applied = _apply(client, english)
    assert applied.status_code == 201, applied.content
    assert applied.json()["applied_commands"] == ["block.replace"]
    row = _english(page_id)
    assert row.body_version == 2
    assert row.body_current.origin == "change_set"
    units = row.body_current.units
    assert units["1/text"]["text"] == "A better paragraph"
    assert units["1/text"]["provenance"]["origin"] == "integration"
    # What the change did not touch keeps who wrote it.
    assert units["0/title"] == _english_version(page_id, 1).units["0/title"]
    assert units["0/title"]["provenance"]["origin"] == "human"
    # The source page did not move: no new draft, the same lock.
    assert Page.all_objects.get(pk=page_id).version == page_version
    assert PageVersion.all_objects.filter(page_id=page_id).count() == page_version

    # So the change computed for the Polish page before it still applies.
    assert _apply(client, polish).status_code == 201
    assert Page.all_objects.get(pk=page_id).version == page_version + 1
    # And the two proposals stand side by side with the same version number.
    proposals = {
        proposal.locale: proposal.version
        for proposal in ContentProposal.all_objects.filter(resource_id=page_id)
    }
    assert proposals == {"pl": 2, "en": 2}


def _english_version(page_id: str, number: int) -> PageLocaleVersion:
    return PageLocaleVersion.all_objects.get(page_id=page_id, locale="en", number=number)


@pytest.mark.parametrize(
    "command",
    [
        {"command": "block.insert", "position": 0, "block": _block(_paragraph("New"))},
        {"command": "block.remove", "position": 1},
        {"command": "block.reorder", "order": [1, 0]},
    ],
)
def test_a_language_version_keeps_the_structure_of_its_source(command: dict[str, Any]) -> None:
    client, _, _, site_id, page_id = _site("locale-cs-locked")
    document = _document(client, site_id, page_id, "en", [command])
    for response in (_preview(client, document), _apply(client, document)):
        assert response.status_code == 422, response.content
        assert response.json()["code"] == "locale_structure_locked"
    assert _english(page_id).body_version == 1
    assert PageLocaleVersion.all_objects.filter(page_id=page_id).count() == 1
    # The same command is the source language's to take.
    assert _preview(client, _document(client, site_id, page_id, "pl", [command])).status_code == 200


@pytest.mark.parametrize(
    "replacement",
    [
        # Another kind of block in the hero's place.
        (0, _paragraph("Welcome")),
        # A button the source does not have.
        (
            0,
            {
                "block_type": "core.hero",
                "schema_version": 6,
                "data": {
                    "title": "Welcome",
                    "text": "Studio",
                    "action": {"label": "Call", "href": "tel:+48123123123"},
                },
            },
        ),
    ],
)
def test_a_replacement_that_changes_more_than_text_is_refused(replacement: Any) -> None:
    client, _, _, site_id, page_id = _site("locale-cs-shape")
    document = _document(client, site_id, page_id, "en", [_replace(*replacement)])
    for response in (_preview(client, document), _apply(client, document)):
        assert response.status_code == 422, response.content
        assert response.json()["code"] == "locale_structure_locked"
    assert _english(page_id).body_version == 1


def test_a_command_this_door_does_not_run_is_named_first_in_every_language() -> None:
    client, _, _, site_id, page_id = _site("locale-cs-unsupported")
    link = {
        "command": "internal_link.add",
        "position": 0,
        "target_path": "/",
        "anchor_text": "Home",
    }
    insert = {"command": "block.insert", "position": 0, "block": _block(_paragraph("New"))}
    for commands in ([link], [insert, link]):
        response = _preview(client, _document(client, site_id, page_id, "en", commands))
        assert response.status_code == 422
        assert response.json()["code"] == "change_set_command_unsupported"


def test_a_language_the_site_does_not_have_is_refused_by_the_server() -> None:
    client, organization, _, site_id, page_id = _site("locale-cs-disabled")
    english = _document(client, site_id, page_id, "en", [_replace(1, _paragraph("Better"))])
    # German has the shape the contract asks for; this profile does not offer it.
    german = {**english, "target": {**english["target"], "locale": "de"}}
    for response in (
        client.get(BASE_URL, german["target"]),
        _preview(client, german),
        _apply(client, german),
    ):
        assert response.status_code == 400, response.content
        assert response.json()["code"] == "locale_not_enabled"
    # A company that turned English off: the content stays, the door closes.
    Organization.objects.filter(pk=organization.id).update(public_locales=["pl"])
    response = _apply(client, english)
    assert response.status_code == 400
    assert response.json()["code"] == "locale_not_enabled"
    assert _english(page_id).body_version == 1
    # The source language is always the site's own.
    assert client.get(BASE_URL, {**english["target"], "locale": "pl"}).status_code == 200


def test_titles_in_another_language_change_only_that_language() -> None:
    client, _, _, site_id, page_id = _site("locale-cs-meta")
    page_version = Page.all_objects.get(pk=page_id).version
    document = _document(
        client,
        site_id,
        page_id,
        "en",
        [{"command": "translation.update", "fields": {"description": "A studio near you."}}],
    )
    applied = _apply(client, document)
    assert applied.status_code == 201, applied.content
    row = _english(page_id)
    assert row.description == "A studio near you."
    assert row.version == 2
    # No body was written, yet the language's base moved by one — like the
    # page's own version does for a change to its titles alone.
    assert PageLocaleVersion.all_objects.filter(page_id=page_id).count() == 1
    assert row.body_version == 2
    assert Page.all_objects.get(pk=page_id).version == page_version
    assert PageTranslation.all_objects.get(page_id=page_id, locale="pl").description == "Opis"
    # The same document again is stale, not a second write.
    assert _apply(client, document).status_code == 409


def _linked(first: str, link: str, between: str, bold: str) -> dict[str, Any]:
    return {
        "block_type": "core.rich_text",
        "schema_version": 4,
        "data": {
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"text": first},
                        {"text": link, "href": "/oferta/"},
                        {"text": between},
                        {"text": bold, "bold": True},
                    ],
                }
            ]
        },
    }


def test_marked_runs_may_change_places_but_a_link_keeps_its_target() -> None:
    client, _, _, site_id, _ = _site("locale-cs-inline")
    page_id = str(_page(client, site_id, "linki", [_linked("Zobacz ", "ofertę", " i ", "cennik")]))
    saved = _translate(
        client,
        page_id,
        {"0/content/0/content": "See the ⟦1⟧offer⟦/1⟧ and the ⟦2⟧price list⟦/2⟧"},
        "linki-en",
    )
    assert saved.status_code == 201, saved.data
    rewritten = _linked("Our ", "offer", " — and the ", "prices")
    # The bold run first, the link second: the sentence reads differently in
    # English, the marks are the same two.
    spans = rewritten["data"]["content"][0]["content"]
    spans[1], spans[3] = spans[3], spans[1]
    applied = _apply(client, _document(client, site_id, page_id, "en", [_replace(0, rewritten)]))
    assert applied.status_code == 201, applied.content
    unit = _english(page_id).body_current.units["0/content/0/content"]
    # Numbered as the source numbers its marks: ⟦1⟧ is the link, ⟦2⟧ the bold.
    assert unit["text"] == "Our ⟦2⟧prices⟦/2⟧ — and the ⟦1⟧offer⟦/1⟧"

    elsewhere = _linked("Our ", "offer", " and the ", "prices")
    elsewhere["data"]["content"][0]["content"][1]["href"] = "/kontakt/"
    refused = _apply(client, _document(client, site_id, page_id, "en", [_replace(0, elsewhere)]))
    assert refused.status_code == 422
    assert refused.json()["code"] == "locale_structure_locked"


def test_an_automation_writes_the_working_version_and_a_person_can_take_it_back() -> None:
    client, organization, owner, site_id, page_id = _site("locale-cs-automated")
    automation = _connector(organization, owner, site_id, policy="automated", page_id=page_id)
    document = _document(
        automation, site_id, page_id, "en", [_replace(1, _paragraph("A better paragraph"))]
    )
    applied = _send(automation, "/api/v1/sites/changes/apply/", document)
    assert applied.status_code == 201, applied.content
    row = _english(page_id)
    assert (row.body_version, row.body_pending_id) == (2, None)
    assert row.body_current.units["1/text"]["text"] == "A better paragraph"
    assert row.body_current.created_by_credential == ApiKey.all_objects.get().id

    # The subscriber learns which language, and that language's version.
    (event,) = SiteOutboxEvent.all_objects.filter(event_type="sites.page.draft_saved")
    assert event.payload["locale"] == "en"
    assert event.payload["version"] == 2
    assert event.payload["resource_id"] == page_id
    # A caller whose connection died can ask what its key did.
    status = automation.get(f"/api/v1/sites/operations/{document['idempotency_key']}/")
    assert status.json()["resource_type"] == "page_locale_version"

    # The queue names the language; rejecting puts the earlier text back as a
    # new version and leaves the Polish draft where it was.
    (line,) = client.get("/api/v1/sites/proposals/").json()
    assert (line["locale"], line["version"]) == ("en", 2)
    detail = client.get(f"/api/v1/sites/proposals/{line['proposal_id']}/").json()
    assert detail["blocks_before"][1]["data"] == {"text": "Paragraph"}
    assert detail["blocks_after"][1]["data"] == {"text": "A better paragraph"}
    page_version = Page.all_objects.get(pk=page_id).version
    rejected = client.post(
        f"/api/v1/sites/proposals/{line['proposal_id']}/discard/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert rejected.status_code == 200, rejected.content
    assert rejected.json()["restored_version"] == 3
    row = _english(page_id)
    assert row.body_version == 3
    assert row.body_current.units["1/text"]["text"] == "Paragraph"
    assert Page.all_objects.get(pk=page_id).version == page_version


def _published(slug: str) -> tuple[Any, Any, Any, str, str]:
    """A site live in Polish and English, its home page with both bodies."""
    client, organization, owner = sites_client(slug=slug, role_key="owner")
    site_id = str(create_site(client).data["id"])
    page_id = str(_page(client, site_id, "start", [_hero("Witaj", "Studio projektowe")]))
    _translate_all(client, page_id, "start-en")
    published = publish_site_request(client, site_id, idempotency_key="first")
    assert published.status_code == 201, published.data
    return client, organization, owner, site_id, page_id


def _proposed_change(slug: str) -> tuple[Any, Any, str, str, dict[str, Any]]:
    client, organization, owner, site_id, page_id = _published(slug)
    automation = _connector(organization, owner, site_id, policy="proposed", page_id=page_id)
    document = _document(
        automation,
        site_id,
        page_id,
        "en",
        [
            _replace(0, _hero("Welcome to the studio", "EN Studio projektowe")),
            {"command": "translation.update", "fields": {"description": "A design studio."}},
        ],
    )
    applied = _send(automation, "/api/v1/sites/changes/apply/", document)
    assert applied.status_code == 201, applied.content
    assert applied.json()["pending_commands"] == ["translation.update"]
    return client, automation, site_id, page_id, applied.json()


def test_on_a_proposed_page_the_language_version_waits_for_a_person() -> None:
    client, _, site_id, page_id, applied = _proposed_change("locale-cs-proposed")
    row = _english(page_id)
    # Nothing a visitor or the next publication would get has changed.
    assert row.body_current.units["0/title"]["text"] == "EN Witaj"
    assert row.description == "Opis"
    assert row.body_pending.units["0/title"]["text"] == "Welcome to the studio"
    assert (row.pending_reason, row.body_version) == ("change_set", 2)
    # The whole site does not go out past a language's waiting titles.
    blocked = publish_site_request(client, site_id, idempotency_key="second")
    assert blocked.status_code == 403, blocked.data

    detail = client.get(f"/api/v1/sites/proposals/{applied['proposal_id']}/").json()
    assert detail["blocks_before"][0]["data"]["title"] == "EN Witaj"
    assert detail["blocks_after"][0]["data"]["title"] == "Welcome to the studio"
    accepted = client.post(
        f"/api/v1/sites/proposals/{applied['proposal_id']}/accept/",
        {"review_token": detail["review_token"]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert accepted.status_code == 200, accepted.content
    # Accepted through the language version: it is the working one and, the
    # site being live in English, it is out — the source page is not touched.
    assert accepted.json()["published"] is True
    assert accepted.json()["version"] == 3
    row = _english(page_id)
    assert row.body_pending_id is None
    assert row.body_current.units["0/title"]["text"] == "Welcome to the studio"
    assert row.description == "A design studio."
    snapshot = Site.all_objects.get(pk=site_id).current_publication.snapshot
    entry = next(item for item in snapshot["pages"][0]["locales"] if item["locale"] == "en")
    assert entry["blocks"][0]["data"]["title"] == "Welcome to the studio"
    assert snapshot["pages"][0]["blocks"][0]["data"]["title"] == "Witaj"


def test_rejecting_a_waiting_language_version_drops_it() -> None:
    client, automation, site_id, page_id, applied = _proposed_change("locale-cs-rejected")
    rejected = client.post(
        f"/api/v1/sites/proposals/{applied['proposal_id']}/discard/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert rejected.status_code == 200, rejected.content
    row = _english(page_id)
    assert (row.body_pending_id, row.pending_reason) == (None, "")
    assert row.body_current.units["0/title"]["text"] == "EN Witaj"
    assert row.description == "Opis"
    assert ContentProposal.all_objects.get(pk=applied["proposal_id"]).review_state == "rejected"
    assert publish_site_request(client, site_id, idempotency_key="second").status_code == 201


def test_a_newer_change_replaces_the_one_that_waits_but_not_a_translation() -> None:
    client, automation, site_id, page_id, first = _proposed_change("locale-cs-superseded")
    document = _document(
        automation, site_id, page_id, "en", [_replace(0, _hero("Hello", "EN Studio projektowe"))]
    )
    second = _send(automation, "/api/v1/sites/changes/apply/", document)
    assert second.status_code == 201, second.content
    row = _english(page_id)
    assert row.body_pending.units["0/title"]["text"] == "Hello"
    assert row.body_version == 3
    # One line in the queue for the page's English version: the newer one.
    lines = client.get("/api/v1/sites/proposals/").json()
    assert [line["proposal_id"] for line in lines] == [second.json()["proposal_id"]]

    # A translation waiting for a person's decision is not a change set's to
    # replace: it is decided first.
    waiting = PageLocaleVersion.all_objects.create(
        organization_id=row.organization_id,
        site_id=row.site_id,
        page_id=row.page_id,
        translation=row,
        locale="en",
        number=99,
        source_version=row.body_current.source_version,
        structure_signature=row.body_current.structure_signature,
        units=row.body_current.units,
        content_hash=row.body_current.content_hash,
        created_by_id=row.body_current.created_by_id,
        origin="translation_pending",
        idempotency_key="job-pending",
        request_hash="0" * 64,
    )
    PageTranslation.all_objects.filter(pk=row.pk).update(
        body_pending=waiting, pending_reason="review_mode", body_version=4
    )
    document = _document(
        automation, site_id, page_id, "en", [_replace(0, _hero("Hi", "EN Studio projektowe"))]
    )
    for path in ("/api/v1/sites/changes/", "/api/v1/sites/changes/apply/"):
        refused = _send(automation, path, document)
        assert refused.status_code == 409, refused.content
        assert refused.json()["code"] == "locale_version_waiting"


def test_inventory_and_capabilities_answer_per_language() -> None:
    client, _, _, site_id, page_id = _published("locale-cs-inventory")
    offer = str(_page(client, site_id, "oferta", [_paragraph("Akapit")]))

    capabilities = client.get("/api/v1/sites/capabilities/").json()
    assert capabilities["language_version_commands"] == ["block.replace", "translation.update"]
    site = next(item for item in capabilities["sites"] if item["site_id"] == site_id)
    assert site["locales"] == ["pl", "en"]

    inventory = client.get("/api/v1/sites/inventory/").json()
    entry = next(item for item in inventory["sites"] if item["site_id"] == site_id)
    assert entry["locales"] == ["pl", "en"]
    pages = {page["page_id"]: page for page in entry["pages"]}
    home = {language["locale"]: language for language in pages[page_id]["locales"]}
    # The home page answers at the root of each language.
    assert (home["pl"]["path"], home["en"]["path"]) == ("/", "/en/")
    assert home["pl"]["state"] == "source"
    assert home["pl"]["base_version"] == pages[page_id]["version"]
    assert (home["en"]["state"], home["en"]["untranslated_units"]) == ("complete", 0)
    assert home["en"]["base_version"] == _english(page_id).body_version
    assert home["en"]["published"] is True and home["en"]["published_in_sync"] is True
    assert home["en"]["enabled"] is True and home["en"]["source"] is False
    # What a change set must declare is what content-base answers.
    target = {"kind": "site_page", "site_id": site_id, "page_id": page_id, "locale": "en"}
    assert client.get(BASE_URL, target).json()["base"]["version"] == home["en"]["base_version"]

    # A page written after the publication: an address in English, no text.
    other = {language["locale"]: language for language in pages[offer]["locales"]}
    assert other["en"]["path"] == "/en/oferta-en/"
    assert (other["en"]["state"], other["en"]["untranslated_units"]) == ("untranslated", 1)
    assert other["en"]["published"] is False and other["pl"]["published"] is False
    assert other["en"]["base_version"] == 0
    # The fields a connector already reads are still there.
    assert {"locale", "slug", "version", "slug_locked"} <= set(other["en"])
