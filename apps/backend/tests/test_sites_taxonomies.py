"""Categories and tags (ADR-079 phase CT2): a content type's categories as a
tree with archives in every language, the site's tags beside them, addresses
per language that close once and move at most once, one 308 for every former
address, and nothing shown to a visitor that no publication carries."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.content_protocol.policy import Trigger
from saas_core.content_protocol.provenance import ORIGIN_AI, Provenance
from saas_core.content_protocol.sources import WriteBatch, WriteItem
from saas_core.content_protocol.units import unit_hash
from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.sites.models import (
    LEGACY_TERM_LOCK,
    ContentCollection,
    ContentEntry,
    ContentTag,
    ContentTaxonomy,
    Site,
    SiteTextTranslation,
)
from saas_core.modules.shared.sites.site_text_source import SITE_TEXT_SOURCE
from saas_core.modules.shared.sites.site_texts import published_terms
from saas_core.testing.translation_sources import AUTOMATIC, translation_policy_override
from test_sites_api import csrf_value
from test_sites_blog_languages import Blog, _feed, _get, _items
from test_sites_collections import (
    _tenant_set_before,
    create_entry,
    publish,
    save_entry_draft,
    set_tags,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def a_company_in_three_languages(settings: Any) -> None:
    """What these tests start from, whatever the profile they run under says:
    Polish, English and German, and a platform that offers a second type."""
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    settings.CONTENT_TYPES_OFFERED = True


# -- helpers -------------------------------------------------------------------


def _send(client: Any, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    return getattr(client, method)(
        url, payload or {}, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )


def _code(response: Any) -> tuple[int, str]:
    body = response.json()
    errors = body.get("errors") or []
    return response.status_code, (errors[0]["code"] if errors else body.get("code", ""))


class World:
    """A Polish site in three languages with its blog and „Realizacje”
    (`/realizacje/`, `/en/projects/`, `/de/referenzen/`)."""

    def __init__(self, slug: str) -> None:
        self.blog = Blog(slug)
        self.client, self.host, self.site_id = self.blog.client, self.blog.host, self.blog.site_id
        self.organization_id = Site.all_objects.get(pk=self.site_id).organization_id
        Organization.objects.filter(pk=self.organization_id).update(
            public_locales=["pl", "en", "de"]
        )
        made = self.client.post(
            f"/api/v1/sites/{self.site_id}/collections/",
            {
                "key": "realizacje",
                "name": "Realizacje",
                "kind": "blog",
                "base_path": "realizacje",
                "locale_paths": {"en": "projects", "de": "referenzen"},
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
            HTTP_IDEMPOTENCY_KEY=f"projects-{slug}",
        )
        assert made.status_code == 201, made.data
        self.projects = str(made.data["id"])
        self.blog_id = self.blog.collection_id

    # -- terms

    def terms(self, type_id: str, kind: str = "categories") -> dict[str, Any]:
        response = self.client.get(f"/api/v1/sites/collections/{type_id}/terms/?kind={kind}")
        assert response.status_code == 200, response.data
        return dict(response.json())

    def term(self, type_id: str, term_id: str, kind: str = "categories") -> dict[str, Any]:
        return next(item for item in self.terms(type_id, kind)["terms"] if item["id"] == term_id)

    def category(self, type_id: str, name: str, parent: str | None = None) -> str:
        made = _send(
            self.client,
            "post",
            f"/api/v1/sites/collections/{type_id}/terms/",
            {"kind": "categories", "name": name, **({"parent_id": parent} if parent else {})},
        )
        assert made.status_code == 201, made.json()
        return str(made.json()["id"])

    def names(self, type_id: str, term_id: str, **names: str) -> Any:
        return _send(
            self.client,
            "put",
            f"/api/v1/sites/collections/{type_id}/terms/{term_id}/names/",
            {"names": names},
        )

    def address(self, type_id: str, term_id: str, *, preview: bool = False, **body: Any) -> Any:
        url = f"/api/v1/sites/collections/{type_id}/terms/{term_id}/address/"
        return _send(
            self.client, "post" if preview else "put", url + ("preview/" if preview else ""), body
        )

    def update(self, type_id: str, term_id: str, *, preview: bool = False, **body: Any) -> Any:
        url = f"/api/v1/sites/collections/{type_id}/terms/{term_id}/"
        if preview:
            return _send(self.client, "post", url + "preview/", body)
        return _send(self.client, "patch", url, body)

    def remove(self, type_id: str, term_id: str, *, preview: bool = False) -> Any:
        url = f"/api/v1/sites/collections/{type_id}/terms/{term_id}/"
        if preview:
            return _send(self.client, "post", url + "removal/preview/")
        return _send(self.client, "delete", url)

    # -- entries

    def entry(
        self,
        type_id: str,
        slug: str,
        *,
        categories: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        out: bool = True,
    ) -> str:
        entry_id = str(
            create_entry(self.client, type_id, slug=slug, idempotency_key=f"e-{slug}").data["id"]
        )
        save_entry_draft(
            self.client,
            entry_id,
            expected_version=0,
            text=f"Treść {slug}.",
            idempotency_key=f"d-{slug}",
        )
        self.file(entry_id, categories=categories, tags=tags)
        if out:
            self.out(entry_id)
        return entry_id

    def file(
        self,
        entry_id: str,
        *,
        categories: tuple[str, ...] | None = None,
        tags: tuple[str, ...] | None = None,
    ) -> None:
        if categories is not None:
            filed = _send(
                self.client,
                "put",
                f"/api/v1/sites/entries/{entry_id}/categories/",
                {"term_ids": list(categories)},
            )
            assert filed.status_code == 200, filed.json()
        if tags is not None:
            assert set_tags(self.client, entry_id, list(tags)).status_code == 200

    def out(self, entry_id: str) -> None:
        done = publish(self.client, entry_id, idempotency_key=f"p-{uuid4()}")
        assert done.status_code == 201, done.data

    def translated(
        self,
        entry_id: str,
        locale: str,
        slug: str,
        title: str,
        *,
        categories: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        out: bool = True,
    ) -> str:
        created = self.client.post(
            f"/api/v1/sites/entries/{entry_id}/translations/",
            {"locale": locale, "slug": slug, "title": title},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(self.client),
            HTTP_IDEMPOTENCY_KEY=f"tr-{slug}",
        )
        assert created.status_code == 201, created.data
        translated = str(created.data["id"])
        save_entry_draft(
            self.client,
            translated,
            expected_version=0,
            text=f"{title}.",
            idempotency_key=f"trd-{slug}",
        )
        self.file(translated, categories=categories, tags=tags)
        if out:
            self.out(translated)
        return translated


def _status(host: str, path: str) -> int:
    return int(_get(host, path).status_code)


def _moved(host: str, path: str) -> tuple[int, str | None]:
    response = _get(host, path)
    return response.status_code, response.get("Location")


def _one_hop(host: str, path: str, to: str) -> None:
    """`path` answers one 308 to `to`, and `to` answers."""
    assert _moved(host, path) == (308, to), path
    assert _status(host, to) == 200, to


def _sitemap(host: str) -> str:
    return str(_feed(host, "sitemap.xml").content.decode())


# -- the tree and its archives -------------------------------------------------


def test_a_types_categories_are_a_tree_with_an_archive_in_each_language() -> None:
    world = World("tax-tree")
    client, host, origin = world.client, world.host, f"https://{world.host}"
    interiors = world.category(world.projects, "Wnętrza")
    bathrooms = world.category(world.projects, "Łazienki", interiors)
    small = world.category(world.projects, "Małe łazienki", bathrooms)
    kitchens = world.category(world.projects, "Kuchnie")
    # Three levels and no more.
    deeper = _send(
        client,
        "post",
        f"/api/v1/sites/collections/{world.projects}/terms/",
        {"kind": "categories", "name": "Najmniejsze", "parent_id": small},
    )
    assert _code(deeper) == (400, "term_too_deep")
    # The blog's categories are its own: the same word is another category.
    blog_bathrooms = world.category(world.blog_id, "Łazienki")
    assert blog_bathrooms != bathrooms

    listed = world.terms(world.projects)
    # In the order they were made, a category before those under it.
    assert [(item["name"], item["depth"]) for item in listed["terms"]] == [
        ("Wnętrza", 1),
        ("Łazienki", 2),
        ("Małe łazienki", 3),
        ("Kuchnie", 1),
    ]
    assert listed["segments"] == {"pl": "kategoria", "en": "category", "de": "kategorie"}
    assert (listed["max_depth"], listed["max_per_entry"]) == (3, 10)
    # Nothing published carries any of them: no archive, no address answers.
    assert all(item["published"] == {} and item["removable"] for item in listed["terms"])
    assert _status(host, "/realizacje/kategoria/lazienki/") == 404

    first = world.entry(world.projects, "dom-jeden", categories=(bathrooms,))
    second = world.entry(world.projects, "dom-dwa", categories=(small,))
    world.entry(world.projects, "dom-trzy", categories=(bathrooms, kitchens))
    world.translated(first, "en", "house-one", "House one", categories=(bathrooms,))
    world.translated(second, "en", "house-two", "House two", categories=(small,))
    world.translated(first, "de", "haus-eins", "Haus eins", categories=(bathrooms,))
    world.entry(world.blog_id, "wpis-o-lazience", categories=(blog_bathrooms,))

    archive = _get(host, "/realizacje/kategoria/lazienki/")
    assert archive.status_code == 200, archive.data
    # Its own entries and those of the category under it, newest first.
    assert _items(archive) == [
        "/realizacje/dom-trzy/",
        "/realizacje/dom-dwa/",
        "/realizacje/dom-jeden/",
    ]
    assert archive.data["title"] == "Kategoria: Łazienki"
    assert archive.data["noindex"] is False
    assert archive.data["canonical_url"] == f"{origin}/realizacje/kategoria/lazienki/"
    # The address is flat; the trail is where the tree shows.
    assert archive.data["show_breadcrumbs"] is True
    assert [(crumb["title"], crumb["path"]) for crumb in archive.data["breadcrumbs"]] == [
        ("Realizacje", "/realizacje/"),
        ("Wnętrza", "/realizacje/kategoria/wnetrza/"),
        ("Łazienki", "/realizacje/kategoria/lazienki/"),
    ]
    assert _status(host, "/realizacje/kategoria/wnetrza/lazienki/") == 404
    assert archive.data["hreflang"] == {
        "pl": f"{origin}/realizacje/kategoria/lazienki/",
        "en": f"{origin}/en/projects/category/lazienki/",
        "de": f"{origin}/de/referenzen/kategorie/lazienki/",
    }
    # The top category lists everything under it; the smallest its own.
    assert _items(_get(host, "/realizacje/kategoria/wnetrza/")) == _items(archive)
    thin = _get(host, "/realizacje/kategoria/male-lazienki/")
    assert (_items(thin), thin.data["noindex"]) == (["/realizacje/dom-dwa/"], True)
    assert _items(_get(host, "/realizacje/kategoria/kuchnie/")) == ["/realizacje/dom-trzy/"]
    # Each language lists its own entries, under its own word for „category”.
    english = _get(host, "/en/projects/category/lazienki/")
    assert _items(english) == ["/en/projects/house-two/", "/en/projects/house-one/"]
    assert english.data["title"] == "Category: Łazienki"
    assert _items(_get(host, "/de/referenzen/kategorie/lazienki/")) == ["/de/referenzen/haus-eins/"]
    # Another language's word is no address, nor is the German archive of a
    # category no German entry carries.
    assert _status(host, "/en/projects/kategoria/lazienki/") == 404
    assert _status(host, "/de/referenzen/kategorie/kuchnie/") == 404
    # The blog's category of the same name is the blog's: its own entries.
    assert _items(_get(host, "/blog/kategoria/lazienki/")) == ["/blog/wpis-o-lazience/"]
    assert _status(host, "/blog/kategoria/kuchnie/") == 404

    # The sitemap names an archive once it is a topic — three entries.
    sitemap = _sitemap(host)
    for path, there in (
        ("/realizacje/kategoria/lazienki/", True),
        ("/realizacje/kategoria/wnetrza/", True),
        ("/realizacje/kategoria/male-lazienki/", False),
        ("/realizacje/kategoria/kuchnie/", False),
        ("/en/projects/category/lazienki/", False),
        ("/blog/kategoria/lazienki/", False),
    ):
        assert (f"<loc>{origin}{path}</loc>" in sitemap) is there, path

    # What the panel says is what visitors get.
    row = world.term(world.projects, bathrooms)
    assert row["published"] == {"pl": 3, "en": 2, "de": 1}
    assert (row["entries"], row["removable"]) == (4, False)
    assert row["paths"] == {
        "pl": "/realizacje/kategoria/lazienki/",
        "en": "/en/projects/category/lazienki/",
        "de": "/de/referenzen/kategorie/lazienki/",
    }
    # The same word in two types: two keys, one address each in its own type.
    keys = {item["key"] for item in (row, world.term(world.blog_id, blog_bathrooms))}
    assert keys == {"lazienki", "lazienki-2"}
    assert world.term(world.blog_id, blog_bathrooms)["slugs"]["pl"] == "lazienki"
    # The key always leads to the category.
    _one_hop(host, "/blog/kategoria/lazienki-2/", "/blog/kategoria/lazienki/")


def test_a_category_is_never_a_tag() -> None:
    world = World("tax-not-tag")
    host = world.host
    wood = world.category(world.projects, "Drewno")
    for slug in ("dom-a", "dom-b", "dom-c"):
        world.entry(world.projects, slug, categories=(wood,), tags=("Porady",))
    plain = world.entry(world.projects, "dom-d", tags=("Porady",))

    page = _get(host, "/realizacje/dom-a/").data
    assert [tag["slug"] for tag in page["article"]["tags"]] == ["porady"]
    assert page["article"]["categories"] == [
        {"name": "Drewno", "path": "/realizacje/kategoria/drewno/"}
    ]
    keywords = [
        node.get("keywords") for node in page["structured_data"]["@graph"] if node.get("keywords")
    ]
    assert keywords and all("Drewno" not in str(found) for found in keywords)
    # An entry under no category reads as entries always did: no such key.
    assert "categories" not in _get(host, "/realizacje/dom-d/").data["article"]
    # No tag archive for a category, no category archive for a tag.
    assert _status(host, "/realizacje/tag/drewno/") == 404
    assert _status(host, "/realizacje/kategoria/porady/") == 404
    assert _status(host, "/realizacje/kategoria/drewno/") == 200
    assert _status(host, "/realizacje/tag/porady/") == 200
    sitemap = _sitemap(host)
    assert "/realizacje/tag/drewno/" not in sitemap
    assert "/realizacje/kategoria/drewno/" in sitemap and "/realizacje/tag/porady/" in sitemap
    # In the panel and in the publication: tags among tags, categories apart.
    entry = next(
        item
        for item in world.client.get(f"/api/v1/sites/collections/{world.projects}/entries/").json()[
            "items"
        ]
        if item["id"] == plain
    )
    assert (entry["tags"], entry["categories"]) == ([{"slug": "porady", "name": "Porady"}], [])
    filed = ContentEntry.all_objects.get(slug="dom-a").current_publication
    assert filed is not None
    assert filed.snapshot["tags"] == [{"slug": "porady", "name": "Porady"}]
    assert sorted(term["key"] for term in filed.snapshot["terms"]) == ["drewno", "porady"]
    assert [item["key"] for item in world.terms(world.projects, "tags")["terms"]] == ["porady"]
    assert [item["key"] for item in world.terms(world.projects)["terms"]] == ["drewno"]
    # Setting an entry's tags leaves its categories, and the other way round.
    world.file(plain, categories=(wood,))
    world.file(plain, tags=("Inne",))
    kept = world.client.get(f"/api/v1/sites/entries/{plain}/categories/").json()
    assert [term["key"] for term in kept] == ["drewno"]
    # A category of another type is nobody's here.
    other = world.category(world.blog_id, "Blogowa")
    refused = _send(
        world.client, "put", f"/api/v1/sites/entries/{plain}/categories/", {"term_ids": [other]}
    )
    assert _code(refused) == (400, "term_not_of_type")


def test_a_visitor_learns_of_nothing_unpublished() -> None:
    world = World("tax-unpublished")
    host = world.host
    shown = world.category(world.projects, "Pokazana")
    hidden = world.category(world.projects, "Schowana")
    draft_only = world.category(world.projects, "Tylko szkic")
    entry = world.entry(world.projects, "dom-a", categories=(shown,), tags=("Widoczny",))
    world.entry(
        world.projects, "dom-szkic", categories=(draft_only,), tags=("Szkicowy",), out=False
    )
    # Filed anew in the panel, not published again: visitors see what went out.
    world.file(entry, categories=(hidden,), tags=("Nowy",))

    assert _status(host, "/realizacje/kategoria/pokazana/") == 200
    for path in (
        "/realizacje/kategoria/schowana/",
        "/realizacje/kategoria/tylko-szkic/",
        "/realizacje/tag/nowy/",
        "/realizacje/tag/szkicowy/",
    ):
        assert _status(host, path) == 404, path
    page = _get(host, "/realizacje/dom-a/").data["article"]
    assert [item["name"] for item in page["categories"]] == ["Pokazana"]
    assert [tag["name"] for tag in page["tags"]] == ["Widoczny"]
    # Offered for translation, and so named in a publication of the site: only
    # what a publication carries.
    site = Site.all_objects.get(pk=world.site_id)
    assert sorted(term.name for term in published_terms(site)) == ["Pokazana", "Porady", "Widoczny"]
    texts = world.client.get(f"/api/v1/sites/{world.site_id}/texts/en/").json()
    named = {item["source_text"] for item in texts["items"] if item["key"].startswith("tag/")}
    assert named == {"Pokazana", "Porady", "Widoczny"}
    # The panel says so too: filed under it, but on no page of the site.
    row = world.term(world.projects, hidden)
    assert (row["entries"], row["published"], row["removable"]) == (1, {}, False)
    assert world.term(world.projects, shown)["published"] == {"pl": 1}
    # An entry that asks not to be indexed is on no archive's list and links
    # to none.
    quiet = world.entry(world.projects, "dom-cichy", categories=(draft_only,), out=False)
    asked = _send(
        world.client, "patch", f"/api/v1/sites/entries/{quiet}/metadata/", {"noindex": True}
    )
    assert asked.status_code == 200, asked.json()
    world.out(quiet)
    assert _status(host, "/realizacje/kategoria/tylko-szkic/") == 404
    assert "categories" not in _get(host, "/realizacje/dom-cichy/").data["article"]


def test_moving_and_renaming_a_category_shows_at_once_and_moves_no_address() -> None:
    world = World("tax-move")
    host = world.host
    interiors = world.category(world.projects, "Wnętrza")
    bathrooms = world.category(world.projects, "Łazienki", interiors)
    gardens = world.category(world.projects, "Ogrody")
    world.entry(world.projects, "dom-a", categories=(bathrooms,))
    assert _items(_get(host, "/realizacje/kategoria/wnetrza/")) == ["/realizacje/dom-a/"]

    preview = world.update(world.projects, bathrooms, preview=True, parent_id=gardens)
    assert preview.status_code == 200, preview.json()
    assert (preview.json()["changed"], preview.json()["published"]) == (True, 1)
    assert _status(host, "/realizacje/kategoria/ogrody/") == 404
    moved = world.update(world.projects, bathrooms, parent_id=gardens)
    assert moved.status_code == 200, moved.json()

    # No publication happened; the archives changed, the address did not.
    assert _status(host, "/realizacje/kategoria/wnetrza/") == 404
    assert _items(_get(host, "/realizacje/kategoria/ogrody/")) == ["/realizacje/dom-a/"]
    assert _status(host, "/realizacje/kategoria/lazienki/") == 200
    # A new name shows at once too; the address closed with the first
    # publication and stays.
    renamed = world.update(world.projects, bathrooms, name="Łazienki i sauny")
    assert renamed.status_code == 200, renamed.json()
    archive = _get(host, "/realizacje/kategoria/lazienki/")
    assert archive.data["title"] == "Kategoria: Łazienki i sauny"
    assert _status(host, "/realizacje/kategoria/lazienki-i-sauny/") == 404
    assert world.term(world.projects, bathrooms)["locked"] == ["pl"]
    # The categories above a published one answer with it, so they closed
    # with it: „Wnętrza” at the publication, „Ogrody” when it took the
    # category in. Their names no longer move their addresses either.
    for term_id, name, address in (
        (interiors, "Wnętrza domów", "wnetrza"),
        (gardens, "Ogrody i tarasy", "ogrody"),
    ):
        assert world.update(world.projects, term_id, name=name).status_code == 200
        assert world.term(world.projects, term_id)["slugs"]["pl"] == address
    # A category nothing published is under follows its name freely.
    terraces = world.category(world.projects, "Tarasy")
    assert world.update(world.projects, terraces, name="Tarasy i balkony").status_code == 200
    row = world.term(world.projects, terraces)
    assert (row["slugs"]["pl"], row["locked"]) == ("tarasy-i-balkony", [])
    # A category cannot lie under itself or under what lies under it, and a
    # name is one among those beside it.
    assert _code(world.update(world.projects, gardens, parent_id=bathrooms)) == (
        400,
        "term_parent_invalid",
    )
    again = _send(
        world.client,
        "post",
        f"/api/v1/sites/collections/{world.projects}/terms/",
        {"kind": "categories", "name": "łazienki i sauny", "parent_id": gardens},
    )
    assert _code(again) == (400, "term_name_taken")
    # Order among those beside it.
    first = world.category(world.projects, "Altany", gardens)
    reordered = world.update(world.projects, first, position=0)
    assert reordered.status_code == 200, reordered.json()
    under = [item["name"] for item in world.terms(world.projects)["terms"] if item["depth"] == 2]
    assert under == ["Altany", "Łazienki i sauny"]
    unchanged = world.update(world.projects, first, position=0)
    assert unchanged.json()["changed"] is False


# -- an address per language: closed once, moved at most once ------------------


def _english(world: World, term_id: str, type_id: str | None = None) -> dict[str, Any]:
    row = world.term(type_id or world.projects, term_id)
    return {"slug": row["slugs"]["en"], "locked": "en" in row["locked"], "path": row["paths"]["en"]}


def test_a_name_accepted_before_the_first_entry_is_the_address_from_the_start() -> None:
    world = World("tax-name-first")
    host = world.host
    kitchens = world.category(world.projects, "Kuchnie")
    named = world.names(world.projects, kitchens, en="Kitchens")
    assert named.status_code == 200, named.json()
    # Nothing answered yet, so nothing moved and nothing is closed.
    assert named.json()["moved"] == []
    assert _english(world, kitchens) == {
        "slug": "kitchens",
        "locked": False,
        "path": "/en/projects/category/kitchens/",
    }
    # Still open: a better name is a better address.
    assert world.names(world.projects, kitchens, en="Kitchen ideas").status_code == 200
    assert _english(world, kitchens)["slug"] == "kitchen-ideas"

    polish = world.entry(world.projects, "kuchnia-a", categories=(kitchens,))
    # A Polish entry closes the Polish address; English has no archive yet.
    assert world.term(world.projects, kitchens)["locked"] == ["pl"]
    assert _status(host, "/en/projects/category/kitchen-ideas/") == 404
    world.translated(polish, "en", "kitchen-a", "Kitchen A", categories=(kitchens,))

    assert _english(world, kitchens)["locked"] is True
    assert _status(host, "/en/projects/category/kitchen-ideas/") == 200
    # The Polish address and the key lead there, one step.
    _one_hop(host, "/en/projects/category/kuchnie/", "/en/projects/category/kitchen-ideas/")
    # Closed: a new name is a new title, never a new address.
    assert world.names(world.projects, kitchens, en="Kitchens").json()["moved"] == []
    assert _english(world, kitchens)["slug"] == "kitchen-ideas"
    world.blog.publish("after-names")
    assert _get(host, "/en/projects/category/kitchen-ideas/").data["title"] == "Category: Kitchens"


def test_an_entry_out_before_the_name_moves_the_archive_once_with_one_308() -> None:
    world = World("tax-entry-first")
    host = world.host
    bathrooms = world.category(world.projects, "Łazienki")
    polish = world.entry(world.projects, "dom-a", categories=(bathrooms,))
    world.translated(polish, "en", "house-a", "House A", categories=(bathrooms,))
    # No English name yet: the archive answers under the site's language's.
    interim = "/en/projects/category/lazienki/"
    assert _status(host, interim) == 200
    assert _english(world, bathrooms) == {"slug": "lazienki", "locked": False, "path": interim}

    named = world.names(world.projects, bathrooms, en="Bathrooms")

    assert named.status_code == 200, named.json()
    final = "/en/projects/category/bathrooms/"
    assert named.json()["moved"] == [{"locale": "en", "from_path": interim, "to_path": final}]
    assert _english(world, bathrooms) == {"slug": "bathrooms", "locked": True, "path": final}
    _one_hop(host, interim, final)
    # The Polish archive is where it was, and names the English one.
    polish_archive = _get(host, "/realizacje/kategoria/lazienki/")
    assert polish_archive.status_code == 200
    assert polish_archive.data["hreflang"]["en"] == f"https://{host}{final}"
    # At most once: whatever the name becomes, the address has closed.
    for again in ("Baths", "Bathrooms and spas", ""):
        assert world.names(world.projects, bathrooms, en=again).json()["moved"] == []
        assert _english(world, bathrooms)["slug"] == "bathrooms"
        assert _status(host, final) == 200
        assert _moved(host, interim) == (308, final)


def test_the_site_languages_address_closes_with_the_first_entry_in_any_language() -> None:
    """The archive of a language without a name answers under the site's
    language's address — so an English entry out first closes the Polish
    address too, or a new Polish name would move a live English archive with
    no 308."""
    world = World("tax-lock-timing")
    host = world.host
    saunas = world.category(world.projects, "Sauny")
    polish = world.entry(world.projects, "sauna-a", categories=(saunas,), out=False)
    world.translated(polish, "en", "sauna-a-en", "Sauna A", categories=(saunas,))
    assert _status(host, "/en/projects/category/sauny/") == 200
    assert world.term(world.projects, saunas)["locked"] == ["pl"]

    assert world.update(world.projects, saunas, name="Sauny ogrodowe").status_code == 200

    assert world.term(world.projects, saunas)["slugs"] == {
        "pl": "sauny",
        "en": "sauny",
        "de": "sauny",
    }
    assert _status(host, "/en/projects/category/sauny/") == 200


def _job_writes(world: World, texts: dict[str, str], *, read: Any = None) -> tuple[Any, str]:
    """A translation job writes site texts in English as the engine would:
    what it read (now, or `read` taken earlier), then its texts, live."""
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    job_ref = f"translation_job:{uuid4()}"
    context = acting_context(context_from_membership(membership), via="ai_translation", ref=job_ref)
    site_id = Site.all_objects.get(pk=world.site_id).id
    with activate_tenant_context(context), translation_policy_override(AUTOMATIC):
        seen = read or SITE_TEXT_SOURCE.read(
            context=context, object_id=site_id, locale="en", basis="published"
        )
        units = {unit.key: unit for unit in seen.units}
        outcomes = SITE_TEXT_SOURCE.write(
            context=context,
            batch=WriteBatch(
                source_key=SITE_TEXT_SOURCE.key,
                scope=seen.scope,
                trigger=Trigger(kind="click", job_ref=job_ref, cause="user"),
                protected="propose",
                items=(
                    WriteItem(
                        object_id=site_id,
                        locale="en",
                        basis="published",
                        basis_version=seen.basis_version,
                        target_version=seen.target_version,
                        texts={
                            key: (
                                text,
                                Provenance(
                                    origin=ORIGIN_AI,
                                    source_hash=units[key].source_hash,
                                    written_hash=unit_hash(units[key].kind, text),
                                    model="test",
                                    at="2026-10-08T12:00:00+00:00",
                                ),
                            )
                            for key, text in texts.items()
                            if key in units
                        },
                        requested="live",
                    ),
                ),
                idempotency_key=f"{job_ref}:1",
            ),
        )
        if any(outcome.state == "live" for outcome in outcomes):
            SITE_TEXT_SOURCE.publish(
                context=context, scope=seen.scope, job_ref=job_ref, idempotency_key=f"{job_ref}:p"
            )
    return outcomes, job_ref


def _read_for_job(world: World) -> Any:
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    context = context_from_membership(membership)
    with activate_tenant_context(context):
        return SITE_TEXT_SOURCE.read(
            context=context,
            object_id=Site.all_objects.get(pk=world.site_id).id,
            locale="en",
            basis="published",
        )


def test_a_translation_job_moves_the_archive_once_and_undoing_it_moves_nothing() -> None:
    world = World("tax-job")
    host = world.host
    bathrooms = world.category(world.projects, "Łazienki")
    polish = world.entry(world.projects, "dom-a", categories=(bathrooms,), tags=("Drewno",))
    world.translated(polish, "en", "house-a", "House A", categories=(bathrooms,), tags=("Drewno",))
    wood = str(ContentTag.all_objects.get(site_id=world.site_id, slug="drewno").id)
    assert _status(host, "/en/projects/category/lazienki/") == 200
    assert _status(host, "/en/projects/tag/drewno/") == 200

    outcomes, job_ref = _job_writes(world, {f"tag/{bathrooms}": "Bathrooms", f"tag/{wood}": "Wood"})

    assert [outcome.state for outcome in outcomes] == ["live"]
    # A category and a tag made today alike: named, moved once, closed.
    _one_hop(host, "/en/projects/category/lazienki/", "/en/projects/category/bathrooms/")
    _one_hop(host, "/en/projects/tag/drewno/", "/en/projects/tag/wood/")
    assert _get(host, "/en/projects/category/bathrooms/").data["title"] == "Category: Bathrooms"
    assert _english(world, bathrooms)["locked"] is True
    # A name typed on an English entry means the tag that answers there.
    other = world.entry(world.projects, "dom-b", out=False)
    english = world.translated(other, "en", "house-b", "House B", out=False)
    assert set_tags(world.client, english, ["Wood"]).json() == [
        {"slug": "drewno", "name": "Drewno"}
    ]
    assert ContentTag.all_objects.filter(site_id=world.site_id, taxonomy__isnull=True).count() == 2

    # Undone: the names go, the addresses search engines may hold stay.
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    context = context_from_membership(membership)
    with activate_tenant_context(context):
        SITE_TEXT_SOURCE.revert(context=context, job_ref=job_ref, idempotency_key=f"{job_ref}:r")
    assert _status(host, "/en/projects/category/bathrooms/") == 200
    assert _moved(host, "/en/projects/category/lazienki/") == (
        308,
        "/en/projects/category/bathrooms/",
    )
    assert _get(host, "/en/projects/category/bathrooms/").data["title"] == "Category: Łazienki"
    assert world.term(world.projects, bathrooms)["names"] == {}


def test_a_term_renamed_or_removed_under_a_running_job_leaves_the_job_settled() -> None:
    """The twin of the gap phase 1 found: a job that carries a term's name
    reads, the term changes, the job writes. The write must come back with an
    answer — the job settles its credits in that transaction — and no address
    may move on a name that is no longer the term's."""
    world = World("tax-job-gap")
    host = world.host
    bathrooms = world.category(world.projects, "Łazienki")
    going = world.category(world.projects, "Do usunięcia")
    polish = world.entry(world.projects, "dom-a", categories=(bathrooms, going))
    world.translated(polish, "en", "house-a", "House A", categories=(bathrooms, going))
    read = _read_for_job(world)
    assert {f"tag/{bathrooms}", f"tag/{going}"} <= {unit.key for unit in read.units}

    # Meanwhile: one renamed, the other taken off its entries and removed.
    assert world.update(world.projects, bathrooms, name="Łazienki i sauny").status_code == 200
    for entry in ContentEntry.all_objects.filter(collection_id=world.projects):
        world.file(str(entry.id), categories=(bathrooms,))
        world.out(str(entry.id))
    assert world.remove(world.projects, going).json()["removed"] is True

    outcomes, _job_ref = _job_writes(
        world, {f"tag/{bathrooms}": "Bathrooms", f"tag/{going}": "Going"}, read=read
    )

    # Answered, not raised: what the job read is no longer what the site says.
    assert [(outcome.state, outcome.reason) for outcome in outcomes] == [
        ("conflict", "source_changed")
    ]
    assert world.term(world.projects, bathrooms)["names"] == {}
    assert _english(world, bathrooms) == {
        "slug": "lazienki",
        "locked": False,
        "path": "/en/projects/category/lazienki/",
    }
    assert _status(host, "/en/projects/category/lazienki/") == 200
    assert not SiteTextTranslation.all_objects.filter(site_id=world.site_id, text="Going").exists()
    # The next read is of the site as it is, and that one lands.
    again, _ref = _job_writes(world, {f"tag/{bathrooms}": "Bathrooms and saunas"})
    assert [outcome.state for outcome in again] == ["live"]
    _one_hop(host, "/en/projects/category/lazienki/", "/en/projects/category/bathrooms-and-saunas/")


