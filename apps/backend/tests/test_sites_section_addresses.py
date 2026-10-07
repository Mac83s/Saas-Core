"""A section's name in the site's addresses, per language (ADR-071 pkt 14,
„Uzupełnienie 2026-10-07”): `/poradnik/`, `/en/blog/`, `/de/ratgeber/`.

The first test is the one that matters most and was written before the
change: a site that names no section per language keeps every address it had,
byte for byte, on every surface that prints one."""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings

from test_sites_blog_languages import Blog, _feed, _get, _items, _menu, _translate_entry
from test_sites_collections import _tagged_entry
from test_sites_llms import _links, _llms

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _locs(sitemap: str, host: str) -> list[str]:
    return sorted(
        loc.removeprefix(f"https://{host}") for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap)
    )


def _alternates(sitemap: str, host: str, path: str) -> dict[str, str]:
    """The language versions the sitemap names for one address."""
    entry = next(url for url in sitemap.split("<url>") if f"<loc>https://{host}{path}</loc>" in url)
    return {
        code: href.removeprefix(f"https://{host}")
        for code, href in re.findall(r'hreflang="([^"]+)" href="([^"]+)"', entry)
    }


def _addresses(blog: Blog) -> dict[str, Any]:
    """Every address the blog of a two-language site prints, by surface."""
    host = blog.host
    origin = f"https://{host}"

    def head(path: str) -> dict[str, Any]:
        response = _get(host, path)
        assert response.status_code == 200, (path, response.status_code)
        return {
            "canonical": response.data["canonical_url"].removeprefix(origin),
            "hreflang": {
                code: url.removeprefix(origin) for code, url in response.data["hreflang"].items()
            },
            "x_default": response.data["x_default"].removeprefix(origin),
            "breadcrumbs": [crumb["path"] for crumb in response.data["breadcrumbs"]],
            "switcher": [link["path"] for link in response.data["language_links"]],
        }

    with override_settings(SITES_ENTRY_INDEX_PAGE_SIZE=1):
        second = _get(host, "/blog/strona/2/")
        first = _get(host, "/blog/")
        paging = {
            "second": second.data["canonical_url"].removeprefix(origin),
            "previous": second.data["pagination"]["previous_path"],
            "next": first.data["pagination"]["next_path"],
        }
    sitemap = _feed(host, "sitemap.xml").content.decode()
    polish_index, english_index = _get(host, "/blog/"), _get(host, "/en/blog/")
    return {
        "index": {"pl": head("/blog/"), "en": head("/en/blog/")},
        "items": {"pl": _items(polish_index), "en": _items(english_index)},
        "entry": {"pl": head("/blog/wpis-jeden/"), "en": head("/en/blog/in-english/")},
        "tag": {"pl": head("/blog/tag/porady/"), "en": head("/en/blog/tag/porady/")},
        "paging": paging,
        "menu": {
            "pl": [path for _title, path, _lang in _menu(_get(host, "/"))],
            "en": [path for _title, path, _lang in _menu(_get(host, "/en/"))],
        },
        "rss": {
            "pl": re.findall(r"<link>([^<]+)</link>", _feed(host, "feed.xml").content.decode()),
            "en": re.findall(
                r"<link>([^<]+)</link>", _feed(host, "feed.xml", "en").content.decode()
            ),
        },
        "atom": re.findall(r'<entry>.*?href="([^"]+)"', _feed(host, "atom.xml").content.decode()),
        "sitemap": _locs(sitemap, host),
        "sitemap_alternates": {
            "/blog/": _alternates(sitemap, host, "/blog/"),
            "/en/blog/in-english/": _alternates(sitemap, host, "/en/blog/in-english/"),
        },
        "llms": {
            "pl": [link for link in _links(_llms(host)[1]) if "/blog/" in link],
            "en": [link for link in _links(_llms(host, "en")[1]) if "/blog/" in link],
        },
        "overview": sorted(
            cell["path"]
            for row in blog.client.get(
                f"/api/v1/sites/{blog.site_id}/translations/", {"kind": "entry"}
            ).json()["items"]
            for cell in row["cells"]
            if cell.get("path")
        ),
        "inventory": [
            collection["base_path"]
            for site in blog.client.get("/api/v1/sites/inventory/").json()["sites"]
            for collection in site["collections"]
        ],
    }


