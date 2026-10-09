"""What a product's own pages read of the platform's published content
(ADR-079 pkt 29–33): `GET /api/v1/public/content/…`, the pictures behind
`/media/` on the platform's host, and the workspace's own builder site that
answers at no host.

Order of what these tests hold: nothing unpublished can be read or guessed;
only the one platform workspace is read; a company's site, its media and its
renderer answer as before.

The test database connects as the owner of the tables and row-level security
does not apply to it. What is asserted here instead is what stays observable
either way: every statement on the tables that carry no policy names the
workspace, and every read of a table that forces one comes after `SET LOCAL`
inside the same transaction. That the policies then let exactly these rows
through is shown on a running stack, under the application's role.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization, WorkspaceKind
from saas_core.modules.core.organizations.platform_workspace import platform_workspace_slug
from saas_core.modules.shared.sites.html_blocks import convert_html
from saas_core.modules.shared.sites.models import (
    ContentCollection,
    ContentEntry,
    ContentTag,
    Site,
)
from saas_core.modules.shared.sites.publication_routing import (
    PublicSiteNotFound,
    published_entries,
    resolve_public_page,
    site_host_company,
)
from saas_core.modules.shared.sites.tls import authorize_tls_hostname
from test_media_api import MemoryStorage
from test_sites_api import (
    create_media_asset,
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_draft,
    save_translation,
    sites_client,
)
from test_sites_collections import _verified_platform_domain, create_entry, publish, set_tags
from test_sites_content_types import _new_type, _switch

pytestmark = pytest.mark.django_db

#: The tables of this module without row-level security: the renderer reads
#: them before a tenant is set, so a query's own filter is all that separates
#: one company's rows from another's.
OPEN_TABLES = (
    "sites_site",
    "sites_contententry",
    "sites_contentcollection",
    "sites_contententrypublication",
)
#: The tables this read touches that force row-level security.
GUARDED_TABLES = (
    "sites_contenttag",
    "sites_contenttaxonomy",
    "sites_sitetexttranslation",
    "media_mediaasset",
    "organizations_organization",
)
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _read(path: str, **query: Any) -> Any:
    return APIClient().get(f"/api/v1/public/content/{path}", query)


def _site_page(host: str, path: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)


def _names(sql: str, organization: Any) -> bool:
    """Whether a statement names the organization, in either spelling the
    database driver gives an identifier."""
    return str(organization.id) in sql or organization.id.hex in sql


def _refusal(response: Any) -> tuple[int, dict[str, Any]]:
    """A refusal without what names the one request: its address, its trace."""
    return response.status_code, {
        key: value
        for key, value in response.json().items()
        if key not in ("instance", "correlation_id")
    }


class Publisher:
    """A workspace with a guide, „Poradnik” (`guide` in English addresses).

    Built as a company: entering the platform's workspace takes an operator's
    second factor, and what these tests exercise is the read. `enter` makes it
    the deployment's publisher once its content is in; `leave` goes back to
    write more."""

    def __init__(self, slug: str) -> None:
        self.client, self.organization, self.user = sites_client(slug=slug, role_key="owner")
        self.slug = slug
        self.site_id = str(create_site(self.client).data["id"])
        self.host = str(_verified_platform_domain(self.site_id).hostname)
        made = _new_type(
            self.client, self.site_id, "Poradnik", "poradnik", locale_paths={"en": "guide"}
        )
        assert made.status_code == 201, made.data
        self.type_id = str(made.data["id"])

    def enter(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            workspace_kind=WorkspaceKind.PLATFORM, slug=platform_workspace_slug()
        )

    def leave(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            workspace_kind=WorkspaceKind.BUSINESS, slug=self.slug
        )

    def entry(
        self,
        slug: str,
        *,
        tags: list[str] | None = None,
        out: bool = True,
        noindex: bool = False,
        type_id: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        media: list[str] | None = None,
    ) -> str:
        entry_id = str(
            create_entry(
                self.client, type_id or self.type_id, slug=slug, idempotency_key=f"e-{slug}"
            ).data["id"]
        )
        self.draft(entry_id, 0, blocks=blocks or _text(f"Treść {slug}."), media=media)
        if tags:
            assert set_tags(self.client, entry_id, tags).status_code == 200
        if noindex:
            ContentEntry.all_objects.filter(pk=entry_id).update(noindex=True)
        if out:
            self.publish(entry_id)
        return entry_id

    def draft(
        self,
        entry_id: str,
        version: int,
        *,
        blocks: list[dict[str, Any]],
        media: list[str] | None = None,
    ) -> None:
        saved = self.client.put(
            f"/api/v1/sites/entries/{entry_id}/draft/",
            {"expected_version": version, "blocks": blocks, "media_asset_ids": media or []},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
            HTTP_IDEMPOTENCY_KEY=f"d-{entry_id}-{version}",
        )
        assert saved.status_code == 201, saved.data

    def publish(self, entry_id: str, key: str = "p") -> None:
        done = publish(self.client, entry_id, idempotency_key=f"{key}-{entry_id}")
        assert done.status_code == 201, done.data

    def withdraw(self, entry_id: str) -> None:
        gone = self.client.delete(
            f"/api/v1/sites/entries/{entry_id}/publication/",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
        )
        assert gone.status_code in (200, 204), gone.data

    def english(
        self, entry_id: str, slug: str, title: str, *, tags: list[str] | None = None
    ) -> str:
        created = self.client.post(
            f"/api/v1/sites/entries/{entry_id}/translations/",
            {"locale": "en", "slug": slug, "title": title},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
            HTTP_IDEMPOTENCY_KEY=f"tr-{slug}",
        )
        assert created.status_code == 201, created.data
        english = str(created.data["id"])
        self.draft(english, 0, blocks=_text(f"{title}."))
        if tags:
            assert set_tags(self.client, english, tags).status_code == 200
        self.publish(english)
        return english

    def english_names(self, texts: dict[str, str]) -> None:
        url = f"/api/v1/sites/{self.site_id}/texts/en/"
        saved = self.client.put(
            url,
            {"expected_version": self.client.get(url).data["version"], "texts": texts},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
        )
        assert saved.status_code == 200, saved.data

    def tag(self, slug: str) -> str:
        return str(ContentTag.all_objects.get(site_id=self.site_id, slug=slug).id)

    def picture(self) -> Any:
        return create_media_asset(self.organization, self.user)


def _text(text: str) -> list[dict[str, Any]]:
    return [{"block_type": "core.rich_text", "schema_version": 1, "data": {"text": text}}]


def _hero(asset: Any, title: str = "Ze zdjęciem") -> list[dict[str, Any]]:
    return [
        {
            "block_type": "core.hero",
            "schema_version": 3,
            "data": {"title": title, "image": {"asset_id": str(asset.id), "alt": "Szczeniak"}},
        }
    ]


def _slugs(answer: Any) -> list[str]:
    return [item["slug"] for item in answer.data["list"]["items"]]


# --- the read ----------------------------------------------------------------


def test_an_entry_is_read_by_type_language_and_slug_in_address_parts() -> None:
    guide = Publisher("read-entry")
    polish = guide.entry("zywienie-szczeniaka", tags=["Porady"])
    guide.english(polish, "feeding-a-puppy", "Feeding a puppy", tags=["Porady"])
    guide.enter()

    answer = _read("types/poradnik/entries/pl/zywienie-szczeniaka/")

    assert answer.status_code == 200, answer.data
    assert answer.data["moved"] is None
    entry = answer.data["entry"]
    assert (entry["type"], entry["locale"], entry["slug"]) == (
        "poradnik",
        "pl",
        "zywienie-szczeniaka",
    )
    assert entry["title"] == "Zywienie Szczeniaka"
    assert entry["blocks"] == _text("Treść zywienie-szczeniaka.")
    assert entry["terms"] == [{"taxonomy": "tag", "slug": "porady", "name": "Porady"}]
    # Its language versions as (language, slug), itself included, the site's
    # own language first: what hreflang and a language switch are built from.
    assert entry["versions"] == [
        {"locale": "pl", "slug": "zywienie-szczeniaka"},
        {"locale": "en", "slug": "feeding-a-puppy"},
    ]
    assert (entry["noindex"], entry["schema_type"], entry["machine_text"]) == (
        False,
        "BlogPosting",
        None,
    )
    assert entry["published_at"] and entry["updated_at"] and entry["timezone"]
    assert (entry["image"], entry["image_sizes"], entry["ai_media_ids"]) == (None, {}, [])
    assert entry["structured_data"] is None
    english = _read("types/poradnik/entries/en/feeding-a-puppy/").data["entry"]
    assert (english["title"], english["versions"]) == ("Feeding a puppy", entry["versions"])
    # Parts, never paths: the product composes addresses from its own table,
    # so nothing here spells the builder's.
    for spelled in ("/poradnik/", "/en/guide/", "/guide/"):
        assert spelled not in json.dumps([answer.json(), english])


def test_the_entrys_own_structured_data_is_built_from_the_address_the_product_gives() -> None:
    guide = Publisher("read-jsonld")
    guide.entry("zywienie", tags=["Porady"])
    guide.enter()
    # On the platform's own host: that is where a product's pages stand.
    origin = f"https://{settings.SITES_PLATFORM_DOMAIN}"
    address = f"{origin}/poradnik/zywienie"

    entry = _read("types/poradnik/entries/pl/zywienie/", canonical_url=address).data["entry"]

    page, article = entry["structured_data"]
    assert (page["@type"], page["@id"], page["url"]) == ("WebPage", f"{address}#webpage", address)
    assert (article["@type"], article["@id"]) == ("BlogPosting", f"{address}#article")
    assert article["headline"] == "Zywienie"
    assert article["keywords"] == ["Porady"]
    assert article["mainEntityOfPage"] == {"@id": f"{address}#webpage"}
    # The site around the entry is the product's to state, under these names.
    assert article["isPartOf"] == {"@id": f"{origin}/#website"}
    assert article["publisher"] == {"@id": f"{origin}/#organization"}
    # A port and the other scheme are the same host still.
    local = f"http://{settings.SITES_PLATFORM_DOMAIN}:8083/poradnik/zywienie"
    assert _read("types/poradnik/entries/pl/zywienie/", canonical_url=local).status_code == 200
    assert {node["@type"] for node in entry["structured_data"]} == {"WebPage", "BlogPosting"}


@pytest.mark.parametrize(
    "address",
    [
        "/poradnik/zywienie",
        "javascript:alert(1)",
        "https://user:secret@{host}/x",
        "https://{host}/x?next=1",
        "https://{host}/x#frag",
        "https://{host}/a b",
        "https:///x",
        # Somebody else's host, and one that only starts or ends like ours.
        "https://serwis.example.test/poradnik/zywienie",
        "https://{host}.example.test/x",
        "https://evil-{host}/x",
        # What would close a quote or a tag where the address is printed.
        "https://{host}/x<script>",
        "https://{host}/x>",
        'https://{host}/x"onload=',
        "https://{host}/x\\y",
        "https://{host}/x'y",
        # What no parser reads: once an anonymous 500.
        "http://[::1",
        "https://{host}:port/x",
        "https://{host}:99999999/x",
    ],
)
def test_an_address_that_is_no_plain_address_of_the_platforms_host_is_refused(
    address: str,
) -> None:
    guide = Publisher("read-jsonld-refused")
    guide.entry("zywienie")
    guide.enter()

    refused = _read(
        "types/poradnik/entries/pl/zywienie/",
        canonical_url=address.format(host=settings.SITES_PLATFORM_DOMAIN),
    )

    assert refused.status_code == 400
    assert [(error["field"], error["code"]) for error in refused.json()["errors"]] == [
        ("canonical_url", "canonical_url_invalid")
    ]


def test_nothing_that_is_not_published_can_be_read_or_guessed() -> None:
    guide = Publisher("read-unpublished")
    out = guide.entry("opublikowany", tags=["Porady"])
    guide.entry("szkic", tags=["Tajne"], out=False)
    # Edited since it went out: the draft says something else and carries a
    # tag the publication does not.
    guide.draft(out, 1, blocks=_text("Nowa, niewydana wersja."))
    assert set_tags(guide.client, out, ["Porady", "Niewydany"]).status_code == 200
    withdrawn = guide.entry("wycofany", tags=["Wycofane"])
    guide.withdraw(withdrawn)
    guide.enter()

    nobody = _read("types/poradnik/entries/pl/nie-ma-takiego/")
    entry = _read("types/poradnik/entries/pl/opublikowany/")
    listed = _read("types/poradnik/entries/", locale="pl")
    terms = _read("types/poradnik/terms/", locale="pl")
    sitemap = _read("sitemap/")
    types = _read("types/")

    assert nobody.status_code == 404
    for slug in ("szkic", "wycofany"):
        # The existence of a draft is not readable either: the same answer as
        # for an address nobody ever had.
        assert _refusal(_read(f"types/poradnik/entries/pl/{slug}/")) == _refusal(nobody)
    assert entry.data["entry"]["blocks"] == _text("Treść opublikowany.")
    assert [term["slug"] for term in entry.data["entry"]["terms"]] == ["porady"]
    assert (_slugs(listed), listed.data["list"]["total"]) == (["opublikowany"], 1)
    assert [(term["slug"], term["count"]) for term in terms.data["taxonomies"][0]["terms"]] == [
        ("porady", 1)
    ]
    for hidden in ("tajne", "niewydany", "wycofane"):
        assert _refusal(
            _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term=hidden)
        ) == _refusal(_read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="nie-ma"))
    assert [
        version["slug"] for item in sitemap.data["entries"] for version in item["versions"]
    ] == ["opublikowany"]
    everything = json.dumps(
        [answer.json() for answer in (entry, listed, terms, sitemap, types)], ensure_ascii=False
    ).lower()
    for word in ("szkic", "tajne", "niewydan", "wycofan"):
        assert word not in everything, word


@pytest.mark.usefixtures("content_types_offered")
def test_a_type_exists_for_the_read_only_once_an_entry_of_it_is_listed() -> None:
    guide = Publisher("read-types")
    guide.entry("pierwszy")
    secret = _new_type(guide.client, guide.site_id, "Tajny projekt", "tajny-projekt")
    guide.entry("zarys", type_id=str(secret.data["id"]), out=False)
    news = _new_type(guide.client, guide.site_id, "Aktualnosci", "aktualnosci")
    guide.entry("nowina", type_id=str(news.data["id"]), tags=["Nowiny"])
    assert _switch(guide.client, str(news.data["id"]), "off").status_code == 200
    guide.enter()

    types = _read("types/")

    assert types.status_code == 200
    assert types.json() == [
        {
            "key": "poradnik",
            "schema_type": "BlogPosting",
            "languages": ["pl"],
            "names": {"pl": "Poradnik"},
            "segments": {"pl": "poradnik"},
        }
    ]
    # A type nothing of which is out, and one switched off, answer like a
    # type nobody ever made — on every read.
    for path, query in (
        ("types/{key}/entries/", {"locale": "pl"}),
        ("types/{key}/terms/", {"locale": "pl"}),
        ("types/{key}/entries/pl/zarys/", {}),
        ("types/{key}/entries/pl/nowina/", {}),
    ):
        nobody = _refusal(_read(path.format(key="nie-ma"), **query))
        assert nobody[0] == 404
        for key in ("tajny-projekt", "aktualnosci"):
            assert _refusal(_read(path.format(key=key), **query)) == nobody, (path, key)
    assert "nowin" not in json.dumps(_read("sitemap/").json()).lower()


def test_a_hidden_entry_is_read_by_its_address_and_is_on_no_list() -> None:
    guide = Publisher("read-noindex")
    guide.entry("zwykly", tags=["Porady"])
    guide.entry("ukryty", tags=["Porady", "Tylko ukryty"], noindex=True)
    guide.enter()

    hidden = _read("types/poradnik/entries/pl/ukryty/").data["entry"]

    # Published, so its own address answers — and says it asks not to be
    # indexed. A term only it carries has no list, so it does not name it.
    assert hidden["noindex"] is True
    assert [term["slug"] for term in hidden["terms"]] == ["porady"]
    assert _slugs(_read("types/poradnik/entries/", locale="pl")) == ["zwykly"]
    terms = _read("types/poradnik/terms/", locale="pl").data["taxonomies"][0]["terms"]
    assert [(term["slug"], term["count"]) for term in terms] == [("porady", 1)]
    assert (
        _read(
            "types/poradnik/entries/", locale="pl", taxonomy="tag", term="tylko-ukryty"
        ).status_code
        == 404
    )
    sitemap = json.dumps(_read("sitemap/").json())
    assert "zwykly" in sitemap and "ukryty" not in sitemap


def test_lists_page_filter_by_term_and_say_when_a_term_is_too_thin_to_index() -> None:
    guide = Publisher("read-lists")
    for number in range(1, 6):
        polish = guide.entry(
            f"wpis-{number}", tags=["Porady", "Rzadki"] if number <= 2 else ["Porady"]
        )
        if number == 1:
            guide.english(polish, "entry-1", "Entry one", tags=["Porady"])
    guide.enter()

    first = _read("types/poradnik/entries/", locale="pl", page_size=2)
    last = _read("types/poradnik/entries/", locale="pl", page_size=2, page=3)
    thin = _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="rzadki")
    wide = _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="porady")
    english = _read("types/poradnik/entries/", locale="en")

    assert first.status_code == 200, first.data
    assert first.data["moved"] is None
    # Newest first, as on a company's own list.
    assert _slugs(first) == ["wpis-5", "wpis-4"]
    assert _slugs(last) == ["wpis-1"]
    listed = first.data["list"]
    assert (listed["page"], listed["pages"], listed["total"]) == (1, 3, 5)
    assert (listed["type"], listed["name"], listed["term"]) == ("poradnik", "Poradnik", None)
    assert (listed["languages"], listed["indexable"]) == (["pl", "en"], True)
    # A page past the end is a wrong address, not an empty page.
    assert _read("types/poradnik/entries/", locale="pl", page_size=2, page=4).status_code == 404
    # Fewer than three entries: the core's rule, which the product applies.
    assert (_slugs(thin), thin.data["list"]["indexable"]) == (["wpis-2", "wpis-1"], False)
    assert thin.data["list"]["term"] == {
        "taxonomy": "tag",
        "slug": "rzadki",
        "name": "Rzadki",
        "versions": [{"locale": "pl", "slug": "rzadki"}],
    }
    assert thin.data["list"]["languages"] == ["pl"]
    assert (wide.data["list"]["total"], wide.data["list"]["indexable"]) == (5, True)
    assert wide.data["list"]["languages"] == ["pl", "en"]
    assert _slugs(english) == ["entry-1"]
    # A language the type has nothing in has no list; German is in the
    # platform's registry, so this is about the content, not the code.
    assert _read("types/poradnik/entries/", locale="de").status_code == 404
    item = first.data["list"]["items"][0]
    assert set(item) == {
        "locale",
        "slug",
        "title",
        "excerpt",
        "author_name",
        "published_at",
        "updated_at",
        "image",
        "cover",
        "terms",
    }
    for query in (
        {"locale": "pl", "page": 0},
        {"locale": "pl", "page_size": 101},
        {"locale": "polski"},
        {"locale": "pl", "term": "porady"},
        {},
    ):
        assert _read("types/poradnik/entries/", **query).status_code == 400, query


def _category(guide: Publisher, name: str, parent: str | None = None) -> str:
    made = guide.client.post(
        f"/api/v1/sites/collections/{guide.type_id}/terms/",
        {"kind": "categories", "name": name, **({"parent_id": parent} if parent else {})},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    assert made.status_code == 201, made.json()
    return str(made.json()["id"])


def _filed(guide: Publisher, slug: str, categories: list[str], **more: Any) -> str:
    """An entry filed under categories and then published: an archive lists
    what publications carry."""
    entry_id = guide.entry(slug, out=False, **more)
    filed = guide.client.put(
        f"/api/v1/sites/entries/{entry_id}/categories/",
        {"term_ids": categories},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    assert filed.status_code == 200, filed.json()
    guide.publish(entry_id)
    return entry_id


def _tree(taxonomy: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (term["slug"], term["name"], term["count"], term["indexable"], term["parent_slug"])
        for term in taxonomy["terms"]
    ]


def test_a_types_categories_are_read_as_a_tree_with_lists_per_language() -> None:
    """The category part of the read (ADR-079 pkt 30; CT2): the type's
    categories as a tree through `parent_slug`, each list with the entries of
    the categories under it, addresses per language with „moved" for any
    other name of a term — and, as for tags, only what a published entry that
    asks to be indexed carries."""
    guide = Publisher("read-categories")
    care = _category(guide, "Pielęgnacja")
    coat = _category(guide, "Sierść", care)
    food = _category(guide, "Żywienie")
    unused = _category(guide, "Pusta")
    first = _filed(guide, "wpis-1", [coat], tags=["Porady"])
    _filed(guide, "wpis-2", [coat])
    _filed(guide, "wpis-3", [care])
    _filed(guide, "wpis-4", [food])
    # On no list: a hidden entry, and a draft — their categories count nothing.
    _filed(guide, "ukryty", [food, unused], noindex=True)
    drafted = guide.entry("szkic", out=False)
    guide.client.put(
        f"/api/v1/sites/entries/{drafted}/categories/",
        {"term_ids": [unused]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    english = guide.english(first, "entry-1", "Entry one")
    guide.client.put(
        f"/api/v1/sites/entries/{english}/categories/",
        {"term_ids": [coat]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    guide.publish(english, key="again")
    named = guide.client.put(
        f"/api/v1/sites/collections/{guide.type_id}/terms/{coat}/names/",
        {"names": {"en": "Coat"}},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    assert named.status_code == 200, named.json()
    guide.enter()

    def terms(locale: str) -> list[dict[str, Any]]:
        return list(_read("types/poradnik/terms/", locale=locale).json()["taxonomies"])

    def listed(locale: str, taxonomy: str, term: str) -> Any:
        return _read("types/poradnik/entries/", locale=locale, taxonomy=taxonomy, term=term)

    polish = terms("pl")
    assert [(found["key"], found["hierarchical"], found["segment"]) for found in polish] == [
        ("tag", False, "tag"),
        ("category", True, "kategoria"),
    ]
    # A category before those under it; counts with those under it; the
    # hidden entry and the draft count nothing, so „Pusta” is not here.
    assert _tree(polish[1]) == [
        ("pielegnacja", "Pielęgnacja", 3, True, None),
        ("siersc", "Sierść", 2, False, "pielegnacja"),
        ("zywienie", "Żywienie", 1, False, None),
    ]
    english_terms = terms("en")
    assert english_terms[1]["segment"] == "category"
    # English: the one entry there; „Sierść” under its English name's
    # address, the one above it under the site's language's until it has one.
    assert _tree(english_terms[1]) == [
        ("pielegnacja", "Pielęgnacja", 1, False, None),
        ("coat", "Coat", 1, False, "pielegnacja"),
    ]

    wide = listed("pl", "category", "pielegnacja").json()["list"]
    assert [item["slug"] for item in wide["items"]] == ["wpis-3", "wpis-2", "wpis-1"]
    assert (wide["total"], wide["indexable"], wide["languages"]) == (3, True, ["pl", "en"])
    # Where its list answers, by language — the address it has in each: one
    # read gives a category page its language switch and its `hreflang`.
    assert wide["term"] == {
        "taxonomy": "category",
        "slug": "pielegnacja",
        "name": "Pielęgnacja",
        "versions": [
            {"locale": "pl", "slug": "pielegnacja"},
            {"locale": "en", "slug": "pielegnacja"},
        ],
    }
    assert [version["locale"] for version in wide["term"]["versions"]] == wide["languages"]
    thin = listed("pl", "category", "siersc").json()["list"]
    assert ([item["slug"] for item in thin["items"]], thin["indexable"]) == (
        ["wpis-2", "wpis-1"],
        False,
    )
    # An entry's terms: its tags, then its categories.
    assert thin["items"][1]["terms"] == [
        {"taxonomy": "tag", "slug": "porady", "name": "Porady"},
        {"taxonomy": "category", "slug": "siersc", "name": "Sierść"},
    ]
    assert _read("types/poradnik/entries/pl/wpis-1/").json()["entry"]["terms"] == (
        thin["items"][1]["terms"]
    )
    # The hidden entry names the category other entries make readable, not
    # the one only it carries.
    hidden = _read("types/poradnik/entries/pl/ukryty/").json()["entry"]
    assert hidden["terms"] == [{"taxonomy": "category", "slug": "zywienie", "name": "Żywienie"}]
    # English, by the English address; any other name of the term says where.
    in_english = listed("en", "category", "coat").json()["list"]
    assert [item["slug"] for item in in_english["items"]] == ["entry-1"]
    # The same from either language, each under its own address.
    assert in_english["term"]["versions"] == [
        {"locale": "pl", "slug": "siersc"},
        {"locale": "en", "slug": "coat"},
    ]
    assert listed("pl", "category", "siersc").json()["list"]["term"]["versions"] == (
        in_english["term"]["versions"]
    )
    assert listed("en", "category", "siersc").json() == {
        "list": None,
        "moved": {"type": "poradnik", "locale": "en", "taxonomy": "category", "term": "coat"},
    }
    assert listed("pl", "category", "coat").json()["moved"]["term"] == "siersc"
    # Nothing unpublished, nothing of another vocabulary, nothing made up.
    for locale, taxonomy, term in (
        ("pl", "category", "pusta"),
        ("pl", "category", "nie-ma"),
        ("pl", "category", "porady"),
        ("pl", "tag", "siersc"),
        ("en", "category", "zywienie"),
        ("pl", "kategoria", "siersc"),
    ):
        assert listed(locale, taxonomy, term).status_code == 404, (locale, taxonomy, term)
    everything = json.dumps([polish, english_terms, wide, thin, hidden]).lower()
    assert "pusta" not in everything

    # The sitemap listing: only a list worth indexing.
    sitemap = _read("sitemap/").json()
    assert [
        (item["taxonomy"], [(version["locale"], version["slug"]) for version in item["versions"]])
        for item in sitemap["terms"]
    ] == [("category", [("pl", "pielegnacja")])]

    # The tree is read as it is: a category moved shows at once.
    guide.leave()
    moved = guide.client.patch(
        f"/api/v1/sites/collections/{guide.type_id}/terms/{coat}/",
        {"parent_id": food},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
    )
    assert moved.status_code == 200, moved.json()
    guide.enter()
    assert _tree(terms("pl")[1]) == [
        ("pielegnacja", "Pielęgnacja", 1, False, None),
        ("zywienie", "Żywienie", 3, True, None),
        ("siersc", "Sierść", 2, False, "zywienie"),
    ]


def test_a_longer_list_asks_the_database_no_more_often() -> None:
    """Anonymous and uncached: what a page of a list costs must not grow
    with how many entries are on it. Names in another language once took one
    transaction and one question per entry."""
    guide = Publisher("read-list-cost")
    for number in range(1, 5):
        polish = guide.entry(f"wpis-{number}", tags=["Porady", f"Temat {number}"])
        guide.english(polish, f"entry-{number}", f"Entry {number}", tags=["Porady"])
    guide.english_names({f"tag/{guide.tag('porady')}": "Tips"})
    guide.enter()

    def asked(page_size: int) -> tuple[int, list[str]]:
        with CaptureQueriesContext(connection) as captured:
            answer = _read("types/poradnik/entries/", locale="en", page_size=page_size)
        assert answer.status_code == 200
        return len(captured.captured_queries), [
            term["name"] for item in answer.data["list"]["items"] for term in item["terms"]
        ]

    one, four = asked(1), asked(4)

    assert (one[1], four[1]) == (["Tips"], ["Tips"] * 4)
    assert one[0] == four[0]


def test_the_read_lists_exactly_what_a_companys_own_list_would() -> None:
    """One idea of what is published: the read's lean projection and the
    router's (`published_entries`) name the same entries in the same order."""
    guide = Publisher("read-same-projection")
    polish = guide.entry("pierwszy", tags=["Porady"])
    guide.english(polish, "first", "First")
    guide.entry("drugi")
    guide.entry("ukryty", noindex=True)
    guide.entry("szkic", out=False)
    guide.withdraw(guide.entry("wycofany"))
    guide.enter()

    routed = [
        (item["locale"], item["title"])
        for item in published_entries(organization_id=guide.organization.id, site_id=guide.site_id)
    ]
    read = [
        (item["locale"], item["title"])
        for locale in ("pl", "en")
        for item in _read("types/poradnik/entries/", locale=locale).data["list"]["items"]
    ]

    assert sorted(read) == sorted(routed)
    assert [title for locale, title in read if locale == "pl"] == [
        title for locale, title in routed if locale == "pl"
    ]


