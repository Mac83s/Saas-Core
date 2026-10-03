"""Reading a site in another language (ADR-070 pkt 11, 14, 15; plan TL9d):
forms that survive a later publication, the language of an inquiry and of a
view, internal links that lead to the reader's language, pictures of a carried
language version, and a snapshot parsed once per process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.media.models import MediaAsset
from saas_core.modules.shared.sites.models import (
    PageTranslation,
    PageViewDay,
    Site,
    SiteInquiry,
)
from saas_core.modules.shared.sites.public_media import _published_asset_ids
from saas_core.modules.shared.sites.publication_routing import LINK_FIELDS
from test_site_language_publication import _translate_all
from test_site_language_versions_api import _draft, _hero, _page, _send, _url
from test_sites_api import create_media_asset, create_site, publish_site_request, sites_client
from test_sites_collections import _verified_platform_domain

pytestmark = pytest.mark.django_db
INQUIRIES = "/api/v1/public/site/inquiries/"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _get(host: str, path: str, **headers: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host, **headers)


def _form(title: str = "Napisz do nas", contact: str = "email") -> dict[str, Any]:
    return {
        "block_type": "core.contact_form",
        "schema_version": 2,
        "data": {"title": title, "contact": contact, "submit_label": "Wyślij"},
    }


def _bilingual_site(slug: str) -> tuple[Any, Any, str, dict[str, str], str]:
    """Home, contact (with a form) and offer pages, all live in Polish and
    English except the offer's English, which is not translated yet."""
    client, organization, _ = sites_client(slug=slug, role_key="owner")
    site_id = create_site(client).data["id"]
    pages = {
        "start": str(_page(client, site_id, "start", [_hero("Witaj", "Studio")])),
        "kontakt": str(_page(client, site_id, "kontakt", [_hero("Kontakt", "Napisz"), _form()])),
        "oferta": str(_page(client, site_id, "oferta", [_hero("Oferta", "Projekty")])),
    }
    _translate_all(client, pages["start"], "start-en")
    _translate_all(client, pages["kontakt"], "kontakt-en")
    published = publish_site_request(client, site_id, idempotency_key="first")
    assert published.status_code == 201, published.data
    return client, organization, site_id, pages, _verified_platform_domain(site_id).hostname