def _two_language_blog(slug: str) -> Blog:
    blog = Blog(slug)
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    second = str(_tagged_entry(blog.client, blog.collection_id, "dwa", ["Porady"]).data["id"])
    _translate_entry(blog.client, second, "second-one", "Second one")
    blog.publish("with-articles")
    return blog


def test_a_site_that_names_no_section_per_language_keeps_every_address() -> None:
    """Golden addresses of a site as it was before sections could be named
    per language: nothing here may change for a site that changes nothing."""
    blog = _two_language_blog("section-golden")
    origin = f"https://{blog.host}"
    index = {"pl": "/blog/", "en": "/en/blog/"}
    tag = {"pl": "/blog/tag/porady/", "en": "/en/blog/tag/porady/"}
    first = {"pl": "/blog/wpis-jeden/", "en": "/en/blog/in-english/"}
    switcher_home = ["/", "/en/"]

    assert _addresses(blog) == {
        "index": {
            "pl": {
                "canonical": "/blog/",
                "hreflang": index,
                "x_default": "/blog/",
                "breadcrumbs": ["/blog/"],
                "switcher": ["/blog/", "/en/blog/"],
            },
            "en": {
                "canonical": "/en/blog/",
                "hreflang": index,
                "x_default": "/blog/",
                "breadcrumbs": ["/en/blog/"],
                "switcher": ["/blog/", "/en/blog/"],
            },
        },
        "items": {
            "pl": ["/blog/wpis-dwa/", "/blog/wpis-jeden/"],
            "en": ["/en/blog/second-one/", "/en/blog/in-english/"],
        },
        "entry": {
            "pl": {
                "canonical": "/blog/wpis-jeden/",
                "hreflang": first,
                "x_default": "/blog/wpis-jeden/",
                "breadcrumbs": ["/blog/wpis-jeden/"],
                "switcher": ["/blog/wpis-jeden/", "/en/blog/in-english/"],
            },
            "en": {
                "canonical": "/en/blog/in-english/",
                "hreflang": first,
                "x_default": "/blog/wpis-jeden/",
                "breadcrumbs": ["/en/blog/in-english/"],
                "switcher": ["/blog/wpis-jeden/", "/en/blog/in-english/"],
            },
        },
        "tag": {
            "pl": {
                "canonical": "/blog/tag/porady/",
                "hreflang": tag,
                "x_default": "/blog/tag/porady/",
                # An archive's trail is its blog's place in the menu.
                "breadcrumbs": ["/blog/"],
                "switcher": ["/blog/tag/porady/", "/en/blog/tag/porady/"],
            },
            "en": {
                "canonical": "/en/blog/tag/porady/",
                "hreflang": tag,
                "x_default": "/blog/tag/porady/",
                "breadcrumbs": ["/en/blog/"],
                "switcher": ["/blog/tag/porady/", "/en/blog/tag/porady/"],
            },
        },
        "paging": {
            "second": "/blog/strona/2/",
            "previous": "/blog/",
            "next": "/blog/strona/2/",
        },
        "menu": {"pl": ["/blog/"], "en": ["/en/blog/"]},
        "rss": {
            "pl": [f"{origin}/", f"{origin}/blog/wpis-dwa/", f"{origin}/blog/wpis-jeden/"],
            "en": [
                f"{origin}/en/",
                f"{origin}/en/blog/second-one/",
                f"{origin}/en/blog/in-english/",
            ],
        },
        "atom": [f"{origin}/blog/wpis-dwa/", f"{origin}/blog/wpis-jeden/"],
        "sitemap": [
            "/",
            "/blog/",
            "/blog/wpis-dwa/",
            "/blog/wpis-jeden/",
            "/en/",
            "/en/blog/",
            "/en/blog/in-english/",
            "/en/blog/second-one/",
            "/oferta/",
        ],
        "sitemap_alternates": {
            "/blog/": {**index, "x-default": "/blog/"},
            "/en/blog/in-english/": {**first, "x-default": "/blog/wpis-jeden/"},
        },
        "llms": {
            "pl": [f"{origin}/blog/", f"{origin}/blog/wpis-dwa/", f"{origin}/blog/wpis-jeden/"],
            "en": [
                f"{origin}/en/blog/",
                f"{origin}/en/blog/second-one/",
                f"{origin}/en/blog/in-english/",
            ],
        },
        "overview": ["/en/blog/in-english/", "/en/blog/second-one/"],
        "inventory": ["blog"],
    }
    assert switcher_home == [link["path"] for link in _get(blog.host, "/").data["language_links"]]