def test_names_in_another_language_need_no_publication_of_the_builder_site() -> None:
    """ADR-079 pkt 33: on a company's site a type's and a tag's name in
    another language go out with the site's publication. Nobody publishes the
    workspace's site, so the read takes the accepted names directly — for
    what a published entry carries, and for nothing else."""
    guide = Publisher("read-names")
    polish = guide.entry("pierwszy", tags=["Porady"])
    guide.english(polish, "first", "First", tags=["Porady"])
    drafted = guide.entry("drugi", tags=["Szkicowy"])
    guide.english_names({
        f"collection/{guide.type_id}": "Guide",
        f"tag/{guide.tag('porady')}": "Tips",
        f"tag/{guide.tag('szkicowy')}": "Sketchy",
    })
    # The second entry is withdrawn: its tag's accepted name stays in the
    # panel and reaches no reader.
    guide.withdraw(drafted)
    assert Site.all_objects.get(pk=guide.site_id).current_publication_id is None
    guide.enter()

    types = _read("types/").json()
    listed = _read("types/poradnik/entries/", locale="en").json()["list"]
    terms = _read("types/poradnik/terms/", locale="en").json()["taxonomies"]
    entry = _read("types/poradnik/entries/en/first/").json()["entry"]
    polish_terms = _read("types/poradnik/terms/", locale="pl").json()["taxonomies"]

    assert types[0]["names"] == {"pl": "Poradnik", "en": "Guide"}
    assert types[0]["segments"] == {"pl": "poradnik", "en": "guide"}
    assert listed["name"] == "Guide"
    # A tag made today takes its English address from its English name
    # (ADR-079 pkt 11): the read names it by that, as a company's site does.
    assert listed["items"][0]["terms"] == [{"taxonomy": "tag", "slug": "tips", "name": "Tips"}]
    assert entry["terms"] == [{"taxonomy": "tag", "slug": "tips", "name": "Tips"}]
    assert terms == [
        {
            "key": "tag",
            "hierarchical": False,
            "segment": "tag",
            "terms": [
                {
                    "taxonomy": "tag",
                    "slug": "tips",
                    "name": "Tips",
                    "count": 1,
                    "indexable": False,
                    "parent_slug": None,
                }
            ],
        }
    ]
    assert [(term["slug"], term["name"]) for term in polish_terms[0]["terms"]] == [
        ("porady", "Porady")
    ]
    # Asked by the address it had until the name was accepted — its Polish
    # one, which is also its key — the list says where it answers now.
    by_name = _read("types/poradnik/entries/", locale="en", taxonomy="tag", term="tips").json()
    assert by_name["moved"] is None and by_name["list"]["term"]["slug"] == "tips"
    assert by_name["list"]["term"]["versions"] == [
        {"locale": "pl", "slug": "porady"},
        {"locale": "en", "slug": "tips"},
    ]
    by_key = _read("types/poradnik/entries/", locale="en", taxonomy="tag", term="porady").json()
    assert by_key == {
        "list": None,
        "moved": {"type": "poradnik", "locale": "en", "taxonomy": "tag", "term": "tips"},
    }
    # In Polish its address is what it was, and the English one leads to it.
    polish_list = _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="tips")
    assert polish_list.json()["moved"]["term"] == "porady"
    everything = json.dumps([types, listed, terms, entry, polish_terms]).lower()
    assert "sketchy" not in everything and "szkicowy" not in everything


