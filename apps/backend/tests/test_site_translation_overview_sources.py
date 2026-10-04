"""„Strona internetowa → Tłumaczenia” beyond pages and articles (TL16g): the
site's own texts, the company's card and its booking catalogue as rows of the
same overview, read through the translation sources the modules registered —
and where a version that is on the site answers."""

from __future__ import annotations

from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations.context import context_from_membership
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.sites.appearance import default_appearance, save_site_appearance
from saas_core.modules.shared.sites.models import Site
from saas_core.modules.shared.sites.services import create_site, publish_site
from test_site_language_decisions import _published_site
from test_sites_api import csrf_value, sites_client
from test_sites_site_text_source import _as, _key, home_page

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _site_with_footer(slug: str) -> tuple[Any, Site]:
    client, organization, user = sites_client(slug=slug, role_key="owner")
    context = context_from_membership(Membership.objects.get(organization=organization, user=user))
    with _as(context):
        site = create_site(
            name="Studio Teksty",
            slug=f"t-{uuid7().hex[-12:]}",
            default_locale="pl",
            idempotency_key=_key(),
        ).value
        home_page(site.id)
        appearance = default_appearance(site)
        appearance["footer"] = {
            "layout": "simple",
            "text": "Zapraszamy",
            "links": [{"label": "Kontakt", "href": "/kontakt/"}],
        }
        save_site_appearance(
            site_id=site.id, expected_version=0, appearance=appearance, idempotency_key=_key()
        )
        publish_site(site_id=site.id, idempotency_key=_key())
    return client, site


def _other(client: Any, site_id: Any, **query: Any) -> Any:
    answer = client.get(f"/api/v1/sites/{site_id}/translations/", {"kind": "other", **query})
    assert answer.status_code == 200, answer.data
    return answer.json()


def _save(client: Any, site_id: Any, locale: str, texts: dict[str, str]) -> None:
    read = client.get(f"/api/v1/sites/{site_id}/texts/{locale}/")
    saved = client.put(
        f"/api/v1/sites/{site_id}/texts/{locale}/",
        {"expected_version": read.data["version"], "texts": texts},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert saved.status_code == 200, saved.data


def test_the_sites_own_texts_are_a_row_with_the_pages_states():
    client, site = _site_with_footer("overview-texts")

    listed = _other(client, site.id, locale="en")
    assert listed["locales"] == ["en"]
    [row] = [item for item in listed["items"] if item["source_key"] == "sites.site_texts"]
    assert (row["kind"], row["id"], row["source_id"], row["title"]) == (
        "other",
        str(site.id),
        str(site.id),
        "Studio Teksty",
    )
    # Two texts (the footer and its link), none translated; nothing waits and
    # a site text has no address of its own.
    assert row["cells"] == [
        {
            "locale": "en",
            "state": "missing",
            "untranslated": 2,
            "metadata_complete": None,
            "on_site": None,
            "path": None,
            "review_id": None,
            "review_version": None,
            "review_comparable": None,
        }
    ]

    _save(client, site.id, "en", {"footer/text": "Welcome"})
    [row] = [
        item
        for item in _other(client, site.id, locale="en")["items"]
        if item["source_key"] == "sites.site_texts"
    ]
    assert (row["cells"][0]["state"], row["cells"][0]["untranslated"]) == ("untranslated", 1)

    link = next(
        item["key"]
        for item in client.get(f"/api/v1/sites/{site.id}/texts/en/").data["items"]
        if item["role"] == "footer_link"
    )
    _save(client, site.id, "en", {link: "Contact"})
    done = _other(client, site.id, locale="en", state="complete")
    assert [item["source_key"] for item in done["items"]] == ["sites.site_texts"]
    assert all(
        item["source_key"] != "sites.site_texts"
        for item in _other(client, site.id, locale="en", state="missing")["items"]
    )


def test_a_reworded_text_reads_outdated_and_the_rows_page_by_cursor():
    client, site = _site_with_footer("overview-texts-stale")
    _save(client, site.id, "en", {"footer/text": "Welcome"})
    link = next(
        item["key"]
        for item in client.get(f"/api/v1/sites/{site.id}/texts/en/").data["items"]
        if item["role"] == "footer_link"
    )
    _save(client, site.id, "en", {link: "Contact"})
    organization = Site.all_objects.get(pk=site.id).organization
    context = context_from_membership(Membership.objects.get(organization=organization))
    with _as(context):
        appearance = default_appearance(site)
        appearance["footer"] = {
            "layout": "simple",
            "text": "Zapraszamy serdecznie",
            "links": [{"label": "Kontakt", "href": "/kontakt/"}],
        }
        save_site_appearance(
            site_id=site.id, expected_version=1, appearance=appearance, idempotency_key=_key()
        )
        publish_site(site_id=site.id, idempotency_key=_key())

    rows = _other(client, site.id, locale="en")["items"]
    [texts] = [item for item in rows if item["source_key"] == "sites.site_texts"]
    assert texts["cells"][0]["state"] == "outdated"
    # The site's own row goes first; a cursor continues after the row it names.
    assert rows[0]["source_key"] == "sites.site_texts"
    after = _other(client, site.id, locale="en", cursor=rows[0]["id"])
    assert [item["id"] for item in after["items"]] == [item["id"] for item in rows[1:]]
    assert after["next_cursor"] is None


def test_a_page_on_the_site_says_where_visitors_read_each_language():
    client, _organization, site_id, home, offer, _host = _published_site("overview-paths")

    rows = {
        row["id"]: row
        for row in client.get(f"/api/v1/sites/{site_id}/translations/").json()["items"]
    }
    snapshot = Site.all_objects.get(pk=site_id).current_publication.snapshot
    english = next(
        entry
        for page in snapshot["pages"]
        if page["page_id"] == home
        for entry in page["locales"]
        if entry["locale"] == "en"
    )
    assert rows[home]["source_key"] == "sites.page"
    [cell] = [cell for cell in rows[home]["cells"] if cell["locale"] == "en"]
    assert (cell["on_site"], cell["path"]) == (True, english["path"])
    assert cell["path"].startswith("/en/")
    # Translated, not yet published: no address to open.
    [waiting] = [cell for cell in rows[offer]["cells"] if cell["locale"] == "en"]
    assert (waiting["state"], waiting["on_site"], waiting["path"]) == ("complete", False, None)
