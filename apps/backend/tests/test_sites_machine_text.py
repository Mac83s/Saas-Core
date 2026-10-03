"""The mark on text a machine wrote (ADR-071 pkt 17, TL19b): a version with AI
text always says so to machines; a visitor reads a notice only where the
operator switched it on and nobody stands behind the version yet."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

import test_sites_page_translation_source as page_source
from saas_core.modules.core.organizations import platform_settings
from saas_core.modules.core.organizations.settings_registry import setting_group
from saas_core.modules.shared.sites.language_decisions import publish_locale_version
from saas_core.modules.shared.sites.machine_text import (
    IPTC_AI,
    IPTC_MIXED,
    MACHINE_NOTICE,
    has_machine_text,
    machine_text,
)
from saas_core.modules.shared.sites.seo_graph import page_graph
from test_site_language_publication import _get
from test_sites_collections import _verified_platform_domain
from test_sites_page_translation_source import (  # noqa: F401 - the fixture travels by import
    german_on_the_platform,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The operators' values, as the platform settings table would give them."""
    values: dict[str, Any] = {}
    cache.clear()
    monkeypatch.setattr(platform_settings, "platform_overrides", lambda: values)
    return values


def test_the_switch_is_the_platforms_and_off_until_an_operator_says_so() -> None:
    assert MACHINE_NOTICE.scopes == ("platform",)
    assert (MACHINE_NOTICE.default, MACHINE_NOTICE.operator_level) == (False, 2)
    # An area of the sites' own: products compose the sites without the port.
    assert setting_group(MACHINE_NOTICE.group).area == "sites-platform"


def test_only_a_version_with_ai_text_is_marked(switch: dict[str, Any]) -> None:
    assert machine_text(None) is None
    assert machine_text({"origin": "human", "reviewed": True}) is None
    # A person's text beside copied source text: no model wrote any of it.
    assert machine_text({"origin": "mixed", "machine": False, "reviewed": True}) is None

    assert machine_text({"origin": "ai", "machine": True, "reviewed": False}) == {
        "source_type": IPTC_AI,
        "reviewed": False,
        "notice": False,
    }
    assert machine_text({"origin": "mixed", "machine": True, "reviewed": True}) == {
        "source_type": IPTC_MIXED,
        "reviewed": True,
        "notice": False,
    }
    # A snapshot from before the `machine` key: "mixed" may hold AI text.
    assert has_machine_text({"origin": "mixed", "reviewed": False})
    assert has_machine_text({"origin": "ai", "reviewed": True})


def test_the_notice_needs_the_switch_and_a_version_nobody_accepted(
    switch: dict[str, Any],
) -> None:
    waiting = {"origin": "ai", "machine": True, "reviewed": False}
    accepted = {"origin": "ai", "machine": True, "reviewed": True}
    assert machine_text(waiting)["notice"] is False

    switch[MACHINE_NOTICE.key] = True

    assert machine_text(waiting)["notice"] is True
    # An accepted translation is the company's own text: marked, not noticed.
    assert machine_text(accepted)["notice"] is False


def test_the_graph_names_the_source_type_and_the_work_translated() -> None:
    arguments: dict[str, Any] = {
        "origin": "https://studio.example.test",
        "site_name": "Studio",
        "locale": "de",
        "canonical_url": "https://studio.example.test/de/angebot/",
        "title": "Angebot",
        "description": "",
        "breadcrumbs": [],
        "blocks": [],
        "image": None,
        "facts": None,
    }

    def node(graph: dict[str, Any], kind: str) -> dict[str, Any]:
        return next(item for item in graph["@graph"] if item["@type"] == kind)

    page = node(
        page_graph(
            **arguments,
            article=None,
            machine_source_type=IPTC_AI,
            translation_of="https://studio.example.test/oferta/",
        ),
        "WebPage",
    )
    assert page["digitalSourceType"] == IPTC_AI
    assert page["translationOfWork"] == {"@id": "https://studio.example.test/oferta/#webpage"}

    # For an article the work is the article, not the page around it.
    graph = page_graph(
        **arguments,
        article={"author_name": "", "published_at": None, "updated_at": None, "tags": []},
        machine_source_type=IPTC_MIXED,
        translation_of="https://studio.example.test/blog/wpis/",
    )
    posting = node(graph, "BlogPosting")
    assert posting["digitalSourceType"] == IPTC_MIXED
    assert posting["translationOfWork"] == {"@id": "https://studio.example.test/blog/wpis/#article"}
    assert "digitalSourceType" not in node(graph, "WebPage")

    plain = node(page_graph(**arguments, article=None), "WebPage")
    assert "digitalSourceType" not in plain and "translationOfWork" not in plain


def test_a_page_a_job_translated_says_so_until_and_after_a_person_accepts_it(
    switch: dict[str, Any],
) -> None:
    # The contract's own class is reached through its module: imported by
    # name, pytest would collect and run it here a second time.
    contract, driver = page_source.TestSitesPageSource(), page_source.SitesPageDriver()
    home = driver.create(["Witamy", "Zapraszamy"])
    driver.publish(home)
    page_source._job(contract, driver, home)
    host = _verified_platform_domain(str(driver.site_id)).hostname

    # The page in the site's language is a person's: no mark at all.
    polish = _get(host, "/").json()
    assert polish["machine_text"] is None
    assert "digitalSourceType" not in str(polish["structured_data"])

    german = _get(host, "/de/").json()
    assert german["machine_text"] == {"source_type": IPTC_AI, "reviewed": False, "notice": False}
    page = next(item for item in german["structured_data"]["@graph"] if item["@type"] == "WebPage")
    assert page["digitalSourceType"] == IPTC_AI
    assert page["translationOfWork"] == {"@id": f"https://{host}/#webpage"}

    # The operator switches the notice on: this version has nobody behind it.
    switch[MACHINE_NOTICE.key] = True
    assert _get(host, "/de/").json()["machine_text"]["notice"] is True

    with page_source._as(driver.publisher):
        publish_locale_version(page_id=home, locale="de", idempotency_key=page_source._key())

    accepted = _get(host, "/de/").json()
    # Still a machine's text to machines; the company now stands behind it.
    assert accepted["machine_text"] == {"source_type": IPTC_AI, "reviewed": True, "notice": False}
