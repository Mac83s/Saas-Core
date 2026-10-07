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
it when no published page answers, and the source says what the record is for
structured data (`SourcePage.thing`) and which picture a shared link shows.
And, since slice 5h, what its records make the company itself for structured
data (`business_type`): a company that lets units by the night is a lodging
business whatever category its catalogue card stands in (ADR-071 pkt 16).

A record whose words are written per language and never stand in for one
another — a company's document for its customers (`documents`, slice 5f) —
says so with `per_language`: its page exists only in the languages it has a
text in, the site's own included, and where a visitor asks for it in another
one the source's page says in which languages it can be read instead of
showing a text nobody approved in that language.

Where a record's page answers (2026-10-07, ADR-074 pkt 7 „Uzupełnienie")
----------------------------------------------------------------------
`/<segment>/<slug>/` in the site's own language, `/<xx>/<segment>/<slug>/` in
another. Both parts may differ by language, and a source that says nothing
keeps one of each for all of them:

- the segment: `page_segment` (`stay`), and `page_segments` for the languages
  that name the section differently (`{"en": "dog-breeds", "de":
  "hunderassen"}` beside `page_segment="rasy-psow"`). The key is the language
  the page is read in, whichever of them is the site's own. Every segment of
  every source is reserved for new pages and sections of a site;
- the slug: a record with a slug per language names them in `SourcePage.slugs`
  and `SourcePageAddress.slugs`. `site_page` is asked with the slug of the
  address and looks the record up by its slug in ANY language; the site
  compares the answer with the address and, where the slug or the segment is
  another language's, answers one 308 to the record's address in the language
  asked for. A language the record names no slug in uses the slug of the
  site's own language, then the one it was asked under.