def test_the_sitemap_listing_names_entries_lists_and_terms_worth_indexing() -> None:
    guide = Publisher("read-sitemap")
    polish = guide.entry("pierwszy", tags=["Porady", "Rzadki"])
    guide.english(polish, "first", "First", tags=["Porady"])
    guide.entry("drugi", tags=["Porady"])
    guide.entry("trzeci", tags=["Porady"])
    guide.enter()

    sitemap = _read("sitemap/")

    assert sitemap.status_code == 200
    data = sitemap.json()
    entries = {
        tuple((version["locale"], version["slug"]) for version in item["versions"])
        for item in data["entries"]
    }
    assert entries == {
        (("pl", "pierwszy"), ("en", "first")),
        (("pl", "drugi"),),
        (("pl", "trzeci"),),
    }
    assert all(item["type"] == "poradnik" for item in data["entries"])
    assert all(version["updated_at"] for item in data["entries"] for version in item["versions"])
    assert [
        (item["type"], [version["locale"] for version in item["versions"]])
        for item in data["lists"]
    ] == [("poradnik", ["pl", "en"])]
    # „Porady" has three Polish entries and one English one, „Rzadki" one:
    # only a list worth indexing is a line of a sitemap.
    assert [
        (item["taxonomy"], [(version["locale"], version["slug"]) for version in item["versions"]])
        for item in data["terms"]
    ] == [("tag", [("pl", "porady")])]