# -- one 308 for every former address ------------------------------------------


def _segments(world: World, *, preview: bool = False, **body: Any) -> Any:
    url = f"/api/v1/sites/collections/{world.projects}/category-segments/"
    return _send(
        world.client, "post" if preview else "put", url + ("preview/" if preview else ""), body
    )


def _renamed_world(slug: str) -> tuple[World, str]:
    """„Realizacje” with a category of four entries (three in English), then
    everything an address is made of renamed: the type (`realizacje` →
    `prace`, `projects` → `works`), the category word (`kategoria` → `dzial`,
    `category` → `topic`), the category (`lazienki` → `lazienki-i-spa`,
    English `bathrooms` → `baths`) and one entry's slug."""
    world = World(slug)
    client = world.client
    bathrooms = world.category(world.projects, "Łazienki")
    entries = [
        world.entry(world.projects, f"dom-{mark}", categories=(bathrooms,), tags=("Porady",))
        for mark in ("a", "b", "c", "d")
    ]
    for index, entry_id in enumerate(entries[:3]):
        world.translated(
            entry_id, "en", f"house-{index}", f"House {index}", categories=(bathrooms,)
        )
    assert world.names(world.projects, bathrooms, en="Bathrooms").status_code == 200
    renamed = _send(
        client,
        "put",
        f"/api/v1/sites/collections/{world.projects}/paths/",
        {"base_path": "prace", "locale_paths": {"en": "works", "de": "referenzen"}, "reason": "x"},
    )
    assert renamed.status_code == 200, renamed.json()
    words = _segments(
        world, segment="dzial", locale_segments={"en": "topic", "de": "kategorie"}, reason="x"
    )
    assert words.status_code == 200, words.json()
    for locale, to in (("pl", "lazienki-i-spa"), ("en", "baths")):
        changed = world.address(world.projects, bathrooms, locale=locale, slug=to, reason="x")
        assert changed.status_code == 200, changed.json()
    # What changing an entry's address will write (phase CT4), written here by
    # hand: the resolver reads it already.
    ContentEntry.all_objects.filter(pk=entries[0]).update(former_slugs=["stary-dom"])
    return world, bathrooms


