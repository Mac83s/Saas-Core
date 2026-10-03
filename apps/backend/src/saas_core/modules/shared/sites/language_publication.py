"""Which language versions a publication carries (ADR-070 pkt 6–10).

One verdict for every publication path: a version in another language goes
into the snapshot only complete — its own address, title and description, every
unit translated, no owner slot left in the source — with its language's home
page, and bound to the source version the same snapshot publishes. Otherwise it
is skipped with a reason, and the publication goes on without it.

A version that was public and does not pass any more keeps its last published
entry, so addresses do not flicker; if the source changed a fact it had not
caught up with (a price, a phone, a date), that entry is withheld and answers 307
to the source page until a refreshed version is published (owner answer 5a).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from saas_core.content_protocol.facts import extract_facts

from .language_versions import (
    UNTRANSLATED_ORIGINS,
    _texts,
    _translated_by_source,
    site_locales,
)
from .localization import localized_path
from .localized_bodies import LocaleUnitsInvalid, TextUnit, assemble, extract_units
from .models import Page, PageTranslation, PageVersion, Site

METADATA_INCOMPLETE = "metadata_incomplete"
UNTRANSLATED_UNITS = "untranslated_units"
SOURCE_PLACEHOLDER = "source_placeholder"
LOCALE_HOME_MISSING = "locale_home_missing"
SOURCE_UNPUBLISHED = "source_unpublished"
SOURCE_OUTDATED = "source_outdated"
MEDIA_UNAVAILABLE = "media_unavailable"


@dataclass(slots=True)
class LanguageEntries:
    # (page id, locale) → the locale entry the snapshot carries.
    entries: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    skipped: list[dict[str, str]] = field(default_factory=list)
    live_locales: list[str] = field(default_factory=list)


def home_page(pages: Sequence[Page]) -> Page | None:
    """The page the root shows: the one marked as home, or the first."""
    return next((page for page in pages if page.page_type == "homepage"), None) or (
        pages[0] if pages else None
    )


def language_entries(
    *,
    site: Site,
    pages: Sequence[Page],
    sources: Mapping[UUID, PageVersion],
    blocks: Mapping[UUID, list[dict[str, Any]]],
    translations: Iterable[PageTranslation],
    previous: Mapping[str, Any] | None,
) -> LanguageEntries:
    """The other-language entries of a publication of `pages`.

    `sources` maps each page to the source version this publication carries,
    `blocks` each version id to its blocks (the published sources and the ones
    previous entries were bound to), `translations` the pages' translation rows
    with their current body, `previous` the snapshot being replaced.
    """
    result = LanguageEntries(live_locales=[site.default_locale])
    rows = {(row.page_id, row.locale): row for row in translations}
    before = _previous_entries(previous, site.default_locale)
    home = home_page(pages)
    ordered = sorted(pages, key=lambda page: page is not home)
    for locale in site_locales(site):
        if locale == site.default_locale:
            continue
        live = False
        for page in ordered:
            source = sources[page.id]
            key = (str(page.id), locale)
            row = rows.get((page.id, locale))
            if row is not None and row.withdrawn_at is not None:
                # Taken off by a person: its address keeps answering 308 to
                # the source page until somebody publishes it again.
                result.entries[key] = withdrawn_entry(site, row)
                continue
            entry, reason = (
                fresh_entry(site, row, source, blocks.get(source.id, []))
                if row is not None
                else (None, None)
            )
            if entry is not None and page is not home and not live:
                entry, reason = None, LOCALE_HOME_MISSING
            if entry is None and key in before:
                entry = _carried(
                    before[key],
                    old_blocks=blocks.get(UUID(str(before[key]["source_version_id"])), []),
                    new_blocks=blocks.get(source.id, []),
                    old_meta=_source_meta(previous, page.id, site.default_locale),
                    new_meta=_meta(rows.get((page.id, site.default_locale))),
                )
            if entry is not None:
                result.entries[key] = entry
                if page is home:
                    live = True
            elif reason is not None:
                result.skipped.append({"page_id": str(page.id), "locale": locale, "reason": reason})
        if live:
            result.live_locales.append(locale)
    return result


def fresh_entry(
    site: Site,
    row: PageTranslation,
    source: PageVersion,
    source_blocks: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """The entry for `row`'s current body against `source`, or why there is none."""
    if not (row.slug and row.title.strip() and row.description.strip()):
        return None, METADATA_INCOMPLETE
    body = row.body_current
    if body is None:
        return None, UNTRANSLATED_UNITS
    units = extract_units(source_blocks)
    stored: Mapping[str, Any] = body.units
    if body.source_version_id != source.id:
        # Bound to another source version: still this source's translation
        # when every unit's text is translated by hash — the blocks only
        # moved, or what changed has no words (ADR-070 pkt 4).
        realigned = _realigned(stored, units)
        if realigned is None:
            bound = body.source_version
            return None, (SOURCE_UNPUBLISHED if bound.number > source.number else SOURCE_OUTDATED)
        stored = realigned
    if any(unit.placeholder for unit in units):
        return None, SOURCE_PLACEHOLDER
    if any(not _translated(unit, stored.get(unit.key)) for unit in units):
        return None, UNTRANSLATED_UNITS
    texts = _texts(stored)
    try:
        assembled = assemble(source_blocks, texts).blocks
    except LocaleUnitsInvalid:
        return None, UNTRANSLATED_UNITS
    path = localized_path(default_locale=site.default_locale, locale=row.locale, slug=row.slug)
    return {
        "locale": row.locale,
        "translation_id": str(row.id),
        "version": row.version,
        "slug": row.slug,
        "path": path,
        "canonical_path": path,
        "title": row.title.strip(),
        "description": row.description.strip(),
        "social_title": row.social_title.strip() or row.title.strip(),
        "social_description": row.social_description.strip() or row.description.strip(),
        "fallback_fields": [],
        "blocks": assembled,
        "locale_version_id": str(body.id),
        "source_version_id": str(source.id),
        "content_hash": body.content_hash,
        "changed_at": body.created_at.isoformat(),
        "origin": _origin(body.units.values()),
        "withheld": False,
    }, None


