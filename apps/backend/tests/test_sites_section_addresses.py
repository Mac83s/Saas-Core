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
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from saas_core.modules.core.organizations import public_sources
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.public_sources import (
    PageAddress,
    PublicSource,
    SourcePage,
    SourcePageAddress,
    page_source,
    page_source_segments,
    register_public_source,
)
from saas_core.modules.shared.sites.localization import first_segment_reserved
from saas_core.modules.shared.sites.models import ContentCollection, Page, Site
from saas_core.modules.shared.sites.publication_routing import _localized_href
from saas_core.modules.shared.sites.translation_source import free_slug
from test_sites_api import csrf_value
from test_sites_blog_languages import Blog, _feed, _get, _items, _menu, _translate_entry
from test_sites_collections import _tagged_entry, create_collection
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


def _rename(
    blog: Blog,
    base_path: str,
    locale_paths: dict[str, str] | None = None,
    *,
    reason: str = "",
    preview: bool = False,
    collection_id: str | None = None,
) -> Any:
    url = f"/api/v1/sites/collections/{collection_id or blog.collection_id}/paths/"
    send = blog.client.post if preview else blog.client.put
    return send(
        url + ("preview/" if preview else ""),
        {"base_path": base_path, "locale_paths": locale_paths or {}, "reason": reason},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
    )


def _moved(host: str, path: str) -> tuple[int, str | None]:
    response = _get(host, path)
    return response.status_code, response.get("Location")


def _errors(response: Any) -> list[tuple[str | None, str]]:
    return [(error["field"], error["code"]) for error in response.json()["errors"]]


def test_a_language_names_the_section_its_own_way_on_every_surface() -> None:
    blog = _two_language_blog("section-own-name")
    host, origin = blog.host, f"https://{blog.host}"

    renamed = _rename(blog, "blog", {"en": "journal"}, reason="The English blog is a journal")

    assert renamed.status_code == 200, renamed.data
    assert renamed.data["moved"] == [
        {"locale": "en", "from_path": "/en/blog/", "to_path": "/en/journal/"}
    ]
    assert renamed.data["collection"]["paths"] == {"pl": "/blog/", "en": "/en/journal/"}
    listed = blog.client.get(f"/api/v1/sites/{blog.site_id}/collections/").data[0]
    assert (listed["base_path"], listed["locale_paths"]) == ("blog", {"en": "journal"})
    assert listed["paths"] == {"pl": "/blog/", "en": "/en/journal/"}

    # The site was not published again and no article was: every surface
    # reads the section's name as it is today.
    index = {"pl": "/blog/", "en": "/en/journal/"}
    article = {"pl": "/blog/wpis-jeden/", "en": "/en/journal/in-english/"}
    for path, versions in (
        ("/en/journal/", index),
        ("/blog/", index),
        ("/en/journal/in-english/", article),
        ("/blog/wpis-jeden/", article),
        ("/en/journal/tag/porady/", {"pl": "/blog/tag/porady/", "en": "/en/journal/tag/porady/"}),
    ):
        page = _get(host, path)
        assert page.status_code == 200, (path, page.status_code)
        assert page.data["canonical_url"] == origin + path
        assert page.data["hreflang"] == {code: origin + to for code, to in versions.items()}
        assert page.data["x_default"] == origin + versions["pl"]
        assert [link["path"] for link in page.data["language_links"]] == list(versions.values())
    english = _get(host, "/en/journal/")
    assert _items(english) == ["/en/journal/second-one/", "/en/journal/in-english/"]
    assert english.data["breadcrumbs"] == [{"title": "Blog", "path": "/en/journal/"}]
    assert [path for _title, path, _lang in _menu(_get(host, "/en/"))] == ["/en/journal/"]
    assert [path for _title, path, _lang in _menu(_get(host, "/"))] == ["/blog/"]
    # The article's structured data names the same address as its head.
    graph = str(_get(host, "/en/journal/in-english/").data["structured_data"])
    assert f"{origin}/en/journal/in-english/" in graph and "/en/blog/" not in graph

    sitemap = _feed(host, "sitemap.xml").content.decode()
    assert "/en/blog/" not in sitemap
    assert {"/en/journal/", "/en/journal/in-english/", "/en/journal/second-one/"} <= set(
        _locs(sitemap, host)
    )
    assert _alternates(sitemap, host, "/blog/") == {**index, "x-default": "/blog/"}
    assert _alternates(sitemap, host, "/blog/wpis-jeden/") == {
        **article,
        "x-default": "/blog/wpis-jeden/",
    }
    rss = _feed(host, "feed.xml", "en").content.decode()
    atom = _feed(host, "atom.xml", "en").content.decode()
    assert f"<link>{origin}/en/journal/in-english/</link>" in rss and "/en/blog/" not in rss
    assert f'href="{origin}/en/journal/in-english/"' in atom and "/en/blog/" not in atom
    llms = _links(_llms(host, "en")[1])
    assert f"{origin}/en/journal/" in llms and f"{origin}/en/journal/in-english/" in llms
    assert not any("/en/blog/" in link for link in llms)
    overview = blog.client.get(
        f"/api/v1/sites/{blog.site_id}/translations/", {"kind": "entry"}
    ).json()["items"]
    assert sorted(cell["path"] for row in overview for cell in row["cells"]) == [
        "/en/journal/in-english/",
        "/en/journal/second-one/",
    ]
    inventory = blog.client.get("/api/v1/sites/inventory/").json()["sites"][0]["collections"][0]
    assert (inventory["base_path"], inventory["paths"]) == ("blog", index)

    # Every address under the old name: one 308, straight to where it answers.
    with override_settings(SITES_ENTRY_INDEX_PAGE_SIZE=1):
        assert _moved(host, "/en/blog/page/2/") == (308, "/en/journal/page/2/")
        assert _moved(host, "/en/blog/tag/porady/page/2/") == (
            308,
            "/en/journal/tag/porady/page/2/",
        )
    for old, new in (
        ("/en/blog/", "/en/journal/"),
        ("/en/blog", "/en/journal/"),
        ("/en/blog/in-english/", "/en/journal/in-english/"),
        ("/en/blog/tag/porady/", "/en/journal/tag/porady/"),
    ):
        assert _moved(host, old) == (308, new), old
        assert _get(host, new).status_code == 200
    # An old name leads nowhere for what is not there.
    assert _get(host, "/en/blog/never-written/").status_code == 404
    assert _get(host, "/en/blog/tag/nothing/").status_code == 404