@pytest.mark.parametrize(
    ("asked", "answers"),
    [
        # Each part alone, then together: always one step to today's address.
        ("/realizacje/", "/prace/"),
        ("/realizacje/dom-a/", "/prace/dom-a/"),
        ("/prace/stary-dom/", "/prace/dom-a/"),
        ("/realizacje/stary-dom/", "/prace/dom-a/"),
        ("/prace/kategoria/lazienki-i-spa/", "/prace/dzial/lazienki-i-spa/"),
        ("/prace/dzial/lazienki/", "/prace/dzial/lazienki-i-spa/"),
        ("/realizacje/dzial/lazienki-i-spa/", "/prace/dzial/lazienki-i-spa/"),
        ("/realizacje/kategoria/lazienki/", "/prace/dzial/lazienki-i-spa/"),
        ("/realizacje/kategoria/lazienki/strona/2/", "/prace/dzial/lazienki-i-spa/strona/2/"),
        ("/prace/dzial/lazienki-i-spa/page/2/", "/prace/dzial/lazienki-i-spa/strona/2/"),
        ("/realizacje/tag/porady/", "/prace/tag/porady/"),
        ("/realizacje/tag/porady/strona/2/", "/prace/tag/porady/strona/2/"),
        # English: the interim address, the first English one, the Polish one.
        ("/en/projects/category/lazienki/", "/en/works/topic/baths/"),
        ("/en/projects/category/bathrooms/", "/en/works/topic/baths/"),
        ("/en/works/topic/bathrooms/", "/en/works/topic/baths/"),
        ("/en/works/category/baths/", "/en/works/topic/baths/"),
        ("/en/works/topic/lazienki-i-spa/", "/en/works/topic/baths/"),
        ("/en/projects/category/bathrooms/page/2/", "/en/works/topic/baths/page/2/"),
        ("/en/projects/house-0/", "/en/works/house-0/"),
        # Today's addresses answer; what never was an address answers nothing.
        ("/prace/dzial/lazienki-i-spa/", None),
        ("/en/works/topic/baths/", None),
        ("/prace/dom-a/", None),
        ("/prace/dzial/nic/", 404),
        ("/realizacje/kategoria/nic/", 404),
        ("/realizacje/nie-ma/", 404),
        ("/prace/kategoria/", 404),
        ("/prace/inne/lazienki/", 404),
        ("/en/works/dzial/baths/", 404),
        ("/prace/tag/lazienki/", 404),
        ("/blog/dzial/lazienki-i-spa/", 404),
        ("/prace/dzial/lazienki-i-spa/strona/9/", 404),
        ("/realizacje/kategoria/lazienki/strona/9/", 404),
    ],
)
def test_every_former_address_answers_one_308_to_todays(
    asked: str, answers: str | int | None
) -> None:
    world, _bathrooms = _renamed_world("tax-resolver")
    with override_settings(SITES_ENTRY_INDEX_PAGE_SIZE=2):
        if answers is None:
            assert _status(world.host, asked) == 200
        elif answers == 404:
            assert _moved(world.host, asked) == (404, None)
        else:
            assert isinstance(answers, str)
            _one_hop(world.host, asked, answers)