def test_a_language_the_workspace_switched_off_answers_where_the_entry_is_read_now() -> None:
    guide = Publisher("read-moved")
    polish = guide.entry("pierwszy")
    guide.english(polish, "first", "First")
    only_english = guide.entry("drugi")
    guide.english(only_english, "second", "Second")
    guide.withdraw(only_english)
    Organization.objects.filter(pk=guide.organization.pk).update(public_locales=["pl"])
    guide.enter()

    moved = _read("types/poradnik/entries/en/first/")

    assert moved.status_code == 200
    assert moved.json() == {
        "entry": None,
        "moved": {"type": "poradnik", "locale": "pl", "slug": "pierwszy"},
    }
    # No version left in a language that is read: nothing, not a loop.
    assert _read("types/poradnik/entries/en/second/").status_code == 404
    assert _read("types/poradnik/entries/pl/pierwszy/").data["entry"]["versions"] == [
        {"locale": "pl", "slug": "pierwszy"}
    ]
    assert _read("types/poradnik/entries/", locale="en").status_code == 404
    assert _read("types/").json()[0]["languages"] == ["pl"]


# --- only the platform's workspace -------------------------------------------


def _twin(slug: str) -> tuple[Publisher, Any]:
    """A company with the same type key, entry slug, tag and a published
    picture as the publisher of these tests."""
    company = Publisher(slug)
    asset = company.picture()
    company.entry("wspolny", tags=["Porady"], blocks=_hero(asset, "Firmowy"), media=[str(asset.id)])
    company.entry("tylko-firmy", tags=["Firmowe"])
    return company, asset


