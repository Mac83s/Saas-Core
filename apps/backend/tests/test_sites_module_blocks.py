"""Block types a module brings to the site builder (ADR-077,
docs/architecture/site-block-types.md).

The core ships none of its own beyond `core.*`, so the proof is a test-only
vertical, `vertical.sample`: its contract is the fixture
`packages/contracts/site-blocks/fixtures/modules/vertical.sample`, composed
here the way a product's profile composes its vertical. One block a person
places on a page (`record_list`, filled live by the module's public source)
and one the module builds for a record's own page (`record_profile`, written
by nobody). Without the module in the composition neither type exists.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from saas_core.config.composition import ModuleDescriptor
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.core.organizations.public_sources import (
    PageAddress,
    PublicSource,
    SiteBlock,
    SourcePage,
    SourcePageAddress,
)
from saas_core.modules.shared.sites import api as sites_api
from saas_core.modules.shared.sites.api import validate_built_site_block
from saas_core.modules.shared.sites.apps import check_content_contracts
from saas_core.modules.shared.sites.block_contracts import (
    InvalidSiteBlockData,
    ServerBuiltSiteBlock,
    UnknownSiteBlockType,
    module_block_prefix,
    site_block_contracts,
    validate_site_block,
)
from saas_core.modules.shared.sites.localized_bodies import (
    DATA_PUBLIC,
    DATA_PUBLIC_PERSONAL,
    UNIT_NAME,
    UNIT_TEXT,
    assemble,
    extract_units,
    text_fields,
)
from saas_core.modules.shared.sites.models import Site
from test_site_language_publication import _get, _publish, _site, _translate_all
from test_site_language_versions_api import _hero, _page, _translate, _url
from test_sites_api import create_page, create_site, csrf_value, sites_client
from test_sites_collections import _verified_platform_domain

pytestmark = pytest.mark.django_db

MODULE = "vertical.sample"
FIXTURES = Path(settings.SITE_BLOCK_CONTRACTS_PATH) / "fixtures" / "modules"
LIST = "vertical.sample.record_list"
PROFILE = "vertical.sample.record_profile"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _forget_contracts() -> None:
    """The contracts are read once per process; a test that changes the
    composition reads them again, and puts the suite's own back."""
    site_block_contracts.cache_clear()
    text_fields.cache_clear()


@pytest.fixture
def composed() -> Iterator[Any]:
    """A deployment whose profile composes `vertical.sample`, the way a
    product's profile composes its vertical: `compose(directory)` — by
    default with the fixture's block types."""
    opened: list[Any] = []

    def compose(directory: Path = FIXTURES, modules: tuple[str, ...] = (MODULE,)) -> None:
        override = override_settings(
            ACTIVE_MODULES=(*settings.ACTIVE_MODULES, *modules),
            KNOWN_MODULES=frozenset({*settings.KNOWN_MODULES, *modules}),
            MODULE_CATALOG={
                **settings.MODULE_CATALOG,
                **{
                    module: ModuleDescriptor(
                        id=module, layer="vertical", depends_on=("shared.sites",), django_app=None
                    )
                    for module in modules
                },
            },
            SITE_BLOCK_MODULE_CONTRACTS_PATH=directory,
        )
        override.enable()
        opened.append(override)
        _forget_contracts()

    yield compose
    for override in reversed(opened):
        override.disable()
    _forget_contracts()


def list_block(version: int = 2, **data: Any) -> dict[str, Any]:
    return {
        "block_type": LIST,
        "schema_version": version,
        "data": {"heading": "Nasze rekordy", **data},
    }


def profile_block(name: str = "Rekord pierwszy") -> dict[str, Any]:
    return {
        "block_type": PROFILE,
        "schema_version": 1,
        "data": {
            "name": name,
            "summary": "Krótko o rekordzie.",
            "facts": [{"label": "Pochodzenie", "value": "Polska"}],
            "ratings": [{"label": "Energia", "value": 4}],
            "sections": [{"heading": "Charakter", "text": "Spokojny i uważny."}],
            "related": [{"name": "Rekord drugi", "href": "/samples/second/"}],
        },
    }


