"""Rich content (phase 1-2): the section presentation envelope, page-local
presentation, images nested in block data, heading anchors, v4 recipes and the
blueprint slot rules. docs/architecture/site-rich-content.md is the contract."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4, uuid7

import pytest
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.shared.media.models import MediaAssetState
from saas_core.modules.shared.sites.blueprints import template_slots
from saas_core.modules.shared.sites.connections import REVIEW_SALT, _review_digest
from saas_core.modules.shared.sites.models import (
    ContentProposal,
    Domain,
    Page,
    PageBlock,
    PageVersion,
    Publication,
    canonical_json_hash,
)
from saas_core.modules.shared.sites.page_templates import (
    PageTemplate,
    PageTemplateCatalog,
    page_template_catalog,
)
from test_content_operations_api import _apply, _change_set, _preview
from test_media_api import MemoryStorage
from test_site_section_decoration import DECORATION
from test_sites_api import (
    CleanTemplateMediaScanner,
    TemplateMediaStorage,
    create_media_asset,
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    rollback_site_request,
    save_translation,
    sites_client,
    template_png,
)
from test_sites_collections import (
    _verified_platform_domain,
    create_collection,
    create_entry,
    publish,
)

pytestmark = pytest.mark.django_db
PRESENTATION = {"schemaVersion": 1, "inner": "wide", "surface": "muted"}
PAGE = {"schemaVersion": 1, "width": "full", "headingFont": "lora", "bodyFont": "inter"}
ORIGINAL_TEMPLATES = (
    "core.profile",
    "core.specialist_landing",
    "core.company",
    "core.service_landing",
    "core.medicine_clinic",
    "core.agriculture_services",
    "core.electronics_service",
    "core.business_studio",
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture
def page_surface():
    client, org, owner = sites_client(slug="rich-content", role_key="owner")
    site = create_site(client).data["id"]
    page = create_page(client, site).data["id"]
    return client, org, owner, site, page


def block(**extra):
    return {"block_type": "core.rich_text", "schema_version": 1, "data": {"text": "Hello"}, **extra}


def para(text):
    return {"type": "paragraph", "content": [{"text": text}]}


def heading(anchor):
    return {"type": "heading", "level": 2, "anchor": anchor, "text": anchor.title()}


def figure(asset_id):
    return {"type": "figure", "image": {"asset_id": str(asset_id), "alt": "Ilustracja"}}


def rich(*nodes, **data):
    return {
        "block_type": "core.rich_text",
        "schema_version": 2,
        "data": {"content": list(nodes), **data},
    }


def product(*asset_ids):
    return {
        "block_type": "core.product",
        "schema_version": 1,
        "data": {
            "title": "Produkt",
            "images": [{"asset_id": str(asset), "alt": "Zdjęcie"} for asset in asset_ids],
        },
    }


def save(client, page, blocks, *, version=0, key="draft", entry=False, media=(), **body):
    return client.put(
        f"/api/v1/sites/{'entries' if entry else 'pages'}/{page}/draft/",
        {
            "expected_version": version,
            "blocks": blocks,
            "media_asset_ids": [str(asset) for asset in media],
            **body,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def ids(values):
    return sorted(str(value) for value in values)


def publish_home(client, site, page, *, key):
    translation = save_translation(
        client, page, "pl", expected_version=0, slug="home", title="Home",
        description="Hello", idempotency_key="translation",
    )
    assert translation.status_code == 201, translation.data
    result = publish_site_request(client, site, idempotency_key=key)
    assert result.status_code == 201, result.data
    return Publication.all_objects.get(pk=result.data["id"])


def public_home(site):
    host = Domain.all_objects.get(site_id=site, is_canonical=True).hostname
    response = APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host)
    assert response.status_code == 200, response.data
    return response.data


def test_presentation_envelope_roundtrip_legacy_hash_null_reset_and_immutability(page_surface):
    client, _, _, site, page = page_surface
    legacy_hash = canonical_json_hash({"blocks": [block()], "media_asset_ids": []})
    styled = save(client, page, [block(presentation=PRESENTATION)])
    assert styled.status_code == 201, styled.data
    assert styled.data["content_hash"] != legacy_hash
    assert styled.data["blocks"][0]["presentation"] == PRESENTATION
    both = save(
        client, page, [block(decoration=DECORATION, presentation=PRESENTATION)],
        version=1, key="both",
    )
    assert both.status_code == 201, both.data
    stored = client.get(f"/api/v1/sites/pages/{page}/draft/").data["blocks"][0]
    assert (stored["decoration"], stored["presentation"]) == (DECORATION, PRESENTATION)
    publication = publish_home(client, site, page, key="publish")
    assert publication.snapshot["pages"][0]["blocks"][0]["presentation"] == PRESENTATION
    assert public_home(site)["blocks"][0]["presentation"] == PRESENTATION
    with pytest.raises(DatabaseError), transaction.atomic():
        PageBlock.all_objects.filter(page_version_id=both.data["draft_id"]).update(
            presentation={"schemaVersion": 1, "inner": "full"}
        )
    reset = save(client, page, [block(presentation=None)], version=2, key="clear")
    assert reset.status_code == 201, reset.data
    assert reset.data["content_hash"] == legacy_hash
    assert "presentation" not in reset.data["blocks"][0]
    assert PageBlock.all_objects.get(page_version_id=reset.data["draft_id"]).presentation is None


@pytest.mark.parametrize(
    "presentation",
    [
        {},
        {"schemaVersion": 2},
        {"schemaVersion": 1, "inner": "huge"},
        {"schemaVersion": 1, "surface": "#ff0000"},
        {"schemaVersion": 1, "width": "full"},
        [],
        "wide",
    ],
)
def test_invalid_section_presentation_is_rejected_without_a_version(page_surface, presentation):
    client, _, _, _, page = page_surface
    result = save(client, page, [block(presentation=presentation)])
    assert result.status_code == 400, result.data
    assert result.data["code"] == "invalid_section_presentation"
    assert not PageVersion.all_objects.filter(page_id=page).exists()


def test_page_presentation_absent_inherits_null_clears_and_travels_with_publication(
    page_surface,
):
    client, _, _, site, page = page_surface
    legacy_hash = canonical_json_hash({"blocks": [block()], "media_asset_ids": []})
    styled_hash = canonical_json_hash(
        {"blocks": [block()], "media_asset_ids": [], "page_presentation": PAGE}
    )
    first = save(client, page, [block()])
    assert first.status_code == 201
    assert first.data["page_presentation"] is None
    assert first.data["content_hash"] == legacy_hash

    styled = save(client, page, [block()], version=1, key="styled", page_presentation=PAGE)
    assert styled.status_code == 201, styled.data
    assert styled.data["page_presentation"] == PAGE
    assert styled.data["content_hash"] == styled_hash
    replay = save(client, page, [block()], version=1, key="styled", page_presentation=PAGE)
    assert replay.status_code == 200
    # The same key without the field is a different request.
    assert save(client, page, [block()], version=1, key="styled").status_code == 409

    # Older clients, which never send the field, keep what a person chose.
    inherited = save(client, page, [block()], version=2, key="inherit")
    assert inherited.status_code == 201, inherited.data
    assert inherited.data["page_presentation"] == PAGE
    assert inherited.data["content_hash"] == styled_hash

    publication = publish_home(client, site, page, key="publish")
    assert publication.snapshot["pages"][0]["page_presentation"] == PAGE
    assert public_home(site)["page_presentation"] == PAGE

    cleared = save(client, page, [block()], version=3, key="clear", page_presentation=None)
    assert cleared.status_code == 201, cleared.data
    assert cleared.data["page_presentation"] is None
    assert cleared.data["content_hash"] == legacy_hash
    assert PageVersion.all_objects.get(pk=cleared.data["draft_id"]).presentation is None
    plain = publish_site_request(client, site, idempotency_key="publish-plain")
    assert plain.status_code == 201, plain.data
    assert "page_presentation" not in Publication.all_objects.get(
        pk=plain.data["id"]
    ).snapshot["pages"][0]
    assert public_home(site)["page_presentation"] is None

    rollback = rollback_site_request(
        client, site, str(publication.id), idempotency_key="rollback"
    )
    assert rollback.status_code == 201, rollback.data
    restored = Publication.all_objects.get(pk=rollback.data["id"])
    assert restored.snapshot["pages"][0]["page_presentation"] == PAGE
    assert public_home(site)["page_presentation"] == PAGE
    preview = client.get(
        f"/api/v1/sites/pages/{page}/preview/{styled.data['draft_id']}/"
    )
    assert preview.status_code == 200
    assert preview.data["page_presentation"] == PAGE
    with pytest.raises(DatabaseError), transaction.atomic():
        PageVersion.all_objects.filter(pk=styled.data["draft_id"]).update(presentation=None)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schemaVersion": 1, "width": "wide"},
        {"schemaVersion": 1, "headingFont": "comic-sans"},
        {"schemaVersion": 1, "inner": "full"},
        ["full"],
    ],
)
def test_invalid_page_presentation_is_rejected_without_a_version(page_surface, value):
    client, _, _, _, page = page_surface
    result = save(client, page, [block()], page_presentation=value)
    assert result.status_code == 400, result.data
    assert result.data["code"] == "invalid_page_presentation"
    assert not PageVersion.all_objects.filter(page_id=page).exists()


def test_change_set_keeps_presentation_inherits_page_presentation_and_references_media(
    page_surface,
):
    client, org, owner, site, page = page_surface
    asset = create_media_asset(org, owner)
    saved = save(
        client, page, [block(presentation=PRESENTATION), block()], page_presentation=PAGE
    )
    assert saved.status_code == 201, saved.data
    target = {"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"}
    base = client.get("/api/v1/sites/content-base/", target).json()
    assert base["blocks"][0]["presentation"] == PRESENTATION
    replacement = rich(heading("intro"), para("Nowy tekst"), figure(asset.id))
    doc = _change_set(
        target=target,
        base=base["base"],
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 2,
                    "data": replacement["data"],
                },
            },
        ],
    )
    preview = _preview(client, doc)
    assert preview.status_code == 200, preview.data
    assert preview.data["blocks_after"][0]["presentation"] == PRESENTATION
    result = _apply(
        client,
        doc,
        approval_digest=preview.data["approval_digest"],
        approval_token=preview.data["approval_token"],
    )
    assert result.status_code == 201, result.data
    draft = client.get(f"/api/v1/sites/pages/{page}/draft/").data
    assert draft["blocks"][0]["schema_version"] == 2
    assert draft["blocks"][0]["presentation"] == PRESENTATION
    assert draft["page_presentation"] == PAGE
    # The connector's figure is referenced although the old list did not name it.
    assert ids(draft["media_asset_ids"]) == ids([asset.id])
    proposal = ContentProposal.all_objects.get(id=result.data["proposal_id"])
    detail = client.get(f"/api/v1/sites/proposals/{proposal.id}/").data
    assert detail["page_presentation_before"] == PAGE
    assert detail["page_presentation_after"] == PAGE
    signed = signing.loads(detail["review_token"], salt=REVIEW_SALT)
    assert signed["digest"] == _review_digest(proposal, detail["blocks_after"], PAGE)
    assert signed["digest"] != _review_digest(proposal, detail["blocks_after"])


def test_discard_restores_the_previous_page_presentation(page_surface, monkeypatch):
    client, _, _, site, _ = page_surface
    template = PageTemplate(
        id="core.presentation_test",
        version=1,
        category="article",
        labels={
            "pl": {"name": "Test", "description": "Test"},
            "en": {"name": "Test", "description": "Test"},
        },
        required_entitlements=(),
        media=(),
        blocks=(rich(heading("intro"), para("Tekst")),),
        page_presentation=PAGE,
    )
    catalog = PageTemplateCatalog(templates={template.id: {1: template}})
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.page_templates.page_template_catalog", lambda: catalog
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.blueprints.page_template_catalog", lambda: catalog
    )
    listing = client.get("/api/v1/sites/blueprint-catalog/", {"site_id": str(site)}).data
    item = listing["templates"][0]
    accepted = client.post(
        f"/api/v1/sites/{site}/blueprint-draft/",
        {
            "generation_id": str(uuid4()),
            "catalog_hash": listing["catalog_hash"],
            "template_id": template.id,
            "template_version": 1,
            "slots": {slot["key"]: "Przygotowany tekst" for slot in item["slots"]},
            "locale": "pl",
            "name": "Blueprint",
            "key": "blueprint",
            "idempotency_key": "blueprint",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert accepted.status_code == 201, accepted.data
    page = Page.all_objects.get(id=accepted.data["page_id"])
    assert page.current_draft.presentation == PAGE
    detail = client.get(f"/api/v1/sites/proposals/{accepted.data['proposal_id']}/").data
    assert detail["page_presentation_after"] == PAGE
    assert "page_presentation_before" not in detail
    discarded = client.post(
        f"/api/v1/sites/proposals/{accepted.data['proposal_id']}/discard/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert discarded.status_code == 200, discarded.data
    page.refresh_from_db()
    assert page.current_draft.number == 2
    assert page.current_draft.presentation is None


def test_nested_media_is_referenced_published_and_served(page_surface, monkeypatch):
    client, org, owner, site, page = page_surface
    figure_asset = create_media_asset(org, owner)
    gallery_asset = create_media_asset(org, owner)
    expected = ids([figure_asset.id, gallery_asset.id])
    blocks = [rich(para("Tekst"), figure(figure_asset.id)), product(gallery_asset.id)]
    implicit = save(client, page, blocks)
    assert implicit.status_code == 201, implicit.data
    assert ids(implicit.data["media_asset_ids"]) == expected
    other = create_page(client, site, key="other", idempotency_key="other").data["id"]
    explicit = save(client, other, blocks, media=expected)
    assert explicit.status_code == 201, explicit.data
    # A client that already lists everything gets the same content hash.
    assert explicit.data["content_hash"] == implicit.data["content_hash"]

    missing = save(client, page, [rich(figure(uuid7()))], version=1, key="missing")
    assert missing.status_code == 409, missing.data
    assert missing.data["code"] == "site_media_reference_unavailable"
    scanning = create_media_asset(org, owner, state=MediaAssetState.SCANNING)
    unready = save(client, page, [product(scanning.id)], version=1, key="unready")
    assert unready.status_code == 409, unready.data

    save_translation(
        client, other, "pl", expected_version=0, slug="other", title="Other",
        description="Other", idempotency_key="translation-other",
    )
    publication = publish_home(client, site, page, key="publish")
    assert ids(publication.snapshot["pages"][0]["media_asset_ids"]) == expected
    storage = MemoryStorage()
    storage.objects[figure_asset.object_key] = (b"\x89PNG\r\n\x1a\n", "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    platform = _verified_platform_domain(site)
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        served = APIClient().get(
            f"/api/v1/public/site/media/{figure_asset.id}/", HTTP_HOST=platform.hostname
        )
    assert served.status_code == 200
    assert served.content == b"\x89PNG\r\n\x1a\n"

    collection = create_collection(client, site).data["id"]
    entry = create_entry(client, collection, slug="wpis", idempotency_key="entry").data["id"]
    entry_draft = save(client, entry, blocks, entry=True, key="entry")
    assert entry_draft.status_code == 201, entry_draft.data
    assert ids(entry_draft.data["media_asset_ids"]) == expected
    assert publish(client, entry, idempotency_key="entry-publish").status_code == 201


@pytest.mark.parametrize(
    "blocks",
    [
        [rich(heading("intro"), para("A"), heading("intro"))],
        [rich(heading("intro")), block(), rich(heading("intro"))],
    ],
)
def test_duplicate_heading_anchors_are_refused_on_pages_and_entries(page_surface, blocks):
    client, _, _, site, page = page_surface
    result = save(client, page, blocks)
    assert result.status_code == 400, result.data
    assert result.data["code"] == "duplicate_rich_text_anchor"
    assert not PageVersion.all_objects.filter(page_id=page).exists()
    collection = create_collection(client, site).data["id"]
    entry = create_entry(client, collection, slug="wpis", idempotency_key="entry").data["id"]
    refused = save(client, entry, blocks, entry=True, key="entry")
    assert refused.status_code == 400, refused.data
    assert refused.data["code"] == "duplicate_rich_text_anchor"
    unique = save(client, page, [rich(heading("intro")), rich(heading("intro-2"))], key="ok")
    assert unique.status_code == 201, unique.data


def test_change_set_inserting_a_duplicate_anchor_is_refused_at_preview(page_surface):
    client, _, _, site, page = page_surface
    assert save(client, page, [rich(heading("intro"), para("Tekst"))]).status_code == 201
    target = {"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"}
    doc = _change_set(
        target=target,
        base=client.get("/api/v1/sites/content-base/", target).data["base"],
        commands=[
            {
                "command": "block.insert",
                "position": 1,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 2,
                    "data": {"content": [heading("intro")]},
                },
            },
        ],
    )
    response = _preview(client, doc)
    assert response.status_code == 400, response.data
    assert response.data["code"] == "duplicate_rich_text_anchor"


def _binding(position, path=None, alt="Zdjęcie"):
    return {
        "blockPosition": position,
        "mediaId": "photo",
        "alt": {"pl": alt, "en": f"{alt} EN"},
        **({"path": path} if path is not None else {}),
    }


def _recipe(sha256="0" * 64):
    blocks = [
        {
            "block_type": "core.product",
            "schema_version": 1,
            "data": {"title": "Produkt", "images": []},
            "presentation": PRESENTATION,
        },
        {
            "block_type": "core.rich_text",
            "schema_version": 2,
            # The figure is only valid once its image is bound.
            "data": {"content": [para("Wstęp"), {"type": "figure", "caption": "Podpis"}]},
            "decoration": DECORATION,
        },
        {"block_type": "core.hero", "schema_version": 5, "data": {"title": "Hero"}},
    ]
    return {
        "id": "core.rich_fixture",
        "version": 1,
        "category": "article",
        "labels": {
            "pl": {"name": "Fixture", "description": "Fixture"},
            "en": {"name": "Fixture", "description": "Fixture"},
        },
        "pagePresentation": PAGE,
        "media": [
            {
                "id": "photo",
                "source": "assets/fixture/photo.png",
                "filename": "photo.png",
                "contentType": "image/png",
                "sha256": sha256,
            }
        ],
        "blocks": blocks,
        "localizedBlocks": {"en": deepcopy(blocks)},
        "mediaBindings": [
            _binding(0, ["images", 0]),
            _binding(0, ["images", 1]),
            _binding(1, ["content", 1, "image"]),
            _binding(2),
        ],
    }


def _write_contracts(tmp_path: Path, recipe: dict[str, Any]) -> Path:
    contracts = tmp_path / "page-templates"
    contracts.mkdir(exist_ok=True)
    source = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["templates"] = [
        {"id": recipe["id"], "latestVersion": 1, "versions": {"1": "fixture.v1.json"}}
    ]
    (contracts / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (contracts / manifest["recipe"]).write_text(
        (source / manifest["recipe"]).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (contracts / "fixture.v1.json").write_text(json.dumps(recipe), encoding="utf-8")
    return contracts


def _load(tmp_path: Path, recipe: dict[str, Any]) -> PageTemplateCatalog:
    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=_write_contracts(tmp_path, recipe)):
            return page_template_catalog()
    finally:
        page_template_catalog.cache_clear()


def test_v4_recipe_binds_images_by_path_and_keeps_its_presentation(tmp_path):
    template = _load(tmp_path, _recipe()).get(template_id="core.rich_fixture", version=1)
    assert template.page_presentation == PAGE
    for locale in ("pl", "en"):
        blocks = template.draft_blocks(locale)
        template.bind_media(blocks, {"photo": "asset"}, locale)
        image = {"asset_id": "asset", "alt": "Zdjęcie" if locale == "pl" else "Zdjęcie EN"}
        assert blocks[0]["data"]["images"] == [image, image]
        assert blocks[0]["presentation"] == PRESENTATION
        assert blocks[1]["data"]["content"][1]["image"] == image
        assert blocks[1]["decoration"] == DECORATION
        # A binding without a path is the v3 behaviour.
        assert blocks[2]["data"]["image"] == image
    # The recipe itself stays free of asset ids.
    assert template.blocks[0]["data"]["images"] == []


def test_historical_recipes_still_load_under_the_v4_recipe_contract():
    page_template_catalog.cache_clear()
    try:
        catalog = page_template_catalog()
    finally:
        page_template_catalog.cache_clear()
    assert set(ORIGINAL_TEMPLATES) <= set(catalog.templates)
    assert catalog.get(template_id="core.profile", version=1).page_presentation is None


def _drop_figure_binding(recipe):
    recipe["mediaBindings"].pop(2)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda r: r["mediaBindings"].__setitem__(2, _binding(1, ["content", 5, "image"])),
            id="missing-parent",
        ),
        pytest.param(
            lambda r: r["mediaBindings"].__setitem__(0, _binding(0, ["images", 3])),
            id="index-past-end",
        ),
        pytest.param(
            lambda r: r["mediaBindings"].__setitem__(0, _binding(0, ["title", "image"])),
            id="through-a-string",
        ),
        pytest.param(
            lambda r: r["mediaBindings"].append(_binding(0, ["images", 1])), id="duplicate"
        ),
        pytest.param(lambda r: r["mediaBindings"].append(_binding(2)), id="duplicate-default"),
        pytest.param(lambda r: r["mediaBindings"].append(_binding(7)), id="position"),
        pytest.param(_drop_figure_binding, id="unbound-figure"),
        pytest.param(
            lambda r: r.__setitem__("pagePresentation", {"schemaVersion": 1, "width": "wide"}),
            id="page-presentation",
        ),
        pytest.param(
            lambda r: r["blocks"][0].__setitem__("presentation", {"schemaVersion": 3}),
            id="block-presentation",
        ),
        pytest.param(
            lambda r: r["localizedBlocks"]["en"][1].__setitem__("decoration", {"css": "x"}),
            id="block-decoration",
        ),
        pytest.param(
            lambda r: r["blocks"][1]["data"]["content"].extend([heading("wstep")] * 2),
            id="duplicate-anchor",
        ),
    ],
)
def test_broken_v4_recipes_fail_loudly(tmp_path, mutate):
    recipe = _recipe()
    mutate(recipe)
    with pytest.raises(ImproperlyConfigured):
        _load(tmp_path, recipe)


def test_v4_recipe_import_binds_nested_images_and_sets_page_presentation(
    page_surface, tmp_path, monkeypatch
):
    client, org, _, _, page = page_surface
    from saas_core.modules.shared.billing.models import EntitlementSnapshot

    snapshot = EntitlementSnapshot.all_objects.get(organization=org)
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
    content = template_png()
    contracts = _write_contracts(tmp_path, _recipe(hashlib.sha256(content).hexdigest()))
    (contracts / "assets" / "fixture").mkdir(parents=True)
    (contracts / "assets" / "fixture" / "photo.png").write_bytes(content)
    assert save(client, page, [block()], page_presentation=None).status_code == 201
    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts):
            imported = client.post(
                f"/api/v1/sites/pages/{page}/template-import/",
                {
                    "expected_version": 1,
                    "template_id": "core.rich_fixture",
                    "template_version": 1,
                    "locale": "en",
                },
                format="json",
                HTTP_X_CSRFTOKEN=csrf_value(client),
                HTTP_IDEMPOTENCY_KEY="import",
            )
    finally:
        page_template_catalog.cache_clear()
    assert imported.status_code == 201, imported.data
    [asset] = imported.data["media_asset_ids"]
    image = {"asset_id": str(asset), "alt": "Zdjęcie EN"}
    assert imported.data["blocks"][0]["data"]["images"] == [image, image]
    assert imported.data["blocks"][1]["data"]["content"][1]["image"] == image
    assert imported.data["blocks"][0]["presentation"] == PRESENTATION
    assert imported.data["page_presentation"] == PAGE


def _legacy_slots(template: PageTemplate) -> list[dict[str, Any]]:
    """template_slots before rich content, verbatim, to pin existing recipes."""
    fields = {"title", "text", "question", "answer", "label", "subtitle"}
    slots: list[dict[str, Any]] = []

    def visit(value: Any, path: str, field: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + "/" + key, key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + "/" + str(index))
        elif isinstance(value, str) and field in fields:
            slots.append({
                "key": path,
                "kind": "text",
                "max_length": 2000 if field in {"text", "answer"} else 200,
                "default": value,
            })

    for index, block in enumerate(template.blocks):
        if block["block_type"] in {"core.pricing", "core.legal"}:
            continue
        visit(block["data"], f"/{index}/data")
    return slots


def test_existing_recipes_keep_their_blueprint_slots():
    page_template_catalog.cache_clear()
    try:
        catalog = page_template_catalog()
    finally:
        page_template_catalog.cache_clear()
    for template_id in ORIGINAL_TEMPLATES:
        versions = catalog.templates[template_id]
        template = versions[max(versions)]
        assert template_slots(template) == _legacy_slots(template), template_id


def test_blueprint_slots_skip_quotes_blank_runs_and_captions():
    template = PageTemplate(
        id="core.slots_test",
        version=1,
        category="article",
        labels={},
        required_entitlements=(),
        media=(),
        blocks=(
            rich(
                heading("intro"),
                {
                    "type": "paragraph",
                    "content": [
                        {"text": "Pierwszy", "bold": True},
                        {"text": " "},
                        {"text": "drugi"},
                    ],
                },
                {"type": "quote", "content": [{"text": "Cytat"}], "author": "Autor"},
                {"type": "figure", "image": {"asset_id": str(uuid7()), "alt": "A"}, "caption": "P"},
                title="Tytuł",
                lead="Wstęp",
            ),
            {
                "block_type": "core.quote",
                "schema_version": 1,
                "data": {"quote": "Słowa", "author": "Ktoś", "context": "Kontekst"},
            },
            {
                "block_type": "core.product",
                "schema_version": 1,
                "data": {"title": "Produkt", "tagline": "Hasło", "text": "Opis"},
            },
        ),
    )
    slots = {slot["key"]: slot["max_length"] for slot in template_slots(template)}
    assert slots == {
        # The heuristic keys on the field name; the block schema still caps it.
        "/0/data/content/0/text": 2000,
        "/0/data/content/1/content/0/text": 2000,
        "/0/data/content/1/content/2/text": 2000,
        "/0/data/title": 200,
        "/0/data/lead": 1200,
        "/2/data/title": 200,
        "/2/data/tagline": 200,
        "/2/data/text": 2000,
    }


def test_missing_presentation_contracts_are_detected_before_runtime(tmp_path):
    from shutil import copytree

    from saas_core.modules.shared.sites.apps import check_content_contracts
    from saas_core.modules.shared.sites.block_decoration import (
        page_presentation_validator,
        presentation_validator,
        validate_page_presentation,
        validate_presentation,
    )

    assert check_content_contracts() == []
    contracts = copytree(settings.SITE_BLOCK_CONTRACTS_PATH, tmp_path / "blocks")
    (contracts / "section-presentation.v1.schema.json").unlink()
    (contracts / "page-presentation.v1.schema.json").unlink()
    try:
        with override_settings(SITE_BLOCK_CONTRACTS_PATH=contracts):
            presentation_validator.cache_clear()
            page_presentation_validator.cache_clear()
            assert [error.id for error in check_content_contracts()] == [
                "sites.E007",
                "sites.E008",
            ]
            with pytest.raises(ImproperlyConfigured, match="wyglądu sekcji"):
                validate_presentation(PRESENTATION)
            with pytest.raises(ImproperlyConfigured, match="wyglądu strony"):
                validate_page_presentation(PAGE)
    finally:
        presentation_validator.cache_clear()
        page_presentation_validator.cache_clear()