def test_changing_a_closed_address_takes_a_person_a_reason_and_a_look() -> None:
    world = World("tax-address")
    host = world.host
    bathrooms = world.category(world.projects, "Łazienki")
    kitchens = world.category(world.projects, "Kuchnie")
    world.entry(world.projects, "dom-a", categories=(bathrooms, kitchens))

    # Another category's address is taken, whoever asks.
    taken = world.address(world.projects, bathrooms, locale="pl", slug="kuchnie", reason="x")
    assert _code(taken) == (400, "term_slug_taken")
    preview = world.address(world.projects, bathrooms, preview=True, locale="pl", slug="spa")
    assert preview.status_code == 200, preview.json()
    assert preview.json()["moved"] == [
        {
            "locale": "pl",
            "from_path": "/realizacje/kategoria/lazienki/",
            "to_path": "/realizacje/kategoria/spa/",
        }
    ]
    assert _status(host, "/realizacje/kategoria/lazienki/") == 200
    # An archive visitors can open moves only with a stated reason.
    assert _code(world.address(world.projects, bathrooms, locale="pl", slug="spa")) == (
        400,
        "redirect_reason_required",
    )
    assert (
        world.address(
            world.projects, bathrooms, locale="pl", slug="spa", reason="Nowa oferta"
        ).status_code
        == 200
    )
    _one_hop(host, "/realizacje/kategoria/lazienki/", "/realizacje/kategoria/spa/")

    assert (
        world.address(
            world.projects, bathrooms, locale="pl", slug="wellness", reason="Jeszcze raz"
        ).status_code
        == 200
    )
    # Two former addresses, each one step from today's.
    _one_hop(host, "/realizacje/kategoria/lazienki/", "/realizacje/kategoria/wellness/")
    _one_hop(host, "/realizacje/kategoria/spa/", "/realizacje/kategoria/wellness/")

    # `spa` only redirects now. Code never takes it: a new category of that
    # name gets the next free address and key…
    new = world.category(world.projects, "Spa")
    row = world.term(world.projects, new)
    assert (row["key"], row["slugs"]["pl"]) == ("spa-2", "spa-2")
    _one_hop(host, "/realizacje/kategoria/spa/", "/realizacje/kategoria/wellness/")
    # …and a person takes it only having been told which redirect stops.
    look = world.address(world.projects, new, preview=True, locale="pl", slug="spa")
    assert [item["name"] for item in look.json()["takes_over"]] == ["Łazienki"]
    assert _code(world.address(world.projects, new, locale="pl", slug="spa")) == (
        400,
        "term_slug_former",
    )
    took = world.address(world.projects, new, locale="pl", slug="spa", take_over_former=True)
    assert took.status_code == 200, took.json()
    world.entry(world.projects, "dom-b", categories=(new,))
    # The address is the new category's own now; that redirect is gone, the
    # other one of the old category still leads to it.
    assert _items(_get(host, "/realizacje/kategoria/spa/")) == ["/realizacje/dom-b/"]
    _one_hop(host, "/realizacje/kategoria/lazienki/", "/realizacje/kategoria/wellness/")

    # The word for „category” moves every archive of the type at once.
    look = _segments(world, preview=True, segment="temat", locale_segments={"en": "category"})
    assert look.json()["moved"] == [
        {
            "locale": "pl",
            "from_path": "/realizacje/kategoria/",
            "to_path": "/realizacje/temat/",
        }
    ]
    assert _code(_segments(world, segment="temat", locale_segments={})) == (
        400,
        "redirect_reason_required",
    )
    for word, code in (
        ("tag", "taxonomy_segment_reserved"),
        ("strona", "taxonomy_segment_reserved"),
    ):
        assert _code(_segments(world, segment=word, locale_segments={}, reason="x")) == (400, code)
    assert _segments(world, segment="temat", locale_segments={}, reason="Krócej").status_code == 200
    _one_hop(host, "/realizacje/kategoria/wellness/", "/realizacje/temat/wellness/")
    _one_hop(host, "/realizacje/kategoria/lazienki/", "/realizacje/temat/wellness/")
    _one_hop(host, "/realizacje/kategoria/spa/", "/realizacje/temat/spa/")
    # A type without categories has no word to change.
    blog_words = _send(
        world.client,
        "put",
        f"/api/v1/sites/collections/{world.blog_id}/category-segments/",
        {"segment": "temat", "locale_segments": {}},
    )
    assert _code(blog_words) == (404, "taxonomy_not_found")


