"""The SEO preview (TL18): what a search engine would read on one page after
the next publication — worked out through the publication's own steps, and
never saved."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.profiles.models import PublicProfile
from saas_core.modules.shared.sites import publication_routing
from saas_core.modules.shared.sites.models import Publication, Site
from saas_core.modules.shared.sites.seo_preview import next_snapshot
from test_booking import tenant
from test_site_language_publication import _get, _publish
from test_site_language_versions_api import _draft, _hero
from test_sites_api import create_site, sites_client
from test_sites_sitemap_head import _two_language_site

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _preview(client: Any, site_id: str, page_id: str, locale: str) -> Any:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return client.get(
            f"/api/v1/sites/{site_id}/seo/preview/", {"page_id": page_id, "locale": locale}
        )


SAME = ("title", "description", "noindex", "hreflang", "x_default", "structured_data")


def test_the_preview_is_what_the_next_publication_shows() -> None:
    client, site_id, _home, offer, host = _two_language_site("preview-next")
    site = Site.all_objects.get(pk=site_id)
    # Since the last publication: a card, and a new text on the offer.
    PublicProfile.all_objects.create(
        organization_id=site.organization_id,
        subject_kind="organization",
        display_name="Studio Projektowe Ewa",
        contact_phone="+48 600 100 200",
        contact_address="Długa 5",
    )
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 120 zł za m²")], "offer-v2")
    publications = Publication.all_objects.filter(site_id=site_id).count()
    before = _get(host, "/oferta/").json()
    cached = len(publication_routing._VISIBLE_SNAPSHOTS)

    polish = _preview(client, site_id, offer, "pl")
    english = _preview(client, site_id, offer, "en")

    assert polish.status_code == 200, polish.content
    assert polish["Cache-Control"] == "private, no-store"
    assert polish.json()["public"] is True and english.json()["public"] is True
    assert polish.json()["url"] == f"https://{host}/oferta/"
    assert english.json()["url"] == f"https://{host}/en/oferta-en/"
    # The card is already in the preview, and not yet on the public site.
    company = next(
        node
        for node in polish.json()["structured_data"]["@graph"]
        if node["@id"].endswith("#organization")
    )
    assert company["telephone"] == "+48 600 100 200"
    assert "LocalBusiness" not in str(before["structured_data"])
    assert _get(host, "/oferta/").json()["structured_data"] == before["structured_data"]
    # Nothing was saved, published or left in the renderer's cache.
    assert Publication.all_objects.filter(site_id=site_id).count() == publications
    assert Site.all_objects.get(pk=site_id).current_publication_id == site.current_publication_id
    assert len(publication_routing._VISIBLE_SNAPSHOTS) == cached

    _publish(client, site_id, "after-preview")

    for locale, path, preview in (
        ("pl", "/oferta/", polish.json()),
        ("en", "/en/oferta-en/", english.json()),
    ):
        public = _get(host, path).json()
        assert public["locale"] == locale
        assert preview["url"] == public["canonical_url"]
        for field in SAME:
            assert preview[field] == public[field], field
        assert preview["site_name"] == public["social"]["site_name"]
        assert preview["image"] == public["social"]["image"]


def test_the_preview_builds_the_snapshot_the_publication_writes() -> None:
    """`next_snapshot` repeats the steps of `publish_site`; when one of them
    changes and the other does not, this is the test that says so."""
    client, site_id, _home, offer, _host = _two_language_site("preview-snapshot")
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 120 zł za m²")], "offer-v2")
    site = Site.all_objects.select_related("current_publication").get(pk=site_id)
    member = Membership.objects.get(organization_id=site.organization_id)

    with tenant(member) as context:
        expected = next_snapshot(context=context, site=site)

    assert _publish(client, site_id, "written") == expected


def test_a_language_version_that_would_not_go_out_says_why() -> None:
    client, site_id, _home, offer, _host = _two_language_site("preview-held")
    # A price changes on the offer and English is not refreshed: held back.
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 150 zł za m²")], "offer-v2")

    held = _preview(client, site_id, offer, "en")
    absent = _preview(client, site_id, offer, "de")

    assert held.status_code == 200, held.content
    assert (held.json()["public"], held.json()["reason"]) == (False, "withheld")
    assert "title" not in held.json()
    assert absent.json() == {
        "site_id": str(site_id),
        "page_id": offer,
        "locale": "de",
        "public": False,
        "reason": "not_written",
        "image": None,
    }
    assert _preview(client, site_id, offer, "pl").json()["public"] is True


def test_a_preview_exists_before_the_first_publication() -> None:
    client, _, _ = sites_client(slug="preview-first", role_key="owner")
    site_id = create_site(client).data["id"]
    empty = _preview(client, site_id, "01990000-0000-7000-8000-000000000000", "pl")
    assert empty.status_code == 404

    from test_site_language_versions_api import _page

    page = str(_page(client, site_id, "start", [_hero("Witaj", "Studio projektowe")]))
    first = _preview(client, site_id, page, "pl")

    assert first.status_code == 200, first.content
    assert first.json()["public"] is True
    assert first.json()["url"].endswith("/")
    assert Publication.all_objects.filter(site_id=site_id).count() == 0


def test_only_the_company_reads_its_preview() -> None:
    client, site_id, _home, offer, _host = _two_language_site("preview-own")
    other, _, _ = sites_client(slug="preview-other", role_key="owner")

    assert _preview(other, site_id, offer, "pl").status_code == 404
    assert _preview(APIClient(), site_id, offer, "pl").status_code in {401, 403}
    assert _preview(client, site_id, offer, "polski").status_code == 400
