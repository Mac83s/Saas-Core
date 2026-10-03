"""`/llms.txt` per language (TL19): the site's map for a language model's
first read — its name, what it is, the pages in the menu's order and the
newest articles, in one language, and only addresses a visitor gets now."""

from __future__ import annotations

import re

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import Site
from test_site_language_publication import _get, _publish
from test_site_language_versions_api import _draft, _hero
from test_sites_blog_languages import Blog, _translate_entry
from test_sites_sitemap_head import _two_language_site

pytestmark = pytest.mark.django_db

LINK = re.compile(r"^- \[([^\]]+)\]\((https://[^)]+)\)(?:: (.*))?$")


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _llms(host: str, locale: str | None = None) -> tuple[int, str]:
    cache.clear()
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        response = APIClient().get(
            "/api/v1/public/site/llms.txt",
            {"locale": locale} if locale else {},
            HTTP_HOST=host,
            HTTP_ACCEPT="text/plain",
        )
    return response.status_code, response.content.decode()


def _links(document: str) -> list[str]:
    return [match.group(2) for line in document.splitlines() if (match := LINK.match(line))]


def test_the_file_is_one_h1_a_summary_and_sections_of_links_in_one_language() -> None:
    _client, _site_id, _home, _offer, host = _two_language_site("llms-shape")

    status, polish = _llms(host)
    english_status, english = _llms(host, "en")

    assert (status, english_status) == (200, 200)
    lines = polish.splitlines()
    assert lines[0].startswith("# ") and polish.count("\n# ") == 0
    assert "## Strony" in polish and "## Pages" in english
    # Every list item under a section is a link — no loose text there.
    for document in (polish, english):
        section = document.split("\n## ", 1)[1]
        assert all(LINK.match(line) for line in section.splitlines()[1:] if line.strip())
    assert f"https://{host}/" in _links(polish)
    assert f"https://{host}/oferta/" in _links(polish)
    assert _links(english) == [f"https://{host}/en/", f"https://{host}/en/oferta-en/"]
    # One language per file: no English address in the Polish one.
    assert not any("/en/" in link for link in _links(polish))


def test_the_sites_own_language_has_the_bare_address_only() -> None:
    _client, _site_id, _home, _offer, host = _two_language_site("llms-bare")

    assert _llms(host, "pl")[0] == 404
    assert _llms(host, "de")[0] == 404
    assert _llms("unknown.example.test")[0] == 404


def test_only_addresses_a_visitor_gets_now_are_listed() -> None:
    client, site_id, _home, offer, host = _two_language_site("llms-available")
    # A price changes on the offer and English is not refreshed: withheld.
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 150 zł za m²")], "offer-v2")
    _publish(client, site_id, "second")

    assert _links(_llms(host, "en")[1]) == [f"https://{host}/en/"]

    Organization.objects.filter(pk=Site.all_objects.get(pk=site_id).organization_id).update(
        public_locales=["pl"]
    )
    assert _llms(host, "en")[0] == 404
    assert f"https://{host}/oferta/" in _links(_llms(host)[1])


def test_the_newest_articles_follow_the_pages_within_fifty_links() -> None:
    blog = Blog("llms-blog")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")

    polish = _llms(blog.host)[1]
    english = _llms(blog.host, "en")[1]

    assert "## Najnowsze wpisy" in polish
    assert "## Latest articles" in english
    assert any(link.endswith("/en/blog/in-english/") for link in _links(english))
    assert not any("/en/" in link for link in _links(polish))
    assert len(_links(polish)) <= 50


def test_a_page_points_at_the_llms_file_of_its_language() -> None:
    client, _site_id, _home, _offer, host = _two_language_site("llms-describedby")
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        polish = _get(host, "/").json()
        english = _get(host, "/en/").json()

    assert polish["describedby"] == f"https://{host}/llms.txt"
    assert english["describedby"] == f"https://{host}/en/llms.txt"
