"""A site's content types beyond its blog (ADR-079, phase CT1): the platform's
switch and the plan's limit, a second type on every surface in two languages,
what a type is to search engines and feeds, switching one off and on, removing
an empty one, and a page that never takes a type's name.

The limit never takes anything away: every test of it also asks the types
that are there — they answer visitors and take edits."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.utils import timezone

from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    WorkspaceKind,
)
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.billing.models import AccessMode, EntitlementSnapshot
from saas_core.modules.shared.sites.change_sets import read_content_base
from saas_core.modules.shared.sites.collections import create_collection as make_type
from saas_core.modules.shared.sites.collections import list_collections
from saas_core.modules.shared.sites.content_type_limit import (
    CONTENT_TYPES_ADDITIONAL_MAX as QUOTA,
)
from saas_core.modules.shared.sites.content_type_limit import ContentTypeArchived
from saas_core.modules.shared.sites.content_types import (
    switch_off_content_type,
    switch_on_content_type,
)
from saas_core.modules.shared.sites.entry_translation_source import ENTRY_SOURCE
from saas_core.modules.shared.sites.inventory import read_inventory
from saas_core.modules.shared.sites.models import (
    ContentCollection,
    ContentEntry,
    EntryScheduleState,
    Site,
)
from test_site_language_versions_api import _draft, _hero
from test_sites_api import create_page, create_site, csrf_value, save_translation, sites_client
from test_sites_blog_languages import Blog, _feed, _get, _items, _menu
from test_sites_collections import (
    _automation,
    _grant,
    create_entry,
    publish,
    save_entry_draft,
    schedule,
)
from test_sites_llms import _links, _llms

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def a_platform_that_offers_no_further_types(settings: Any) -> None:
    """What these tests start from, whatever the profile they run under says:
    no content types beyond the first unless a test asks for the offer
    (`content_types_offered`), and companies that speak Polish and English."""
    settings.CONTENT_TYPES_OFFERED = False
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en")


def _send(client: Any, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    return getattr(client, method)(
        url, payload or {}, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )


def _new_type(client: Any, site_id: str, name: str, path: str, **more: Any) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/collections/",
        {"key": path, "name": name, "kind": "blog", "base_path": path, **more},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=f"type-{path}-{len(name)}",
    )


def _code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json().get("code", "")


def _plan(organization: Any, **snapshot: Any) -> None:
    EntitlementSnapshot.all_objects.filter(organization=organization).update(**snapshot)


def _organization(site_id: str) -> Organization:
    return Organization.objects.get(pk=Site.all_objects.get(pk=site_id).organization_id)


def _entry(client: Any, type_id: str, slug: str, *, out: bool = True) -> str:
    entry_id = str(
        create_entry(client, type_id, slug=slug, idempotency_key=f"e-{slug}").data["id"]
    )
    save_entry_draft(
        client, entry_id, expected_version=0, text=f"Treść {slug}.", idempotency_key=f"d-{slug}"
    )
    if out:
        assert publish(client, entry_id, idempotency_key=f"p-{slug}").status_code == 201
    return entry_id


def _in_english(client: Any, entry_id: str, slug: str, title: str) -> str:
    created = client.post(
        f"/api/v1/sites/entries/{entry_id}/translations/",
        {"locale": "en", "slug": slug, "title": title},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=f"tr-{slug}",
    )
    assert created.status_code == 201, created.data
    english = str(created.data["id"])
    save_entry_draft(
        client, english, expected_version=0, text=f"{title}.", idempotency_key=f"trd-{slug}"
    )
    assert publish(client, english, idempotency_key=f"trp-{slug}").status_code == 201
    return english


def _types(client: Any, site_id: str) -> Any:
    return client.get(f"/api/v1/sites/{site_id}/content-types/")


def _switch(client: Any, type_id: str, to: str, *, preview: bool = False) -> Any:
    return _send(
        client,
        "post",
        f"/api/v1/sites/collections/{type_id}/switch-{to}/" + ("preview/" if preview else ""),
    )


def _graph_types(host: str, path: str) -> list[Any]:
    return [node["@type"] for node in _get(host, path).data["structured_data"]["@graph"]]


def _projects(blog: Blog) -> tuple[str, str]:
    """„Realizacje” beside the blog — `/realizacje/`, `/en/projects/` — with
    one project out in Polish and English. Answers (type id, Polish entry id)."""
    made = _new_type(
        blog.client,
        blog.site_id,
        "Realizacje",
        "realizacje",
        locale_paths={"en": "projects"},
        schema_type="WebPage",
    )
    assert made.status_code == 201, made.data
    type_id = str(made.data["id"])
    polish = _entry(blog.client, type_id, "dom-w-gdyni")
    _in_english(blog.client, polish, "house-in-gdynia", "House in Gdynia")
    return type_id, polish


# --- the two gates ----------------------------------------------------------


def test_without_the_platforms_offer_a_site_has_its_first_type_and_no_other() -> None:
    client, _organization_row, _user = sites_client(slug="types-not-offered", role_key="owner")
    site_id = str(create_site(client).data["id"])

    first = _new_type(client, site_id, "Blog", "blog")
    second = _new_type(client, site_id, "Realizacje", "realizacje")

    assert first.status_code == 201, first.data
    assert _code(second) == (400, "content_types_not_offered")
    assert second.json()["errors"] == [
        {
            "field": None,
            "code": "content_types_not_offered",
            "message": second.json()["errors"][0]["message"],
        }
    ]
    assert "działają dalej" in second.json()["errors"][0]["message"]
    listed = _types(client, site_id).json()
    assert [row["collection"]["base_path"] for row in listed["types"]] == ["blog"]
    assert listed["limit"]["offered"] is False
    assert (listed["limit"]["allowed"], listed["limit"]["code"]) == (
        False,
        "content_types_not_offered",
    )


@pytest.mark.usefixtures("content_types_offered")
def test_the_plan_limits_further_types_and_takes_none_away() -> None:
    blog = Blog("types-limit")
    client, host = blog.client, blog.host
    organization = _organization(blog.site_id)
    _plan(organization, quotas={QUOTA: 1})

    type_id, polish = _projects(blog)
    third = _new_type(client, blog.site_id, "Aktualności", "aktualnosci")

    assert _code(third) == (400, "quota_exceeded")
    assert "limit poza pierwszym: 1" in third.json()["errors"][0]["message"]
    limit = _types(client, blog.site_id).json()["limit"]
    assert (limit["allowed"], limit["additional_max"], limit["additional_used"]) == (False, 1, 1)

    # A cheaper plan, a platform that stops offering types, a subscription
    # that only reads: the site keeps both types, on the site and in the panel.
    for change in (
        {"quotas": {QUOTA: 0}},
        {"access_mode": AccessMode.READ_ONLY},
    ):
        before = EntitlementSnapshot.all_objects.get(organization=organization)
        _plan(organization, **change)
        for path in ("/blog/", "/blog/wpis-jeden/", "/realizacje/", "/en/projects/"):
            assert _get(host, path).status_code == 200, (change, path)
        assert _get(host, "/realizacje/dom-w-gdyni/").status_code == 200
        assert [
            (row["collection"]["base_path"], row["collection"]["archived"])
            for row in _types(client, blog.site_id).json()["types"]
        ] == [("blog", False), ("realizacje", False)]
        refused = _new_type(client, blog.site_id, "Poradnik", "poradnik")
        assert refused.status_code in (400, 403), refused.data
        _plan(organization, quotas=before.quotas, access_mode=before.access_mode)
    _plan(organization, quotas={QUOTA: 0})
    # Over the limit the types that are there still take edits and publish.
    edited = save_entry_draft(
        client, polish, expected_version=1, text="Poprawka.", idempotency_key="over-limit-edit"
    )
    assert edited.status_code in (200, 201), edited.data
    assert publish(client, polish, idempotency_key="over-limit-publish").status_code == 201
    assert _entry(client, type_id, "dom-w-sopocie")
    assert _get(host, "/realizacje/dom-w-sopocie/").status_code == 200


@pytest.mark.usefixtures("content_types_offered")
def test_a_plan_without_the_number_has_no_limit_and_one_that_cannot_write_says_why() -> None:
    client, organization, _user = sites_client(slug="types-no-number", role_key="owner")
    site_id = str(create_site(client).data["id"])
    for number, path in enumerate(("blog", "realizacje", "aktualnosci", "poradnik")):
        assert _new_type(client, site_id, path.title(), path).status_code == 201, number
    limit = _types(client, site_id).json()["limit"]
    assert (limit["allowed"], limit["additional_max"], limit["additional_used"]) == (True, None, 3)

    _plan(organization, access_mode=AccessMode.READ_ONLY)
    refused = _new_type(client, site_id, "Oferty", "oferty")

    # The entitlement check of every write says so first; the limit's own
    # reason is what the list of types reads.
    assert refused.status_code in (400, 403), refused.data
    assert ContentCollection.all_objects.filter(site_id=site_id).count() == 4


@pytest.mark.usefixtures("content_types_offered")
def test_the_limit_reads_a_subscription_that_cannot_write_as_its_own_refusal() -> None:
    from saas_core.modules.shared.sites.content_type_limit import content_types_limit

    client, organization, _user = sites_client(slug="types-read-only", role_key="owner")
    site_id = str(create_site(client).data["id"])
    assert _new_type(client, site_id, "Blog", "blog").status_code == 201
    _plan(organization, access_mode=AccessMode.READ_ONLY, quotas={QUOTA: 5})
    membership = Membership.objects.get(organization=organization)

    with activate_tenant_context(context_from_membership(membership)):
        limit = content_types_limit(Site.all_objects.get(pk=site_id))

    assert (limit.allowed, limit.code) == (False, "plan_access_denied")
    assert "tylko do odczytu" in limit.message


def test_the_platforms_own_workspace_is_asked_neither_gate() -> None:
    client, organization, _user = sites_client(slug="types-platform", role_key="owner")
    site_id = create_site(client).data["id"]
    _plan(organization, quotas={QUOTA: 0})
    Organization.objects.filter(pk=organization.pk).update(workspace_kind=WorkspaceKind.PLATFORM)
    membership = Membership.objects.get(organization=organization)

    # The switch is off and the plan says zero: neither is the workspace's.
    with activate_tenant_context(context_from_membership(membership)):
        for path in ("blog", "poradnik", "aktualnosci"):
            _made, created = make_type(
                site_id=site_id,
                key=path,
                name=path.title(),
                kind="blog",
                base_path=path,
                idempotency_key=f"platform-{path}",
            )
            assert created

    assert ContentCollection.all_objects.filter(site_id=site_id).count() == 3


# --- a second type, end to end ----------------------------------------------


@pytest.mark.usefixtures("content_types_offered")
def test_a_second_type_answers_on_every_surface_in_two_languages() -> None:
    blog = Blog("types-projects")
    client, host, origin = blog.client, blog.host, f"https://{blog.host}"
    type_id, _polish = _projects(blog)

    made = ContentCollection.all_objects.get(pk=type_id)
    # A type of plain pages stays out of the feed until the company says so.
    assert (made.schema_type, made.in_site_feed) == ("WebPage", False)
    index = {"pl": "/realizacje/", "en": "/en/projects/"}
    entry = {"pl": "/realizacje/dom-w-gdyni/", "en": "/en/projects/house-in-gdynia/"}
    for path, versions, title in (
        ("/realizacje/", index, "Realizacje"),
        ("/en/projects/", index, "Realizacje"),
        ("/realizacje/dom-w-gdyni/", entry, "Dom W Gdyni"),
        ("/en/projects/house-in-gdynia/", entry, "House in Gdynia"),
    ):
        page = _get(host, path)
        assert page.status_code == 200, (path, page.status_code)
        assert page.data["canonical_url"] == origin + path
        assert page.data["hreflang"] == {code: origin + to for code, to in versions.items()}
        assert page.data["x_default"] == origin + versions["pl"]
        assert page.data["title"] == title
    assert _items(_get(host, "/realizacje/")) == ["/realizacje/dom-w-gdyni/"]
    # The blog is where it was, and each type lists its own entries.
    assert _items(_get(host, "/blog/")) == ["/blog/wpis-jeden/"]

    sitemap = _feed(host, "sitemap.xml").content.decode()
    for path in (*index.values(), *entry.values(), "/blog/", "/blog/wpis-jeden/"):
        assert f"<loc>{origin}{path}</loc>" in sitemap, path
    assert f"{origin}/realizacje/dom-w-gdyni/" in _links(_llms(host)[1])
    assert f"{origin}/en/projects/house-in-gdynia/" in _links(_llms(host, "en")[1])
    # The feed is the blog's readers': the project is not in it, the article is.
    for name in ("feed.xml", "atom.xml"):
        feed = _feed(host, name).content.decode()
        assert "/blog/wpis-jeden/" in feed and "/realizacje/" not in feed, name

    # To a search engine a project is its page; an article is an article.
    assert "BlogPosting" not in _graph_types(host, "/realizacje/dom-w-gdyni/")
    project = _get(host, "/realizacje/dom-w-gdyni/").data
    page_node = next(
        node for node in project["structured_data"]["@graph"] if node["@type"] == "WebPage"
    )
    assert page_node["datePublished"] == project["article"]["published_at"]
    assert "mainEntity" not in page_node
    assert "BlogPosting" in _graph_types(host, "/blog/wpis-jeden/")

    # The menu names a type the company put in it, in each language.
    assert _send(
        client,
        "put",
        f"/api/v1/sites/collections/{type_id}/navigation/",
        {"show_in_navigation": True},
    ).status_code == 200
    blog.publish("with-projects")
    assert [path for _title, path, _lang in _menu(_get(host, "/"))] == ["/blog/", "/realizacje/"]
    assert [path for _title, path, _lang in _menu(_get(host, "/en/"))] == ["/en/projects/"]


@pytest.mark.usefixtures("content_types_offered")
def test_what_a_type_is_changes_at_once_and_republishes_nothing() -> None:
    blog = Blog("types-settings")
    client, host = blog.client, blog.host
    type_id, _polish = _projects(blog)
    url = f"/api/v1/sites/collections/{type_id}/settings/"
    publications = ContentEntry.all_objects.filter(collection_id=type_id).values_list(
        "current_publication_id", flat=True
    )
    out_before = sorted(map(str, publications))

    preview = _send(
        client, "post", url + "preview/", {"name": "Nasze realizacje", "in_site_feed": True}
    )
    assert preview.status_code == 200, preview.data
    assert (preview.data["changed"], preview.data["collection"]["name"]) == (
        True,
        "Nasze realizacje",
    )
    assert _get(host, "/realizacje/").data["title"] == "Realizacje"
    assert "/realizacje/" not in _feed(host, "feed.xml").content.decode()

    saved = _send(
        client,
        "put",
        url,
        {"name": "Nasze realizacje", "schema_type": "NewsArticle", "in_site_feed": True},
    )

    assert saved.status_code == 200, saved.data
    assert saved.data["changed"] is True
    assert _get(host, "/realizacje/").data["title"] == "Nasze realizacje"
    assert "/realizacje/dom-w-gdyni/" in _feed(host, "feed.xml").content.decode()
    assert "/en/projects/house-in-gdynia/" in _feed(host, "atom.xml", "en").content.decode()
    assert "NewsArticle" in _graph_types(host, "/realizacje/dom-w-gdyni/")
    assert sorted(map(str, publications)) == out_before
    audit = OrganizationAuditEntry.objects.get(action="sites.content_type.updated")
    assert set(audit.metadata["changes"]) == {"name", "schema_type", "in_site_feed"}
    # The same values again change nothing; a kind nobody offers is refused
    # at its field, and one field alone leaves the others.
    again = _send(client, "put", url, {"name": "Nasze realizacje"})
    assert (again.status_code, again.data["changed"]) == (200, False)
    wrong = _send(client, "put", url, {"schema_type": "Recipe"})
    assert wrong.status_code == 400
    assert [(error["field"], error["code"]) for error in wrong.json()["errors"]] == [
        ("schema_type", "invalid_choice")
    ]
    assert _send(client, "put", url, {"name": "R"}).json()["errors"][0]["field"] == "name"
    # The blog was never touched: an article is still an article, in the feed.
    assert "BlogPosting" in _graph_types(host, "/blog/wpis-jeden/")
    assert "/blog/wpis-jeden/" in _feed(host, "feed.xml").content.decode()


@pytest.mark.usefixtures("content_types_offered")
def test_the_list_names_each_type_with_its_entries_and_languages() -> None:
    blog = Blog("types-list")
    type_id, _polish = _projects(blog)
    _entry(blog.client, type_id, "szkic-domu", out=False)

    listed = _types(blog.client, blog.site_id)

    assert listed.status_code == 200, listed.data
    rows = [
        (
            row["collection"]["name"],
            row["collection"]["paths"],
            row["entries"],
            row["published"],
            row["locales"],
            row["collection"]["schema_type"],
            row["collection"]["in_site_feed"],
        )
        for row in listed.json()["types"]
    ]
    assert rows == [
        ("Blog", {"pl": "/blog/", "en": "/en/blog/"}, 1, 1, ["pl"], "BlogPosting", True),
        (
            "Realizacje",
            {"pl": "/realizacje/", "en": "/en/projects/"},
            3,
            2,
            ["pl", "en"],
            "WebPage",
            False,
        ),
    ]
    assert listed.json()["limit"]["allowed"] is True
    assert [
        (option["schema_type"], option["in_site_feed"])
        for option in listed.json()["schema_types"]
    ] == [
        ("BlogPosting", True),
        ("NewsArticle", True),
        ("Article", True),
        ("WebPage", False),
    ]
    assert all(
        option["title"][language] and option["hint"][language]
        for option in listed.json()["schema_types"]
        for language in ("pl", "en")
    )


# --- switching a type off and on ---------------------------------------------


@pytest.mark.usefixtures("content_types_offered")
def test_a_switched_off_type_answers_nothing_and_comes_back_whole() -> None:
    blog = Blog("types-off")
    client, host = blog.client, blog.host
    type_id, polish = _projects(blog)
    assert _send(
        client,
        "put",
        f"/api/v1/sites/collections/{type_id}/navigation/",
        {"show_in_navigation": True},
    ).status_code == 200
    blog.publish("with-projects")
    waiting = _entry(client, type_id, "dom-w-oliwie", out=False)
    moment = (timezone.now() + timedelta(days=2)).isoformat()
    assert schedule(client, waiting, moment).status_code == 200
    answering = (
        "/realizacje/",
        "/realizacje/dom-w-gdyni/",
        "/en/projects/",
        "/en/projects/house-in-gdynia/",
    )
    for path in answering:
        assert _get(host, path).status_code == 200, path

    preview = _switch(client, type_id, "off", preview=True)
    assert preview.status_code == 200, preview.data
    assert preview.data["paths"] == {"pl": "/realizacje/", "en": "/en/projects/"}
    assert (preview.data["published"], preview.data["scheduled"]) == (2, 1)
    assert (preview.data["changed"], preview.data["restorable"]) == (True, True)
    assert _get(host, "/realizacje/").status_code == 200

    done = _switch(client, type_id, "off")

    assert done.status_code == 200, done.data
    assert done.data["collection"]["archived"] is True
    for path in (*answering, "/realizacje/strona/2/", "/en/projects/page/2/"):
        assert _get(host, path).status_code == 404, path
    sitemap = _feed(host, "sitemap.xml").content.decode()
    assert "realizacje" not in sitemap and "projects" not in sitemap
    for document in (_llms(host)[1], _llms(host, "en")[1]):
        assert "realizacje" not in document and "projects" not in document
    assert [path for _title, path, _lang in _menu(_get(host, "/"))] == ["/blog/"]
    assert _menu(_get(host, "/en/")) == []
    # The rest of the site is as it was.
    for path in ("/", "/blog/", "/blog/wpis-jeden/", "/blog/tag/porady/"):
        assert _get(host, path).status_code == 200, path

    # Nothing was removed or unpublished; the entries just take no work.
    assert ContentEntry.all_objects.filter(collection_id=type_id, state="published").count() == 2
    called_off = ContentEntry.all_objects.get(pk=waiting)
    assert called_off.schedule_state == EntryScheduleState.CANCELLED
    assert "wyłączony" in called_off.schedule_error
    for refused in (
        save_entry_draft(
            client, polish, expected_version=1, text="Zmiana.", idempotency_key="off-edit"
        ),
        publish(client, polish, idempotency_key="off-publish"),
        create_entry(client, type_id, slug="nowy-dom", idempotency_key="off-new"),
        _send(
            client,
            "put",
            f"/api/v1/sites/collections/{type_id}/settings/",
            {"name": "Inaczej"},
        ),
        _send(
            client,
            "put",
            f"/api/v1/sites/collections/{type_id}/paths/",
            {"base_path": "prace", "locale_paths": {}, "reason": "Nowa nazwa"},
        ),
    ):
        assert _code(refused) == (409, "content_type_archived")
    # Its names stay taken — for another type and for a page alike.
    assert _new_type(client, blog.site_id, "Inne", "realizacje").status_code == 400
    again = _switch(client, type_id, "off")
    assert (again.status_code, again.data["changed"]) == (200, False)

    back = _switch(client, type_id, "on")

    assert back.status_code == 200, back.data
    assert (back.data["changed"], back.data["published"]) == (True, 2)
    assert back.data["collection"]["archived"] is False
    for path in answering:
        assert _get(host, path).status_code == 200, path
    assert [path for _title, path, _lang in _menu(_get(host, "/"))] == ["/blog/", "/realizacje/"]
    assert f"https://{host}/realizacje/dom-w-gdyni/" in _feed(host, "sitemap.xml").content.decode()
    # What was called off stays called off: nothing publishes by surprise.
    assert ContentEntry.all_objects.get(pk=waiting).schedule_state == EntryScheduleState.CANCELLED
    assert [
        entry.action
        for entry in OrganizationAuditEntry.objects.filter(
            action__startswith="sites.content_type."
        ).order_by("occurred_at")
    ] == ["sites.content_type.switched_off", "sites.content_type.switched_on"]


@pytest.mark.usefixtures("content_types_offered")
def test_no_former_address_leads_into_a_switched_off_type() -> None:
    blog = Blog("types-off-moved")
    client, host = blog.client, blog.host
    type_id, _polish = _projects(blog)
    renamed = _send(
        client,
        "put",
        f"/api/v1/sites/collections/{type_id}/paths/",
        {"base_path": "prace", "locale_paths": {"en": "projects"}, "reason": "Krócej"},
    )
    assert renamed.status_code == 200, renamed.data
    assert _get(host, "/realizacje/dom-w-gdyni/").status_code == 308

    assert _switch(client, type_id, "off").status_code == 200

    for path in ("/realizacje/", "/realizacje/dom-w-gdyni/", "/prace/", "/prace/dom-w-gdyni/"):
        assert _get(host, path).status_code == 404, path
    assert _switch(client, type_id, "on").status_code == 200
    moved = _get(host, "/realizacje/dom-w-gdyni/")
    assert (moved.status_code, moved["Location"]) == (308, "/prace/dom-w-gdyni/")


@pytest.mark.usefixtures("content_types_offered")
def test_switching_on_needs_room_and_switching_off_says_so_beforehand() -> None:
    blog = Blog("types-restore")
    client = blog.client
    organization = _organization(blog.site_id)
    _plan(organization, quotas={QUOTA: 1})
    type_id, _polish = _projects(blog)

    # Within the limit the type can come back; it does not count while off.
    assert _switch(client, type_id, "off", preview=True).data["restorable"] is True
    assert _switch(client, type_id, "off").status_code == 200
    assert _types(client, blog.site_id).json()["limit"]["additional_used"] == 0
    news = _new_type(client, blog.site_id, "Aktualności", "aktualnosci")
    assert news.status_code == 201, news.data

    refused = _switch(client, type_id, "on")

    assert _code(refused) == (400, "quota_exceeded")
    assert ContentCollection.all_objects.get(pk=type_id).archived_at is not None
    # A site over its limit is told before it switches a type off that the
    # plan as it is would not let that type back.
    _plan(organization, quotas={QUOTA: 0})
    warned = _switch(client, str(news.data["id"]), "off", preview=True)
    assert (warned.data["restorable"], warned.data["restore_problem_code"]) == (
        False,
        "quota_exceeded",
    )
    assert "limit poza pierwszym: 0" in warned.data["restore_problem"]
    # The blog alone on the site would always come back: it would be the first.
    assert _switch(client, str(news.data["id"]), "off").status_code == 200
    assert _switch(client, blog.collection_id, "off", preview=True).data["restorable"] is True


@pytest.mark.usefixtures("content_types_offered")
def test_only_a_person_switches_a_type_off_and_on() -> None:
    blog = Blog("types-person")
    type_id, _polish = _projects(blog)
    membership = Membership.objects.get(organization=_organization(blog.site_id))
    assistant = acting_context(
        context_from_membership(membership), via="assistant", ref=f"conversation:{uuid7()}"
    )

    with activate_tenant_context(assistant):
        for switch in (switch_off_content_type, switch_on_content_type):
            with pytest.raises(PersonRequired):
                switch(collection_id=type_id)  # type: ignore[arg-type]
            with pytest.raises(PersonRequired):
                switch(collection_id=type_id, dry_run=True)  # type: ignore[arg-type]

    assert ContentCollection.all_objects.get(pk=type_id).archived_at is None


@pytest.mark.usefixtures("content_types_offered")
def test_nobody_orders_a_translation_of_a_switched_off_types_entry() -> None:
    blog = Blog("types-off-translation")
    type_id, polish = _projects(blog)
    membership = Membership.objects.get(organization=_organization(blog.site_id))
    context = context_from_membership(membership)

    def offered_entries() -> set[str]:
        with activate_tenant_context(context):
            page = ENTRY_SOURCE.list_objects(context=context, cursor=None, limit=50)
        return {str(item.object_id) for item in page.items}

    assert polish in offered_entries()
    assert _switch(blog.client, type_id, "off").status_code == 200

    assert polish not in offered_entries()
    assert blog.polish in offered_entries()
    with activate_tenant_context(context), pytest.raises(ContentTypeArchived):
        ENTRY_SOURCE.authorize(context=context, action="translate", object_ids=[polish])  # type: ignore[list-item]


@pytest.mark.usefixtures("content_types_offered")
def test_an_integration_is_not_shown_a_switched_off_type_and_plans_nothing_for_it() -> None:
    blog = Blog("types-off-key")
    type_id, polish = _projects(blog)
    organization = _organization(blog.site_id)
    user = Membership.objects.get(organization=organization).user
    credential_id = uuid7()
    _grant(organization.id, credential_id, user.id, collection_id=type_id, mode="draft_write")
    key = _automation(organization.id, user.id, credential_id)
    target = {
        "kind": "content_entry",
        "site_id": blog.site_id,
        "collection_id": type_id,
        "entry_id": polish,
        "locale": "pl",
    }

    def shown() -> tuple[list[str], list[str]]:
        with activate_tenant_context(key):
            inventory = read_inventory()
            listed = list_collections(site_id=blog.site_id)  # type: ignore[arg-type]
        return (
            [item["collection_id"] for site in inventory["sites"] for item in site["collections"]],
            [str(row.id) for row in listed],
        )

    assert shown() == ([type_id], [type_id])
    with activate_tenant_context(key):
        assert read_content_base(target)

    assert _switch(blog.client, type_id, "off").status_code == 200

    # Left out of what the key reads, and a change set for it is refused when
    # it is planned, not only when it is applied.
    assert shown() == ([], [])
    with activate_tenant_context(key), pytest.raises(ContentTypeArchived):
        read_content_base(target)
    # The person's panel still lists it, marked.
    assert [
        row["collection"]["archived"] for row in _types(blog.client, blog.site_id).json()["types"]
    ] == [False, True]
    # Switched on, it is the same section under the same id.
    assert _switch(blog.client, type_id, "on").status_code == 200
    assert shown() == ([type_id], [type_id])


# --- removing an empty type --------------------------------------------------


@pytest.mark.usefixtures("content_types_offered")
def test_only_a_type_without_entries_is_removed() -> None:
    blog = Blog("types-delete")
    client, host = blog.client, blog.host
    type_id, _polish = _projects(blog)
    empty = _new_type(client, blog.site_id, "Aktualności", "aktualnosci")
    assert empty.status_code == 201, empty.data
    empty_id = str(empty.data["id"])
    assert _send(
        client,
        "put",
        f"/api/v1/sites/collections/{empty_id}/navigation/",
        {"show_in_navigation": True},
    ).status_code == 200
    blog.publish("with-news")
    assert "/aktualnosci/" in [path for _title, path, _lang in _menu(_get(host, "/"))]

    refused = _send(client, "delete", f"/api/v1/sites/collections/{type_id}/")
    removed = _send(client, "delete", f"/api/v1/sites/collections/{empty_id}/")

    assert _code(refused) == (409, "content_type_not_empty")
    assert removed.status_code == 204
    assert not ContentCollection.all_objects.filter(pk=empty_id).exists()
    # Gone from the menu without a publication, and its name is free again.
    assert "/aktualnosci/" not in [path for _title, path, _lang in _menu(_get(host, "/"))]
    assert _get(host, "/aktualnosci/").status_code == 404
    assert _send(client, "delete", f"/api/v1/sites/collections/{empty_id}/").status_code == 404
    assert _new_type(client, blog.site_id, "Nowości", "aktualnosci").status_code == 201
    assert OrganizationAuditEntry.objects.filter(action="sites.content_type.deleted").count() == 1


# --- a page never stands in front of a type -----------------------------------


@pytest.mark.usefixtures("content_types_offered")
def test_a_page_never_takes_a_types_name_in_its_language() -> None:
    blog = Blog("types-page-slug")
    client, host = blog.client, blog.host
    type_id, _polish = _projects(blog)
    page_id = str(
        create_page(client, blog.site_id, key="prace", idempotency_key="page-prace").data["id"]
    )
    _draft(client, page_id, 0, [_hero("Prace", "Nasze prace")], "prace-v1")

    def save(locale: str, slug: str, version: int = 0) -> Any:
        return save_translation(
            client,
            page_id,
            locale,
            expected_version=version,
            slug=slug,
            title="Prace",
            description="Opis",
            idempotency_key=f"prace-{locale}-{slug}-{version}",
        )

    # The type's name in each language is closed in that language; the other
    # language's word is an address like any other there.
    assert _code(save("pl", "realizacje")) == (400, "slug_is_content_type")
    assert _code(save("pl", "blog")) == (400, "slug_is_content_type")
    assert _code(save("en", "projects")) == (400, "slug_is_content_type")
    assert save("pl", "prace").status_code in (200, 201)
    assert save("en", "works").status_code in (200, 201)
    moved = _send(
        client,
        "put",
        f"/api/v1/sites/pages/{page_id}/url/",
        {"locale": "pl", "slug": "realizacje", "reason": "Test."},
    )
    assert _code(moved) == (400, "slug_is_content_type")
    assert moved.json()["errors"][0]["field"] == "slug"

    # A switched-off type keeps its names: it comes back to them.
    assert _switch(client, type_id, "off").status_code == 200
    assert _code(save("pl", "realizacje", 1)) == (400, "slug_is_content_type")
    assert _switch(client, type_id, "on").status_code == 200
    assert _get(host, "/realizacje/").status_code == 200
    # The other direction is as before: a type never takes a page's address.
    assert _new_type(client, blog.site_id, "Prace", "prace").status_code == 400
