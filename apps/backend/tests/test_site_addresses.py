"""Addresses of a customer site as visitors get them (ADR-071, plan TL2): the
home page at `/` and `/xx/`, one spelling per address, and no language version
that serves the source text under another language."""

from typing import Any
from uuid import uuid7

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    Publication,
    Site,
)
from test_domains import create_site, domain_client

pytestmark = pytest.mark.django_db

HERO = [{"block_type": "core.hero", "schema_version": 1, "data": {"heading": "x"}}]


def _locale(locale: str, path: str, title: str, *, body: bool = False) -> dict[str, Any]:
    return {
        "locale": locale,
        "path": path,
        "canonical_path": path,
        "title": title,
        "description": f"{title} opis",
        "social_title": title,
        "social_description": f"{title} opis",
        # A language version with its own body (ADR-070); the source language
        # uses the page's blocks.
        **({"blocks": HERO} if body else {}),
    }


def _page(key: str, locales: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "page_id": str(uuid7()),
        "key": key,
        "version_id": str(uuid7()),
        "version": 1,
        "blocks": HERO,
        "media_asset_ids": [],
        "locales": locales,
        "hreflang": {item["locale"]: item["path"] for item in locales},
        "x_default": locales[0]["path"],
        **extra,
    }


def _published(slug: str, pages: list[dict[str, Any]]) -> tuple[Site, str]:
    client, _, user = domain_client(slug=slug)
    site = Site.all_objects.get(pk=create_site(client, slug).data["id"])
    navigation = [
        {"page_id": page["page_id"], "parent_page_id": None, "position": position}
        for position, page in enumerate(pages)
    ]
    publication = Publication.all_objects.create(
        organization=site.organization,
        site=site,
        sequence=1,
        snapshot={
            "site_id": str(site.id),
            "site_slug": site.slug,
            "default_locale": "pl",
            "navigation": navigation,
            "redirects": [],
            "pages": pages,
        },
        snapshot_hash="",
        created_by=user,
        idempotency_key=f"{slug}-publication",
    )
    Site.all_objects.filter(pk=site.pk).update(current_publication=publication)
    hostname = Domain.all_objects.get(site=site, kind=DomainKind.PLATFORM).hostname
    return site, hostname


def _get(hostname: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=hostname)


def test_home_pages_answer_at_the_root_of_each_language():
    _, host = _published(
        "addr-home",
        [
            _page(
                "home",
                [_locale("pl", "/start/", "Start"), _locale("en", "/en/home/", "Home", body=True)],
                page_type="homepage",
            ),
            _page("offer", [_locale("pl", "/oferta/", "Oferta")]),
        ],
    )

    polish, english = _get(host, "/"), _get(host, "/en/")
    assert polish.status_code == 200
    assert polish.data["canonical_url"] == f"https://{host}/"
    assert polish.data["hreflang"] == {"pl": f"https://{host}/", "en": f"https://{host}/en/"}
    assert polish.data["x_default"] == f"https://{host}/"
    assert english.status_code == 200
    assert english.data["locale"] == "en"
    assert english.data["canonical_url"] == f"https://{host}/en/"
    # The menu links home by its root, like every other surface.
    assert [link["path"] for link in polish.data["navigation"]] == ["/", "/oferta/"]

    # The home page's slug address is the same page under a second address.
    for path, target in (("/start/", "/"), ("/start", "/"), ("/en/home/", "/en/")):
        moved = _get(host, path)
        assert moved.status_code == 308, path
        assert moved["Location"] == f"https://{host}{target}"


def test_a_language_version_without_its_own_body_moves_to_the_source_page():
    """Snapshots before per-language bodies carry one block list per page, so
    an English version served the Polish text under `lang="en"`."""
    site, host = _published(
        "addr-v1",
        [
            _page(
                "home",
                [_locale("pl", "/start/", "Start"), _locale("en", "/en/home/", "Home")],
                page_type="homepage",
            ),
            _page(
                "offer", [_locale("pl", "/oferta/", "Oferta"), _locale("en", "/en/offer/", "Offer")]
            ),
        ],
    )

    for path, target in (
        ("/en/offer/", "/oferta/"),
        ("/en/offer", "/oferta/"),
        ("/en/home/", "/"),
        ("/en/", "/"),
    ):
        moved = _get(host, path)
        assert moved.status_code == 308, path
        assert moved["Location"] == f"https://{host}{target}"

    offer = _get(host, "/oferta/")
    assert offer.status_code == 200
    assert offer.data["hreflang"] == {"pl": f"https://{host}/oferta/"}
    assert offer.data["x_default"] == f"https://{host}/oferta/"

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        sitemap = APIClient().get("/api/v1/public/site/sitemap.xml", HTTP_HOST=host)
    body = sitemap.content.decode()
    assert f"<loc>https://{host}/</loc>" in body
    assert f"<loc>https://{host}/oferta/</loc>" in body
    assert "/en/" not in body
    assert "/start/" not in body
    # Nothing was rewritten: the reading rule is applied, the snapshot kept.
    stored = Site.all_objects.get(pk=site.pk).current_publication.snapshot
    assert stored["pages"][1]["locales"][1]["path"] == "/en/offer/"


def test_an_address_answers_in_one_spelling():
    _, host = _published(
        "addr-slash",
        [
            _page("home", [_locale("pl", "/start/", "Start")], page_type="homepage"),
            _page("offer", [_locale("pl", "/oferta/", "Oferta")]),
        ],
    )

    assert _get(host, "/oferta/").status_code == 200
    other = _get(host, "/oferta")
    assert other.status_code == 308
    assert other["Location"] == f"https://{host}/oferta/"
    assert _get(host, "/nie-ma/").status_code == 404


def test_an_unprefixed_address_never_takes_a_language_prefix_or_a_platform_path():
    from io import StringIO

    from django.core.cache import cache
    from django.core.management import call_command

    from saas_core.modules.shared.sites.models import PageTranslation
    from test_sites_api import create_page, csrf_value, save_translation, sites_client
    from test_sites_api import create_site as create_sites_site
    from test_sites_collections import create_collection

    cache.clear()
    client, organization, _ = sites_client(slug="addr-reserved", role_key="owner")
    site_id = create_sites_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]

    def polish(slug: str, key: str) -> Any:
        return save_translation(
            client, page_id, "pl", expected_version=0, slug=slug, title="T", idempotency_key=key
        )

    for index, slug in enumerate(("de", "it", "api", "media", "site-renderer")):
        refused = polish(slug, f"reserved-{index}")
        assert refused.status_code == 400, slug
        assert refused.data["code"] == "slug_reserved"
    assert polish("apiary", "allowed").status_code in (200, 201)
    # Under its own prefix an English address may be two letters.
    english = save_translation(
        client, page_id, "en", expected_version=0, slug="de", title="T", idempotency_key="en"
    )
    assert english.status_code in (200, 201)
    blog = create_collection(client, site_id, base_path="en")
    assert blog.status_code == 400
    assert blog.data["code"] == "slug_reserved"
    moved = client.put(
        f"/api/v1/sites/pages/{page_id}/url/",
        {"locale": "pl", "slug": "fr", "reason": "Test."},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert moved.status_code == 400
    assert moved.data["code"] == "slug_reserved"

    # One saved before the rule keeps working and is listed for a decision.
    PageTranslation.all_objects.filter(page_id=page_id, locale="pl").update(slug="pl")
    out = StringIO()
    call_command("sites_reserved_slugs", stdout=out)
    assert f"{organization.id}\tmain-site\tpage\t/pl/\thome" in out.getvalue()