def _realigned(
    stored: Mapping[str, Any], units: Sequence[TextUnit]
) -> dict[str, Any] | None:
    by_source = _translated_by_source(stored.values())
    found: dict[str, Any] = {}
    for unit in units:
        if unit.copied:
            continue
        entry = by_source.get(unit.source_hash)
        if entry is None:
            return None
        found[unit.key] = entry
    return found


def _translated(unit: TextUnit, entry: Any) -> bool:
    if unit.copied:
        return True
    if not isinstance(entry, dict) or "text" not in entry:
        return False
    return entry.get("provenance", {}).get("origin") not in UNTRANSLATED_ORIGINS


def _origin(entries: Iterable[Any]) -> dict[str, Any]:
    """Who wrote the version, for the machine marker on AI text (ADR-071 pkt 17)."""
    origins = {
        str(entry.get("provenance", {}).get("origin", ""))
        for entry in entries
        if isinstance(entry, dict) and "text" in entry
    } - {""}
    kind = next(iter(origins)) if len(origins) == 1 else ("mixed" if origins else "human")
    return {"origin": kind, "reviewed": "ai" not in origins}


def _carried(
    entry: Mapping[str, Any],
    *,
    old_blocks: list[dict[str, Any]],
    new_blocks: list[dict[str, Any]],
    old_meta: Sequence[str],
    new_meta: Sequence[str],
) -> dict[str, Any]:
    return {
        **entry,
        "withheld": facts_changed(old_blocks, new_blocks, old_meta=old_meta, new_meta=new_meta),
    }


def facts_changed(
    old_blocks: list[dict[str, Any]],
    new_blocks: list[dict[str, Any]],
    *,
    old_meta: Sequence[str] = (),
    new_meta: Sequence[str] = (),
) -> bool:
    """Whether the source says something a translation of the old one does not.

    Per unit in the same place (position, kind of block, field) and as a
    multiset over the whole page, so a value repeated in two units or moved to
    another one is not hidden by an equal set.
    """
    old_units, new_units = extract_units(old_blocks), extract_units(new_blocks)
    new_by_key = {unit.key: unit for unit in new_units}
    for unit in old_units:
        other = new_by_key.get(unit.key)
        position = int(unit.key.split("/", 1)[0])
        if (
            other is not None
            and other.kind == unit.kind
            and position < len(new_blocks)
            and old_blocks[position]["block_type"] == new_blocks[position]["block_type"]
            and extract_facts(unit.text) != extract_facts(other.text)
        ):
            return True
    return _bag([unit.text for unit in old_units], old_meta) != _bag(
        [unit.text for unit in new_units], new_meta
    )


