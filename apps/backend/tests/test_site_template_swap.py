"""Swapping a page's template without losing its content (F4-C): the page's
sections take the template's places the editor matched, the rest follow it,
and only the photos of the template's sections that stay are brought in."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from shutil import copytree
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.media.models import MediaAsset
from saas_core.modules.shared.sites.models import PageVersion
from test_site_own_templates import FAQ, HERO, create, post
from test_sites_api import (
    CleanTemplateMediaScanner,
    TemplateMediaStorage,
    catalogue_template_media,
    create_page,
    create_site,
    csrf_value,
    sites_client,
    template_png,
)

pytestmark = pytest.mark.django_db

MINE_HERO = {
    "block_type": "core.hero",
    "schema_version": 6,
    "data": {"title": "Opieka weterynaryjna w gospodarstwie", "layout": "classic"},
}
MINE_TEXT = {
    "block_type": "core.rich_text",
    "schema_version": 4,
    "data": {
        "layout": "column",
        "content": [{"type": "paragraph", "content": [{"text": "O nas"}]}],
    },
}


def save_page(client: Any, page_id: str, blocks: list[dict[str, Any]]) -> Any:
    return client.put(
        f"/api/v1/sites/pages/{page_id}/draft/",
        {"expected_version": 0, "blocks": blocks, "media_asset_ids": []},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="page",
    )


def test_an_own_template_takes_the_pages_sections_in_its_places_and_after_it() -> None:
    client, organization, _ = sites_client(slug="swap-own")
    page_id = create_page(client, create_site(client).data["id"]).data["id"]
    assert save_page(client, page_id, [MINE_TEXT, MINE_HERO]).status_code == 201
    template = create(client, kind="page", name="Nowy układ", blocks=[HERO, FAQ]).data
    url = f"/api/v1/sites/pages/{page_id}/own-template-import/"
    base = {"expected_version": 1, "template_id": template["id"], "template_version": 1}

    wrong_type = post(client, url, {**base, "kept": [{"slot": 1, "block": MINE_HERO}]}, "k1")
    twice = post(
        client,
        url,
        {**base, "kept": [{"slot": 0, "block": MINE_HERO}, {"slot": 0, "block": MINE_HERO}]},
        "k2",
    )
    swapped = post(
        client,
        url,
        {**base, "kept": [{"slot": 0, "block": MINE_HERO}], "appended": [MINE_TEXT]},
        "k3",
    )

    assert wrong_type.status_code == 400
    assert twice.status_code == 400
    assert swapped.status_code == 201, swapped.data
    blocks = swapped.data["blocks"]
    assert [block["block_type"] for block in blocks] == [
        "core.hero",
        "core.faq",
        "core.rich_text",
    ]
    assert blocks[0]["data"]["title"] == MINE_HERO["data"]["title"]
    assert blocks[1]["data"] == FAQ["data"]
    version = PageVersion.all_objects.get(pk=swapped.data["draft_id"])
    assert (version.origin, version.origin_ref) == ("own_template", "Nowy układ@1")
    audit = OrganizationAuditEntry.objects.get(
        organization=organization, action="sites.page.own_template_imported"
    )
    assert (audit.metadata["kept_sections"], audit.metadata["appended_sections"]) == (1, 1)


def test_a_ready_template_brings_only_the_photos_of_the_sections_that_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saas_core.modules.shared.sites.page_templates import page_template_catalog

    client, organization, _ = sites_client(slug="swap-recipe")
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    snapshot.features["storage.enabled"] = True
    snapshot.quotas["storage.bytes"] = 10 * 1024**2
    snapshot.sources["storage.enabled"] = {"kind": "plan"}
    snapshot.sources["storage.bytes"] = {"kind": "plan"}
    snapshot.save(update_fields=["features", "quotas", "sources", "updated_at"])
    storage, scanner = TemplateMediaStorage(), CleanTemplateMediaScanner()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner
    )
    contracts = tmp_path / "page-templates"
    copytree(Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH), contracts)
    content = template_png()
    photo = contracts / "assets" / "swap" / "hero.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(content)
    recipe_path = contracts / "core.profile.v2.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    [binding] = recipe["mediaBindings"]
    assert recipe["blocks"][binding["blockPosition"]]["block_type"] == "core.hero"
    recipe["media"] = [
        {
            **recipe["media"][0],
            "source": "assets/swap/hero.png",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    catalogue_template_media(contracts, recipe["media"][0])

    page_id = create_page(client, create_site(client).data["id"]).data["id"]
    assert save_page(client, page_id, [MINE_HERO]).status_code == 201
    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts):
            swapped = client.post(
                f"/api/v1/sites/pages/{page_id}/template-import/",
                {
                    "expected_version": 1,
                    "template_id": "core.profile",
                    "template_version": 2,
                    "kept": [{"slot": binding["blockPosition"], "block": MINE_HERO}],
                },
                format="json",
                HTTP_X_CSRFTOKEN=csrf_value(client),
                HTTP_IDEMPOTENCY_KEY="swap",
            )
    finally:
        page_template_catalog.cache_clear()

    assert swapped.status_code == 201, swapped.data
    hero = swapped.data["blocks"][binding["blockPosition"]]
    assert hero["data"]["title"] == MINE_HERO["data"]["title"]
    # The template's hero photo stayed with the template's hero.
    assert MediaAsset.all_objects.filter(organization=organization).count() == 0
    assert storage.objects == {}
    version = PageVersion.all_objects.get(pk=swapped.data["draft_id"])
    assert version.origin_ref == "core.profile@2"
