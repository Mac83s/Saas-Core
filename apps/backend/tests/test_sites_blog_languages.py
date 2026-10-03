"""Each language of a site has its own blog: an index and tag archives
listing its own articles under the names in that language, a menu that
names the blog only once it has an article there, and feeds of its own
(TL14b). Blog pages wear the site's look and menu, having none of their own."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import ContentTag, Site
from test_site_language_publication import _site, _translate_all
from test_sites_api import csrf_value, publish_site_request
from test_sites_collections import (
    _tagged_entry,
    create_collection,
    publish,
    save_entry_draft,
    set_tags,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _get(host: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)


def _feed(host: str, name: str, locale: str | None = None) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get(
            f"/api/v1/public/site/{name}",
            {"locale": locale} if locale else {},
            HTTP_HOST=host,
            HTTP_ACCEPT="application/xml",
        )


def _items(response: Any) -> list[str]:
    return [item["path"] for item in response.data["blocks"][0]["data"]["items"]]


def _menu(response: Any) -> list[tuple[str, str, str | None]]:
    return [(link["title"], link["path"], link.get("lang")) for link in response.data["navigation"]]


def _translate_entry(client: Any, entry_id: str, slug: str, title: str) -> str:
    created = client.post(
        f"/api/v1/sites/entries/{entry_id}/translations/",
        {"locale": "en", "slug": slug, "title": title},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=f"translate-{slug}",
    )
    assert created.status_code == 201, created.data
    english = str(created.data["id"])
    save_entry_draft(
        client, english, expected_version=0, text=f"{title}.", idempotency_key=f"draft-{slug}"
    )
    # A person's translation carries the tags they give it.
    assert set_tags(client, english, ["Porady"]).status_code == 200
    assert publish(client, english, idempotency_key=f"publish-{slug}").status_code == 201
    return english


class Blog:
    """A Polish site live in English, with a footer, a blog in its menu and
    one Polish article tagged „Porady”."""

    def __init__(self, slug: str) -> None:
        self.client, self.site_id, home, _offer, self.host = _site(slug)
        _translate_all(self.client, home, f"{slug}-home-en")
        url = f"/api/v1/sites/{self.site_id}/appearance/"
        appearance = self.client.get(url).data["appearance"]
        appearance["footer"] = {"layout": "simple", "text": "Zapraszamy", "links": []}
        saved = self.client.put(
            url,
            {"expected_version": 0, "appearance": appearance},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
            HTTP_IDEMPOTENCY_KEY=f"appearance-{slug}",
        )
        assert saved.status_code == 200, saved.data
        self.collection_id = str(create_collection(self.client, self.site_id).data["id"])
        linked = self.client.put(
            f"/api/v1/sites/collections/{self.collection_id}/navigation/",
            {"show_in_navigation": True},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
        )
        assert linked.status_code == 200
        self.polish = str(
            _tagged_entry(self.client, self.collection_id, "jeden", ["Porady"]).data["id"]
        )
        self.publish()

    def publish(self, key: str = "site") -> None:
        published = publish_site_request(
            self.client, self.site_id, idempotency_key=f"{key}-{self.site_id}"
        )
        assert published.status_code == 201, published.data

    def english_names(self, collection: str, tag: str) -> None:
        tag_id = ContentTag.all_objects.get(site_id=self.site_id, slug="porady").id
        read = self.client.get(f"/api/v1/sites/{self.site_id}/texts/en/")
        saved = self.client.put(
            f"/api/v1/sites/{self.site_id}/texts/en/",
            {
                "expected_version": read.data["version"],
                "texts": {
                    f"collection/{self.collection_id}": collection,
                    f"tag/{tag_id}": tag,
                    "footer/text": "Welcome",
                },
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
        )
        assert saved.status_code == 200, saved.data
        self.publish("names")


def test_each_language_lists_its_own_articles_under_its_own_name() -> None:
    blog = Blog("blog-lang-index")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    blog.english_names("Journal", "Tips")

    polish, english = _get(blog.host, "/blog/"), _get(blog.host, "/en/blog/")

    assert _items(polish) == ["/blog/wpis-jeden/"]
    assert english.status_code == 200, english.data
    assert (english.data["locale"], english.data["title"]) == ("en", "Journal")
    assert _items(english) == ["/en/blog/in-english/"]
    # One page in two languages, and the switch leads to the other one.
    origin = f"https://{blog.host}"
    assert polish.data["hreflang"] == {"pl": f"{origin}/blog/", "en": f"{origin}/en/blog/"}
    assert english.data["x_default"] == f"{origin}/blog/"
    assert [(link["locale"], link["path"]) for link in polish.data["language_links"]] == [
        ("pl", "/blog/"),
        ("en", "/en/blog/"),
    ]

    archive = _get(blog.host, "/en/blog/tag/porady/")
    assert archive.status_code == 200, archive.data
    assert archive.data["title"] == "Entries tagged: Tips"
    assert _items(archive) == ["/en/blog/in-english/"]
    assert _get(blog.host, "/blog/tag/porady/").data["title"] == "Wpisy oznaczone: Porady"

    # A language the company switches off has no blog either.
    Organization.objects.filter(pk=Site.all_objects.get(pk=blog.site_id).organization_id).update(
        public_locales=["pl"]
    )
    assert _get(blog.host, "/en/blog/").status_code == 404


def test_the_menu_names_the_blog_in_a_language_only_once_it_has_an_article_there() -> None:
    blog = Blog("blog-lang-menu")

    # No English article: no English blog to link to, and no address for one.
    assert _menu(_get(blog.host, "/en/")) == []
    assert _get(blog.host, "/en/blog/").status_code == 404
    # The site's own language keeps its blog even before the first article.
    assert ("Blog", "/blog/", None) in _menu(_get(blog.host, "/"))

    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    # The name not yet translated says which language it is in.
    assert ("Blog", "/en/blog/", "pl") in _menu(_get(blog.host, "/en/"))

    blog.english_names("Journal", "Tips")
    assert ("Journal", "/en/blog/", None) in _menu(_get(blog.host, "/en/"))


def test_blog_pages_wear_the_sites_look_menu_and_feeds() -> None:
    blog = Blog("blog-lang-chrome")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    blog.english_names("Journal", "Tips")
    snapshot = Site.all_objects.get(pk=blog.site_id).current_publication.snapshot

    article = _get(blog.host, "/en/blog/in-english/")
    index = _get(blog.host, "/blog/")

    assert article.data["design_tokens"] == snapshot["design_tokens"]
    # The footer in the article's language, as on every page of that language.
    assert article.data["appearance"]["footer"]["text"] == "Welcome"
    assert index.data["appearance"]["footer"]["text"] == "Zapraszamy"
    assert ("Journal", "/en/blog/", None) in _menu(article)
    assert ("Blog", "/blog/", None) in _menu(index)
    # The trail of an index starts at its place in the menu.
    assert _get(blog.host, "/en/blog/").data["breadcrumbs"] == [
        {"title": "Journal", "path": "/en/blog/"}
    ]
    # Each page links the feeds of its own language only.
    assert article.data["feeds"] == {
        "rss": f"https://{blog.host}/en/rss.xml",
        "atom": f"https://{blog.host}/en/atom.xml",
    }
    assert index.data["feeds"]["rss"] == f"https://{blog.host}/rss.xml"


def test_each_language_pages_its_index_with_its_own_word_for_page() -> None:
    blog = Blog("blog-lang-pages")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    second = str(_tagged_entry(blog.client, blog.collection_id, "dwa", ["Porady"]).data["id"])
    _translate_entry(blog.client, second, "second-one", "Second one")

    with override_settings(SITES_ENTRY_INDEX_PAGE_SIZE=1):
        first = _get(blog.host, "/en/blog/")
        page_two = _get(blog.host, "/en/blog/page/2/")
        spelled_in_polish = _get(blog.host, "/en/blog/strona/2/")
        polish_two = _get(blog.host, "/blog/strona/2/")

    assert first.data["pagination"]["next_path"] == "/en/blog/page/2/"
    assert page_two.status_code == 200
    assert page_two.data["canonical_url"].endswith("/en/blog/page/2/")
    assert spelled_in_polish.status_code == 308
    assert spelled_in_polish["Location"] == "/en/blog/page/2/"
    assert polish_two.status_code == 200


def test_each_language_has_its_own_feed() -> None:
    blog = Blog("blog-lang-feeds")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")

    polish = _feed(blog.host, "feed.xml").content.decode()
    english = _feed(blog.host, "feed.xml", "en").content.decode()
    atom = _feed(blog.host, "atom.xml", "en").content.decode()
    sitemap = _feed(blog.host, "sitemap.xml").content.decode()

    assert "<language>pl</language>" in polish
    assert "/blog/wpis-jeden/" in polish and "/en/blog/in-english/" not in polish
    assert "<language>en</language>" in english
    assert "/en/blog/in-english/" in english and "/blog/wpis-jeden/" not in english
    assert f"<link>https://{blog.host}/en/</link>" in english
    assert 'xml:lang="en"' in atom
    assert f'<link rel="self" href="https://{blog.host}/en/atom.xml"/>' in atom
    assert f"https://{blog.host}/en/blog/</loc>" in sitemap
    # The site's language has one address for its feed, and a language
    # visitors cannot read has none.
    assert _feed(blog.host, "feed.xml", "pl").status_code == 404
    assert _feed(blog.host, "feed.xml", "fr").status_code == 404


def test_the_tag_name_is_looked_up_as_the_tenant_the_host_named() -> None:
    """The test database bypasses RLS; on the stack sites_contenttag answers
    nothing until the tenant is set, and the archive fell back to the Polish
    name (03.10). The order of the statements is what proves it here."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    blog = Blog("blog-lang-tag-rls")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    blog.english_names("Journal", "Tips")

    with CaptureQueriesContext(connection) as queries:
        archive = _get(blog.host, "/en/blog/tag/porady/")

    assert archive.data["title"] == "Entries tagged: Tips"
    statements = [query["sql"] for query in queries.captured_queries]
    tag_query = next(
        index for index, sql in enumerate(statements) if 'FROM "sites_contenttag"' in sql
    )
    # In its own transaction: on the stack each block is one, so a tenant set
    # by an earlier block is gone by then (in a test it would linger).
    opened = max(
        index for index, sql in enumerate(statements[:tag_query]) if sql.startswith("SAVEPOINT")
    )
    assert any("SET LOCAL app.organization_id" in sql for sql in statements[opened:tag_query]), (
        statements[opened : tag_query + 1]
    )
