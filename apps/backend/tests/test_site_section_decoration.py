from copy import deepcopy
from uuid import uuid4, uuid7

import pytest
from django.core import signing
from django.core.cache import cache
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from saas_core.modules.shared.sites.connections import REVIEW_SALT, _review_digest
from saas_core.modules.shared.sites.models import (
    ContentEntryPublication,
    ContentProposal,
    Page,
    PageBlock,
    PageVersion,
    Publication,
    canonical_json_hash,
)
from saas_core.modules.shared.sites.page_templates import PageTemplate, PageTemplateCatalog
from test_content_operations_api import _apply, _change_set, _preview
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_translation,
    sites_client,
)
from test_sites_collections import create_collection, create_entry, publish

pytestmark = pytest.mark.django_db
DECORATION = {
    "schemaVersion": 1,
    "background": "tint",
    "frame": "outline",
    "ornament": "rings",
    "placement": "top_right",
    "intensity": "subtle",
    "motion": "drift",
}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture
def page_surface():
    client, org, owner = sites_client(slug="section-decoration", role_key="owner")
    site = create_site(client).data["id"]
    page = create_page(client, site).data["id"]
    return client, org, owner, site, page


def block(**extra):
    return {"block_type": "core.rich_text", "schema_version": 1, "data": {"text": "Hello"}, **extra}


def save(client, page, blocks, *, version=0, key="draft", entry=False):
    return client.put(
        f"/api/v1/sites/{'entries' if entry else 'pages'}/{page}/draft/",
        {"expected_version": version, "blocks": blocks, "media_asset_ids": []},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_page_roundtrip_hashes_snapshot_immutability_and_null_reset(page_surface):
    client, _, _, site, page = page_surface
    legacy = save(client, page, [block()])
    assert legacy.status_code == 201, legacy.data
    expected_legacy_hash = canonical_json_hash({"blocks": [block()], "media_asset_ids": []})
    assert legacy.data["content_hash"] == expected_legacy_hash
    assert "decoration" not in legacy.data["blocks"][0]
    assert PageBlock.all_objects.get(page_version_id=legacy.data["draft_id"]).decoration is None
    decorated = save(client, page, [block(decoration=DECORATION)], version=1, key="decorated")
    assert decorated.status_code == 201, decorated.data
    assert decorated.data["content_hash"] != expected_legacy_hash
    assert (
        client.get(f"/api/v1/sites/pages/{page}/draft/").data["blocks"][0]["decoration"]
        == DECORATION
    )
    assert (
        save(client, page, [block(decoration=DECORATION)], version=1, key="decorated").status_code
        == 200
    )
    changed = {**DECORATION, "motion": "breathe"}
    assert (
        save(client, page, [block(decoration=changed)], version=1, key="decorated").status_code
        == 409
    )
    translation = save_translation(
        client,
        page,
        "pl",
        expected_version=0,
        slug="home",
        title="Home",
        description="Hello",
        idempotency_key="translation",
    )
    assert translation.status_code == 201
    result = publish_site_request(client, site, idempotency_key="publish")
    assert result.status_code == 201, result.data
    publication = Publication.all_objects.get(site_id=site)
    snapshot = deepcopy(publication.snapshot)
    assert snapshot["pages"][0]["blocks"][0]["decoration"] == DECORATION
    with pytest.raises(DatabaseError), transaction.atomic():
        PageBlock.all_objects.filter(page_version_id=decorated.data["draft_id"]).update(
            decoration=changed
        )
    reset = save(client, page, [block(decoration=None)], version=2, key="clear")
    assert reset.status_code == 201
    assert reset.data["content_hash"] == expected_legacy_hash
    assert "decoration" not in reset.data["blocks"][0]
    publication.refresh_from_db()
    assert publication.snapshot == snapshot
    assert (
        PageBlock.all_objects.get(page_version_id=decorated.data["draft_id"]).decoration
        == DECORATION
    )
    from saas_core.modules.shared.sites.models import Domain

    host = Domain.all_objects.get(site_id=site, is_canonical=True).hostname
    public = APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host)
    assert public.status_code == 200
    assert public.data["blocks"][0]["decoration"] == DECORATION