def test_a_tag_older_than_addresses_per_language_keeps_its_key_everywhere() -> None:
    world = World("tax-legacy")
    host = world.host
    tips = ContentTag.all_objects.get(site_id=world.site_id, slug="porady")
    # As the migration leaves every tag that was there before it.
    ContentTag.all_objects.filter(pk=tips.pk).update(slug_locked_at=LEGACY_TERM_LOCK)
    entry = world.entry(world.projects, "dom-a", tags=("Porady",))
    world.translated(entry, "en", "house-a", "House A", tags=("Porady",))

    named = world.names(world.projects, str(tips.id), en="Tips")

    assert named.status_code == 200, named.json()
    assert named.json()["moved"] == []
    row = world.term(world.projects, str(tips.id), "tags")
    assert row["slugs"] == {"pl": "porady", "en": "porady", "de": "porady"}
    assert row["locked"] == ["pl", "en", "de"]
    assert _get(host, "/en/projects/tag/porady/").data["title"] == "Entries tagged: Tips"
    assert _status(host, "/en/projects/tag/tips/") == 404
    # A person may still move it, deliberately.
    moved = world.address(
        world.projects, str(tips.id), locale="en", slug="tips", reason="Po angielsku"
    )
    assert moved.status_code == 200, moved.json()
    _one_hop(host, "/en/projects/tag/porady/", "/en/projects/tag/tips/")
    assert _status(host, "/realizacje/tag/porady/") == 200


