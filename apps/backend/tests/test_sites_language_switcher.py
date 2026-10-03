"""A visitor switches language at the same page's version, or at the
language's home when the page has none, and a missing address speaks the
language it was asked in (TL14a)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

# The module, not its contract class: importing the class would collect the
# whole page contract here a second time.
import test_sites_page_translation_source as page_tests
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.models import Domain, DomainKind, PageTranslation

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


def _get(driver: page_tests.SitesPageDriver, path: str, host: str | None = None) -> Any:
    hostname = (
        host or Domain.all_objects.get(site_id=driver.site_id, kind=DomainKind.PLATFORM).hostname
    )
    cache.clear()
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=hostname)


def _links(response: Any) -> list[tuple[str, str, str, bool]]:
    return [
        (link["locale"], link["name"], link["path"], link["current"])
        for link in response.data["language_links"]
    ]


def _site_with_german_home() -> tuple[page_tests.SitesPageDriver, UUID, UUID]:
    contract, driver = page_tests.TestSitesPageSource(), page_tests.SitesPageDriver()
    home = driver.create(["Witamy"])
    offer = driver.create(["Oferta"])
    driver.publish(home)
    page_tests._job(contract, driver, home)  # German is live with the home page
    return driver, home, offer


def test_each_live_language_at_this_pages_version_or_its_home() -> None:
    driver, _home, offer = _site_with_german_home()
    slug = PageTranslation.all_objects.get(page_id=offer, locale="pl").slug

    home_pl = _get(driver, "/")
    home_de = _get(driver, "/de/")
    offer_pl = _get(driver, f"/{slug}/")

    assert _links(home_pl) == [
        ("pl", "Polski", "/", True),
        ("de", "Deutsch", "/de/", False),
    ]
    assert _links(home_de) == [
        ("pl", "Polski", "/", False),
        ("de", "Deutsch", "/de/", True),
    ]
    # The offer has no German version: German starts at its home page.
    assert _links(offer_pl) == [
        ("pl", "Polski", f"/{slug}/", True),
        ("de", "Deutsch", "/de/", False),
    ]


def test_one_live_language_needs_no_switch() -> None:
    driver = page_tests.SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.publish(home)

    assert _get(driver, "/").data["language_links"] == []


def test_a_language_the_company_switched_off_is_not_offered() -> None:
    driver, _home, _offer = _site_with_german_home()
    Organization.objects.filter(pk=driver.publisher.organization_id).update(public_locales=["pl"])

    assert _get(driver, "/").data["language_links"] == []


def test_a_missing_address_speaks_the_language_it_was_asked_in() -> None:
    driver, _home, _offer = _site_with_german_home()

    german = _get(driver, "/de/gibt-es-nicht/")
    polish = _get(driver, "/nie-ma-takiej/")
    unknown = _get(driver, "/de/", host="nikt-taki.example.test")

    assert german.status_code == 404
    assert (german.data["locale"], german.data["home_path"]) == ("de", "/de/")
    assert (polish.data["locale"], polish.data["home_path"]) == ("pl", "/")
    assert unknown.status_code == 404
    assert "locale" not in unknown.data