@pytest.mark.parametrize(
    "decoration",
    [
        {},
        {"schemaVersion": 2},
        {"schemaVersion": True},
        [],
        "tint",
        1,
        {"schemaVersion": 1, "background": "url(https://example.test/x)"},
        {"schemaVersion": 1, "frame": "custom"},
        {"schemaVersion": 1, "ornament": "<svg>"},
        {"schemaVersion": 1, "placement": "fixed"},
        {"schemaVersion": 1, "intensity": "bright"},
        {"schemaVersion": 1, "motion": "flash"},
        {"schemaVersion": 1, "css": "position:fixed"},
    ],
)
def test_invalid_decoration_is_rejected_without_a_version(page_surface, decoration):
    client, _, _, _, page = page_surface
    result = save(client, page, [block(decoration=decoration)])
    assert result.status_code == 400, result.data
    assert result.data["code"] == "invalid_section_decoration"
    assert not PageVersion.all_objects.filter(page_id=page).exists()


@pytest.mark.parametrize("denial", ["permission", "entitlement"])
def test_decoration_cannot_bypass_service_authorization(denial):
    client, _, _ = sites_client(
        slug=f"deco-{denial}",
        role_key="viewer" if denial == "permission" else "owner",
        feature_enabled=denial != "entitlement",
    )
    result = save(client, uuid7(), [block(decoration={"schemaVersion": 999})])
    assert result.status_code == 403


def test_v1_content_operations_preserve_decoration_and_bind_review_digest(page_surface):
    client, _, _, site, page = page_surface
    assert save(client, page, [block(decoration=DECORATION), block()]).status_code == 201
    target = {"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"}
    base = client.get("/api/v1/sites/content-base/", target).json()
    assert base["blocks"][0]["decoration"] == DECORATION
    doc = _change_set(
        target=target,
        base=base["base"],
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Changed by connector"},
                },
            },
            {"command": "block.reorder", "order": [1, 0]},
        ],
    )
    preview = _preview(client, doc)
    assert preview.status_code == 200, preview.data
    assert preview.data["blocks_after"][1]["decoration"] == DECORATION
    result = _apply(
        client,
        doc,
        approval_digest=preview.data["approval_digest"],
        approval_token=preview.data["approval_token"],
    )
    assert result.status_code == 201, result.data
    draft = client.get(f"/api/v1/sites/pages/{page}/draft/").data
    assert draft["blocks"][1]["decoration"] == DECORATION
    assert draft["blocks"][1]["data"]["text"] == "Changed by connector"
    proposal = ContentProposal.all_objects.get(id=result.data["proposal_id"])
    detail = client.get(f"/api/v1/sites/proposals/{proposal.id}/").data
    assert detail["blocks_after"][1]["decoration"] == DECORATION
    signed = signing.loads(detail["review_token"], salt=REVIEW_SALT)
    assert signed["digest"] == _review_digest(proposal, detail["blocks_after"])
    changed = deepcopy(detail["blocks_after"])
    changed[1]["decoration"]["motion"] = "breathe"
    assert signed["digest"] != _review_digest(proposal, changed)


@pytest.mark.parametrize("value", [None, DECORATION])
def test_frozen_v1_content_operation_refuses_setting_decoration_explicitly(page_surface, value):
    client, _, _, site, page = page_surface
    assert save(client, page, [block(decoration=DECORATION)]).status_code == 201
    target = {"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"}
    doc = _change_set(
        target=target,
        base=client.get("/api/v1/sites/content-base/", target).data["base"],
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "New"},
                    "decoration": value,
                },
            },
        ],
    )
    response = _preview(client, doc)
    assert response.status_code == 400
    assert response.data["code"] == "change_set_malformed"
    assert PageVersion.all_objects.filter(page_id=page).count() == 1


def test_entry_roundtrip_content_operation_and_publication(page_surface):
    client, _, _, site, _ = page_surface
    collection = create_collection(client, site).data["id"]
    entry = create_entry(client, collection, slug="decorated", idempotency_key="entry").data["id"]
    saved = save(client, entry, [block(decoration=DECORATION)], entry=True)
    assert saved.status_code == 201, saved.data
    assert (
        client.get(f"/api/v1/sites/entries/{entry}/draft/").data["blocks"][0]["decoration"]
        == DECORATION
    )
    target = {
        "kind": "content_entry",
        "site_id": str(site),
        "collection_id": str(collection),
        "entry_id": str(entry),
        "locale": "pl",
    }
    doc = _change_set(
        target=target,
        base=client.get("/api/v1/sites/content-base/", target).data["base"],
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Article updated"},
                },
            },
        ],
    )
    preview = _preview(client, doc)
    assert preview.status_code == 200, preview.data
    result = _apply(
        client,
        doc,
        approval_digest=preview.data["approval_digest"],
        approval_token=preview.data["approval_token"],
    )
    assert result.status_code == 201, result.data
    assert (
        client.get(f"/api/v1/sites/entries/{entry}/draft/").data["blocks"][0]["decoration"]
        == DECORATION
    )
    assert publish(client, entry, idempotency_key="publish-entry").status_code == 201
    snapshot = ContentEntryPublication.all_objects.get(entry_id=entry).snapshot
    assert snapshot["blocks"][0]["decoration"] == DECORATION
    reset = save(client, entry, [block(decoration=None)], version=2, key="entry-clear", entry=True)
    assert reset.status_code == 201
    assert "decoration" not in reset.data["blocks"][0]
    assert ContentEntryPublication.all_objects.get(entry_id=entry).snapshot == snapshot


