"""A language the company switches off is off at once (ADR-071 pkt 8, 9; plan TL10c):
its addresses answer 308 to the source page and leave hreflang, the menu, the
sitemap and the feed; nothing is deleted or published, and switching it on
again brings the pages back as they were."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import ContentCollection, PageTranslation, Site
from test_site_language_publication import _translate_all
from test_site_language_versions_api import _hero, _page
from test_sites_api import create_site, csrf_value, publish_site_request, sites_client
from test_sites_collections import (
    _verified_platform_domain,
    create_collection,
    create_entry,
    publish,
    save_entry_draft,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/organizations/current/public-locales/"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _get(host: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)


def _xml(host: str, path: str) -> str:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get(path, HTTP_HOST=host).content.decode()


def _locales(client: Any, locales: list[str], key: str, *, preview: bool = False) -> Any:
    version = client.get(URL).data["version"]
    return getattr(client, "post" if preview else "put")(
        URL + ("preview/" if preview else ""),
        {"public_locales": locales, "expected_version": version},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        **({} if preview else {"HTTP_IDEMPOTENCY_KEY": key}),
    )


def _site_in_two_languages(slug: str) -> tuple[Any, str, dict[str, str], str]:
    """Home and offer pages live in Polish and English, and an article in both."""
    client, organization, _ = sites_client(slug=slug, role_key="owner")
    Organization.objects.filter(pk=organization.pk).update(public_locales=["pl", "en"])
    site_id = create_site(client).data["id"]
    pages = {
        "start": str(_page(client, site_id, "start", [_hero("Witaj", "Studio")])),
        "oferta": str(_page(client, site_id, "oferta", [_hero("Oferta", "Projekty")])),
    }
    for key, page_id in pages.items():
        _translate_all(client, page_id, f"{key}-en")
    collection = create_collection(client, site_id)
    polish = create_entry(client, collection.data["id"], slug="po-polsku", idempotency_key="pl")
    save_entry_draft(
        client, polish.data["id"], expected_version=0, text="Treść.", idempotency_key="pl-d"
    )
    publish(client, polish.data["id"], idempotency_key="pl-p")
    english = client.post(
        f"/api/v1/sites/entries/{polish.data['id']}/translations/",
        {"locale": "en", "slug": "in-english", "title": "In English"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="en",
    )
    save_entry_draft(
        client, english.data["id"], expected_version=0, text="Text.", idempotency_key="en-d"
    )
    publish(client, english.data["id"], idempotency_key="en-p")
    published = publish_site_request(client, site_id, idempotency_key="site")
    assert published.status_code == 201, published.data
    return client, site_id, pages, _verified_platform_domain(site_id).hostname


def test_switching_a_language_off_redirects_its_addresses_and_on_brings_them_back():
    client, site_id, pages, host = _site_in_two_languages("lang-off")
    publication = Site.all_objects.get(pk=site_id).current_publication_id
    assert _get(host, "/en/oferta-en/").status_code == 200

    preview = _locales(client, ["pl"], "", preview=True)
    removed = _locales(client, ["pl"], "off")

    assert preview.status_code == 200, preview.data
    assert {(item["path"], item["target"]) for item in preview.data["redirects"]} == {
        ("/en/", "/"),
        ("/en/oferta-en/", "/oferta/"),
        ("/en/blog/in-english/", "/blog/po-polsku/"),
    }
    assert removed.status_code == 200, removed.data
    for path, target in (
        ("/en/oferta-en/", "/oferta/"),
        ("/en/", "/"),
        ("/en/blog/in-english/", "/blog/po-polsku/"),
    ):
        moved = _get(host, path)
        assert (moved.status_code, moved["Location"]) == (308, target), path
    polish = _get(host, "/oferta/").data
    assert set(polish["hreflang"]) == {"pl"}
    assert set(_get(host, "/blog/po-polsku/").data["hreflang"]) == {"pl"}
    sitemap = _xml(host, "/api/v1/public/site/sitemap.xml")
    assert "/en/" not in sitemap and "/oferta/" in sitemap
    assert "in-english" not in _xml(host, "/api/v1/public/site/feed.xml")
    # Nothing deleted, nothing published.
    assert Site.all_objects.get(pk=site_id).current_publication_id == publication
    assert PageTranslation.all_objects.get(page_id=pages["oferta"], locale="en").body_current_id

    restored = _locales(client, ["pl", "en"], "on")

    assert restored.status_code == 200, restored.data
    assert _get(host, "/en/oferta-en/").status_code == 200
    assert _get(host, "/en/").status_code == 200
    assert set(_get(host, "/oferta/").data["hreflang"]) == {"pl", "en"}
    assert Site.all_objects.get(pk=site_id).current_publication_id == publication


def test_a_language_whose_prefix_is_already_an_address_cannot_be_added():
    client, organization, _ = sites_client(slug="lang-conflict", role_key="owner")
    Organization.objects.filter(pk=organization.pk).update(public_locales=["pl"])
    site_id = create_site(client).data["id"]
    collection = create_collection(client, site_id, key="news", base_path="aktualnosci")
    # An address older than the rule that reserves two-letter segments.
    ContentCollection.all_objects.filter(pk=collection.data["id"]).update(base_path="en")

    refused = _locales(client, ["pl", "en"], "conflict")

    assert refused.status_code == 400
    assert {(error["field"], error["code"]) for error in refused.data["errors"]} == {
        ("public_locales", "locale_path_conflict")
    }