def test_a_deployment_without_a_publisher_reads_nothing() -> None:
    company, asset = _twin("read-no-publisher")

    assert _read("types/").json() == []
    assert _read("sitemap/").json() == {"entries": [], "lists": [], "terms": []}
    for path, query in (
        ("types/poradnik/entries/", {"locale": "pl"}),
        ("types/poradnik/terms/", {"locale": "pl"}),
        ("types/poradnik/entries/pl/wspolny/", {}),
        (f"media/{asset.id}/", {}),
    ):
        assert _read(path, **query).status_code == 404, path
    # The company's own site answers as it always did.
    assert _site_page(company.host, "/poradnik/wspolny/").status_code == 200


def test_an_entry_and_its_card_say_when_the_body_opens_with_a_picture() -> None:
    """An import puts a post's cover first in its text, and a product draws
    it above the title: the read says which picture that is, so the page
    need not take the body apart to find out."""
    guide = Publisher("read-cover")
    asset = guide.picture()

    def body(html: str) -> list[dict[str, Any]]:
        return list(convert_html(html, image_assets={"a.jpg": str(asset.id)}).blocks)

    picture = '<img src="a.jpg" alt="Szczeniak">'
    for slug, html in (
        ("otwiera", f"{picture}<p>Tekst pod zdjęciem.</p>"),
        ("dalej", f"<p>Najpierw słowa.</p>{picture}<p>Potem reszta.</p>"),
        ("bez", "<p>Same słowa.</p>"),
    ):
        guide.entry(slug, blocks=body(html), media=[str(asset.id)] if "img" in html else None)
    guide.enter()

    shown = {"asset_id": str(asset.id), "alt": "Szczeniak"}
    covers = {
        slug: (entry["image"], entry["cover"])
        for slug in ("otwiera", "dalej", "bez")
        for entry in [_read(f"types/poradnik/entries/pl/{slug}/").json()["entry"]]
    }
    assert covers == {"otwiera": (shown, shown), "dalej": (shown, None), "bez": (None, None)}
    cards = _read("types/poradnik/entries/", locale="pl").json()["list"]["items"]
    assert {card["slug"]: (card["image"], card["cover"]) for card in cards} == covers
    # The body itself is as published: nothing is taken out of the answer.
    opening = _read("types/poradnik/entries/pl/otwiera/").json()["entry"]["blocks"][0]
    assert opening["data"]["content"][0]["image"]["asset_id"] == str(asset.id)


