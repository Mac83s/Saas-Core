"""Changing an entry's address (ADR-079 pkt 13, 14, 16; „Uzupełnienie CT4”).

The slug an entry had answers one 308 to today's address — also under a name
its type had, in any language, never through a second address — a published
entry goes out again with what is public, not with its draft, and a former
slug never shadows an entry that answers."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditEntry
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.sites.entry_addresses import change_entry_slug, former_slug_owners
from saas_core.modules.shared.sites.entry_translation_source import free_entry_slug
from saas_core.modules.shared.sites.models import (
    ContentEntry,
    ContentEntryPublication,
    ContentEntryTag,
    Site,
)
from saas_core.modules.shared.sites.publication_routing import PublicSiteNotFound, _find_entry
from test_sites_api import automation_context, csrf_value
from test_sites_blog_languages import Blog, _feed, _get
from test_sites_collections import create_entry, publish, save_entry_draft
from test_sites_content_reads import Publisher, _category, _filed, _read
from test_sites_section_addresses import _errors, _rename
from test_sites_taxonomies import World, _moved, _one_hop, _renamed_world, _send, _status

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def a_company_in_three_languages(settings: Any) -> None:
    """As the taxonomy tests start: Polish, English and German, and a
    platform that offers a second content type."""
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    settings.CONTENT_TYPES_OFFERED = True


def _address(client: Any, entry_id: str, *, preview: bool = False, **body: Any) -> Any:
    url = f"/api/v1/sites/entries/{entry_id}/address/"
    return _send(client, "post" if preview else "put", url + ("preview/" if preview else ""), body)


def _entry(entry_id: str) -> ContentEntry:
    return ContentEntry.all_objects.select_related("current_publication").get(pk=entry_id)


def _entry_site(blog: Blog) -> Site:
    return Site.all_objects.get(pk=blog.site_id)


def _text_of(response: Any) -> str:
    return str(response.data["blocks"][0]["data"]["text"])


def _answers_with(host: str, path: str) -> str:
    """The title of the entry that answers at `path`."""
    response = _get(host, path)
    assert response.status_code == 200, path
    return str(response.data["article"]["title"])


def test_a_published_entry_moves_with_one_308_and_its_draft_stays_a_draft() -> None:
    blog = Blog("address-change")
    client, host, entry_id = blog.client, blog.host, blog.polish
    # The type was renamed first: its former name must lead to the entry's
    # new address in the same single step.
    assert _rename(blog, "poradnik", reason="Polish name").status_code == 200
    before = _entry(entry_id)
    assert before.current_publication is not None
    public_before = _get(host, "/poradnik/wpis-jeden/")
    assert public_before.status_code == 200
    # Work in progress: a new text and a new title nobody published.
    saved = save_entry_draft(
        client, entry_id, expected_version=1, text="Niewydana poprawka.", idempotency_key="wip"
    )
    assert saved.status_code == 201, saved.data
    retitled = _send(
        client, "patch", f"/api/v1/sites/entries/{entry_id}/metadata/", {"title": "Nowy tytuł"}
    )
    assert retitled.status_code == 200, retitled.data

    preview = _address(client, entry_id, preview=True, slug="pierwszy-wpis")
    assert preview.status_code == 200, preview.data
    assert preview.data["changed"] is True
    assert preview.data["published"] is True
    assert preview.data["unpublished_changes"] is True
    assert preview.data["path"] == "/poradnik/pierwszy-wpis/"
    assert preview.data["moved"] == [
        {"from_path": "/poradnik/wpis-jeden/", "to_path": "/poradnik/pierwszy-wpis/"}
    ]
    assert preview.data["redirects"] == preview.data["moved"]
    assert preview.data["takes_over"] == []
    # A preview saves nothing.
    assert _entry(entry_id).slug == "wpis-jeden"
    assert _status(host, "/poradnik/wpis-jeden/") == 200

    # An address visitors can open moves only with a reason.
    refused = _address(client, entry_id, slug="pierwszy-wpis")
    assert refused.status_code == 400
    assert _errors(refused) == [("reason", "redirect_reason_required")]
    for bad in ("Pierwszy Wpis", "a--b", "-a", "ąę", "x" * 121):
        invalid = _address(client, entry_id, slug=bad, reason="x")
        assert invalid.status_code == 400, bad

    done = _address(client, entry_id, slug="pierwszy-wpis", reason="Lepszy adres")
    assert done.status_code == 200, done.data
    assert done.data["changed"] is True

    # The new address answers with what was public — not with the draft.
    public_after = _get(host, "/poradnik/pierwszy-wpis/")
    assert public_after.status_code == 200
    assert _text_of(public_after) == _text_of(public_before) != "Niewydana poprawka."
    assert public_after.data["title"] == public_before.data["title"] != "Nowy tytuł"
    assert (
        public_after.data["article"]["published_at"]
        == public_before.data["article"]["published_at"]
    )
    # The text did not change, so neither did its `changed` date.
    assert public_after.data["article"]["updated_at"] == public_before.data["article"]["updated_at"]
    after = _entry(entry_id)
    assert after.current_publication is not None
    assert (after.slug, after.former_slugs) == ("pierwszy-wpis", ["wpis-jeden"])
    assert after.current_publication.snapshot["slug"] == "pierwszy-wpis"
    assert (
        after.current_publication.snapshot["version"]
        == before.current_publication.snapshot["version"]
    )
    assert (
        after.current_publication.snapshot["blocks"]
        == before.current_publication.snapshot["blocks"]
    )
    # The draft is still ahead of the publication, untouched.
    draft = client.get(f"/api/v1/sites/entries/{entry_id}/draft/")
    assert draft.data["version"] == 2
    assert _entry(entry_id).title == "Nowy tytuł"

    # One 308 from every address the entry ever had — also under the type's
    # former name — and never a second hop.
    _one_hop(host, "/poradnik/wpis-jeden/", "/poradnik/pierwszy-wpis/")
    _one_hop(host, "/blog/wpis-jeden/", "/poradnik/pierwszy-wpis/")
    _one_hop(host, "/blog/pierwszy-wpis/", "/poradnik/pierwszy-wpis/")
    # The lists and the sitemap name today's address only.
    assert "/poradnik/pierwszy-wpis/" in _feed(host, "sitemap.xml").content.decode()
    assert "wpis-jeden" not in _feed(host, "sitemap.xml").content.decode()
    rss = _feed(host, "feed.xml")
    assert rss.status_code == 200 and "pierwszy-wpis" in rss.content.decode()
    assert "wpis-jeden" not in rss.content.decode()

    # The history says who moved what, and why.
    audit = OrganizationAuditEntry.objects.filter(
        action="sites.entry.address_changed", target_id=str(entry_id)
    ).get()
    assert audit.metadata["from"] == "wpis-jeden"
    assert audit.metadata["to"] == "pierwszy-wpis"
    assert audit.metadata["reason"] == "Lepszy adres"
    assert audit.metadata["republished"] is True
    republished = ContentEntryPublication.all_objects.filter(entry_id=entry_id).order_by("sequence")
    assert [item.sequence for item in republished] == [1, 2]

    # The same slug again changes nothing and publishes nothing.
    same = _address(client, entry_id, slug="pierwszy-wpis")
    assert (same.status_code, same.data["changed"]) == (200, False)
    assert ContentEntryPublication.all_objects.filter(entry_id=entry_id).count() == 2
    # A second move: the first slug leads to the third, never through the second.
    assert _address(client, entry_id, slug="trzeci", reason="Jeszcze lepszy").status_code == 200
    _one_hop(host, "/blog/wpis-jeden/", "/poradnik/trzeci/")
    _one_hop(host, "/poradnik/pierwszy-wpis/", "/poradnik/trzeci/")
    # Taking a slug back makes it the entry's again, not a former one.
    assert _address(client, entry_id, slug="wpis-jeden", reason="Wracamy").status_code == 200
    assert _status(host, "/poradnik/wpis-jeden/") == 200
    assert _entry(entry_id).former_slugs == ["pierwszy-wpis", "trzeci"]
    shown = client.get(f"/api/v1/sites/entries/{entry_id}/address/")
    assert shown.status_code == 200
    assert [item["from_path"] for item in shown.data["redirects"]] == [
        "/poradnik/pierwszy-wpis/",
        "/poradnik/trzeci/",
    ]


def test_an_entry_moved_after_everything_else_was_renamed_answers_in_one_step() -> None:
    """A type renamed, its category word and a category renamed, and then an
    entry's address changed — in the site's language and in English: every
    older address of the entry and of the archive is one 308."""
    world, _bathrooms = _renamed_world("address-everything")
    host = world.host
    english = ContentEntry.all_objects.get(site_id=world.site_id, locale="en", slug="house-1")
    polish = ContentEntry.all_objects.get(site_id=world.site_id, locale="pl", slug="dom-b")
    assert _address(world.client, str(english.id), slug="lake-house", reason="x").status_code == 200
    assert _address(world.client, str(polish.id), slug="dom-nad-jeziorem", reason="x").status_code
    for asked, answers in (
        # The entry: former slug, under the type's former and today's name.
        ("/en/projects/house-1/", "/en/works/lake-house/"),
        ("/en/works/house-1/", "/en/works/lake-house/"),
        ("/en/projects/lake-house/", "/en/works/lake-house/"),
        ("/realizacje/dom-b/", "/prace/dom-nad-jeziorem/"),
        ("/prace/dom-b/", "/prace/dom-nad-jeziorem/"),
        # The archive it is listed in: all three renames at once.
        ("/en/projects/category/bathrooms/", "/en/works/topic/baths/"),
        ("/realizacje/kategoria/lazienki/", "/prace/dzial/lazienki-i-spa/"),
        # The slug written by hand in CT2's fixture still answers.
        ("/realizacje/stary-dom/", "/prace/dom-a/"),
    ):
        _one_hop(host, asked, answers)
    # A slug of one language is not an address in another.
    assert _moved(host, "/prace/house-1/") == (404, None)
    assert _moved(host, "/en/works/dom-b/") == (404, None)
    # The language versions name each other's new addresses.
    page = _get(host, "/en/works/lake-house/")
    assert page.status_code == 200
    # The language switched off: an old English address goes straight to the
    # Polish article's address of today.
    organization = Organization.objects.get(pk=world.organization_id)
    Organization.objects.filter(pk=organization.pk).update(public_locales=["pl"])
    assert _moved(host, "/en/projects/house-1/") == (308, "/prace/dom-nad-jeziorem/")


def test_a_former_slug_is_taken_only_by_a_person_who_saw_what_stops() -> None:
    blog = Blog("address-takeover")
    client, host = blog.client, blog.host
    first = blog.polish
    assert _address(client, first, slug="nowy-adres", reason="x").status_code == 200
    # The old slug redirects: a new entry cannot start under it…
    refused = create_entry(client, blog.collection_id, slug="wpis-jeden", idempotency_key="again")
    assert refused.status_code == 400
    assert _errors(refused) == [("slug", "entry_slug_former")]
    # …and a slug made by code keeps clear of it.
    other = create_entry(client, blog.collection_id, slug="drugi", idempotency_key="second")
    second = str(other.data["id"])
    assert free_entry_slug(_entry(second), "pl", "wpis-jeden") == "wpis-jeden-2"
    assert free_entry_slug(_entry(second), "pl", "nowy-adres") == "nowy-adres-2"
    # A slug another entry answers under is never available.
    taken = _address(client, second, slug="nowy-adres")
    assert _errors(taken) == [("slug", "entry_slug_taken")]

    save_entry_draft(client, second, expected_version=0, text="Drugi.", idempotency_key="d2")
    assert publish(client, second, idempotency_key="p2").status_code == 201
    preview = _address(client, second, preview=True, slug="wpis-jeden")
    assert preview.status_code == 200
    assert preview.data["takes_over"] == [
        {"slug": "wpis-jeden", "entry_id": first, "title": _entry(first).title}
    ]
    unconfirmed = _address(client, second, slug="wpis-jeden", reason="x")
    assert _errors(unconfirmed) == [("slug", "entry_slug_former")]
    assert _moved(host, "/blog/wpis-jeden/") == (308, "/blog/nowy-adres/")

    taken_over = _address(
        client,
        second,
        slug="wpis-jeden",
        reason="Ten adres należy się temu wpisowi",
        **{"take_over_former": True},
    )
    assert taken_over.status_code == 200, taken_over.data
    # The address answers the entry that took it; the first entry's redirect
    # from it is gone, and its own address is what it was.
    assert _answers_with(host, "/blog/wpis-jeden/") == _entry(second).title
    assert _entry(first).former_slugs == []
    assert _status(host, "/blog/nowy-adres/") == 200
    _one_hop(host, "/blog/drugi/", "/blog/wpis-jeden/")


def test_a_former_slug_never_shadows_an_entry_that_answers() -> None:
    """Whatever the rows say — here two of them disagree, written by hand —
    an address an entry answers under leads to that entry."""
    blog = Blog("address-live-wins")
    client, host = blog.client, blog.host
    other = create_entry(client, blog.collection_id, slug="zywy", idempotency_key="live")
    live = str(other.data["id"])
    save_entry_draft(client, live, expected_version=0, text="Żywy.", idempotency_key="dl")
    assert publish(client, live, idempotency_key="pl").status_code == 201
    ContentEntry.all_objects.filter(pk=blog.polish).update(former_slugs=["zywy"])
    assert _answers_with(host, "/blog/zywy/") == _entry(live).title
    assert _rename(blog, "poradnik", reason="x").status_code == 200
    # Under the type's former name too: the entry that answers, in one step.
    _one_hop(host, "/blog/zywy/", "/poradnik/zywy/")
    assert _answers_with(host, "/poradnik/zywy/") == _entry(live).title


def test_an_entry_named_like_a_part_of_an_archives_address_shadows_nothing() -> None:
    """An entry answers two segments under its type, an archive and a later
    page of a list three: an entry — or a former slug — called „kategoria”,
    „tag”, „strona”, „category”, „page” or like a feed takes no address from
    them, in any language. So no slug of an entry is reserved (ADR-079,
    „Adresy”), and this is what holds that."""
    world = World("address-reserved")
    host, client = world.host, world.client
    bathrooms = world.category(world.projects, "Łazienki")
    assert world.names(world.projects, bathrooms, en="Bathrooms").status_code == 200
    plain = [
        world.entry(world.projects, f"dom-{mark}", categories=(bathrooms,), tags=("Porady",))
        for mark in ("a", "b", "c")
    ]
    world.translated(plain[0], "en", "house-a", "House A", categories=(bathrooms,))
    named = {
        slug: world.entry(world.projects, slug, categories=(bathrooms,), tags=("Porady",))
        for slug in ("kategoria", "tag", "strona", "rss", "sitemap", "2")
    }
    english = {
        slug: world.translated(
            named[source], "en", slug, slug.title(), categories=(bathrooms,), tags=("Porady",)
        )
        for slug, source in (("category", "kategoria"), ("page", "strona"), ("tag", "tag"))
    }

    def is_entry(path: str) -> bool:
        response = _get(host, path)
        assert response.status_code == 200, (path, response.status_code)
        return bool(response.data.get("article"))

    with override_settings(SITES_ENTRY_INDEX_PAGE_SIZE=2):
        # Every entry answers at its own address…
        for slug in named:
            assert is_entry(f"/realizacje/{slug}/"), slug
        for slug in english:
            assert is_entry(f"/en/projects/{slug}/"), slug
        # …and every archive and later page is still an archive.
        for path in (
            "/realizacje/kategoria/lazienki/",
            "/realizacje/kategoria/lazienki/strona/2/",
            "/realizacje/tag/porady/",
            "/realizacje/strona/2/",
            "/realizacje/",
            "/en/projects/category/bathrooms/",
            "/en/projects/tag/porady/",
            "/en/projects/page/2/",
        ):
            assert not is_entry(path), path
        for feed in ("feed.xml", "atom.xml", "sitemap.xml"):
            assert _feed(host, feed).status_code == 200

        # As former slugs they redirect their own address only.
        for slug, to in (("kategoria", "pokoje"), ("strona", "kartka"), ("tag", "znaczek")):
            assert _address(client, named[slug], slug=to, reason="x").status_code == 200
            _one_hop(host, f"/realizacje/{slug}/", f"/realizacje/{to}/")
        assert _address(client, english["category"], slug="rooms", reason="x").status_code == 200
        _one_hop(host, "/en/projects/category/", "/en/projects/rooms/")
        for path in (
            "/realizacje/kategoria/lazienki/",
            "/realizacje/tag/porady/",
            "/realizacje/strona/2/",
            "/en/projects/category/bathrooms/",
        ):
            assert not is_entry(path), path
        # What was never an address stays one that answers nothing.
        assert _moved(host, "/realizacje/kategoria/nic/") == (404, None)
        assert _moved(host, "/realizacje/strona/99/") == (404, None)


def test_before_the_first_publication_an_address_is_free_and_leaves_no_trace() -> None:
    blog = Blog("address-draft")
    client = blog.client
    made = create_entry(client, blog.collection_id, slug="szkic", idempotency_key="draft")
    entry_id = str(made.data["id"])
    preview = _address(client, entry_id, preview=True, slug="lepszy-szkic")
    assert (preview.data["published"], preview.data["moved"], preview.data["redirects"]) == (
        False,
        [],
        [],
    )
    done = _address(client, entry_id, slug="lepszy-szkic")
    assert done.status_code == 200, done.data
    assert (_entry(entry_id).slug, _entry(entry_id).former_slugs) == ("lepszy-szkic", [])
    assert not ContentEntryPublication.all_objects.filter(entry_id=entry_id).exists()
    # Nothing ever answered there, so nothing redirects.
    assert _moved(blog.host, "/blog/szkic/") == (404, None)


def test_only_a_person_moves_an_address_that_answered() -> None:
    blog = Blog("address-person")
    site = Site.all_objects.get(pk=blog.site_id)
    entry = _entry(blog.polish)
    with (
        activate_tenant_context(automation_context(site.organization_id, entry.created_by_id)),
        pytest.raises(PersonRequired),
    ):
        change_entry_slug(entry_id=entry.id, slug="przez-klucz", reason="x")
    with (
        activate_tenant_context(automation_context(site.organization_id, entry.created_by_id)),
        pytest.raises(PersonRequired),
    ):
        change_entry_slug(entry_id=entry.id, slug="przez-klucz", dry_run=True)
    assert _entry(blog.polish).slug == "wpis-jeden"


def test_a_withdrawn_entry_keeps_its_slugs_and_a_removed_one_frees_them() -> None:
    blog = Blog("address-gone")
    client, host = blog.client, blog.host
    first = blog.polish
    assert _address(client, first, slug="przeniesiony", reason="x").status_code == 200
    gone = client.delete(
        f"/api/v1/sites/entries/{first}/publication/", HTTP_X_CSRFTOKEN=csrf_value(client)
    )
    assert gone.status_code in (200, 204)
    # Withdrawn: nothing answers and nothing redirects, but the slugs are
    # still its own — it can come back.
    assert _moved(host, "/blog/wpis-jeden/") == (404, None)
    assert _moved(host, "/blog/przeniesiony/") == (404, None)
    refused = create_entry(client, blog.collection_id, slug="wpis-jeden", idempotency_key="w")
    assert _errors(refused) == [("slug", "entry_slug_former")]
    # Moving it while it is off the site needs no reason and keeps the trail.
    moved = _address(client, first, slug="po-wycofaniu")
    assert moved.status_code == 200, moved.data
    assert _entry(first).former_slugs == ["wpis-jeden", "przeniesiony"]
    assert publish(client, first, idempotency_key="back").status_code == 201
    _one_hop(host, "/blog/wpis-jeden/", "/blog/po-wycofaniu/")
    _one_hop(host, "/blog/przeniesiony/", "/blog/po-wycofaniu/")

    removed = client.delete(f"/api/v1/sites/entries/{first}/", HTTP_X_CSRFTOKEN=csrf_value(client))
    assert removed.status_code in (200, 204), removed.data
    assert _moved(host, "/blog/wpis-jeden/") == (404, None)
    # Removed: its slugs hold nothing any more. The row keeps `former_slugs`
    # as history (for the day a removed entry can be brought back), but no
    # reader of entries sees a removed row — `all_objects` leaves it out, and
    # that is what everything that asks „whose slug is this” reads.
    assert ContentEntry.with_removed.get(pk=first).former_slugs == ["wpis-jeden", "przeniesiony"]
    assert (
        former_slug_owners(
            organization_id=_entry_site(blog).organization_id,
            collection_id=blog.collection_id,
            locale="pl",
            slug="wpis-jeden",
        )
        == []
    )
    again = create_entry(client, blog.collection_id, slug="wpis-jeden", idempotency_key="free")
    assert again.status_code == 201, again.data
    taken = create_entry(client, blog.collection_id, slug="przeniesiony", idempotency_key="free2")
    assert taken.status_code == 201, taken.data


def test_an_entry_is_found_by_its_slug_without_reading_the_sites_other_entries() -> None:
    blog = Blog("address-lookup")
    for mark in ("a", "b", "c"):
        made = create_entry(blog.client, blog.collection_id, slug=mark, idempotency_key=mark)
        save_entry_draft(
            blog.client, made.data["id"], expected_version=0, text=mark, idempotency_key=f"d{mark}"
        )
        assert publish(blog.client, made.data["id"], idempotency_key=f"p{mark}").status_code == 201
    site = Site.all_objects.get(pk=blog.site_id)
    arguments = {
        "organization_id": site.organization_id,
        "site_id": site.id,
        "default_locale": "pl",
    }
    with CaptureQueriesContext(connection) as queries:
        page, document, _publication = _find_entry(requested_path="/blog/b/", **arguments)
    assert document["canonical_path"] == "/blog/b/"
    lookup = queries.captured_queries[0]["sql"]
    assert '"sites_contententry"."slug" = ' in lookup
    # Every published entry's row carries the slug of its publication: what
    # the lookup stands on.
    for entry in ContentEntry.all_objects.filter(site_id=site.id, state="published"):
        assert entry.current_publication is not None
        assert entry.current_publication.snapshot["slug"] == entry.slug
    # Not an entry's address: one small query, and no entry is read.
    with CaptureQueriesContext(connection) as missed, pytest.raises(PublicSiteNotFound):
        _find_entry(requested_path="/blog/", **arguments)
    assert len(missed.captured_queries) == 1
    with CaptureQueriesContext(connection) as nothing, pytest.raises(PublicSiteNotFound):
        _find_entry(requested_path="/", **arguments)
    assert len(nothing.captured_queries) == 0


def test_a_language_version_made_by_hand_is_filed_like_its_original() -> None:
    world = World("address-version-terms")
    category = world.category(world.projects, "Łazienki")
    original = world.entry(world.projects, "dom", categories=(category,), tags=("Drewno",))
    created = world.client.post(
        f"/api/v1/sites/entries/{original}/translations/",
        {"locale": "en", "slug": "house", "title": "House"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(world.client),
        HTTP_IDEMPOTENCY_KEY="by-hand",
    )
    assert created.status_code == 201, created.data

    def filed(entry_id: str) -> set[Any]:
        return set(
            ContentEntryTag.all_objects.filter(entry_id=entry_id).values_list("tag_id", flat=True)
        )

    assert filed(str(created.data["id"])) == filed(original) != set()
    terms = world.client.get(f"/api/v1/sites/entries/{created.data['id']}/categories/")
    assert [term["id"] for term in terms.json()] == [category]


def test_a_products_page_is_told_where_a_former_slug_leads() -> None:
    guide = Publisher("read-former")
    care = _category(guide, "Pielęgnacja")
    polish = _filed(guide, "pierwszy", [care])
    english = guide.english(polish, "first", "First")
    assert _address(guide.client, polish, slug="najpierw", reason="x").status_code == 200
    assert _address(guide.client, english, slug="at-first", reason="x").status_code == 200
    other = guide.entry("drugi")
    guide.enter()

    for asked, slug, locale in (("pierwszy", "najpierw", "pl"), ("first", "at-first", "en")):
        moved = _read(f"types/poradnik/entries/{locale}/{asked}/")
        assert moved.status_code == 200
        assert moved.json() == {
            "entry": None,
            "moved": {"type": "poradnik", "locale": locale, "slug": slug},
        }
        # What it leads to answers, and names its versions' addresses of today.
        today = _read(f"types/poradnik/entries/{locale}/{slug}/")
        assert today.status_code == 200
        assert today.data["moved"] is None
        assert today.data["entry"]["versions"] == [
            {"locale": "pl", "slug": "najpierw"},
            {"locale": "en", "slug": "at-first"},
        ]
    # A slug of one language is not a former slug of another, and a slug
    # nobody had leads nowhere.
    assert _read("types/poradnik/entries/en/pierwszy/").status_code == 404
    assert _read("types/poradnik/entries/pl/nikt/").status_code == 404
    # The lists and the sitemap name today's slugs only.
    listed = _read("types/poradnik/entries/", locale="pl")
    assert sorted(item["slug"] for item in listed.data["list"]["items"]) == ["drugi", "najpierw"]
    # A list says in whose time zone its dates are days, as an entry does.
    assert listed.data["list"]["timezone"] == today.data["entry"]["timezone"] != ""
    sitemap = _read("sitemap/").json()
    assert "pierwszy" not in str(sitemap)

    # A live address wins over a former one, whatever the rows say.
    guide.leave()
    ContentEntry.all_objects.filter(pk=other).update(former_slugs=["najpierw"])
    guide.enter()
    assert _read("types/poradnik/entries/pl/najpierw/").data["entry"]["slug"] == "najpierw"

    # A language the workspace switched off: a former slug there goes
    # straight to the version that is read — one hop, as on a company's site.
    Organization.objects.filter(pk=guide.organization.pk).update(public_locales=["pl"])
    off = _read("types/poradnik/entries/en/first/")
    assert off.json() == {
        "entry": None,
        "moved": {"type": "poradnik", "locale": "pl", "slug": "najpierw"},
    }


def test_the_address_change_holds_with_the_public_feeds_dates() -> None:
    """Publishing the same text again — an address change does — moves no
    date a reader, a feed or a sitemap shows."""
    blog = Blog("address-dates")
    host = blog.host
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        atom_before = _feed(host, "atom.xml").content.decode()
        sitemap_before = _feed(host, "sitemap.xml").content.decode()
    assert _address(blog.client, blog.polish, slug="inny", reason="x").status_code == 200
    atom_after = _feed(host, "atom.xml").content.decode()
    sitemap_after = _feed(host, "sitemap.xml").content.decode()

    def stamps(document: str, tag: str) -> list[str]:
        import re

        return re.findall(rf"<{tag}>([^<]+)</{tag}>", document)

    assert stamps(atom_after, "updated") == stamps(atom_before, "updated")
    assert stamps(atom_after, "published") == stamps(atom_before, "published")
    assert stamps(sitemap_after, "lastmod") == stamps(sitemap_before, "lastmod")