def _save_draft(client: Any, page_id: str, blocks: list[dict[str, Any]], key: str) -> Any:
    return client.put(
        f"/api/v1/sites/pages/{page_id}/draft/",
        {"expected_version": 0, "blocks": blocks, "media_asset_ids": []},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _offered(client: Any) -> dict[str, dict[str, Any]]:
    capabilities = client.get("/api/v1/sites/capabilities/")
    assert capabilities.status_code == 200, capabilities.content
    return {row["block_type"]: row for row in capabilities.json()["block_schemas"]}


# --- Where the module is not composed ---------------------------------------


def test_a_deployment_without_the_module_does_not_know_its_blocks() -> None:
    """The module's files lie beside the core's, and nobody composed it: the
    type is not registered, nothing written may carry it, and what a
    connector is told it may write does not name it."""
    with override_settings(SITE_BLOCK_MODULE_CONTRACTS_PATH=FIXTURES):
        _forget_contracts()
        try:
            contracts = site_block_contracts()
            assert not [name for name in contracts.validators if not name.startswith("core.")]
            assert contracts.modules == {} and contracts.translation == {}
            with pytest.raises(UnknownSiteBlockType):
                validate_site_block(block_type=LIST, schema_version=2, data={"heading": "x"})
            with pytest.raises(UnknownSiteBlockType):
                validate_built_site_block(
                    block_type=PROFILE, schema_version=1, data=profile_block()["data"]
                )

            client, _, _ = sites_client(slug="module-blocks-absent")
            site_id = create_site(client).data["id"]
            page_id = create_page(client, site_id).data["id"]
            refused = _save_draft(client, page_id, [list_block()], "absent-draft")
            assert refused.status_code == 400, refused.content
            assert refused.json()["code"] == "unknown_site_block_type"
            assert not {LIST, PROFILE} & set(_offered(client))
            # The fixture's directory names a module this catalog does not have.
            assert [error.id for error in check_content_contracts()] == ["sites.E011"]
        finally:
            _forget_contracts()


# --- Where it is -------------------------------------------------------------


def test_a_composed_module_registers_its_types_beside_the_core(composed: Any) -> None:
    composed()
    contracts = site_block_contracts()

    assert contracts.modules == {LIST: MODULE, PROFILE: MODULE}
    assert sorted(contracts.validators[LIST]) == [1, 2]
    assert "core.hero" in contracts.validators
    # What only the server builds: the core's document and the module's
    # record page.
    assert contracts.server_built == {"core.document", PROFILE}
    assert check_content_contracts() == []


def test_a_placed_block_is_validated_like_a_core_block(composed: Any) -> None:
    composed()
    client, _, _ = sites_client(slug="module-blocks-written")
    site_id = create_site(client).data["id"]

    # Both versions are written: an added version only adds.
    for number, block in enumerate(
        (list_block(1, order="newest"), list_block(2, intro="Wstęp", order="name"))
    ):
        page_id = create_page(
            client, site_id, key=f"lista-{number}", idempotency_key=f"page-{number}"
        ).data["id"]
        saved = _save_draft(client, page_id, [_hero("Start", "Opis"), block], f"draft-{number}")
        assert saved.status_code in (200, 201), saved.content

    page_id = create_page(client, site_id, key="zla", idempotency_key="page-bad").data["id"]
    for wrong, code in (
        # v1 has no introduction; an unknown field; a version nobody shipped.
        (list_block(1, intro="Wstęp"), "invalid_site_block_data"),
        (list_block(2, colour="red"), "invalid_site_block_data"),
        (list_block(2, order="random"), "invalid_site_block_data"),
        (list_block(3), "unknown_site_block_version"),
        # The record's own page is the module's to build, never a person's.
        (profile_block(), "server_built_site_block"),
    ):
        refused = _save_draft(client, page_id, [wrong], f"bad-{code}-{json.dumps(wrong)[:40]}")
        assert refused.status_code == 400, refused.content
        assert refused.json()["code"] == code, wrong

    offered = _offered(client)
    assert offered[LIST] == {"block_type": LIST, "versions": [1, 2], "latest_version": 2}
    assert PROFILE not in offered


def test_a_built_block_is_held_to_its_schema_by_the_module_that_builds_it(
    composed: Any,
) -> None:
    composed()
    built = profile_block()
    validate_built_site_block(block_type=PROFILE, schema_version=1, data=built["data"])
    with pytest.raises(ServerBuiltSiteBlock):
        validate_site_block(block_type=PROFILE, schema_version=1, data=built["data"])
    built["data"]["ratings"][0]["value"] = 9
    with pytest.raises(InvalidSiteBlockData):
        validate_built_site_block(block_type=PROFILE, schema_version=1, data=built["data"])


def test_translation_units_come_from_the_schema_and_the_manifest(composed: Any) -> None:
    """Free strings are prose; the manifest names the three exceptions the
    schema cannot: a person's name is copied, a printed date is data, and a
    real person's role is personal text."""
    composed()
    block = list_block(
        intro="Wstęp do listy",
        order="name",
        curator="Anna Nowak",
        curator_role="Opiekunka zbioru",
        reviewed_on="2026-10-07",
        action={"label": "Zobacz wszystkie", "href": "/samples/"},
    )
    units = {unit.key: unit for unit in extract_units([_hero("Start", "Opis"), block])}
    mine = {key: unit for key, unit in units.items() if key.startswith("1/")}

    assert {key: (unit.kind, unit.data_class) for key, unit in mine.items()} == {
        "1/heading": (UNIT_TEXT, DATA_PUBLIC),
        "1/intro": (UNIT_TEXT, DATA_PUBLIC),
        "1/curator": (UNIT_NAME, DATA_PUBLIC),
        "1/curator_role": (UNIT_TEXT, DATA_PUBLIC_PERSONAL),
        "1/action/label": (UNIT_TEXT, DATA_PUBLIC),
    }
    assert mine["1/heading"].required and mine["1/heading"].max_length == 120
    # v1 has fewer places, and the same rules.
    assert set(text_fields(LIST, 1)) == {"heading"}

    english = assemble(
        [block],
        {
            "0/heading": "Our records",
            "0/intro": "About the list",
            "0/curator_role": "Curator",
            "0/action/label": "See all",
        },
    )
    data = english.blocks[0]["data"]
    assert english.missing == ()
    assert (data["heading"], data["action"]["label"]) == ("Our records", "See all")
    # Structure and data are the source's: only text differs.
    assert (data["curator"], data["reviewed_on"], data["order"], data["action"]["href"]) == (
        "Anna Nowak",
        "2026-10-07",
        "name",
        "/samples/",
    )


# --- On a published site ------------------------------------------------------

RECORDS = {"first": "Rekord pierwszy", "second": "Rekord drugi"}


def _answer(
    _organization_id: UUID, locale: str, blocks: Mapping[str, SiteBlock], page_base: str
) -> Mapping[str, Any]:
    """What the placed block shows now: the module's records, in the order
    the block chose, linked to their own pages."""
    return {
        key: {
            "records": [
                {"name": name, "href": f"{page_base}{slug}/"}
                for slug, name in sorted(
                    RECORDS.items(), reverse=data.get("order") == "newest"
                )
            ],
            "locale": locale,
        }
        for key, (_block_type, data) in blocks.items()
    }


def _record_page(
    _organization_id: UUID, locale: str, slug: str, _address: PageAddress
) -> SourcePage | None:
    if slug not in RECORDS:
        return None
    name = RECORDS[slug] if locale == "pl" else f"EN {RECORDS[slug]}"
    block = profile_block(name)
    validate_built_site_block(
        block_type=block["block_type"], schema_version=block["schema_version"], data=block["data"]
    )
    return SourcePage(
        key=f"record-{slug}",
        title=name,
        description="Opis rekordu",
        blocks=[block],
        locales=frozenset({"en"}),
    )


@pytest.fixture
def records(register_test_source: Any) -> PublicSource:
    """The module's public source (PB1's protocol): it fills the placed
    block and gives each record a page of its own."""
    source = PublicSource(
        key="sample.records",
        shown_media=lambda _organization_id: (),
        site_block_types=frozenset({LIST}),
        site_blocks=_answer,
        page_segment="samples",
        site_page=_record_page,
        site_pages=lambda _organization_id: [
            SourcePageAddress(slug=slug, locales=frozenset({"en"})) for slug in RECORDS
        ],
    )
    # In a registry of the test's own: a composition may hold the segment.
    registered: PublicSource = register_test_source(source)
    return registered


def test_a_placed_block_is_published_translated_and_filled_live(
    composed: Any, records: PublicSource
) -> None:
    composed()
    client, _, _ = sites_client(slug="module-blocks-live", role_key="owner")
    site_id = create_site(client).data["id"]
    page_id = str(
        _page(
            client,
            site_id,
            "start",
            [_hero("Witaj", "Opis"), list_block(intro="Wstęp do listy", order="newest")],
        )
    )
    host = _verified_platform_domain(site_id).hostname

    # The language version lists the block's text as units, by position.
    body = client.get(_url(page_id)).data
    assert {
        unit["key"]: unit["source_text"] for unit in body["units"] if unit["key"][0] == "1"
    } == {"1/heading": "Nasze rekordy", "1/intro": "Wstęp do listy"}
    saved = _translate(
        client,
        page_id,
        {
            "0/title": "Welcome",
            "0/text": "Description",
            "1/heading": "Our records",
            "1/intro": "About the list",
        },
        "start-en",
    )
    assert saved.status_code in (200, 201), saved.data
    assert saved.data["untranslated"] == 0
    snapshot = _publish(client, site_id, "publish")
    assert snapshot["live_locales"] == ["pl", "en"]

    polish = _get(host, "/")
    assert polish.status_code == 200, polish.data
    block = polish.data["blocks"][1]
    assert (block["block_type"], block["schema_version"]) == (LIST, 2)
    assert block["data"] == {
        "heading": "Nasze rekordy",
        "intro": "Wstęp do listy",
        "order": "newest",
    }
    # The answer travels beside the snapshot, by the block's position, and
    # links the records' own pages where the site answers for them.
    assert polish.data["live"] == {
        "1": {
            "records": [
                {"name": "Rekord drugi", "href": "/samples/second/"},
                {"name": "Rekord pierwszy", "href": "/samples/first/"},
            ],
            "locale": "pl",
        }
    }

    english = _get(host, "/en/")
    assert english.status_code == 200, english.data
    assert english.data["blocks"][1]["data"] == {
        "heading": "Our records",
        "intro": "About the list",
        "order": "newest",
    }
    assert english.data["live"]["1"]["locale"] == "en"
    assert english.data["live"]["1"]["records"][0]["href"] == "/en/samples/second/"


def test_a_record_page_is_one_block_the_module_built(
    composed: Any, records: PublicSource
) -> None:
    composed()
    client, _, _ = sites_client(slug="module-blocks-record", role_key="owner")
    site_id = create_site(client).data["id"]
    home = str(_page(client, site_id, "start", [_hero("Witaj", "Opis")]))
    host = _verified_platform_domain(site_id).hostname
    _translate(client, home, {"0/title": "Welcome", "0/text": "Description"}, "start-en")
    _publish(client, site_id, "publish")

    for path, name in (
        ("/samples/first/", "Rekord pierwszy"),
        ("/en/samples/first/", "EN Rekord pierwszy"),
    ):
        page = _get(host, path)
        assert page.status_code == 200, (path, page.data)
        assert [block["block_type"] for block in page.data["blocks"]] == [PROFILE]
        assert page.data["blocks"][0]["data"]["name"] == name
        assert page.data["title"] == name
    assert _get(host, "/samples/third/").status_code == 404
    # The segment is the module's: no page of the site may take it.
    taken = create_page(client, site_id, key="samples", idempotency_key="page-samples")
    saved = client.put(
        f"/api/v1/sites/pages/{taken.data['id']}/translations/pl/",
        {"expected_version": 0, "slug": "samples", "title": "Rekordy", "description": "Opis"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="samples-pl",
    )
    assert (saved.status_code, saved.json()["code"]) == (400, "slug_reserved"), saved.content


def test_a_module_reads_a_body_as_units_and_its_pages_address_through_the_api() -> None:
    """What a module needs to translate a record made of placed blocks and to
    link its pages outside a page request, from the module's public door."""
    body = [_hero("Start", "Opis"), _hero("Dalej", "Więcej")]
    units = [unit.key for unit in sites_api.extract_units(body)]
    assert {"0/title", "0/text", "1/title", "1/text"} <= set(units)

    texts = {"0/title": "Home", "0/text": "About", "1/title": "Next", "1/text": "More"}
    english = sites_api.assemble(body, texts)
    assert (english.missing, english.blocks[1]["data"]["title"]) == ((), "Next")
    # Whole blocks from outside become the same units again.
    assert sites_api.texts_against(body, english.blocks) == texts
    with pytest.raises(sites_api.StructureDiffers):
        sites_api.texts_against(body, english.blocks[:1])
    with pytest.raises(sites_api.LocaleUnitsInvalid) as refused:
        sites_api.assemble(body, {"9/title": "Nowhere"})
    assert [(problem.key, problem.code) for problem in refused.value.problems] == [
        ("9/title", "unknown_unit")
    ]

    # The site puts a record's address together, never the module.
    assert sites_api.source_page_base("pl", "pl", "samples") == "/samples/"
    assert sites_api.source_page_base("pl", "en", "samples") == "/en/samples/"


def test_a_products_code_builds_a_site_through_the_api() -> None:
    """What a product's site command does beside pages and drafts — the look,
    the menu, a section, a language version's words, the site's texts, a
    page's kind and its removal — from the module's public door, as the
    person it acts for."""
    client, site_id, home, offer, _host = _site("api-built")
    _translate_all(client, home, "api-built-home")
    site = Site.all_objects.get(pk=site_id)
    person = context_from_membership(Membership.objects.get(organization=site.organization_id))

    with activate_tenant_context(person):
        look = sites_api.get_site_appearance(site_id=site.id)
        wanted = {
            **look["appearance"],
            "footer": {"layout": "simple", "text": "Zapraszamy", "links": []},
        }
        saved = sites_api.save_site_appearance(
            site_id=site.id,
            expected_version=look["version"],
            appearance=wanted,
            idempotency_key="api-look",
        )
        assert (saved["version"], saved["appearance"]) == (look["version"] + 1, wanted)
        with pytest.raises(sites_api.AppearanceVersionConflict):
            sites_api.save_site_appearance(
                site_id=site.id,
                expected_version=look["version"],
                appearance=wanted,
                idempotency_key="api-look-stale",
            )

        menu = sites_api.get_site_navigation(site_id=site.id)
        assert isinstance(menu, sites_api.SiteNavigation)
        placed = sites_api.save_site_navigation(
            site_id=site.id,
            expected_version=menu.site.navigation_version,
            items=[{"page_id": offer, "visible": True}, {"page_id": home, "visible": True}],
        )
        assert [str(item.page_id) for item in placed.items] == [offer, home]
        with pytest.raises(sites_api.NavigationVersionConflict):
            sites_api.save_site_navigation(
                site_id=site.id, expected_version=menu.site.navigation_version, items=[]
            )

        section, created = sites_api.create_collection(
            site_id=site.id,
            key="guide",
            name="Poradnik",
            kind="blog",
            base_path="poradnik",
            locale_paths={"en": "guide"},
            idempotency_key="api-guide",
        )
        assert created and [one.key for one in sites_api.list_collections(site_id=site.id)] == [
            "guide"
        ]
        assert sites_api.set_collection_navigation(
            collection_id=section.id, show=True
        ).show_in_navigation

        body = sites_api.get_locale_body(page_id=UUID(home), locale="en")
        assert isinstance(body, sites_api.LocaleBody) and body.untranslated == 0
        written = sites_api.save_locale_body(
            page_id=UUID(home),
            locale="en",
            source_version_id=body.source_version.id,
            expected_body_version=body.translation.body_version,
            units={"0/title": "Welcome"},
            idempotency_key="api-home-en",
            imported=True,
        )
        states: dict[str, Any] = {state.unit.key: state for state in written.value.units}
        assert isinstance(states["0/title"], sites_api.UnitState)
        assert (states["0/title"].text, states["0/title"].origin) == ("Welcome", "import")
        with pytest.raises(sites_api.LocaleBodyVersionConflict):
            sites_api.save_locale_body(
                page_id=UUID(home),
                locale="en",
                source_version_id=body.source_version.id,
                expected_body_version=body.translation.body_version,
                units={"0/title": "Hello"},
                idempotency_key="api-home-en-stale",
            )
        # Already on the page's current version: nothing to move.
        assert not sites_api.rebase_locale_body(
            page_id=UUID(home),
            locale="en",
            expected_body_version=written.value.translation.body_version,
            idempotency_key="api-home-rebase",
        ).created
        with pytest.raises(sites_api.LocaleIsSource):
            sites_api.get_locale_body(page_id=UUID(home), locale="pl")

    _publish(client, site_id, "api-built-site")

    with activate_tenant_context(person):
        texts = sites_api.list_site_texts(site_id=site.id, locale="en")
        assert isinstance(texts, sites_api.SiteTexts)
        assert {"footer/text", f"collection/{section.id}"} <= {item.key for item in texts.items}
        said = sites_api.save_site_texts(
            site_id=site.id,
            locale="en",
            expected_version=texts.version,
            texts={"footer/text": "Welcome"},
        )
        assert {item.key: item.text for item in said.items}["footer/text"] == "Welcome"
        with pytest.raises(sites_api.SiteTextsVersionConflict):
            sites_api.save_site_texts(
                site_id=site.id, locale="en", expected_version=texts.version, texts={}
            )
        with pytest.raises(sites_api.SiteTextLocaleInvalid):
            sites_api.list_site_texts(site_id=site.id, locale="pl")
        out = sites_api.publish_site_texts(
            site_id=site.id, locale="en", idempotency_key="api-texts-en"
        )
        assert out.snapshot["site_texts"]["en"]["footer/text"] == "Welcome"

        draft = str(_page(client, site_id, "robocza", [_hero("Szkic", "Do usunięcia")]))
        assert (
            sites_api.set_page_type(page_id=UUID(draft), page_type="landing").page_type == "landing"
        )
        with pytest.raises(sites_api.PageInvalidType):
            sites_api.set_page_type(page_id=UUID(draft), page_type="unknown")
        removed = sites_api.delete_page(
            page_id=UUID(draft),
            expected_version=sites_api.get_draft(page_id=UUID(draft)).page.version,
            redirect_to_page_id=None,
            idempotency_key="api-draft-away",
        )
        assert isinstance(removed, sites_api.PageDeletion)
        assert removed.created and removed.page.deleted_at is not None
        with pytest.raises(sites_api.PageAlreadyDeleted):
            sites_api.delete_page(
                page_id=UUID(draft),
                expected_version=removed.page.version,
                redirect_to_page_id=None,
                idempotency_key="api-draft-again",
            )


# --- A manifest that breaks its contract stops the deploy ---------------------


def _broken(tmp_path: Path, change: Any, *, directory: str = MODULE) -> Path:
    """The fixture's files with one thing wrong in the manifest."""
    target = tmp_path / directory
    shutil.copytree(FIXTURES / MODULE, target)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    change(manifest)
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def _rename_type(manifest: dict[str, Any]) -> None:
    manifest["blocks"][0]["type"] = "vertical.other.record_list"


def _take_core_type(manifest: dict[str, Any]) -> None:
    manifest["blocks"][0]["type"] = "core.hero"


def _name_another_module(manifest: dict[str, Any]) -> None:
    manifest["module"] = "vertical.other"


def _skip_a_version(manifest: dict[str, Any]) -> None:
    del manifest["blocks"][0]["schemas"]["1"]


def _offer_a_built_block(manifest: dict[str, Any]) -> None:
    manifest["blocks"][1]["sections"] = manifest["blocks"][0]["sections"]


def _unknown_key(manifest: dict[str, Any]) -> None:
    manifest["blocks"][0]["component"] = "RecordList"


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (_rename_type, "nie nosi nazwy modułu vertical.sample"),
        (_take_core_type, "nie spełnia kontraktu"),
        (_name_another_module, "nazywa moduł vertical.other"),
        (_skip_a_version, "liniowej historii"),
        (_offer_a_built_block, "nie ma sekcji w bibliotece"),
        (_unknown_key, "nie spełnia kontraktu"),
    ],
)
def test_a_manifest_that_breaks_the_contract_fails_the_system_check(
    composed: Any, tmp_path: Path, change: Any, says: str
) -> None:
    composed(_broken(tmp_path, change))

    with pytest.raises(ImproperlyConfigured, match=says):
        site_block_contracts()
    assert [error.id for error in check_content_contracts()] == ["sites.E012"]


def test_a_translation_exception_must_name_a_place_of_the_schema(
    composed: Any, tmp_path: Path
) -> None:
    def mistype(manifest: dict[str, Any]) -> None:
        manifest["blocks"][0]["translation"]["copied"] = {"curators": "name"}

    composed(_broken(tmp_path, mistype))

    problems = check_content_contracts()
    assert [error.id for error in problems] == ["sites.E013"]
    assert "curators" in problems[0].msg


def test_a_type_carries_its_module_id_with_hyphens_as_underscores() -> None:
    assert module_block_prefix("vertical.sample") == "vertical.sample."
    assert module_block_prefix("shared.model-port") == "shared.model_port."