def test_blueprint_preserves_approved_decoration_but_text_slots_cannot_change_it(
    page_surface, monkeypatch
):
    client, _, _, site, _ = page_surface
    template = PageTemplate(
        id="core.decoration_test",
        version=1,
        category="profile",
        labels={
            "pl": {"name": "Test", "description": "Test"},
            "en": {"name": "Test", "description": "Test"},
        },
        required_entitlements=(),
        media=(),
        blocks=(block(decoration=DECORATION),),
    )
    catalog = PageTemplateCatalog(templates={template.id: {1: template}})
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.page_templates.page_template_catalog", lambda: catalog
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.blueprints.page_template_catalog", lambda: catalog
    )
    response = client.get("/api/v1/sites/blueprint-catalog/", {"site_id": str(site)})
    assert response.status_code == 200, response.data
    item = response.data["templates"][0]
    assert all("decoration" not in slot["key"] for slot in item["slots"])
    document = {
        "generation_id": str(uuid4()),
        "catalog_hash": response.data["catalog_hash"],
        "template_id": template.id,
        "template_version": 1,
        "slots": {slot["key"]: "Prepared text" for slot in item["slots"]},
        "locale": "pl",
        "name": "Decorated blueprint",
        "key": "decorated-blueprint",
        "idempotency_key": "decorated-blueprint",
    }
    url = f"/api/v1/sites/{site}/blueprint-draft/"
    hostile = deepcopy(document)
    hostile["slots"]["/0/decoration/background"] = "gradient"
    denied = client.post(url, hostile, format="json", HTTP_X_CSRFTOKEN=csrf_value(client))
    assert denied.status_code == 422, denied.data
    accepted = client.post(url, document, format="json", HTTP_X_CSRFTOKEN=csrf_value(client))
    assert accepted.status_code == 201, accepted.data
    page = Page.all_objects.get(id=accepted.data["page_id"])
    assert page.current_draft.blocks.get().decoration == DECORATION
    assert page.current_draft.blocks.get().data["text"] == "Prepared text"
    detail = client.get(f"/api/v1/sites/proposals/{accepted.data['proposal_id']}/").data
    assert detail["blocks_after"][0]["decoration"] == DECORATION


def test_separator_uses_the_same_decoration_envelope(page_surface):
    client, _, _, _, page = page_surface
    separator = {
        "block_type": "core.separator",
        "schema_version": 1,
        "data": {"layout": "wave", "size": "small", "width": "full", "tone": "accent"},
        "decoration": DECORATION,
    }
    result = save(client, page, [block(), separator, block()])
    assert result.status_code == 201, result.data
    stored = client.get(f"/api/v1/sites/pages/{page}/draft/").data["blocks"][1]
    assert {key: stored[key] for key in separator} == separator


def test_missing_decoration_contract_is_detected_before_runtime(settings, tmp_path):
    from shutil import copytree

    from django.core.exceptions import ImproperlyConfigured
    from django.test import override_settings

    from saas_core.modules.shared.sites.apps import check_content_contracts
    from saas_core.modules.shared.sites.block_decoration import (
        decoration_validator,
        validate_decoration,
    )

    assert check_content_contracts() == []
    validate_decoration(DECORATION)
    contracts = copytree(settings.SITE_BLOCK_CONTRACTS_PATH, tmp_path / "blocks")
    (contracts / "section-decoration.v1.schema.json").unlink()
    try:
        with override_settings(SITE_BLOCK_CONTRACTS_PATH=contracts):
            decoration_validator.cache_clear()
            assert [error.id for error in check_content_contracts()] == ["sites.E006"]
            with pytest.raises(ImproperlyConfigured, match="kontrakt dekoracji"):
                validate_decoration(DECORATION)
    finally:
        decoration_validator.cache_clear()
