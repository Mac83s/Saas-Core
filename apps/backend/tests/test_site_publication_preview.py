"""Before publishing, a person sees what each other language would carry —
the same verdict the publication uses, with nothing saved (TL15b)."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.shared.sites.models import Publication
from test_site_language_decisions import _post
from test_site_language_publication import _publish, _site, _translate_all
from test_site_language_versions_api import _draft, _hero, _translate, _url

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _plan(client: Any, site_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/sites/{site_id}/publications/preview/")
    assert response.status_code == 200, response.data
    return response.json()


def _outcomes(plan: dict[str, Any], locale: str = "en") -> dict[str, tuple[str, str]]:
    language = next(item for item in plan["languages"] if item["locale"] == locale)
    return {page["page_name"]: (page["outcome"], page["reason"]) for page in language["pages"]}


def _english(plan: dict[str, Any]) -> tuple[bool, bool]:
    language = next(item for item in plan["languages"] if item["locale"] == "en")
    return language["live"], language["live_after"]


def test_a_language_waits_for_its_home_page_and_says_which_page_is_why() -> None:
    client, site_id, _home, offer, _host = _site("plan-home-first")
    _translate_all(client, offer, "offer-en")

    plan = _plan(client, site_id)

    assert plan["ready_to_publish"] is True
    assert _english(plan) == (False, False)
    assert _outcomes(plan) == {
        "Start": ("skipped", "untranslated_units"),
        "Oferta": ("skipped", "locale_home_missing"),
    }
    # Asking saves nothing.
    assert Publication.all_objects.filter(site_id=site_id).count() == 0


def test_complete_versions_go_out_and_then_read_as_unchanged() -> None:
    client, site_id, home, offer, _host = _site("plan-publish")
    _translate_all(client, home, "home-en")
    _translate_all(client, offer, "offer-en")

    before = _plan(client, site_id)
    assert _english(before) == (False, True)
    assert _outcomes(before) == {"Start": ("publish", ""), "Oferta": ("publish", "")}

    _publish(client, site_id, "first")
    after = _plan(client, site_id)
    assert _english(after) == (True, True)
    assert _outcomes(after) == {"Start": ("unchanged", ""), "Oferta": ("unchanged", "")}


def test_a_stale_version_is_carried_or_withheld_and_a_withdrawn_one_stays_off() -> None:
    client, site_id, home, offer, _host = _site("plan-carried")
    _translate_all(client, home, "home-en")
    _translate_all(client, offer, "offer-en")
    _publish(client, site_id, "first")
    # New words on the home page, a new price on the offer; English untouched.
    _draft(client, home, 1, [_hero("Witamy", "Studio projektowe")], "home-v2")
    _draft(client, offer, 1, [_hero("Oferta", "Projekt od 150 zł za m²")], "offer-v2")

    stale = _outcomes(_plan(client, site_id))
    assert stale["Start"][0] == "carried"
    assert stale["Oferta"][0] == "withheld"
    assert stale["Start"][1] == stale["Oferta"][1] != ""

    _publish(client, site_id, "second")
    assert _post(client, _url(home, tail="withdraw/"), key="off").status_code == 200
    assert _outcomes(_plan(client, site_id))["Start"] == ("withdrawn", "")


def test_the_body_says_whether_its_current_version_is_the_one_on_the_site() -> None:
    client, site_id, home, _offer, _host = _site("plan-live-version")
    _translate_all(client, home, "home-en")
    fresh = client.get(_url(home)).json()
    assert (fresh["live_version_id"], fresh["version_id"] is not None) == (None, True)

    _publish(client, site_id, "first")
    live = client.get(_url(home)).json()
    assert live["live_version_id"] == live["version_id"]

    key = next(unit["key"] for unit in live["units"] if unit["kind"] == "text")
    assert _translate(client, home, {key: "Welcome again"}, "home-en-2").status_code in (200, 201)
    changed = client.get(_url(home)).json()
    assert changed["live_version_id"] == live["version_id"] != changed["version_id"]
