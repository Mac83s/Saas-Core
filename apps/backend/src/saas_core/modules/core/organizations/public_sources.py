"""Live records the public sees, by the module that owns them (ADR-074 pkt 7).

A published page is a snapshot, and its pictures are named by the snapshot. A
unit of a booking form or a product of a shop is live data: nothing publishes
it, so nothing but its own module knows what of it is shown. A module registers
a source here and whoever must respect it asks the registry instead of the
module — the registry lives in core because media depends on neither booking
nor the shop.

A source says three things. Which media its records show now: media keeps
those objects when the asset is deleted from the library, as it keeps a
published page's. Which of them the company's own site may serve a visitor
(slice 5d): the site's host vouches for the pictures of its publication, and
for these on the source's word. And what the site's blocks that show its
records show now: a publication is a snapshot, a free day and a price cannot
be one, so the block carries a choice and the source answers it at each read.
And, since slice 5e, the pages its records have by themselves on the company's
site — a unit's own page — under one first segment of the address that is the
source's (`stay`): nobody publishes such a page, the site asks the source for
it when no published page answers. What else a source names — the facts for
structured data — joins the same record with its first reader.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

#: A block of a site as a source reads it: its type and its published data.
SiteBlock = tuple[str, Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class SourcePage:
    """A record's own page on its company's site: what the site needs to
    answer at its address — the page's words and the blocks that draw it."""

    #: The record across languages and renames (a unit's id).
    key: str
    title: str
    description: str
    blocks: list[dict[str, Any]]
    #: The languages the record has words of its own in, beside the site's
    #: source language — only in those does the page have another address.
    locales: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SourcePageAddress:
    """One record that has a page, for whoever lists them (the sitemap)."""

    slug: str
    locales: frozenset[str] = frozenset()
    changed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PublicSource:
    #: `<module>.<what>`, e.g. `booking.units`.
    key: str
    #: `shown_media(organization_id)` → the ids of the media assets its
    #: records of that company show now. Called inside the company's tenant.
    shown_media: Callable[[UUID], Iterable[UUID]]
    #: `served_media(organization_id)` → the ids of the media assets the
    #: company's own site may serve a visitor — what the source itself would
    #: show them, never all it keeps. Called inside the company's tenant.
    served_media: Callable[[UUID], Iterable[UUID]] | None = None
    #: The types of site blocks this source fills (`core.stay_units`).
    site_block_types: frozenset[str] = frozenset()
    #: `site_blocks(organization_id, locale, blocks, page_base)` → what each
    #: of those blocks shows now, by the key it was asked under; a block the
    #: source has nothing for is left out. `blocks` maps a key to the block's
    #: type and its published data — the choice. `page_base` is where the
    #: site answers for this source's own pages in that language (`/stay/`,
    #: `/de/stay/`), empty where it does not. The source sets its own tenant.
    site_blocks: Callable[[UUID, str, Mapping[str, SiteBlock], str], Mapping[str, Any]] | None = (
        None
    )
    #: The first segment of the address of its records' own pages on a
    #: company's site, the same in every language (ADR-074 pkt 7); empty — its
    #: records have no pages.
    page_segment: str = ""
    #: `site_page(organization_id, locale, slug)` → the page of the record at
    #: that address, in that language where the record has words in it, or
    #: None. The source sets its own tenant.
    site_page: Callable[[UUID, str, str], SourcePage | None] | None = None
    #: `site_pages(organization_id)` → every record that has a page now.
    site_pages: Callable[[UUID], Iterable[SourcePageAddress]] | None = None


_sources: dict[str, PublicSource] = {}


def register_public_source(source: PublicSource) -> None:
    existing = _sources.get(source.key)
    if existing is not None and existing != source:
        raise ImproperlyConfigured(f"Publiczne źródło jest już zarejestrowane: {source.key}")
    _sources[source.key] = source


def shown_media_ids(organization_id: UUID) -> set[UUID]:
    """The media assets some live record of the company shows now. The caller
    holds the company's tenant."""
    shown: set[UUID] = set()
    for source in _sources.values():
        shown.update(source.shown_media(organization_id))
    return shown


def served_media_ids(organization_id: UUID) -> set[UUID]:
    """The media assets the company's own site may serve beyond what its
    publication names: what its live records show a visitor. The caller holds
    the company's tenant."""
    served: set[UUID] = set()
    for source in _sources.values():
        if source.served_media is not None:
            served.update(source.served_media(organization_id))
    return served


def live_site_blocks(
    organization_id: UUID,
    locale: str,
    blocks: Sequence[Mapping[str, Any]],
    page_base: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """What the blocks of a published page that show live records show now,
    by their position on the page. A page without such a block asks nobody; a
    block no source answers is left out and draws nothing. `page_base` says
    where the site answers for a segment's pages in that language."""
    answers: dict[str, Any] = {}
    for source in _sources.values():
        if source.site_blocks is None:
            continue
        asked = {
            str(position): (str(block.get("block_type")), block.get("data") or {})
            for position, block in enumerate(blocks)
            if isinstance(block, Mapping) and block.get("block_type") in source.site_block_types
        }
        if asked:
            base = page_base(source.page_segment) if page_base and source.page_segment else ""
            answers.update(source.site_blocks(organization_id, locale, asked, base))
    return answers


def page_sources() -> dict[str, PublicSource]:
    """The sources whose records have pages of their own, by the first
    segment of those pages' addresses."""
    return {
        source.page_segment: source
        for source in _sources.values()
        if source.page_segment and source.site_page is not None
    }