def test_a_renamed_section_answers_every_former_name_in_one_step() -> None:
    blog = _two_language_blog("section-renamed")
    host = blog.host

    # Naming nothing moves nothing, and asks for no reason.
    same = _rename(blog, "blog")
    assert (same.status_code, same.data["changed"], same.data["moved"]) == (200, False, [])
    # A move of an address visitors can open needs a reason: the preview says
    # which, and saves nothing.
    preview = _rename(blog, "poradnik", preview=True)
    assert preview.status_code == 200, preview.data
    assert preview.data["moved"] == [
        {"locale": "pl", "from_path": "/blog/", "to_path": "/poradnik/"},
        {"locale": "en", "from_path": "/en/blog/", "to_path": "/en/poradnik/"},
    ]
    assert preview.data["collection"]["paths"] == {"pl": "/poradnik/", "en": "/en/poradnik/"}
    assert _get(host, "/blog/").status_code == 200
    refused = _rename(blog, "poradnik")
    assert refused.status_code == 400
    assert _errors(refused) == [("reason", "redirect_reason_required")]
    assert _get(host, "/blog/").status_code == 200

    assert _rename(blog, "poradnik", reason="Polish name").status_code == 200
    # English follows the site's language until it has a name of its own.
    for old, new in (
        ("/blog/", "/poradnik/"),
        ("/blog/wpis-jeden/", "/poradnik/wpis-jeden/"),
        ("/blog/tag/porady/", "/poradnik/tag/porady/"),
        ("/en/blog/", "/en/poradnik/"),
        ("/en/blog/in-english/", "/en/poradnik/in-english/"),
    ):
        assert _moved(host, old) == (308, new), old
        assert _get(host, new).status_code == 200

    # A second rename: the first name leads to the third, never through the
    # second; then English gets its own, and its old addresses follow it.
    assert _rename(blog, "wiedza", reason="Better word").status_code == 200
    assert _rename(blog, "wiedza", {"en": "guides"}, reason="English name").status_code == 200
    for old, new in (
        ("/blog/wpis-jeden/", "/wiedza/wpis-jeden/"),
        ("/poradnik/wpis-jeden/", "/wiedza/wpis-jeden/"),
        ("/en/blog/in-english/", "/en/guides/in-english/"),
        ("/en/poradnik/in-english/", "/en/guides/in-english/"),
        ("/en/wiedza/", "/en/guides/"),
    ):
        assert _moved(host, old) == (308, new), old
        assert _get(host, new).status_code == 200

    # A language the company switched off: an old address of its article goes
    # straight to the article in the site's language.
    organization = Organization.objects.get(
        pk=Site.all_objects.get(pk=blog.site_id).organization_id
    )
    Organization.objects.filter(pk=organization.pk).update(public_locales=["pl"])
    assert _moved(host, "/en/blog/in-english/") == (308, "/wiedza/wpis-jeden/")
    Organization.objects.filter(pk=organization.pk).update(
        public_locales=organization.public_locales
    )

    # Taking a name back makes it the section's again, not a former one.
    assert _rename(blog, "blog", {"en": "guides"}, reason="Back").status_code == 200
    assert _get(host, "/blog/wpis-jeden/").status_code == 200
    assert _moved(host, "/wiedza/wpis-jeden/") == (308, "/blog/wpis-jeden/")
    collection = ContentCollection.all_objects.get(pk=blog.collection_id)
    assert {"locale": "pl", "path": "blog"} not in collection.former_paths
    assert {"locale": "pl", "path": "wiedza"} in collection.former_paths
    # An article published after the rename answers under today's name only.
    _tagged_entry(blog.client, blog.collection_id, "trzy", ["Porady"])
    assert _get(host, "/blog/wpis-trzy/").status_code == 200
    assert _moved(host, "/wiedza/wpis-trzy/") == (308, "/blog/wpis-trzy/")


