"""Publishing pages in other languages (ADR-070 pkt 6–10, plan TL9a): snapshot v2,
one verdict for what may go out, the home page opening a language, a version
that was public kept in its last form, and a stale fact withholding it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.shared.sites.language_publication import facts_changed
from saas_core.modules.shared.sites.models import PageTranslation, Site
from test_site_language_versions_api import _draft, _hero, _page, _paragraph, _translate, _url
from test_sites_api import create_site, publish_site_request, sites_client
from test_sites_collections import _verified_platform_domain

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _translate_all(client: Any, page_id: str, key: str, prefix: str = "EN ") -> None:
    body = client.get(_url(page_id)).data
    units = {
        unit["key"]: f"{prefix}{unit['source_text']}"
        for unit in body["units"]
        if unit["kind"] in ("text", "inline")
    }
    saved = _translate(client, page_id, units, key)
    assert saved.status_code in (200, 201), saved.data
    assert saved.data["untranslated"] == 0


def _publish(client: Any, site_id: str, key: str) -> dict[str, Any]:
    published = publish_site_request(client, site_id, idempotency_key=key)
    assert published.status_code == 201, published.data
    return Site.all_objects.get(pk=site_id).current_publication.snapshot


def _get(host: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)


def _site(slug: str) -> tuple[Any, str, str, str, str]:
    client, _, _ = sites_client(slug=slug, role_key="owner")
    site_id = create_site(client).data["id"]
    home = str(_page(client, site_id, "start", [_hero("Witaj", "Studio projektowe")]))
    offer = str(_page(client, site_id, "oferta", [_hero("Oferta", "Projekt od 120 zł za m²")]))
    host = _verified_platform_domain(site_id).hostname
    return client, site_id, home, offer, host


def test_a_complete_language_goes_out_with_its_own_body():
    client, site_id, home, offer, host = _site("lang-publish")
    _translate_all(client, home, "home-en")
    _translate_all(client, offer, "offer-en")

    snapshot = _publish(client, site_id, "publish")

    assert snapshot["live_locales"] == ["pl", "en"]
    assert snapshot["skipped_locales"] == []
    page = next(item for item in snapshot["pages"] if item["page_id"] == offer)
    # The source language keeps the page's own blocks: a reader of schema 1
    # still serves Polish correctly.
    assert page["blocks"][0]["data"]["title"] == "Oferta"
    english = next(item for item in page["locales"] if item["locale"] == "en")
    assert english["blocks"][0]["data"]["title"] == "EN Oferta"
    assert english["origin"] == {"origin": "human", "machine": False, "reviewed": True}
    assert page["hreflang"] == {"pl": "/oferta/", "en": "/en/oferta-en/"}

    # The overview says the versions are on the site, not only translated.
    overview = client.get(f"/api/v1/sites/{site_id}/translations/").json()["items"]
    assert {(row["id"], row["source_id"]) for row in overview} == {(home, home), (offer, offer)}
    assert [[(cell["state"], cell["on_site"]) for cell in row["cells"]] for row in overview] == [
        [("complete", True)],
        [("complete", True)],
    ]

    served = _get(host, "/en/oferta-en/")
    assert served.status_code == 200, served.data
    assert served.data["locale"] == "en"
    assert served.data["blocks"][0]["data"]["text"] == "EN Projekt od 120 zł za m²"
    assert set(served.data["hreflang"]) == {"pl", "en"}
    root = _get(host, "/en/")
    assert root.status_code == 200
    assert root.data["blocks"][0]["data"]["title"] == "EN Witaj"
    assert PageTranslation.all_objects.get(page_id=offer, locale="en").slug_locked_at is not None


def test_a_language_waits_for_its_home_page_and_for_every_unit():
    client, site_id, home, offer, host = _site("lang-home-first")
    _translate_all(client, offer, "offer-en")

    snapshot = _publish(client, site_id, "publish")

    assert snapshot["live_locales"] == ["pl"]
    assert {(item["page_id"], item["reason"]) for item in snapshot["skipped_locales"]} == {
        (home, "untranslated_units"),
        (offer, "locale_home_missing"),
    }
    # Never public, so not an address anybody has: 404, not a redirect.
    assert _get(host, "/en/oferta-en/").status_code == 404
    # „Przetłumaczona” alone does not put a version on the site.
    cells = {
        row["id"]: row["cells"][0]
        for row in client.get(f"/api/v1/sites/{site_id}/translations/").json()["items"]
    }
    assert (cells[offer]["state"], cells[offer]["on_site"]) == ("complete", False)
    assert cells[home]["on_site"] is False
    assert _get(host, "/oferta/").data["hreflang"] == {"pl": f"https://{host}/oferta/"}


def test_a_public_version_keeps_its_last_form_and_a_changed_price_withholds_it():
    client, site_id, home, offer, host = _site("lang-carried")
    _translate_all(client, home, "home-en")
    _translate_all(client, offer, "offer-en")
    _publish(client, site_id, "first")

    # Words change on the home page, a price on the offer; English is not
    # refreshed for either.
    _draft(client, home, 1, [_hero("Witamy", "Studio projektowe")], "home-v2")
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 150 zł za m²")], "offer-v2")
    snapshot = _publish(client, site_id, "second")

    entries = {
        item["page_id"]: next(entry for entry in item["locales"] if entry["locale"] == "en")
        for item in snapshot["pages"]
    }
    assert entries[home]["withheld"] is False
    assert entries[home]["blocks"][0]["data"]["title"] == "EN Witaj"
    assert entries[offer]["withheld"] is True
    assert _get(host, "/en/").status_code == 200

    stale = _get(host, "/en/oferta-en/")
    assert stale.status_code == 307
    assert stale["Location"] == "/oferta/"
    assert _get(host, "/oferta/").data["hreflang"] == {"pl": f"https://{host}/oferta/"}
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        sitemap = APIClient().get("/api/v1/public/site/sitemap.xml", HTTP_HOST=host)
    assert "/en/oferta-en/" not in sitemap.content.decode()
    assert "/en/" in sitemap.content.decode()


def test_a_version_of_an_older_source_that_was_never_public_waits_for_a_move():
    client, site_id, home, offer, host = _site("lang-outdated")
    _translate_all(client, home, "home-en")
    _translate_all(client, offer, "offer-en")
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 120 zł za m² brutto")], "offer-v2")

    snapshot = _publish(client, site_id, "publish")

    assert snapshot["live_locales"] == ["pl", "en"]
    assert snapshot["skipped_locales"] == [
        {"page_id": offer, "locale": "en", "reason": "source_outdated"}
    ]
    assert _get(host, "/en/oferta-en/").status_code == 404


def test_fact_changes_are_caught_per_unit_and_across_the_page():
    def body(*texts: str) -> list[dict[str, Any]]:
        return [_paragraph(text) for text in texts]

    assert not facts_changed(body("Cena 120 zł", "Bez zmian"), body("Cena: 120 zł", "Nadal"))
    assert facts_changed(body("Cena 120 zł"), body("Cena 150 zł"))
    # The same values swapped between two services: equal as a set, not in place.
    assert facts_changed(
        body("Strzyżenie 120 zł", "Koloryzacja 150 zł"),
        body("Strzyżenie 150 zł", "Koloryzacja 120 zł"),
    )
    # A value repeated in two places, then changed in one.
    assert facts_changed(body("120 zł", "120 zł"), body("120 zł", "150 zł"))
    # Tokens of an inline run are not facts.
    rich = {
        "block_type": "core.rich_text",
        "schema_version": 4,
        "data": {"content": [{"type": "paragraph", "content": [{"text": "a", "bold": True}]}]},
    }
    assert not facts_changed([rich], [rich])
    # Metadata counts too.
    assert facts_changed(body("x"), body("x"), old_meta=("Od 99 zł",), new_meta=("Od 89 zł",))


def test_fifty_pages_in_five_languages_fit_the_snapshot_budget():
    recipe = json.loads(
        (Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH) / "core.service_focused.v2.json").read_text(
            encoding="utf-8"
        )
    )
    per_page = len(json.dumps(recipe["blocks"], ensure_ascii=False).encode())
    # Blocks dominate the snapshot: 50 pages, each in 5 languages.
    assert per_page * 50 * 5 <= 3_000_000, per_page