def _bag(texts: Sequence[str], meta: Sequence[str]) -> Counter[tuple[str, str]]:
    return Counter(fact for text in (*texts, *meta) for fact in extract_facts(text))


def _meta(row: PageTranslation | None) -> tuple[str, ...]:
    return (row.title, row.description) if row is not None else ()


def _previous_entries(
    previous: Mapping[str, Any] | None, default_locale: str
) -> dict[tuple[str, str], dict[str, Any]]:
    if previous is None:
        return {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for page in previous.get("pages", []):
        if not isinstance(page, dict):
            continue
        for entry in page.get("locales", []):
            if (
                isinstance(entry, dict)
                and entry.get("locale") != default_locale
                and "blocks" in entry
                and entry.get("source_version_id")
            ):
                found[(str(page.get("page_id")), str(entry["locale"]))] = entry
    return found


def _source_meta(
    previous: Mapping[str, Any] | None, page_id: UUID, default_locale: str
) -> tuple[str, ...]:
    for page in (previous or {}).get("pages", []):
        if isinstance(page, dict) and page.get("page_id") == str(page_id):
            for entry in page.get("locales", []):
                if isinstance(entry, dict) and entry.get("locale") == default_locale:
                    return (str(entry.get("title", "")), str(entry.get("description", "")))
    return ()


def previous_source_ids(previous: Mapping[str, Any] | None, default_locale: str) -> set[UUID]:
    """Source versions the previous snapshot's language entries are bound to."""
    return {
        UUID(str(entry["source_version_id"]))
        for entry in _previous_entries(previous, default_locale).values()
    }


def withdrawn_entry(site: Site, row: PageTranslation) -> dict[str, Any]:
    """A language version a person took off: an address without a body of its
    own, which the reading rule answers with 308 to the source page."""
    path = localized_path(default_locale=site.default_locale, locale=row.locale, slug=row.slug)
    return {
        "locale": row.locale,
        "translation_id": str(row.id),
        "slug": row.slug,
        "path": path,
        "canonical_path": path,
        "withdrawn": True,
    }


def snapshot_home(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    pages = [page for page in snapshot.get("pages", []) if isinstance(page, dict)]
    return next((page for page in pages if page.get("page_type") == "homepage"), None) or (
        pages[0] if pages else None
    )


def with_language_entry(
    snapshot: Mapping[str, Any], *, page_id: str, locale: str, entry: dict[str, Any] | None
) -> dict[str, Any]:
    """The snapshot with one language entry of one page replaced, and only
    what follows from it: that page's hreflang and the live languages. A
    snapshot of schema 1 comes back as 2, without its other-language entries
    that never had a body of their own (ADR-070 pkt 8)."""
    default_locale = str(snapshot.get("default_locale"))
    pages: list[dict[str, Any]] = []
    for page in snapshot.get("pages", []):
        if not isinstance(page, dict):
            continue
        locales = [
            item
            for item in page.get("locales", [])
            if isinstance(item, dict)
            and (
                item.get("locale") == default_locale
                or "blocks" in item
                or item.get("withdrawn")
            )
            and not (page.get("page_id") == page_id and item.get("locale") == locale)
        ]
        if page.get("page_id") == page_id and entry is not None:
            locales.append(entry)
        pages.append({
            **page,
            "locales": locales,
            "hreflang": {
                str(item["locale"]): str(item["path"])
                for item in locales
                if item.get("path")
                and (item.get("locale") == default_locale or "blocks" in item)
                and not item.get("withheld")
            },
        })
    home = snapshot_home({"pages": pages})
    live = [default_locale] + sorted(
        str(item["locale"])
        for item in (home or {}).get("locales", [])
        if item.get("locale") != default_locale and "blocks" in item
    )
    return {
        **snapshot,
        "pages": pages,
        "live_locales": live,
        "skipped_locales": [
            item
            for item in snapshot.get("skipped_locales", [])
            if not (item.get("page_id") == page_id and item.get("locale") == locale)
        ],
    }
