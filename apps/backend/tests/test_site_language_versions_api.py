"""Writing a page body in another language through the API (ADR-070, plan
TL8c): text units only, an own lock, every problem named by unit, preview
without writing, history and restore."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.sites.models import Page, PageLocaleVersion
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture
def english_page() -> tuple[Any, str]:
    client, _, _ = sites_client(slug="locale-body-api", role_key="owner")
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    save_draft(client, page_id, expected_version=0, idempotency_key="d1", heading="Witaj")
    for locale, slug in (("pl", "start"), ("en", "home")):
        save_translation(
            client,
            page_id,
            locale,
            expected_version=0,
            slug=slug,
            title=slug.title(),
            description="Opis",
            idempotency_key=f"t-{locale}",
        )
    return client, page_id


def _url(page_id: str, locale: str = "en", tail: str = "") -> str:
    return f"/api/v1/sites/pages/{page_id}/translations/{locale}/body/{tail}"


def _send(client: Any, method: str, url: str, payload: dict[str, Any], key: str = "") -> Any:
    return getattr(client, method)(
        url,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        **({"HTTP_IDEMPOTENCY_KEY": key} if key else {}),
    )


def test_a_language_body_lists_the_source_units_and_saves_text_only(english_page):
    client, page_id = english_page
    body = client.get(_url(page_id))
    assert body.status_code == 200
    assert body.data["version"] is None
    assert body.data["body_version"] == 0
    assert body.data["outdated"] is False
    assert [(unit["key"], unit["source_text"]) for unit in body.data["units"]] == [
        ("0/heading", "Witaj"),
        ("1/text", "Treść"),
    ]
    assert body.data["untranslated"] == 2
    page_version = Page.all_objects.get(pk=page_id).version

    payload = {
        "source_version_id": body.data["source_version_id"],
        "expected_body_version": 0,
        "units": {"0/heading": "Welcome"},
    }
    saved = _send(client, "put", _url(page_id), payload, key="s1")
    assert saved.status_code == 201, saved.data
    assert saved.data["body_version"] == 1
    assert saved.data["untranslated"] == 1
    heading = saved.data["units"][0]
    assert (heading["text"], heading["origin"], heading["translated"]) == ("Welcome", "human", True)
    # The language has its own lock; the page's stays where it was.
    assert Page.all_objects.get(pk=page_id).version == page_version
    assert OrganizationAuditEntry.objects.filter(
        action="sites.page.locale_body_saved", target_id=PageLocaleVersion.all_objects.get().id
    ).exists()

    again = _send(client, "put", _url(page_id), payload, key="s1")
    assert again.status_code == 200
    assert PageLocaleVersion.all_objects.count() == 1
    different = _send(client, "put", _url(page_id), {**payload, "units": {"0/heading": "Hi"}}, "s1")
    assert different.status_code == 409
    stale = _send(client, "put", _url(page_id), payload, key="s2")
    assert stale.status_code == 409
    assert stale.data["code"] == "locale_body_version_conflict"
    moved = _send(
        client,
        "put",
        _url(page_id),
        {**payload, "expected_body_version": 1, "source_version_id": page_id},
        key="s3",
    )
    assert moved.status_code == 409
    assert moved.data["code"] == "source_version_mismatch"


def test_every_unit_that_does_not_fit_is_named_and_a_preview_writes_nothing(english_page):
    client, page_id = english_page
    source = client.get(_url(page_id)).data["source_version_id"]
    payload = {
        "source_version_id": source,
        "expected_body_version": 0,
        "units": {"0/heading": "Welcome", "1/text": "x" * 10001, "7/title": "Nowhere"},
    }
    for method, tail, key in (("put", "", "bad"), ("post", "preview/", "")):
        refused = _send(client, method, _url(page_id, tail=tail), payload, key=key)
        assert refused.status_code == 422, refused.data
        assert refused.data["code"] == "locale_unit_invalid"
        assert sorted(
            (error["field"], error["code"]) for error in refused.data["detail"]["errors"]
        ) == [("units.1/text", "too_long"), ("units.7/title", "unknown_unit")]

    payload["units"] = {"0/heading": "Welcome"}
    preview = _send(client, "post", _url(page_id, tail="preview/"), payload)
    assert preview.status_code == 200
    assert preview.data["units"][0]["text"] == "Welcome"
    assert client.get(_url(page_id)).data["body_version"] == 0
    assert not PageLocaleVersion.all_objects.exists()


def test_the_source_language_and_a_language_not_offered_are_refused(english_page):
    client, page_id = english_page
    source = client.get(_url(page_id)).data["source_version_id"]
    payload = {"source_version_id": source, "expected_body_version": 0, "units": {"0/heading": "x"}}
    polish = _send(client, "put", _url(page_id, "pl"), payload, key="pl")
    assert polish.status_code == 400
    assert polish.data["code"] == "locale_is_source"
    german = client.get(_url(page_id, "de"))
    assert german.status_code == 400
    assert german.data["code"] == "locale_not_enabled"


def test_a_copy_starts_a_manual_translation_and_history_restores(english_page):
    client, page_id = english_page
    source = client.get(_url(page_id)).data["source_version_id"]
    copied = _send(
        client,
        "post",
        _url(page_id, tail="copy/"),
        {"source_version_id": source, "expected_body_version": 0},
        key="copy",
    )
    assert copied.status_code == 201
    # The source text stands in and still counts as untranslated.
    assert [unit["text"] for unit in copied.data["units"]] == ["Witaj", "Treść"]
    assert copied.data["untranslated"] == 2

    kept = _send(
        client,
        "put",
        _url(page_id),
        {"source_version_id": source, "expected_body_version": 1, "units": {"0/heading": "Witaj"}},
        key="keep",
    )
    assert kept.data["untranslated"] == 1
    _send(
        client,
        "put",
        _url(page_id),
        {"source_version_id": source, "expected_body_version": 2, "units": {"0/heading": "Hello"}},
        key="hello",
    )

    versions = client.get(_url(page_id, tail="versions/")).data["items"]
    assert [item["number"] for item in versions] == [3, 2, 1]
    first = versions[-1]
    preview = client.get(_url(page_id, tail=f"versions/{first['id']}/"))
    assert preview.data["blocks"][0]["data"]["heading"] == "Witaj"

    restored = _send(
        client,
        "post",
        _url(page_id, tail=f"versions/{first['id']}/restore/"),
        {"expected_body_version": 3},
        key="restore",
    )
    assert restored.status_code == 201
    assert restored.data["version"] == 4
    assert restored.data["units"][0]["origin"] == "copy"
    assert OrganizationAuditEntry.objects.filter(action="sites.page.locale_body_restored").exists()