def test_another_companys_content_is_never_read(monkeypatch: pytest.MonkeyPatch) -> None:
    company, company_asset = _twin("read-company")
    guide = Publisher("read-publisher")
    asset = guide.picture()
    guide.entry("wspolny", tags=["Porady"], blocks=_hero(asset, "Platformy"), media=[str(asset.id)])
    guide.enter()
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (PNG, "image/png")
    storage.objects[company_asset.object_key] = (PNG, "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )

    with CaptureQueriesContext(connection) as captured:
        answers = [
            _read("types/"),
            _read("types/poradnik/terms/", locale="pl"),
            _read("types/poradnik/entries/", locale="pl"),
            _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="porady"),
            _read("types/poradnik/entries/pl/wspolny/"),
            _read("sitemap/"),
            _read(f"media/{asset.id}/"),
        ]
        strangers = [
            _read("types/poradnik/entries/pl/tylko-firmy/"),
            _read("types/poradnik/entries/", locale="pl", taxonomy="tag", term="firmowe"),
            _read(f"media/{company_asset.id}/"),
        ]

    assert [answer.status_code for answer in answers] == [200] * 7
    assert [answer.status_code for answer in strangers] == [404] * 3
    entry = answers[4].data["entry"]
    assert entry["blocks"][0]["data"]["title"] == "Platformy"
    assert entry["image"] == {"asset_id": str(asset.id), "alt": "Szczeniak"}
    # A hero's picture is the first the body shows, and no cover: the body
    # does not open with a picture of its text.
    assert entry["cover"] is None
    assert _slugs(answers[2]) == ["wspolny"]
    assert answers[2].data["list"]["items"][0]["image"] == entry["image"]
    assert answers[2].data["list"]["items"][0]["cover"] is None
    told = json.dumps([answer.json() for answer in answers[:6]], ensure_ascii=False)
    for theirs in ("Firmow", "firmow", "tylko-firmy", str(company_asset.id)):
        assert theirs not in told, theirs
    # These tables carry no policy: the statement's own filter is the whole
    # separation, so each one names the workspace and none names the company.
    statements = [query["sql"] for query in captured.captured_queries]
    open_reads = [sql for sql in statements if any(f'"{table}"' in sql for table in OPEN_TABLES)]
    assert open_reads
    for sql in open_reads:
        assert _names(sql, guide.organization), sql
    for sql in statements:
        assert not _names(sql, company.organization), sql
    # The company's site still answers with its own entry and picture.
    assert (
        _site_page(company.host, "/poradnik/wspolny/").data["blocks"][0]["data"]["title"]
        == "Firmowy"
    )
    served = APIClient().get(
        f"/api/v1/public/site/media/{company_asset.id}/", HTTP_HOST=company.host
    )
    assert served.status_code == 200


def test_the_tenant_is_set_before_every_read_of_a_guarded_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tags, site texts, media and the organization's row force row-level
    security: read before `SET LOCAL`, or after the transaction that set it
    ended, the application's role sees no row — names fall back, pictures
    answer 404, the read answers nothing. The owner of the tables, which the
    tests connect as, sees every row either way; the order is what a test can
    hold."""
    guide = Publisher("read-order")
    asset = guide.picture()
    polish = guide.entry("pierwszy", tags=["Porady"], blocks=_hero(asset), media=[str(asset.id)])
    guide.english(polish, "first", "First", tags=["Porady"])
    guide.english_names({f"tag/{guide.tag('porady')}": "Tips"})
    guide.enter()
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (PNG, "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )

    with CaptureQueriesContext(connection) as captured:
        answers = [
            _read("types/"),
            _read("types/poradnik/terms/", locale="en"),
            _read("types/poradnik/entries/", locale="en"),
            _read("types/poradnik/entries/en/first/"),
            _read("types/poradnik/entries/pl/pierwszy/"),
            _read("sitemap/"),
            _read(f"media/{asset.id}/"),
        ]

    assert [answer.status_code for answer in answers] == [200] * 7
    statements = [query["sql"] for query in captured.captured_queries]

    def door(sql: str) -> bool:
        return '"organizations_organization"' in sql and "'platform'" in sql

    doors = [sql for sql in statements if door(sql)]
    # One constant question per read, and it selects the identifier alone.
    assert len(doors) == len(answers)
    for sql in doors:
        assert sql.split(" FROM ")[0] == 'SELECT "organizations_organization"."id" AS "id"', sql
        assert f"'{platform_workspace_slug()}'" in sql
    guarded = [
        index
        for index, sql in enumerate(statements)
        if not door(sql) and any(f'FROM "{table}"' in sql for table in GUARDED_TABLES)
    ]
    assert {
        table
        for index in guarded
        for table in GUARDED_TABLES
        if f'FROM "{table}"' in statements[index]
    } == set(GUARDED_TABLES)
    for index in guarded:
        before = statements[:index]
        tenant = max(
            (
                at
                for at, sql in enumerate(before)
                if sql.startswith("SET LOCAL app.organization_id")
            ),
            default=None,
        )
        assert tenant is not None, statements[index]
        assert _names(statements[tenant], guide.organization)
        # Still inside the transaction that set it: no block ended in between.
        between = statements[tenant:index]
        assert not any(
            sql.startswith(("RELEASE SAVEPOINT", "ROLLBACK", "COMMIT")) for sql in between
        ), statements[index]


def test_the_read_answers_on_the_platforms_own_hosts_only() -> None:
    """The host gate lists the routes a company's site is read through, and
    this read is not among them: at a company's host it is an unknown host,
    like any address of the panel's API."""
    guide = Publisher("read-hosts")
    guide.entry("pierwszy")
    company, asset = _twin("read-hosts-company")
    guide.enter()

    for path in ("types/", "types/poradnik/entries/pl/pierwszy/", f"media/{asset.id}/"):
        for host in (company.host, guide.host, "nikt.example.test"):
            refused = APIClient().get(f"/api/v1/public/content/{path}", HTTP_HOST=host)
            assert refused.status_code == 400, (path, host)
    assert _read("types/").status_code == 200