def test_a_section_name_is_one_address_in_its_language() -> None:
    blog = _two_language_blog("section-unique")
    news = str(
        create_collection(
            blog.client, blog.site_id, key="news", base_path="news", idempotency_key="news"
        ).data["id"]
    )

    def refused(*args: Any, **kwargs: Any) -> list[tuple[str | None, str]]:
        response = _rename(blog, *args, **kwargs)
        assert response.status_code == 400, response.data
        return _errors(response)

    # Another section's name — its own, or the one its language follows.
    assert refused("blog", {"en": "news"}, reason="x") == [
        ("locale_paths.en", "section_path_taken")
    ]
    assert refused("news", reason="x") == [("base_path", "section_path_taken")]
    # A page's address in that language (the fixture's pages: /oferta/,
    # /en/oferta-en/), which is another language's free name.
    assert refused("oferta", reason="x") == [("base_path", "section_path_taken")]
    assert refused("blog", {"en": "oferta-en"}, reason="x") == [
        ("locale_paths.en", "section_path_taken")
    ]
    assert _rename(blog, "blog", {"en": "oferta"}, preview=True).status_code == 200
    # Reserved segments, in every language.
    assert refused("blog", {"en": "media"}, reason="x") == [("locale_paths.en", "slug_reserved")]
    assert refused("blog", {"en": "xy"}, reason="x") == [("locale_paths.en", "slug_reserved")]
    assert _rename(blog, "api", reason="x").json()["code"] == "slug_reserved"
    # Not a name, not this site's other language, not a language at all.
    assert refused("blog", {"en": "Dziennik Ąę"}) == [("locale_paths.en", "invalid")]
    assert refused("blog", {"pl": "dziennik"}) == [
        ("locale_paths.pl", "section_path_source_locale")
    ]
    assert refused("blog", {"de": "ratgeber"}) == [("locale_paths.de", "locale_not_enabled")]
    assert refused("blog", {"zz": "blog-zz"}) == [("locale_paths.zz", "locale_not_in_registry")]
    # The other section may take a name of its own in English, and then that
    # name is taken there too.
    taken = _rename(blog, "news", {"en": "journal"}, collection_id=news)
    assert (taken.status_code, taken.data["moved"]) == (200, [])
    assert refused("blog", {"en": "journal"}, reason="x") == [
        ("locale_paths.en", "section_path_taken")
    ]
    # A new page's address in that language steps aside for a section's name.
    assert free_slug(Page.all_objects.filter(site_id=blog.site_id).first(), "en", "journal") == (
        "journal-2"
    )

    # Nothing above was saved for the blog.
    assert _get(blog.host, "/en/blog/").status_code == 200
    created = blog.client.post(
        f"/api/v1/sites/{blog.site_id}/collections/",
        {
            "key": "guide",
            "name": "Guide",
            "kind": "guide",
            "base_path": "przewodnik",
            "locale_paths": {"en": "guide"},
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
        HTTP_IDEMPOTENCY_KEY="guide",
    )
    assert created.status_code == 201, created.data
    assert created.data["paths"] == {"pl": "/przewodnik/", "en": "/en/guide/"}
    clash = blog.client.post(
        f"/api/v1/sites/{blog.site_id}/collections/",
        {"key": "tips", "name": "Tips", "kind": "guide", "base_path": "guide"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
        HTTP_IDEMPOTENCY_KEY="tips",
    )
    # English would follow `guide`, which is the guide's name there.
    assert clash.status_code == 400
    assert _errors(clash) == [("base_path", "section_path_taken")]


def test_only_a_person_renames_a_section() -> None:
    """Moving an address costs what it earned: not an integration's trade,
    and not the assistant's without the person."""
    from django.test import Client as PlainClient

    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.core.organizations.person_gate import PersonRequired
    from saas_core.modules.shared.sites.collections import set_collection_paths
    from test_sites_api import automation_context

    blog = Blog("section-person")
    site = Site.all_objects.get(pk=blog.site_id)
    collection = ContentCollection.all_objects.get(pk=blog.collection_id)

    for method in ("put", "post"):
        suffix = "" if method == "put" else "preview/"
        refused = getattr(PlainClient(), method)(
            f"/api/v1/sites/collections/{blog.collection_id}/paths/{suffix}",
            data='{"base_path": "poradnik"}',
            content_type="application/json",
        )
        assert refused.status_code == 403
    with (
        activate_tenant_context(automation_context(site.organization_id, collection.created_by_id)),
        pytest.raises(PersonRequired),
    ):
        set_collection_paths(
            collection_id=collection.id, base_path="poradnik", locale_paths={}, reason="x"
        )
    assert ContentCollection.all_objects.get(pk=collection.id).base_path == "blog"


# --- A record source with a section name and a slug per language -------------

BREED_SLUGS = {"pl": "owczarek-niemiecki", "en": "german-shepherd"}


def _breed_page(
    _organization_id: Any, locale: str, slug: str, address: PageAddress
) -> SourcePage | None:
    """One record, found by its slug in any language, as the protocol asks."""
    if slug not in BREED_SLUGS.values():
        return None
    # A source links its page's other languages through the site's address.
    other = "en" if locale == "pl" else "pl"
    return SourcePage(
        key="breed-1",
        title={"pl": "Owczarek niemiecki", "en": "German Shepherd"}.get(locale, "Owczarek"),
        description="",
        blocks=[
            {
                "block_type": "core.rich_text",
                "schema_version": 1,
                "data": {"text": address(other, BREED_SLUGS[other])},
            }
        ],
        locales=frozenset({"en"}),
        slugs=BREED_SLUGS,
    )


def _breed_pages(_organization_id: Any) -> list[SourcePageAddress]:
    return [
        SourcePageAddress(
            slug=BREED_SLUGS["pl"], locales=frozenset({"en"}), slugs=BREED_SLUGS
        )
    ]


@pytest.fixture
def breeds(monkeypatch: pytest.MonkeyPatch) -> PublicSource:
    source = PublicSource(
        key="test.breeds",
        shown_media=lambda _organization_id: (),
        page_segment="rasy-psow",
        page_segments={"en": "dog-breeds", "de": "hunderassen"},
        site_page=_breed_page,
        site_pages=_breed_pages,
    )
    # Registered through the front door, taken back with the test.
    monkeypatch.setattr(public_sources, "_sources", dict(public_sources._sources))
    register_public_source(source)
    return source


def test_a_record_answers_under_its_section_and_slug_in_each_language(
    breeds: PublicSource,
) -> None:
    blog = Blog("section-records")
    host, origin = blog.host, f"https://{blog.host}"
    versions = {
        "pl": "/rasy-psow/owczarek-niemiecki/",
        "en": "/en/dog-breeds/german-shepherd/",
    }

    for locale, path in versions.items():
        page = _get(host, path)
        assert page.status_code == 200, (path, page.status_code)
        assert page.data["locale"] == locale
        assert page.data["canonical_url"] == origin + path
        assert page.data["hreflang"] == {code: origin + to for code, to in versions.items()}
        assert page.data["x_default"] == origin + versions["pl"]
        assert page.data["breadcrumbs"][-1]["path"] == path
        # The address the site hands the source for the page's other language.
        other = versions["en" if locale == "pl" else "pl"]
        assert page.data["blocks"][0]["data"]["text"] == other

    # Another language's slug, another language's name of the section, or
    # both: one 308 to the record's address in the language asked for.
    for asked, target in (
        ("/en/dog-breeds/owczarek-niemiecki/", versions["en"]),
        ("/en/rasy-psow/german-shepherd/", versions["en"]),
        ("/en/rasy-psow/owczarek-niemiecki/", versions["en"]),
        ("/en/hunderassen/owczarek-niemiecki", versions["en"]),
        ("/rasy-psow/german-shepherd/", versions["pl"]),
        ("/dog-breeds/german-shepherd/", versions["pl"]),
    ):
        assert _moved(host, asked) == (308, target), asked
    assert _get(host, "/rasy-psow/jamnik/").status_code == 404
    assert _get(host, "/en/dog-breeds/").status_code == 404

    sitemap = _feed(host, "sitemap.xml").content.decode()
    assert set(versions.values()) <= set(_locs(sitemap, host))
    assert _alternates(sitemap, host, versions["en"]) == {**versions, "x-default": versions["pl"]}
    assert "/en/rasy-psow/" not in sitemap and "/hunderassen/" not in sitemap

    # A link written in the site's language leads under the section's name in
    # the reader's language.
    assert _localized_href("/rasy-psow/owczarek-niemiecki/?a=1#b", {}, "/en") == (
        "/en/dog-breeds/owczarek-niemiecki/?a=1#b"
    )
    # Every name of the section, in any language, is the source's alone.
    for name in ("rasy-psow", "dog-breeds", "hunderassen"):
        assert first_segment_reserved(name)
        taken = create_collection(
            blog.client, blog.site_id, key=name, base_path=name, idempotency_key=name
        )
        assert (taken.status_code, taken.json()["code"]) == (400, "slug_reserved")
    named = _rename(blog, "blog", {"en": "dog-breeds"}, preview=True)
    assert _errors(named) == [("locale_paths.en", "slug_reserved")]


def test_a_record_without_words_in_a_language_moves_to_the_site_language_once(
    breeds: PublicSource,
) -> None:
    """German is served but the record has no German words: every German
    spelling of its address answers one 308 to the Polish page."""
    blog = Blog("section-records-de")
    site = Site.all_objects.get(pk=blog.site_id)
    Organization.objects.filter(pk=site.organization_id).update(public_locales=["pl", "en", "de"])

    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        for asked in (
            "/de/hunderassen/owczarek-niemiecki/",
            "/de/hunderassen/german-shepherd/",
            "/de/rasy-psow/german-shepherd/",
        ):
            assert _moved(blog.host, asked) == (308, "/rasy-psow/owczarek-niemiecki/"), asked


def test_two_sources_never_share_a_section_name(breeds: PublicSource) -> None:
    def other(**fields: Any) -> PublicSource:
        return PublicSource(
            key="test.other",
            shown_media=lambda _organization_id: (),
            site_page=_breed_page,
            **fields,
        )

    for fields in (
        {"page_segment": "psy", "page_segments": {"en": "dog-breeds"}},
        {"page_segment": "hunderassen"},
        {"page_segment": "psy", "page_segments": {"en": "Dog Breeds"}},
        {"page_segment": "psy", "page_segments": {"en": "xx"}},
        {"page_segments": {"en": "dogs"}},
    ):
        with pytest.raises(ImproperlyConfigured):
            register_public_source(other(**fields))
    register_public_source(other(page_segment="psy", page_segments={"en": "dogs"}))
    assert page_source("dogs", "en") is page_source("psy", "pl") is page_source("dogs")
    assert page_source("dogs", "pl") is None
    assert {"psy", "dogs", "rasy-psow", "dog-breeds", "hunderassen"} <= page_source_segments()
    # A source that names no segment per language has one in all of them.
    assert breeds.segment("es") == "rasy-psow"
