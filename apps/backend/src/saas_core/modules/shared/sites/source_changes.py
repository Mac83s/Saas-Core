"""Telling the translation engine that a page's or an article's public text
changed (`translation-sources.md` §8.1): from `publish_site`, `publish_entry`
and from taking either off the site — never from a derived publication, a
rollback, a translation write or a machine translation's own publication.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from saas_core.content_protocol.registry import notify_source_changed

PAGE_SOURCE_KEY = "sites.page"
ENTRY_SOURCE_KEY = "sites.entry"
SITE_TEXTS_SOURCE_KEY = "sites.site_texts"


def change_cause(context: Any) -> str:
    return "api_key" if getattr(context, "principal_kind", "") == "api_key" else "user"


def notify_pages_published(
    *,
    context: Any,
    previous: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    default_locale: str,
) -> None:
    """The pages whose source text visitors read changed with this publication:
    a new version, or the source language's title or description."""
    before = _sources(previous, default_locale)
    changed = [
        UUID(page_id)
        for page_id, source in _sources(snapshot, default_locale).items()
        if before.get(page_id) != source
    ]
    if changed:
        notify_source_changed(
            context=context,
            source_key=PAGE_SOURCE_KEY,
            object_ids=changed,
            change="changed",
            cause=change_cause(context),
        )


def notify_page_deleted(*, context: Any, page_id: UUID) -> None:
    notify_source_changed(
        context=context,
        source_key=PAGE_SOURCE_KEY,
        object_ids=[page_id],
        change="deleted",
        cause=change_cause(context),
    )


def notify_site_texts_published(
    *,
    context: Any,
    site_id: UUID,
    previous: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> None:
    """The tagline or the footer visitors read changed with this publication;
    a reordered footer is no change — its texts stay what they were."""
    from .site_texts import appearance_texts

    def texts(value: Mapping[str, Any] | None) -> list[tuple[str, str]]:
        return sorted(
            (text.key, text.text) for text in appearance_texts((value or {}).get("appearance"))
        )

    if texts(previous) != texts(snapshot):
        notify_source_changed(
            context=context,
            source_key=SITE_TEXTS_SOURCE_KEY,
            object_ids=[site_id],
            change="changed",
            cause=change_cause(context),
        )


def notify_entry_published(
    *,
    context: Any,
    entry_id: UUID,
    previous: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> None:
    """A source article went out with other words than visitors had."""
    if previous is not None and _entry_text(previous) == _entry_text(snapshot):
        return
    notify_source_changed(
        context=context,
        source_key=ENTRY_SOURCE_KEY,
        object_ids=[entry_id],
        change="changed",
        cause=change_cause(context),
    )


def notify_entry_withdrawn(*, context: Any, entry_id: UUID) -> None:
    """Its translations are public on their own, so taking them down too is a
    person's item to review (ADR-069 pkt 4)."""
    notify_source_changed(
        context=context,
        source_key=ENTRY_SOURCE_KEY,
        object_ids=[entry_id],
        change="withdrawn",
        cause=change_cause(context),
    )


def _entry_text(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    return (snapshot.get("blocks"), snapshot.get("title"), snapshot.get("excerpt"))


def _sources(snapshot: Mapping[str, Any] | None, default_locale: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for page in (snapshot or {}).get("pages", []):
        if not isinstance(page, dict) or not page.get("page_id"):
            continue
        source = next(
            (
                item
                for item in page.get("locales", [])
                if isinstance(item, dict) and item.get("locale") == default_locale
            ),
            {},
        )
        found[str(page["page_id"])] = (
            page.get("version_id"),
            source.get("title"),
            source.get("description"),
        )
    return found