def test_a_term_is_removed_only_when_nothing_carries_it() -> None:
    world = World("tax-delete")
    host = world.host
    interiors = world.category(world.projects, "Wnętrza")
    bathrooms = world.category(world.projects, "Łazienki", interiors)
    small = world.category(world.projects, "Małe", bathrooms)
    entry = world.entry(world.projects, "dom-a", categories=(bathrooms,))

    held = world.remove(world.projects, bathrooms, preview=True).json()
    assert (held["removable"], held["drafts"], held["published"], held["children"]) == (
        False,
        1,
        1,
        1,
    )
    assert _code(world.remove(world.projects, bathrooms)) == (409, "term_in_use")
    # Off the draft is not off the site: the publication still carries it.
    world.file(entry, categories=())
    held = world.remove(world.projects, bathrooms, preview=True).json()
    assert (held["removable"], held["drafts"], held["published"]) == (False, 0, 1)
    assert _code(world.remove(world.projects, bathrooms)) == (409, "term_in_use")
    assert _status(host, "/realizacje/kategoria/lazienki/") == 200
    world.out(entry)
    assert _status(host, "/realizacje/kategoria/lazienki/") == 404

    gone = world.remove(world.projects, bathrooms)

    assert gone.status_code == 200, gone.json()
    assert (gone.json()["removed"], gone.json()["children"]) == (True, 1)
    # What lay under it moved one level up.
    rows = {item["name"]: item for item in world.terms(world.projects)["terms"]}
    assert set(rows) == {"Wnętrza", "Małe"}
    assert (rows["Małe"]["parent_id"], rows["Małe"]["depth"]) == (interiors, 2)
    assert world.remove(world.projects, small).status_code == 200
    assert world.remove(world.projects, small).status_code == 404
    # A tag of the site is held by any type's entries.
    tips = str(ContentTag.all_objects.get(site_id=world.site_id, slug="porady").id)
    assert _code(world.remove(world.projects, tips)) == (409, "term_in_use")
    row = world.term(world.projects, tips, "tags")
    assert (row["entries"], row["entries_elsewhere"], row["removable"]) == (0, 1, False)