def _submit(host: str, publication_id: Any, path: str, key: str) -> Any:
    return APIClient(enforce_csrf_checks=True).post(
        INQUIRIES,
        {
            "publication_id": str(publication_id),
            "path": path,
            "block_position": 1,
            "name": "Jane Visitor",
            "email": "visitor@example.test",
            "phone": "",
            "message": "Please tell me more.",
            "website": "",
        },
        format="json",
        HTTP_HOST=host,
        HTTP_ORIGIN=f"https://{host}",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _accept_offer_in_english(client: Any, offer: str) -> None:
    """A derived publication elsewhere on the site: the offer's English,
    reviewed and accepted."""
    _translate_all(client, offer, "oferta-en")
    row = PageTranslation.all_objects.get(page_id=offer, locale="en")
    PageTranslation.all_objects.filter(pk=row.pk).update(
        body_pending=row.body_current, body_current=None, pending_reason="review_mode"
    )
    accepted = _send(
        client,
        "post",
        _url(offer, tail="accept/"),
        {"expected_body_version": row.body_version},
        key="accept-offer",
    )
    assert accepted.status_code == 200 and accepted.data["published"], accepted.data


def test_a_form_opened_before_a_later_publication_sends_while_it_is_the_same_form():
    client, _, site_id, pages, host = _bilingual_site("read-form")
    opened = Site.all_objects.get(pk=site_id).current_publication_id
    _accept_offer_in_english(client, pages["oferta"])
    assert Site.all_objects.get(pk=site_id).current_publication_id != opened

    english = _submit(host, opened, "/en/kontakt-en/", "english")
    polish = _submit(host, opened, "/kontakt/", "polish")

    assert english.status_code == 201, english.data
    assert polish.status_code == 201, polish.data
    inquiry = SiteInquiry.all_objects.get(pk=english.data["reference"])
    assert (inquiry.locale, inquiry.page_path) == ("en", "/en/kontakt-en/")
    assert SiteInquiry.all_objects.get(pk=polish.data["reference"]).locale == "pl"
    listed = client.get(f"/api/v1/sites/{site_id}/inquiries/")
    assert {item["locale"] for item in listed.data["items"]} == {"pl", "en"}
    # The form itself changes: a form opened before that is another form.
    _draft(
        client,
        pages["kontakt"],
        1,
        [_hero("Kontakt", "Napisz"), _form(contact="callback")],
        "kontakt-v2",
    )
    publish_site_request(client, site_id, idempotency_key="form-changed")
    stale = _submit(host, opened, "/kontakt/", "stale")
    assert stale.status_code == 409
    assert stale.data["code"] == "site_inquiry_publication_changed"


@override_settings(SITES_PAGE_VIEW_COUNTER_ENABLED=True)
def test_a_view_is_counted_with_the_language_of_its_address():
    _, _, site_id, _pages, host = _bilingual_site("read-views")

    assert _get(host, "/en/kontakt-en/", HTTP_X_SAAS_CORE_COUNT_VIEW="1").status_code == 200
    assert _get(host, "/kontakt/", HTTP_X_SAAS_CORE_COUNT_VIEW="1").status_code == 200

    rows = PageViewDay.all_objects.filter(site_id=site_id)
    assert {(row.path, row.locale) for row in rows} == {
        ("/en/kontakt-en/", "en"),
        ("/kontakt/", "pl"),
    }


def test_internal_links_lead_to_the_live_version_in_the_reader_s_language():
    client, _, site_id, pages, host = _bilingual_site("read-links")
    hero = _hero("Witaj", "Studio")
    hero["data"]["action"] = {"label": "Napisz", "href": "/kontakt/?temat=biuro#formularz"}
    hero["data"]["secondaryAction"] = {"label": "Oferta", "href": "/oferta/"}
    footer = {
        "block_type": "core.footer",
        "schema_version": 2,
        "data": {
            "text": "Studio",
            "links": [
                {"label": "Kontakt", "href": "/kontakt", "rel": "nofollow"},
                {"label": "Start", "href": "/start/"},
                {"label": "Partner", "href": "https://partner.example/kontakt/"},
            ],
        },
    }
    _draft(client, pages["start"], 1, [hero, footer], "start-links")
    body = client.get(_url(pages["start"])).data
    moved = _send(
        client,
        "post",
        _url(pages["start"], tail="rebase/"),
        {"expected_body_version": body["body_version"]},
        key="start-rebase",
    )
    assert moved.status_code == 201, moved.data
    _translate_all(client, pages["start"], "start-en-links")
    publish_site_request(client, site_id, idempotency_key="links")

    english = _get(host, "/en/").data["blocks"]
    polish = _get(host, "/").data["blocks"]

    assert english[0]["data"]["action"]["href"] == "/en/kontakt-en/?temat=biuro#formularz"
    # No English offer yet: the Polish one is where that link still leads.
    assert english[0]["data"]["secondaryAction"]["href"] == "/oferta/"
    assert english[1]["data"]["links"] == [
        {"label": "EN Kontakt", "href": "/en/kontakt-en/", "rel": "nofollow"},
        {"label": "EN Start", "href": "/en/"},
        {"label": "EN Partner", "href": "https://partner.example/kontakt/"},
    ]
    assert polish[0]["data"]["action"]["href"] == "/kontakt/?temat=biuro#formularz"
    assert polish[1]["data"]["links"][0]["href"] == "/kontakt"


def test_every_link_field_of_the_block_contracts_is_localized():
    """A new block with a link field must be added here or to LINK_FIELDS."""
    not_pages = {"path"}  # core.entry_list: an entry, with its own siblings
    found: set[str] = set()

    def walk(node: Any, key: str | None) -> None:
        if isinstance(node, dict):
            pattern = node.get("pattern")
            if (
                key
                and isinstance(pattern, str)
                and any(start in pattern for start in ("^/", "|/", "(?:/", "(/"))
            ):
                found.add(key)
            for child_key, child in node.items():
                walk(child, child_key)
        elif isinstance(node, list):
            for child in node:
                walk(child, key)

    for path in Path(settings.SITE_BLOCK_CONTRACTS_PATH).glob("*.schema.json"):
        walk(json.loads(path.read_text()), None)
    assert found - not_pages == set(LINK_FIELDS)


def test_a_carried_language_version_keeps_its_pictures_or_waits_when_one_is_gone():
    client, organization, site_id, pages, host = _bilingual_site("read-media")
    user = Membership.objects.filter(organization=organization).first().user
    old, new = create_media_asset(organization, user), create_media_asset(organization, user)

    def with_photo(asset: Any, text: str) -> list[dict[str, Any]]:
        block = _hero("Kontakt", text)
        block["data"]["image"] = {"asset_id": str(asset.id), "alt": "Biuro"}
        return [block, _form()]

    def draft(version: int, asset: Any, text: str, key: str) -> None:
        response = _send(
            client,
            "put",
            f"/api/v1/sites/pages/{pages['kontakt']}/draft/",
            {
                "expected_version": version,
                "blocks": with_photo(asset, text),
                "media_asset_ids": [str(asset.id)],
            },
            key=key,
        )
        assert response.status_code in (200, 201), response.data

    draft(1, old, "Napisz", "photo-old")
    body = client.get(_url(pages["kontakt"])).data
    _send(
        client,
        "post",
        _url(pages["kontakt"], tail="rebase/"),
        {"expected_body_version": body["body_version"]},
        key="photo-rebase",
    )
    _translate_all(client, pages["kontakt"], "kontakt-en-photo")
    publish_site_request(client, site_id, idempotency_key="with-old-photo")
    # Polish gets a new picture and new words no English text translates yet
    # (words it already had would be realigned by their hash); English is not
    # refreshed and stays as it was.
    draft(2, new, "Napisz, zadzwoń albo wpadnij", "photo-new")
    publish_site_request(client, site_id, idempotency_key="with-new-photo")

    snapshot = Site.all_objects.get(pk=site_id).current_publication.snapshot
    contact = next(page for page in snapshot["pages"] if page["page_id"] == pages["kontakt"])
    english = next(entry for entry in contact["locales"] if entry["locale"] == "en")
    assert english["media_asset_ids"] == [str(old.id)]
    assert contact["media_asset_ids"] == [str(new.id)]
    assert {str(old.id), str(new.id)} <= _published_asset_ids(
        organization_id=organization.id, site_id=site_id
    )
    assert _get(host, "/en/kontakt-en/").status_code == 200

    # The old picture is deleted from the library: Polish still publishes and
    # English waits, answering 307 to the Polish page.
    MediaAsset.all_objects.filter(pk=old.pk).update(
        deleted_at=timezone.now(), deleted_by=user, deletion_idempotency_key="old-gone"
    )
    published = publish_site_request(client, site_id, idempotency_key="after-delete")

    assert published.status_code == 201, published.data
    snapshot = Site.all_objects.get(pk=site_id).current_publication.snapshot
    assert {"page_id": pages["kontakt"], "locale": "en", "reason": "media_unavailable"} in (
        snapshot["skipped_locales"]
    )
    waiting = _get(host, "/en/kontakt-en/")
    assert waiting.status_code == 307
    assert waiting["Location"] == "/kontakt/"


def test_a_site_snapshot_is_read_once_per_process():
    _, _, _site_id, _pages, host = _bilingual_site("read-once")

    def snapshot_reads(path: str) -> int:
        with CaptureQueriesContext(connection) as queries:
            assert _get(host, path).status_code == 200
        return sum(
            '"sites_publication"."snapshot"' in query["sql"] for query in queries.captured_queries
        )

    assert snapshot_reads("/en/kontakt-en/") == 1
    assert snapshot_reads("/kontakt/") == 0
    assert snapshot_reads("/en/") == 0
