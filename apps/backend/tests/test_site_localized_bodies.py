"""A page body in another language as text units bound to the source structure
(ADR-070, plan TL8): what is text in every block schema version, units out of
blocks and blocks back out of units, and the structure every language shares."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from saas_core.modules.shared.sites.block_contracts import site_block_contracts
from saas_core.modules.shared.sites.localized_bodies import (
    COPIED_FIELDS,
    DATA_FIELDS,
    DATA_PUBLIC_PERSONAL,
    UNIT_INLINE,
    UNIT_NAME,
    LocaleUnitsInvalid,
    UnitProblem,
    assemble,
    extract_units,
    structure_signature,
    text_fields,
)

CONSTRAINED = ("enum", "pattern", "const", "format")


def _string_paths(schema: dict[str, Any]) -> dict[str, bool]:
    """Every string leaf of a schema, by path, and whether it is constrained —
    read independently of the classifier, so the two can disagree."""
    found: dict[str, bool] = {}

    def walk(node: dict[str, Any], path: tuple[str, ...], inline: bool) -> None:
        while "$ref" in node:
            node = schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
        for branch in [*node.get("oneOf", ()), *node.get("anyOf", ())]:
            walk(branch, path, inline)
        if node.get("type") == "object":
            for name, child in node.get("properties", {}).items():
                walk(child, (*path, name), inline)
        elif node.get("type") == "array":
            item = node.get("items", {})
            while "$ref" in item:
                item = schema["$defs"][item["$ref"].removeprefix("#/$defs/")]
            spans = "text" in item.get("properties", {}) and "href" in item.get("properties", {})
            walk(item, (*path, "*"), inline or spans)
        elif node.get("type") == "string" and not inline:
            found["/".join(path)] = any(key in node for key in CONSTRAINED)

    walk(schema, (), False)
    return found


def _all_schemas():
    for block_type, versions in site_block_contracts().validators.items():
        for version, validator in versions.items():
            yield block_type, version, validator.schema


@pytest.mark.parametrize(
    ("block_type", "version", "schema"),
    [pytest.param(*entry, id=f"{entry[0]}.v{entry[1]}") for entry in _all_schemas()],
)
def test_every_string_of_every_schema_version_is_text_or_structure(block_type, version, schema):
    fields = text_fields(block_type, version)
    for path, constrained in _string_paths(schema).items():
        if constrained or (block_type, path) in DATA_FIELDS:
            assert path not in fields, path
        else:
            assert path in fields, path
    for path, field in fields.items():
        if field.kind == UNIT_INLINE:
            assert path.endswith("content") or path == "", path


def test_rich_text_runs_are_one_unit_in_every_version_that_has_them():
    for version in (2, 3, 4):
        fields = text_fields("core.rich_text", version)
        assert fields["content/*/content"].kind == UNIT_INLINE
        assert fields["content/*/items/*/content"].kind == UNIT_INLINE
        assert fields["content/*/text"].kind == "text"


def test_every_listed_exception_names_a_place_that_exists():
    schemas = list(_all_schemas())
    for block_type, path in [*COPIED_FIELDS, *DATA_FIELDS]:
        assert any(
            path in _string_paths(schema)
            for candidate_type, _version, schema in schemas
            if candidate_type == block_type
        ), (block_type, path)


def _corpus() -> list[dict[str, Any]]:
    """Every block the platform ships: fixtures, section seeds and page recipes."""
    blocks: list[dict[str, Any]] = []
    site_blocks = Path(settings.SITE_BLOCK_CONTRACTS_PATH)
    for path in sorted((site_blocks / "fixtures").glob("*.json")):
        blocks.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted(site_blocks.glob("section-templates.v*.json")):
        if path.name.endswith(".schema.json"):
            continue
        for template in json.loads(path.read_text(encoding="utf-8"))["templates"]:
            for data in template["seed"].values():
                blocks.append({
                    "block_type": template["blockType"],
                    "schema_version": template["schemaVersion"],
                    "data": data,
                })
    templates = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    for path in sorted(templates.glob("core.*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        blocks.extend(recipe["blocks"])
        for localized in recipe.get("localizedBlocks", {}).values():
            blocks.extend(localized)
    validators = site_block_contracts().validators
    # A recipe's figures get their photos when it is imported (mediaBindings),
    # so the few blocks still waiting for one are not pages yet.
    return [
        {
            "block_type": block["block_type"],
            "schema_version": block["schema_version"],
            "data": block["data"],
        }
        for block in blocks
        if validators[block["block_type"]][block["schema_version"]].is_valid(block["data"])
    ]


def test_units_assemble_back_into_every_shipped_block():
    corpus = _corpus()
    assert len(corpus) > 100
    units = extract_units(corpus)
    assert units
    assembled = assemble(corpus, {unit.key: unit.text for unit in units})
    assert assembled.blocks == corpus
    assert assembled.missing == ()
    # With no translation at all the source stands in, and every prose unit
    # is reported missing; copied ones (names, addresses) are never missing.
    untouched = assemble(corpus, {})
    assert untouched.blocks == corpus
    assert set(untouched.missing) == {unit.key for unit in units if not unit.copied}


RICH = {
    "block_type": "core.rich_text",
    "schema_version": 4,
    "data": {
        "title": "O nas",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"text": "Przeczytaj "},
                    {"text": "naszą ofertę", "bold": True, "href": "/oferta/"},
                    {"text": " albo "},
                    {"text": "partnera", "href": "https://partner.example", "rel": "sponsored"},
                    {"text": "."},
                ],
            },
            {"type": "heading", "level": 2, "text": "Kontakt", "anchor": "kontakt"},
        ],
    },
}
TESTIMONIALS = {
    "block_type": "core.testimonials",
    "schema_version": 1,
    "data": {
        "title": "Opinie",
        "items": [{"quote": "[Uzupełnij: prawdziwa opinia]", "author": "Jan Kowalski"}],
    },
}


def test_a_rich_text_run_is_one_unit_whose_marks_may_move():
    units = {unit.key: unit for unit in extract_units([RICH, TESTIMONIALS])}
    run = units["0/content/0/content"]
    assert run.kind == UNIT_INLINE
    assert run.text == "Przeczytaj ⟦1⟧naszą ofertę⟦/1⟧ albo ⟦2⟧partnera⟦/2⟧."
    assert units["0/content/1/text"].text == "Kontakt"
    assert "0/content/1/anchor" not in units

    body = assemble(
        [RICH, TESTIMONIALS],
        {
            "0/title": "About us",
            "0/content/0/content": "Visit ⟦2⟧our partner⟦/2⟧ or read ⟦1⟧our offer⟦/1⟧.",
            "0/content/1/text": "Contact",
        },
    )
    assert body.blocks[0]["data"]["content"][0]["content"] == [
        {"text": "Visit "},
        {"text": "our partner", "href": "https://partner.example", "rel": "sponsored"},
        {"text": " or read "},
        {"text": "our offer", "bold": True, "href": "/oferta/"},
        {"text": "."},
    ]
    assert body.blocks[0]["data"]["content"][1]["anchor"] == "kontakt"
    assert body.missing == ("1/title", "1/items/0/quote")
    assert RICH["data"]["content"][0]["content"][0] == {"text": "Przeczytaj "}


def test_names_are_copied_people_are_personal_and_owner_slots_are_flagged():
    units = {unit.key: unit for unit in extract_units([TESTIMONIALS])}
    author = units["0/items/0/author"]
    assert author.kind == UNIT_NAME
    assert author.copied
    assert author.data_class == DATA_PUBLIC_PERSONAL
    assert units["0/items/0/quote"].placeholder
    assert not units["0/title"].placeholder
    # A transliteration given for a name is used; none keeps the source.
    body = assemble([TESTIMONIALS], {"0/items/0/author": "Ян Ковальский"})
    assert body.blocks[0]["data"]["items"][0]["author"] == "Ян Ковальский"
    assert assemble([TESTIMONIALS], {}).blocks == [TESTIMONIALS]


def test_every_invalid_unit_is_reported_at_once_by_key_and_code():
    hero = {
        "block_type": "core.hero",
        "schema_version": 6,
        "data": {"title": "Witaj", "action": {"label": "Umów", "href": "/kontakt/"}},
    }
    with pytest.raises(LocaleUnitsInvalid) as raised:
        assemble(
            [RICH, hero],
            {
                "0/content/0/content": "Read ⟦1⟧our offer⟦/1⟧.",
                "0/title": "⟦1⟧About⟦/1⟧",
                "1/title": "",
                "1/action/label": "x" * 81,
                "1/action/href": "/en/contact/",
                "9/title": "Nowhere",
            },
        )
    assert set(raised.value.problems) == {
        UnitProblem("0/content/0/content", "token_missing"),
        UnitProblem("0/title", "token_unexpected"),
        UnitProblem("1/title", "required"),
        UnitProblem("1/action/label", "too_long"),
        UnitProblem("1/action/href", "unknown_unit"),
        UnitProblem("9/title", "unknown_unit"),
    }
    for text, code in (
        ("Visit ⟦2⟧⟦/2⟧ or ⟦1⟧our offer⟦/1⟧.", "token_empty"),
        ("Visit ⟦1⟧our ⟦2⟧partner⟦/2⟧ offer⟦/1⟧.", "token_nesting"),
    ):
        with pytest.raises(LocaleUnitsInvalid) as raised:
            assemble([RICH], {"0/content/0/content": text})
        assert raised.value.problems == (UnitProblem("0/content/0/content", code),)


def test_the_structure_signature_is_shared_by_languages_and_changes_with_structure():
    translated = assemble(
        [RICH, TESTIMONIALS],
        {
            "0/content/0/content": "Read ⟦1⟧our offer⟦/1⟧ or our ⟦2⟧partner⟦/2⟧ today.",
            "0/title": "About us",
        },
    ).blocks
    signature = structure_signature([RICH, TESTIMONIALS])
    assert structure_signature(translated) == signature

    moved_link = deepcopy(RICH)
    moved_link["data"]["content"][0]["content"][1]["href"] = "/cennik/"
    assert structure_signature([moved_link, TESTIMONIALS]) != signature
    assert structure_signature([TESTIMONIALS, RICH]) != signature
    decorated = {**TESTIMONIALS, "decoration": {"schemaVersion": 1, "preset": "plain"}}
    assert structure_signature([RICH, decorated]) != signature