The site builds every such address itself (`source_page_versions` in
`shared.sites.publication_routing`); a source that links its own pages gets
the address from `PageAddress` (its page's other languages) or from
`page_base` (its blocks), never by joining segments.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

#: A block of a site as a source reads it: its type and its published data.
SiteBlock = tuple[str, Mapping[str, Any]]


class PageAddress(Protocol):
    """Where the site answers for one record's own page in a language: its
    path there, or an empty string where the site is not read in that
    language. `slug` is the record's slug in that language where it has one of
    its own; left out, the slug the page was asked under."""

    def __call__(self, locale: str, slug: str = "") -> str: ...


#: A first segment of an address: Latin letters, digits and single hyphens.
_SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class SourcePage:
    """A record's own page on its company's site: what the site needs to
    answer at its address — the page's words and the blocks that draw it."""

    #: The record across languages and renames (a unit's id).
    key: str
    title: str
    description: str
    blocks: list[dict[str, Any]]
    #: What the record is called by itself, where the title says more (a
    #: town, the company): the page's place in its trail, after the company.
    name: str = ""
    #: The languages the record has words of its own in, beside the site's
    #: source language — only in those does the page have another address.
    locales: frozenset[str] = frozenset()
    #: The record's own picture for a link shared elsewhere: a media asset
    #: the source lets the site serve (`served_media`).
    image: UUID | None = None
    #: What the record is, for structured data: a schema.org node. Its
    #: address and picture (`@id`, `url`, `image`) are the site's to give.
    thing: Mapping[str, Any] | None = None
    #: The record's words are written per language and none stands in for
    #: another (a legal text): its page exists in `locales` only — the site's
    #: own language is no exception — and a page asked for in another one is
    #: the source's own word that the record has no text there, kept out of
    #: search and of the language alternates instead of being moved.
    per_language: bool = False
    #: The record's slug by language, where it has one per language; empty —
    #: one slug in every language, the one the page was asked under.
    slugs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourcePageAddress:
    """One record that has a page, for whoever lists them (the sitemap)."""

    #: The record's slug in the site's own language.
    slug: str
    locales: frozenset[str] = frozenset()
    changed_at: datetime | None = None
    #: As `SourcePage.per_language`: the page is listed in `locales` only.
    per_language: bool = False
    #: As `SourcePage.slugs`.
    slugs: Mapping[str, str] = field(default_factory=dict)


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
    #: company's site (ADR-074 pkt 7), in every language `page_segments` does
    #: not name; empty — its records have no pages.
    page_segment: str = ""
    #: The segment in the languages that name the section differently, by
    #: language code (`{"de": "hunderassen"}`); see the module note.
    page_segments: Mapping[str, str] = field(default_factory=dict)
    #: `site_page(organization_id, locale, slug, address)` → the page of the
    #: record with that slug — in any language, where it has one per language
    #: (`SourcePage.slugs`) — in that language where the record has words in
    #: it, or None. `address(locale, slug)` is where the site answers for this
    #: record's page in a language — empty where the site is not read in it —
    #: for a page that links to its own other languages. The source sets its
    #: own tenant.
    site_page: Callable[[UUID, str, str, PageAddress], SourcePage | None] | None = None
    #: `site_pages(organization_id)` → every record that has a page now.
    site_pages: Callable[[UUID], Iterable[SourcePageAddress]] | None = None
    #: `business_type(organization_id)` → the schema.org subtype of
    #: LocalBusiness its records make the company (`LodgingBusiness`), or ""
    #: when they say nothing about it. Called inside the company's tenant.
    business_type: Callable[[UUID], str] | None = None

    def segment(self, locale: str) -> str:
        """The first segment of its records' pages in a language."""
        return self.page_segments.get(locale) or self.page_segment

    def segments(self) -> frozenset[str]:
        """Every first segment its records' pages take, in any language."""
        return frozenset({self.page_segment, *self.page_segments.values()} - {""})


_sources: dict[str, PublicSource] = {}


def register_public_source(source: PublicSource) -> None:
    existing = _sources.get(source.key)
    if existing is not None and existing != source:
        raise ImproperlyConfigured(f"Publiczne źródło jest już zarejestrowane: {source.key}")
    if source.page_segments and not source.page_segment:
        raise ImproperlyConfigured(
            f"Źródło {source.key} nazywa segment per język bez segmentu podstawowego."
        )
    for segment in source.segments():
        # A two-letter segment is a language's prefix (ADR-071).
        if not _SEGMENT.fullmatch(segment) or len(segment) == 2:
            raise ImproperlyConfigured(f"Segment źródła {source.key} jest niepoprawny: {segment}")
    for other in _sources.values():
        # One segment, one source — in whichever language: `/de/<segment>/`
        # of one must never be `/<segment>/` of another on a German site.
        shared = source.segments() & other.segments() if other.key != source.key else None
        if shared:
            raise ImproperlyConfigured(
                f"Segment {sorted(shared)[0]} należy już do źródła {other.key}."
            )
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


def stated_business_type(organization_id: UUID) -> str:
    """What the company's live records make it, as schema.org names it; ""
    when no source says. A fact: it stands before the subtype the company's
    catalogue category names. The caller holds the company's tenant."""
    for source in _sources.values():
        if source.business_type is not None:
            stated = source.business_type(organization_id)
            if stated:
                return stated
    return ""


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
            base = (
                page_base(source.segment(locale)) if page_base and source.page_segment else ""
            )
            answers.update(source.site_blocks(organization_id, locale, asked, base))
    return answers


def page_sources() -> dict[str, PublicSource]:
    """The sources whose records have pages of their own, by the first
    segment of those pages' addresses in a language that names no other
    (`page_segment`). An address is matched with `page_source`."""
    return {
        source.page_segment: source
        for source in _sources.values()
        if source.page_segment and source.site_page is not None
    }


def page_source(segment: str, locale: str | None = None) -> PublicSource | None:
    """The source whose records' pages answer under `segment` in `locale`;
    without a language — under that segment in any of them."""
    for source in page_sources().values():
        if segment == source.segment(locale) if locale else segment in source.segments():
            return source
    return None


def page_source_segments() -> frozenset[str]:
    """Every first segment a source's pages take, in any language: none of
    them is free for a page or a section of a site."""
    return frozenset().union(*(source.segments() for source in page_sources().values()))