def test_a_second_site_in_the_workspace_reads_nothing_rather_than_guessing() -> None:
    guide = Publisher("read-two-sites")
    guide.entry("pierwszy")
    second = guide.client.post(
        "/api/v1/sites/",
        {"name": "Druga", "slug": "druga", "default_locale": "pl"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(guide.client),
        HTTP_IDEMPOTENCY_KEY="second-site",
    )
    assert second.status_code == 201, second.data
    guide.enter()

    assert _read("types/").json() == []
    assert _read("types/poradnik/entries/pl/pierwszy/").status_code == 404


def test_asking_about_the_publisher_all_the_same_has_its_two_callers() -> None:
    """`serving_locales(…, publisher=True)` is how the rule „the workspace's
    site answers at no host" is stepped around on purpose: by the read of
    its published content, and by the panel's own preview. A third caller
    would serve the workspace somewhere, so the callers are counted."""
    import ast
    from pathlib import Path

    source = Path(settings.BASE_DIR) / "src" / "saas_core"
    callers = {
        path.relative_to(source).as_posix()
        for path in sorted(source.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and any(keyword.arg == "publisher" or keyword.arg is None for keyword in node.keywords)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "serving_locales"
    }

    assert callers == {
        "modules/shared/sites/content_reads.py",
        "modules/shared/sites/seo_preview.py",
    }


def test_the_read_is_called_from_its_own_routes_and_nowhere_else() -> None:
    """The read finds its tenant without a host. What makes that safe is
    where it is mounted: under addresses the host gate answers on the
    platform's own hosts only, with no caller's value choosing the workspace.
    A second caller — another view, a task, a route addressed by a company's
    host — would carry the exception somewhere this file does not test, so
    the modules that import the read are counted here, like the door's."""
    import ast
    from pathlib import Path

    from saas_core.http.hosts import PUBLIC_MEDIA_PREFIX, PUBLIC_SITE_ROUTES

    source = Path(settings.BASE_DIR) / "src" / "saas_core"
    importers = set()
    for path in sorted(source.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module or "", *(alias.name for alias in node.names)]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(name.rsplit(".", 1)[-1] == "content_reads" for name in names):
                importers.add(path.relative_to(source).as_posix())

    assert importers == {
        # The routes, and the shapes they answer with (the page-size bound).
        "modules/shared/sites/content_read_views.py",
        "modules/shared/sites/content_read_serializers.py",
    }
    # And those routes are none of the ones a company's site is read through.
    prefix = "/api/v1/public/content/"
    assert not any(route.startswith(prefix) for route in PUBLIC_SITE_ROUTES)
    assert not prefix.startswith(PUBLIC_MEDIA_PREFIX)


# --- pictures ----------------------------------------------------------------


def test_a_picture_answers_only_while_a_published_entry_shows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = Publisher("read-media")
    shown, drafted, of_page, withdrawn_asset = (guide.picture() for _ in range(4))
    guide.entry("ze-zdjeciem", blocks=_hero(shown), media=[str(shown.id)])
    guide.entry("szkic", blocks=_hero(drafted), media=[str(drafted.id)], out=False)
    withdrawn = guide.entry(
        "wycofany", blocks=_hero(withdrawn_asset), media=[str(withdrawn_asset.id)]
    )
    # A page of the workspace's builder site, published with a picture.
    page = str(create_page(guide.client, guide.site_id, key="start").data["id"])
    assert (
        save_draft(
            guide.client,
            page,
            expected_version=0,
            idempotency_key="media-page-draft",
            heading="Strona kreatora",
            media_asset_ids=[str(of_page.id)],
        ).status_code
        == 201
    )
    assert (
        save_translation(
            guide.client,
            page,
            "pl",
            expected_version=0,
            slug="start",
            title="Start",
            description="Strona kreatora",
            idempotency_key="media-page-pl",
        ).status_code
        == 201
    )
    published = publish_site_request(guide.client, guide.site_id, idempotency_key="media-site")
    assert published.status_code == 201, published.data
    storage = MemoryStorage()
    for asset in (shown, drafted, of_page, withdrawn_asset):
        storage.objects[asset.object_key] = (PNG, "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )

    def media(asset: Any, variant: str = "") -> Any:
        return _read(f"media/{asset.id}/{variant}")

    # Before it is the publisher's: a company's pictures are not read here,
    # and its own site shows the page's picture.
    assert media(shown).status_code == 404
    on_site = APIClient().get(f"/api/v1/public/site/media/{of_page.id}/", HTTP_HOST=guide.host)
    assert on_site.status_code == 200
    guide.enter()

    served = media(shown)
    assert served.status_code == 200
    assert served.content == PNG
    assert served["Content-Type"] == "image/jpeg"
    assert served["Cache-Control"] == "public, max-age=31536000, immutable"
    nobody = _read("media/00000000-0000-7000-8000-000000000000/")
    assert nobody.status_code == 404
    for hidden in (drafted, of_page):
        answer = media(hidden)
        assert (answer.status_code, answer.content) == (nobody.status_code, nobody.content)
    # A copy the pipeline never made is no address either.
    assert media(shown, "preview/").status_code == 404
    assert media(shown, "original/").status_code == 404
    assert media(withdrawn_asset).status_code == 200
    guide.leave()
    guide.withdraw(withdrawn)
    guide.enter()
    assert media(withdrawn_asset).status_code == 404
    guide.leave()
    assert _switch(guide.client, guide.type_id, "off").status_code == 200
    guide.enter()
    # A switched-off type's pictures answer no more than its entries do.
    assert media(shown).status_code == 404


def test_a_picture_answers_where_its_entry_does_and_in_no_switched_off_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = Publisher("read-media-language")
    polish = guide.entry("pierwszy")
    asset = guide.picture()
    english = guide.english(polish, "first", "First")
    guide.draft(english, 1, blocks=_hero(asset), media=[str(asset.id)])
    guide.publish(english, "again")
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (PNG, "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    guide.enter()

    assert _read(f"media/{asset.id}/").status_code == 200
    Organization.objects.filter(pk=guide.organization.pk).update(public_locales=["pl"])

    # The entry answers „moved" now, so its picture is nobody's to see.
    assert _read("types/poradnik/entries/en/first/").json()["entry"] is None
    assert _read(f"media/{asset.id}/").status_code == 404


# --- the workspace's own builder site ----------------------------------------


def test_the_workspaces_own_site_answers_at_no_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-079 pkt 29: the workspace's entries are shown by the product's own
    pages. Its builder site would give each of them a second public address,
    with a canonical, a sitemap and a feed of its own — so every route of its
    host answers as an unknown host does. Its rows stay as they are."""
    from test_sites_blog_languages import Blog

    blog = Blog("workspace-site")
    asset = create_media_asset(
        Organization.objects.get(slug="workspace-site"), _owner("workspace-site")
    )
    with_picture = str(
        create_entry(
            blog.client, blog.collection_id, slug="ze-zdjeciem", idempotency_key="ws-pic"
        ).data["id"]
    )
    saved = blog.client.put(
        f"/api/v1/sites/entries/{with_picture}/draft/",
        {"expected_version": 0, "blocks": _hero(asset), "media_asset_ids": [str(asset.id)]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
        HTTP_IDEMPOTENCY_KEY="ws-pic-draft",
    )
    assert saved.status_code == 201, saved.data
    assert publish(blog.client, with_picture, idempotency_key="ws-pic-out").status_code == 201
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (PNG, "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    other = Blog("company-site")
    host = blog.host
    pages = ("/", "/oferta/", "/blog/", "/blog/wpis-jeden/", "/blog/tag/porady/", "/en/")
    files = (
        ("feed.xml", None),
        ("feed.xml", "en"),
        ("atom.xml", None),
        ("atom.xml", "en"),
        ("llms.txt", None),
        ("llms.txt", "en"),
        ("sitemap.xml", None),
        ("robots.txt", None),
    )

    def file(name: str, locale: str | None, at: str = host) -> Any:
        with override_settings(PUBLIC_SITE_SCHEME="https"):
            return APIClient().get(
                f"/api/v1/public/site/{name}", {"locale": locale} if locale else {}, HTTP_HOST=at
            )

    def picture(at: str = host, variant: str = "") -> Any:
        return APIClient().get(f"/api/v1/public/site/media/{asset.id}/{variant}", HTTP_HOST=at)

    def message_destination(at: str) -> bool:
        """Whether a message sent from a page at this host has a site to go
        to: `submit_site_inquiry` takes its destination from this lookup and
        from nothing in the body."""
        try:
            resolve_public_page(host=at, path="/")
        except PublicSiteNotFound:
            return False
        return True

    # As a company's site, all of it answers.
    for path in pages:
        assert _site_page(host, path).status_code == 200, path
    for name, locale in files:
        assert file(name, locale).status_code == 200, (name, locale)
    assert picture().status_code == 200
    assert message_destination(host)
    assert site_host_company(host) is not None
    assert authorize_tls_hostname(host).allowed
    before = _rows(blog.site_id)

    Organization.objects.filter(slug="workspace-site").update(
        workspace_kind=WorkspaceKind.PLATFORM, slug=platform_workspace_slug()
    )

    unknown = _site_page("nikt.example.test", "/")
    for path in pages:
        assert _refusal(_site_page(host, path)) == _refusal(unknown), path
    for name, locale in files:
        assert file(name, locale).status_code == 404, (name, locale)
    assert picture().status_code == 404
    assert picture(variant="preview/").status_code == 404
    assert not message_destination(host)
    # No certificate for a host that serves nothing, and no browser read of
    # the company's records there. (The gateway's decision is remembered for
    # a while; a new one is what the rule changes.)
    cache.clear()
    assert not authorize_tls_hostname(host).allowed
    assert site_host_company(host) is None
    # Nothing was withdrawn or deleted: the rows are the publisher's still.
    assert _rows(blog.site_id) == before
    # What it published is read by the product's pages instead — the entries,
    # and the pictures they show.
    assert _slugs(_read("types/blog/entries/", locale="pl")) == ["ze-zdjeciem", "wpis-jeden"]
    assert _read(f"media/{asset.id}/").status_code == 200
    # A company's site is what it was.
    for path in pages:
        assert _site_page(other.host, path).status_code == 200, path
    for name, locale in files:
        assert file(name, locale, other.host).status_code == 200, (name, locale)
    assert message_destination(other.host)


def _owner(slug: str) -> Any:
    from saas_core.modules.core.identity.models import User

    return User.objects.get(email=f"{slug}@example.test")


def _rows(site_id: str) -> tuple[Any, ...]:
    site = Site.all_objects.get(pk=site_id)
    return (
        site.current_publication_id,
        sorted(
            ContentEntry.all_objects.filter(site_id=site_id).values_list(
                "id", "state", "current_publication_id"
            )
        ),
        sorted(ContentCollection.all_objects.filter(site_id=site_id).values_list("id", "key")),
    )


def test_the_publishers_panel_is_given_no_address_of_the_builder_site() -> None:
    """„Widoczność w wyszukiwarkach” lists addresses that answer now. For the
    workspace none does, so the read lists none — the panel has nothing of
    that host to show or open. A company's answer is what it was."""
    from saas_core.modules.core.organizations.context import (
        activate_tenant_context,
        context_from_membership,
    )
    from saas_core.modules.core.organizations.models import Membership
    from saas_core.modules.shared.sites.search_visibility import read_search_visibility
    from test_sites_blog_languages import Blog

    blog = Blog("visibility-site")
    membership = Membership.objects.get(organization__slug="visibility-site")

    def read() -> dict[str, Any]:
        with activate_tenant_context(context_from_membership(membership)):
            return read_search_visibility()["sites"][0]

    company = read()
    Organization.objects.filter(slug="visibility-site").update(
        workspace_kind=WorkspaceKind.PLATFORM, slug=platform_workspace_slug()
    )
    publisher = read()

    assert company["origin"].endswith(f"://{blog.host}")
    assert company["sitemap_url"] and company["robots_url"] and company["languages"]
    assert publisher == {
        "site_id": company["site_id"],
        "name": company["name"],
        "origin": None,
        "sitemap_url": None,
        "robots_url": None,
        "languages": [],
    }
    assert blog.host not in str(publisher)


def test_the_panels_preview_of_the_workspaces_pages_is_what_it_was() -> None:
    """The rule is about hosts. The publisher's panel still previews its
    pages in every language, as a company's does."""
    from saas_core.modules.shared.sites.publication_routing import serving_locales

    guide = Publisher("read-panel")
    company = serving_locales(guide.organization.id)
    guide.enter()

    assert company
    assert serving_locales(guide.organization.id) is None
    assert serving_locales(guide.organization.id, publisher=True) == company
