"""What the server reads out of blocks themselves: media ids and page anchors.

Mirrors `blockAssetIds` in `@saas-core/site-blocks` (rich-text.ts). Every block
schema uses `asset_id` for a media asset and nothing else, so one walk covers a
hero photo, a product gallery and a figure inside rich text alike.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException


class DuplicateRichTextAnchor(APIException):
    status_code = 400
    default_code = "duplicate_rich_text_anchor"
    default_detail = "Kotwica sekcji lub śródtytułu powtarza się na tej stronie."


def block_asset_ids(blocks: Iterable[dict[str, Any]]) -> list[UUID]:
    """Every media asset id in the blocks' data, in first-occurrence order.

    Every block schema pins `asset_id` to a UUID pattern; a string that is not
    one cannot name an asset, so it is skipped rather than turned into a 500.
    """
    found: dict[UUID, None] = {}

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key == "asset_id" and isinstance(child, str):
                    with suppress(ValueError):
                        found.setdefault(UUID(child))
                else:
                    visit(child)

    for block in blocks:
        visit(block.get("data"))
    return list(found)


def rich_text_anchors(blocks: Iterable[dict[str, Any]]) -> list[str]:
    """Heading anchors of every structured `core.rich_text` block (v2 onwards;
    v1 has no `content`), duplicates included. Same rule as `richTextAnchors`."""
    return [
        node["anchor"]
        for block in blocks
        if block.get("block_type") == "core.rich_text"
        and isinstance(block["data"].get("content"), list)
        for node in block["data"]["content"]
        if isinstance(node, dict) and node.get("type") == "heading"
    ]


def section_anchors(blocks: Iterable[dict[str, Any]]) -> list[str]:
    """`presentation.anchor` (section presentation v2) of every block that has one."""
    return [
        block["presentation"]["anchor"]
        for block in blocks
        if isinstance(block.get("presentation"), dict) and "anchor" in block["presentation"]
    ]


def assert_unique_anchors(blocks: Iterable[dict[str, Any]]) -> None:
    """Section and heading anchors are one namespace: both become an `id` on the page."""
    blocks = list(blocks)
    anchors = section_anchors(blocks) + rich_text_anchors(blocks)
    if len(anchors) != len(set(anchors)):
        raise DuplicateRichTextAnchor
