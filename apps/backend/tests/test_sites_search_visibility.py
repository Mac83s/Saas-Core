"""„Widoczność w wyszukiwarkach i AI” (TL19): the panel lists, per site and
language, only the addresses that answer now — and the metrics say how much
each language is read."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import PageViewDay, PageViewKind, Site
from test_site_language_publication import _get
from test_sites_api import create_site
from test_sites_blog_languages import Blog, _translate_entry
from test_sites_llms import _llms
from test_sites_sitemap_head import _two_language_site

pytestmark = pytest.mark.django_db
URL = "/api/v1/sites/search-visibility/"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _read(client: Any) -> list[dict[str, Any]]:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        response = client.get(URL)
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "private, no-store"
    sites: list[dict[str, Any]] = response.json()["sites"]
    return sites


def test_each_language_the_site_answers_in_has_its_home_and_its_llms_file() -> None:
    client, site_id, _home, _offer, host = _two_language_site("visible-two")

    (site,) = _read(client)

    assert site["site_id"] == str(site_id)
    assert site["origin"] == f"https://{host}"
    assert site["sitemap_url"] == f"https://{host}/sitemap.xml"
    assert site["robots_url"] == f"https://{host}/robots.txt"
    assert site["languages"] == [
        {
            "locale": "pl",
            "name": "Polski",
            "home_url": f"https://{host}/",
            "llms_url": f"https://{host}/llms.txt",
        },
        {
            "locale": "en",
            "name": "English",
            "home_url": f"https://{host}/en/",
            "llms_url": f"https://{host}/en/llms.txt",
        },
    ]
    # Nothing listed gives 404: the public routes answer each of them.
    assert _llms(host)[0] == 200 and _llms(host, "en")[0] == 200
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        assert _get(host, "/").status_code == 200
        assert _get(host, "/en/").status_code == 200


def test_a_language_the_site_is_not_written_in_is_not_listed() -> None:
    client, site_id, _home, _offer, host = _two_language_site("visible-unwritten")
    organization_id = Site.all_objects.get(pk=site_id).organization_id
    Organization.objects.filter(pk=organization_id).update(public_locales=["pl", "en", "de"])

    assert [row["locale"] for row in _read(client)[0]["languages"]] == ["pl", "en"]
    assert _llms(host, "de")[0] == 404

    # A language the company switched off is off here at once, as it is public.
    Organization.objects.filter(pk=organization_id).update(public_locales=["pl"])
    assert [row["locale"] for row in _read(client)[0]["languages"]] == ["pl"]
    assert _llms(host, "en")[0] == 404


def test_a_language_with_articles_only_has_an_llms_file_and_no_home() -> None:
    blog = Blog("visible-blog")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")

    (site,) = _read(blog.client)
    english = next(row for row in site["languages"] if row["locale"] == "en")

    assert english["llms_url"] == f"https://{blog.host}/en/llms.txt"
    assert _llms(blog.host, "en")[0] == 200
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        home = _get(blog.host, "/en/").status_code
    assert (english["home_url"] is None) == (home != 200)


def test_a_site_nobody_published_lists_nothing() -> None:
    client, _site_id, _home, _offer, _host = _two_language_site("visible-draft")
    created = create_site(client, slug="visible-draft-second", idempotency_key="visible-draft-2")
    assert created.status_code == 201, created.content
    draft = created.json()

    sites = {row["site_id"]: row for row in _read(client)}

    assert sites[draft["id"]]["origin"] is None
    assert sites[draft["id"]]["sitemap_url"] is None
    assert sites[draft["id"]]["languages"] == []


def test_nobody_reads_it_without_a_session() -> None:
    assert APIClient().get(URL).status_code in {401, 403}


def test_the_metrics_sum_the_views_per_language() -> None:
    client, site_id, _home, _offer, _host = _two_language_site("visible-views")
    site = Site.all_objects.get(pk=site_id)
    today = timezone.now().astimezone(datetime.UTC).date()
    for day, path, locale, views in (
        (today, "/", "pl", 5),
        (today - datetime.timedelta(days=1), "/", "pl", 2),
        (today, "/en/", "en", 4),
        (today, "/stara/", "", 1),
    ):
        PageViewDay.all_objects.create(
            organization_id=site.organization_id,
            site=site,
            day=day,
            path=path,
            kind=PageViewKind.PAGE,
            publication_id=site.current_publication_id,
            locale=locale,
            views=views,
        )

    response = client.get(
        f"/api/v1/sites/{site_id}/metrics/?since={today - datetime.timedelta(days=6)}&until={today}"
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["page_views_by_locale"] == [
        {"locale": "pl", "views": 7},
        {"locale": "en", "views": 4},
        {"locale": None, "views": 1},
    ]
    assert sum(row["views"] for row in body["page_views"]) == 12