def test_only_a_person_manages_terms_and_nobody_reaches_another_company() -> None:
    """A name and a place in the tree show to visitors at once, so an
    integration's key — in any mode — and the assistant manage no term.
    Filing an entry stays the entry's business: it shows with the entry's
    publication, which under `proposed` is a person's."""
    from saas_core.modules.core.organizations.context import require_tenant_context
    from saas_core.modules.core.organizations.person_gate import PersonRequired
    from saas_core.modules.shared.sites import taxonomies
    from test_sites_collections import _automation, _grant

    world = World("tax-people")
    bathrooms = world.category(world.projects, "Łazienki")
    kitchens = world.category(world.projects, "Kuchnie")
    entry = world.entry(world.projects, "dom-a", categories=(bathrooms,), tags=("Porady",))
    host = world.host
    assert _status(host, "/realizacje/kategoria/lazienki/") == 200
    assert _status(host, "/realizacje/kategoria/kuchnie/") == 404
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    person = context_from_membership(membership)
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid4()}")
    keys = []
    for mode in ("draft_write", "publish_with_approval", "autonomous"):
        key_id = uuid4()
        # The widest a key gets: the whole site.
        _grant(
            world.organization_id,
            key_id,
            person.actor_id,
            collection_id=None,
            site_id=world.site_id,
            mode=mode,
            # An autonomous grant is bounded, or the database refuses it.
            expires_at=timezone.now() + timedelta(days=7),
            max_changes_per_day=50,
            max_payload_bytes=100_000,
        )
        keys.append(_automation(world.organization_id, person.actor_id, key_id))
    audits = OrganizationAuditEntry.objects.filter(organization_id=world.organization_id).count()
    for context in (*keys, assistant):
        with activate_tenant_context(context):
            assert require_tenant_context() is context
            for kind, name in (("categories", "Salony"), ("tags", "Nowy")):
                with pytest.raises(PersonRequired):
                    taxonomies.create_term(collection_id=world.projects, kind=kind, name=name)
            for dry_run in (True, False):
                with pytest.raises(PersonRequired):
                    taxonomies.update_term(
                        term_id=bathrooms,
                        collection_id=world.projects,
                        name="Cudze",
                        dry_run=dry_run,
                    )
                with pytest.raises(PersonRequired):
                    taxonomies.update_term(
                        term_id=bathrooms,
                        collection_id=world.projects,
                        parent_id=kitchens,
                        dry_run=dry_run,
                    )
            with pytest.raises(PersonRequired):
                taxonomies.set_term_names(
                    term_id=bathrooms, collection_id=world.projects, names={"en": "Theirs"}
                )
            with pytest.raises(PersonRequired):
                taxonomies.change_term_address(
                    term_id=bathrooms, collection_id=world.projects, locale="pl", slug="inne"
                )
            with pytest.raises(PersonRequired):
                taxonomies.delete_term(term_id=kitchens, collection_id=world.projects)
            with pytest.raises(PersonRequired):
                taxonomies.set_taxonomy_segments(
                    collection_id=world.projects, segment="temat", locale_segments={}
                )
    row = ContentTag.all_objects.get(pk=bathrooms)
    assert (row.name, row.parent_id, row.locale_slugs) == ("Łazienki", None, {})
    assert not ContentTag.all_objects.filter(site_id=world.site_id, name__in=["Salony", "Nowy"])
    assert (
        OrganizationAuditEntry.objects.filter(organization_id=world.organization_id).count()
        == audits
    )

    # Filing is the entry's: a key hired for a type that takes drafts files
    # the entry — and no visitor sees it until the entry is published again.
    ContentCollection.all_objects.filter(pk=world.projects).update(automation_policy="proposed")
    with activate_tenant_context(keys[0]):
        filed = taxonomies.set_entry_categories(entry_id=entry, term_ids=[kitchens])  # type: ignore[arg-type,list-item]
        assert [term.name for term in filed] == ["Kuchnie"]
        tagged = taxonomies.set_entry_tags(entry_id=entry, names=["Inspiracje"])  # type: ignore[arg-type]
        assert [tag.name for tag in tagged] == ["Inspiracje"]
    for path, status in (
        ("/realizacje/kategoria/lazienki/", 200),
        ("/realizacje/kategoria/kuchnie/", 404),
        ("/realizacje/tag/porady/", 200),
        ("/realizacje/tag/inspiracje/", 404),
    ):
        assert _status(host, path) == status, path
    assert "kuchnie" not in _sitemap(host)
    # A type a person keeps for themselves takes no filing from a key either.
    ContentCollection.all_objects.filter(pk=world.projects).update(automation_policy="manual")
    with activate_tenant_context(keys[0]), pytest.raises(Exception) as refused:
        taxonomies.set_entry_categories(entry_id=entry, term_ids=[bathrooms])  # type: ignore[arg-type,list-item]
    assert getattr(refused.value, "status_code", None) == 403
    # The person publishes: now it shows.
    assert publish(world.client, entry, idempotency_key="again").status_code == 201
    assert _status(host, "/realizacje/kategoria/kuchnie/") == 200
    assert _status(host, "/realizacje/kategoria/lazienki/") == 404
    assert _status(host, "/realizacje/tag/inspiracje/") == 200

    stranger = World("tax-people-other")
    for response in (
        stranger.client.get(f"/api/v1/sites/collections/{world.projects}/terms/"),
        stranger.update(world.projects, bathrooms, name="Cudze"),
        stranger.names(world.projects, bathrooms, en="Theirs"),
        stranger.remove(world.projects, bathrooms),
        stranger.update(stranger.projects, bathrooms, name="Cudze"),
    ):
        assert response.status_code == 404, response.json()
    assert ContentTag.all_objects.get(pk=bathrooms).name == "Łazienki"
    assert ContentTaxonomy.all_objects.filter(organization_id=stranger.organization_id).count() == 0


# -- locks: one order for every writer of terms --------------------------------


def test_every_writer_takes_the_rows_of_terms_in_one_order() -> None:
    """A publication locks the terms it carries and a change of the
    vocabulary locks terms too; taken in different orders the two would wait
    on each other, and the database would end one — maybe the publication,
    maybe a translation job's write. Proven by the statements, not by
    threads: every change of the vocabulary takes the site's whole
    vocabulary by id in its first lock, a publication takes what it carries
    by id in one, and filing an entry takes no term's row at all."""
    world = World("tax-locks")
    bathrooms = world.category(world.projects, "Łazienki")
    small = world.category(world.projects, "Małe", bathrooms)
    spare = world.category(world.projects, "Zbędne")
    entry = world.entry(world.projects, "dom-a", categories=(small,), tags=("Porady",), out=False)
    terms_url = f"/api/v1/sites/collections/{world.projects}/terms/"

    def locks(act: Any) -> list[str]:
        with CaptureQueriesContext(connection) as queries:
            response = act()
        assert response.status_code in (200, 201, 204), response.content
        return [
            query["sql"]
            for query in queries.captured_queries
            if 'FROM "sites_contenttag"' in query["sql"] and " FOR " in query["sql"]
        ]

    by_id = 'ORDER BY "sites_contenttag"."id" ASC'
    for name, act in (
        ("rename", lambda: world.update(world.projects, bathrooms, name="Łazienki i spa")),
        ("move", lambda: world.update(world.projects, spare, parent_id=bathrooms)),
        ("names", lambda: world.names(world.projects, bathrooms, en="Baths")),
        ("category", lambda: _send(world.client, "post", terms_url, {"name": "Kuchnie"})),
        (
            "tag",
            lambda: _send(world.client, "post", terms_url, {"kind": "tags", "name": "Nowy"}),
        ),
        ("address", lambda: world.address(world.projects, small, locale="pl", slug="male-2")),
        ("remove", lambda: world.remove(world.projects, spare)),
    ):
        taken = locks(act)
        assert taken, name
        for sql in taken:
            where = sql.split(" WHERE ", 1)[1].split(" ORDER BY ", 1)[0]
            assert "FOR NO KEY UPDATE" in sql and by_id in sql, (name, sql)
            # The whole site's, not one namespace's and not one row's.
            assert '"taxonomy_id"' not in where and '"sites_contenttag"."id" ' not in where, (
                name,
                sql,
            )
            assert '"sites_contenttag"."site_id" = ' in where, (name, sql)

    # Filing takes no term's row: it holds the entry's, which a publication
    # takes before its terms.
    assert locks(lambda: set_tags(world.client, entry, ["Porady", "Inspiracje"])) == []
    assert (
        locks(
            lambda: _send(
                world.client,
                "put",
                f"/api/v1/sites/entries/{entry}/categories/",
                {"term_ids": [small]},
            )
        )
        == []
    )
    # A publication: what it carries and the categories above, by id, at once.
    taken = locks(lambda: publish(world.client, entry, idempotency_key="out"))
    assert len(taken) == 1, taken
    assert "FOR NO KEY UPDATE" in taken[0] and by_id in taken[0], taken
    assert '"sites_contenttag"."id" IN (' in taken[0].split(" WHERE ", 1)[1], taken
    # Its categories' addresses closed with it: the stamp followed the lock.
    assert ContentTag.all_objects.get(pk=small).slug_locked_at.get("pl")
    assert ContentTag.all_objects.get(pk=bathrooms).slug_locked_at.get("pl")


# -- row-level security: the order of the statements ---------------------------


