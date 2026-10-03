"""The sitemap names each page's versions in the other languages, with one
x-default and a `lastmod` per language, and leaves out what visitors cannot
read; the head says the page's language and the site's name, and shows its
first picture where the page is shared (TL14c)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import Site
from saas_core.modules.shared.sites.publication_routing import _social_image
from test_site_language_publication import _get, _publish, _site, _translate_all
from test_site_language_versions_api import _draft, _hero
from test_sites_blog_languages import Blog, _translate_entry

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _sitemap(host: str) -> str:
    cache.clear()
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return (
            APIClient()
            .get("/api/v1/public/site/sitemap.xml", HTTP_HOST=host, HTTP_ACCEPT="application/xml")
            .content.decode()
        )


def _url(sitemap: str, host: str, path: str) -> str:
    """The `<url>` element of one address."""
    found = re.search(
        rf"<url><loc>https://{re.escape(host)}{re.escape(path)}</loc>.*?</url>", sitemap
    )
    assert found is not None, (path, sitemap)
    return found.group(0)


def _versions(element: str) -> dict[str, str]:
    return dict(re.findall(r'hreflang="([^"]+)" href="https://[^/]+([^"]*)"', element))


def _two_language_site(slug: str) -> tuple[Any, str, str, str, str]:
    client, site_id, home, offer, host = _site(slug)
    _translate_all(client, home, f"{slug}-home-en")
    _translate_all(client, offer, f"{slug}-offer-en")
    _publish(client, site_id, f"{slug}-first")
    return client, site_id, home, offer, host


def test_each_page_names_its_versions_with_one_x_default_and_its_own_lastmod() -> None:
    _client, _site_id, _home, _offer, host = _two_language_site("map-versions")

    sitemap = _sitemap(host)

    assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in sitemap
    expected = {"pl": "/oferta/", "en": "/en/oferta-en/", "x-default": "/oferta/"}
    # Every version names the whole cluster, itself included.
    assert _versions(_url(sitemap, host, "/oferta/")) == expected
    assert _versions(_url(sitemap, host, "/en/oferta-en/")) == expected
    assert _versions(_url(sitemap, host, "/en/")) == {"pl": "/", "en": "/en/", "x-default": "/"}
    assert "<lastmod>" in _url(sitemap, host, "/en/oferta-en/")


def test_a_withheld_or_switched_off_version_is_nobodys_alternate() -> None:
    client, site_id, home, offer, host = _two_language_site("map-withheld")
    # A price changes on the offer and English is not refreshed: withheld.
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 150 zł za m²")], "offer-v2")
    _publish(client, site_id, "second")

    withheld = _sitemap(host)
    assert "/en/oferta-en/" not in withheld
    assert _versions(_url(withheld, host, "/oferta/")) == {}
    assert _versions(_url(withheld, host, "/")) == {"pl": "/", "en": "/en/", "x-default": "/"}

    Organization.objects.filter(pk=Site.all_objects.get(pk=site_id).organization_id).update(
        public_locales=["pl"]
    )
    switched_off = _sitemap(host)
    assert "/en/" not in switched_off
    assert "hreflang" not in switched_off


def test_a_languages_lastmod_moves_only_with_its_own_text() -> None:
    client, site_id, home, _offer, _host = _two_language_site("map-lastmod")

    def changed() -> dict[str, str]:
        snapshot = Site.all_objects.get(pk=site_id).current_publication.snapshot
        page = next(item for item in snapshot["pages"] if item["page_id"] == home)
        return {item["locale"]: item["changed_at"] for item in page["locales"]}

    first = changed()
    _publish(client, site_id, "again")
    assert changed() == first
    # New words on the Polish home page; English keeps its last form.
    _draft(client, home, 1, [_hero("Witamy", "Studio projektowe")], "home-v2")
    _publish(client, site_id, "words")
    after = changed()
    assert after["pl"] > first["pl"]
    assert after["en"] == first["en"]


def test_articles_indexes_and_topics_are_clusters_of_their_languages() -> None:
    blog = Blog("map-blog")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")

    sitemap = _sitemap(blog.host)

    assert _versions(_url(sitemap, blog.host, "/en/blog/in-english/")) == {
        "pl": "/blog/wpis-jeden/",
        "en": "/en/blog/in-english/",
        "x-default": "/blog/wpis-jeden/",
    }
    assert _versions(_url(sitemap, blog.host, "/blog/")) == {
        "pl": "/blog/",
        "en": "/en/blog/",
        "x-default": "/blog/",
    }
    # One article on the subject is not a topic page in either language.
    assert "/tag/porady/" not in sitemap


def test_the_head_says_the_language_the_site_and_the_article() -> None:
    blog = Blog("head-article")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    blog.english_names("Journal", "Tips")

    english = _get(blog.host, "/en/blog/in-english/").data
    home = _get(blog.host, "/en/").data

    assert english["social"]["locale"] == "en_US"
    assert english["social"]["alternate_locales"] == ["pl_PL"]
    assert english["social"]["site_name"] == Site.all_objects.get(pk=blog.site_id).name
    assert english["social"]["image"] is None
    # The article's subjects in its own language.
    assert [tag["name"] for tag in english["article"]["tags"]] == ["Tips"]
    assert home["social"]["locale"] == "en_US"
    assert home["article"] is None


def test_the_shared_picture_is_the_pages_first_published_one_described_in_its_language() -> None:
    published, other = (
        "019ff20d-a000-7000-8000-000000000001",
        "019ff20d-a000-7000-8000-0000000000ff",
    )
    page = SimpleNamespace(page={"selected_locale": {"media_asset_ids": [published]}})
    blocks = [
        {"block_type": "core.hero", "data": {"heading": "Witaj"}},
        # Not published with the page: a visitor could not fetch it.
        {"block_type": "core.image", "data": {"image": {"asset_id": other, "alt": "Inne"}}},
        {
            "block_type": "core.gallery",
            "data": {"images": [{"asset_id": published, "alt": "Salon from the street"}]},
        },
    ]

    assert _social_image(page, blocks, "https://studio.example.test") == {  # type: ignore[arg-type]
        "url": f"https://studio.example.test/media/{published}",
        "alt": "Salon from the street",
    }
    assert _social_image(page, blocks[:1], "https://studio.example.test") is None  # type: ignore[arg-type]
