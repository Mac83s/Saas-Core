"""The readiness report names the company's languages and what each page's
version in them is, and only the site's own language holds a publication
back (W8, plan UX G2-12)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import override_settings

# The module, not its contract class: importing the class would collect the
# whole page contract here a second time.
import test_sites_page_translation_source as page_tests
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.sites.services import get_site_localization_report
from saas_core.modules.shared.sites.views import _localization_report

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


def _report(driver: page_tests.SitesPageDriver) -> dict[str, Any]:
    with page_tests._as(driver.publisher):
        return _localization_report(get_site_localization_report(site_id=driver.site_id))


def _states(report: dict[str, Any], index: int) -> dict[str, tuple[str, bool]]:
    return {
        locale["locale"]: (locale["state"], locale["blocks_publication"])
        for locale in report["pages"][index]["locales"]
    }


def test_another_language_is_described_and_never_blocks_the_publication() -> None:
    contract, driver = page_tests.TestSitesPageSource(), page_tests.SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.create(["Oferta"])
    driver.publish(home)
    page_tests._job(contract, driver, home)  # German is live with the home page

    report = _report(driver)

    assert report["ready_to_publish"] is True
    assert report["supported_locales"] == ["pl", "de"]
    assert report["languages"] == [
        {"locale": "pl", "is_source": True, "live": True},
        {"locale": "de", "is_source": False, "live": True},
    ]
    assert _states(report, 0) == {"pl": ("complete", False), "de": ("published", False)}
    assert _states(report, 1) == {"pl": ("complete", False), "de": ("missing", False)}


def test_only_the_companys_languages_are_counted() -> None:
    driver = page_tests.SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.publish(home)
    Organization.objects.filter(pk=driver.publisher.organization_id).update(public_locales=["pl"])

    report = _report(driver)

    assert report["supported_locales"] == ["pl"]
    assert report["languages"] == [{"locale": "pl", "is_source": True, "live": True}]


def test_an_unpublished_site_has_no_live_language() -> None:
    driver = page_tests.SitesPageDriver()
    driver.create(["Witamy"])

    report = _report(driver)

    assert [language["live"] for language in report["languages"]] == [False, False]
    assert _states(report, 0)["de"] == ("missing", False)