def test_a_visitors_reads_of_terms_set_the_tenant_the_host_named_first() -> None:
    """The test database bypasses RLS; on the stack `sites_contenttag` and
    `sites_contenttaxonomy` answer nothing until the tenant is set, and an
    archive would be a 404 there with every test green. The order of the
    statements is what proves it here — for each public read of either."""
    world, _bathrooms = _renamed_world("tax-rls")
    host = world.host
    for path, status in (
        ("/prace/dzial/lazienki-i-spa/", 200),
        ("/en/works/topic/baths/", 200),
        ("/prace/tag/porady/", 200),
        ("/prace/dom-a/", 200),
        ("/en/works/house-0/", 200),
        ("/realizacje/kategoria/lazienki/", 308),
        ("/en/projects/category/bathrooms/", 308),
        ("/prace/dzial/nic/", 404),
    ):
        with CaptureQueriesContext(connection) as queries:
            assert _status(host, path) == status, path
        statements = [query["sql"] for query in queries.captured_queries]
        for table in ("sites_contenttag", "sites_contenttaxonomy"):
            verdicts = _tenant_set_before(statements, table)
            assert all(verdicts), (path, table, verdicts)
        assert _tenant_set_before(statements, "sites_contenttag"), path
    with CaptureQueriesContext(connection) as queries:
        assert "/prace/dzial/lazienki-i-spa/" in _sitemap(host)
    statements = [query["sql"] for query in queries.captured_queries]
    for table in ("sites_contenttag", "sites_contenttaxonomy"):
        verdicts = _tenant_set_before(statements, table)
        assert verdicts and all(verdicts), (table, verdicts)


# -- the migration -------------------------------------------------------------


def test_the_migration_closes_every_existing_tag_at_its_key_and_walks_back() -> None:
    """Schema only, with database defaults: a tag older than the columns — or
    written by code older than them, between `migrate` and the restart —
    reads as closed at its key in every language. On the way back categories
    go first; left in the table they would read as the site's tags."""
    from django.db.migrations.executor import MigrationExecutor

    world = World("tax-migration")
    category = world.category(world.projects, "Kategoria")
    entry = world.entry(world.projects, "dom-a", categories=(category,), tags=("Stary",))
    executor = MigrationExecutor(connection)
    name = next(
        found
        for app, found in executor.loader.disk_migrations
        if app == "sites" and found.endswith("_content_taxonomies")
    )
    migration = executor.loader.disk_migrations[("sites", name)]
    before = next(parent for parent in migration.dependencies if parent[0] == "sites")
    with connection.cursor() as cursor:
        # Fire the deferred FK checks now; PostgreSQL refuses ALTER TABLE on a
        # table with pending trigger events.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    executor.migrate([before])

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_name = 'sites_contenttaxonomy'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'sites_contenttag'"
            " AND column_name IN ('taxonomy_id', 'parent_id', 'slug_locked_at', 'locale_slugs')"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT slug FROM sites_contenttag WHERE site_id = %s", [world.site_id])
        assert {row[0] for row in cursor.fetchall()} == {"porady", "stary"}
        cursor.execute("SELECT count(*) FROM sites_contententrytag WHERE entry_id = %s", [entry])
        assert cursor.fetchone()[0] == 1
        # Both tables force row-level security again.
        cursor.execute(
            "SELECT relname, relforcerowsecurity FROM pg_class"
            " WHERE relname IN ('sites_contenttag', 'sites_contententrytag')"
        )
        assert dict(cursor.fetchall()) == {"sites_contenttag": True, "sites_contententrytag": True}

    executor = MigrationExecutor(connection)
    executor.migrate([("sites", name)])

    with connection.cursor() as cursor:
        # Written the way code older than the columns writes a tag.
        cursor.execute(
            "INSERT INTO sites_contenttag"
            " (id, organization_id, site_id, slug, name, created_by_id, created_at, updated_at)"
            " SELECT gen_random_uuid(), organization_id, site_id, 'pozny', 'Późny',"
            " created_by_id, now(), now() FROM sites_contenttag WHERE slug = 'stary'"
        )
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'sites_contenttaxonomy'"
        )
        assert cursor.fetchone() == (True, True)
    tags = {tag.slug: tag for tag in ContentTag.all_objects.filter(site_id=world.site_id)}
    assert set(tags) == {"porady", "stary", "pozny"}
    for tag in tags.values():
        assert tag.slug_locked_at == LEGACY_TERM_LOCK, tag.slug
        assert (tag.locale_slugs, tag.former_slugs, tag.position) == ({}, [], 0)
        assert (tag.taxonomy_id, tag.parent_id) == (None, None)
    assert ContentEntry.all_objects.get(pk=entry).former_slugs == []


def test_a_types_former_name_is_never_taken_quietly() -> None:
    """A name a type used to have leads to it, with everything under it.
    Code never takes such a name; a person does, having been told which
    redirects stop — and then they stop (ADR-079 pkt 14)."""
    from rest_framework.exceptions import ValidationError

    from saas_core.modules.shared.sites import collections
    from test_sites_collections import _automation, _grant

    world = World("tax-former-type")
    client, host = world.client, world.host
    world.entry(world.projects, "dom-a", tags=("Porady",))
    paths = f"/api/v1/sites/collections/{world.projects}/paths/"
    names = {"en": "projects", "de": "referenzen"}
    renamed = _send(
        client, "put", paths, {"base_path": "prace", "locale_paths": names, "reason": "Krócej"}
    )
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["takes_over"] == []
    _one_hop(host, "/realizacje/dom-a/", "/prace/dom-a/")
    _one_hop(host, "/realizacje/tag/porady/", "/prace/tag/porady/")

    new_type = {"key": "galeria", "name": "Galeria", "kind": "blog", "base_path": "realizacje"}
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    person = context_from_membership(membership)
    key_id = uuid4()
    _grant(
        world.organization_id,
        key_id,
        person.actor_id,
        collection_id=None,
        site_id=world.site_id,
        mode="draft_write",
    )
    key = _automation(world.organization_id, person.actor_id, key_id)
    with activate_tenant_context(key), pytest.raises(ValidationError) as refused:
        collections.create_collection(
            site_id=world.site_id,  # type: ignore[arg-type]
            **new_type,
            idempotency_key="by-a-key",
            take_over_former=True,
        )
    assert refused.value.get_codes() == {"base_path": ["section_path_former"]}

    def make(**more: Any) -> Any:
        return client.post(
            f"/api/v1/sites/{world.site_id}/collections/",
            {**new_type, **more},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=f"gallery-{len(more)}",
        )

    told = make()
    assert _code(told) == (400, "section_path_former")
    assert "/realizacje/" in told.json()["errors"][0]["message"]
    assert "Realizacje" in told.json()["errors"][0]["message"]
    _one_hop(host, "/realizacje/tag/porady/", "/prace/tag/porady/")

    made = make(take_over_former=True)

    assert made.status_code == 201, made.json()
    gallery = str(made.json()["id"])
    # The name is the new type's; what it used to lead to is no longer there.
    assert _status(host, "/realizacje/") == 200
    assert _moved(host, "/realizacje/tag/porady/") == (404, None)
    assert _moved(host, "/realizacje/strona/2/") == (404, None)
    # An entry's own first address still leads to it (ADR-071) — until the
    # new type publishes something there.
    _one_hop(host, "/realizacje/dom-a/", "/prace/dom-a/")
    assert not ContentTaxonomy.all_objects.filter(organization_id=world.organization_id).exists()

    # Renaming says beforehand which redirects would stop, in every language
    # the name served, and saves only on the person's word.
    moved_on = _send(
        client,
        "put",
        f"/api/v1/sites/collections/{gallery}/paths/",
        {"base_path": "galeria", "locale_paths": {}, "reason": "Inaczej"},
    )
    assert moved_on.status_code == 200, moved_on.json()
    back = {"base_path": "realizacje", "locale_paths": names, "reason": "Jednak"}
    look = _send(client, "post", paths + "preview/", back)
    assert [(item["path"], item["name"]) for item in look.json()["takes_over"]] == [
        ("/realizacje/", "Galeria"),
        ("/en/realizacje/", "Galeria"),
        ("/de/realizacje/", "Galeria"),
    ]
    assert _code(_send(client, "put", paths, back)) == (400, "section_path_former")
    assert _send(client, "put", paths, {**back, "take_over_former": True}).status_code == 200
    assert _status(host, "/realizacje/dom-a/") == 200
    _one_hop(host, "/prace/dom-a/", "/realizacje/dom-a/")
